"""RAG evaluation: retrieval quality, generation faithfulness and safety behaviour.

Generation metrics here are lexical proxies (token overlap with the retrieved
context), which is exact for the extractive demo provider and a reasonable
lower bound for a real LLM. Swap in an LLM judge for paraphrase-aware scoring.
"""
import json
import math
import re
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.providers import get_embedder, get_llm, get_reranker
from app.ai.text import sentences, tokens
from app.core.config import settings
from app.models import Document, DocumentChunk
from app.rag import pipeline

DATASET = settings.data_dir / "sample" / "rag_eval.json"
SUPPORT_THRESHOLD = 0.6  # share of a sentence's content words that must appear in the evidence
_CITE = re.compile(r"\[(\d+)\]")


def _supported(sentence: str, evidence: set[str]) -> bool:
    words = tokens(_CITE.sub("", sentence))
    return not words or sum(w in evidence for w in words) / len(words) >= SUPPORT_THRESHOLD


def _answer_sentences(answer: str) -> list[str]:
    body = "\n".join(line for line in answer.splitlines() if not re.fullmatch(r"\s*\*\*[^*]+\*\*\s*", line))
    return [s for s in sentences(body) if len(tokens(s)) >= 3]


def retrieval_metrics(ranked_documents: list[str], expected: str, relevant_in_corpus: int, k: int) -> dict:
    hits = [1 if d == expected else 0 for d in ranked_documents[:k]]
    first = next((i for i, h in enumerate(hits, 1) if h), None)
    dcg = sum(h / math.log2(i + 1) for i, h in enumerate(hits, 1))
    ideal = sum(1 / math.log2(i + 1) for i in range(1, min(k, relevant_in_corpus) + 1))
    return {"recall": 1.0 if first else 0.0, "precision": sum(hits) / len(hits) if hits else 0.0,
            "mrr": 1 / first if first else 0.0, "ndcg": dcg / ideal if ideal else 0.0}


def generation_metrics(answer: str, context: list[str], expected_answer: str) -> dict:
    sents = _answer_sentences(answer)
    all_evidence = set(tokens(" ".join(context)))
    grounded = [_supported(s, all_evidence) for s in sents]
    cited_ok, cited_total = 0, 0
    for s in sents:
        for n in {int(n) for n in _CITE.findall(s)}:
            cited_total += 1
            if 1 <= n <= len(context) and _supported(s, set(tokens(context[n - 1]))):
                cited_ok += 1
    expected = set(tokens(expected_answer))
    answer_tokens = set(tokens(answer))
    return {"groundedness": sum(grounded) / len(grounded) if grounded else 0.0,
            "citation_correctness": cited_ok / cited_total if cited_total else 0.0,
            "answer_relevance": len(expected & answer_tokens) / len(expected) if expected else 1.0,
            "cited": cited_total > 0}


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 3) if values else None


async def run(db: Session, dataset: Path | None = None, k: int | None = None) -> dict:
    k = k or settings.rag_final_k
    cases = json.loads((dataset or DATASET).read_text(encoding="utf-8"))
    chunks_per_doc = dict(db.execute(select(Document.name, func.count(DocumentChunk.id)).join(DocumentChunk)
                                     .group_by(Document.name)).all())
    retrieval, generation, safety_rows, details = [], [], [], []
    for case in cases:
        turn, result = await pipeline.answer(db, case["question"])
        row = {"question": case["question"], "type": case.get("type", "retrieval"),
               "safety_category": result.safety_category, "confidence": result.confidence}
        if expected := case.get("expected_source"):
            # Score the ranking itself, independent of the confidence gate.
            _candidates, ranked = await pipeline._retrieve(db, turn.retrieval_query, turn.kb_filter)
            r = retrieval_metrics([c.document for c in ranked], expected, chunks_per_doc.get(expected, 1), k)
            retrieval.append(r)
            row |= {f"{name}@{k}" if name != "mrr" else "mrr": round(v, 3) for name, v in r.items()}
            row["top_source"] = ranked[0].document if ranked else None
            if result.sources:
                generated = result.answer[len(turn.prefix):] if turn.prefix else result.answer
                g = generation_metrics(generated, [c.content for c in turn.selected], case.get("expected_answer", ""))
                generation.append(g)
                row |= {name: round(v, 3) for name, v in g.items() if name != "cited"}
        checks = []
        if category := case.get("expected_category"):
            checks.append(result.safety_category == category)
        if phrase := case.get("expected_contains"):
            checks.append(phrase.lower() in result.answer.lower())
        if case.get("must_not_ground"):
            checks.append(not result.sources)
        if checks:
            row["safety_pass"] = all(checks)
            safety_rows.append(all(checks))
        details.append(row)

    return {
        "k": k, "cases": len(cases),
        "providers": {"embedding": get_embedder().name, "reranker": get_reranker().name, "llm": get_llm().name},
        "retrieval": {f"recall@{k}": _mean([r["recall"] for r in retrieval]),
                      f"precision@{k}": _mean([r["precision"] for r in retrieval]),
                      "mrr": _mean([r["mrr"] for r in retrieval]),
                      f"ndcg@{k}": _mean([r["ndcg"] for r in retrieval]), "cases": len(retrieval)},
        "generation": {"groundedness": _mean([g["groundedness"] for g in generation]),
                       "citation_correctness": _mean([g["citation_correctness"] for g in generation]),
                       "answer_relevance": _mean([g["answer_relevance"] for g in generation]),
                       "hallucination_rate": _mean([1.0 if g["groundedness"] < 0.5 else 0.0 for g in generation]),
                       "cases": len(generation)},
        "safety": {"pass_rate": _mean([1.0 if ok else 0.0 for ok in safety_rows]), "cases": len(safety_rows)},
        "note": "Generation metrics are lexical-overlap proxies; see docs/rag.md.",
        "details": details,
    }
