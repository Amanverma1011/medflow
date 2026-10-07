"""The RAG pipeline.

question -> preprocess -> safety classification -> embed -> hybrid search (metadata filtered)
         -> rerank -> confidence gate -> context -> LLM -> citation extraction -> safety validation
"""
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.ai import safety
from app.ai.providers import ContextChunk, Prompt, get_embedder, get_llm, get_reranker
from app.core.config import settings
from app.rag.prompt import build_prompt
from app.rag.retrieval import Candidate, hybrid_search

MAX_QUESTION_CHARS = 1000
SEMANTIC_CEILING = 0.5  # similarity at or above this counts as a full-strength semantic match
RERANK_FLOOR = 0.2  # chunks below this never enter the context
PERSONAL_TREATMENT_CONFIDENCE = 0.75
ABBREVIATIONS = {"bp": "blood pressure", "er": "emergency department", "ed": "emergency department",
                 "meds": "medication", "gp": "general practitioner", "appt": "appointment"}
_FOLLOW_UP = re.compile(r"^(and|what about|how about|why|how so|is that|does that|can it|what if|tell me more)\b|"
                        r"\b(it|that|this|they|them|those)\b", re.I)


@dataclass
class Turn:
    """Everything decided before generation. Also the debug trace for /rag/debug."""
    question: str
    retrieval_query: str
    safety: safety.SafetyResult
    kb_filter: str | None = None
    candidates: list[Candidate] = field(default_factory=list)  # hybrid top-K, pre-rerank order
    selected: list[Candidate] = field(default_factory=list)  # reranked top-N in the context
    confidence: float = 0.0
    scope: str = "none"  # medical | hospital | none
    fixed_answer: str | None = None  # set when the pipeline must not call the LLM
    prefix: str = ""  # safety preamble placed before a generated answer
    prompt: Prompt | None = None
    notes: list[str] = field(default_factory=list)


@dataclass
class RagResult:
    answer: str
    sources: list[dict]
    confidence: float
    safety_category: str
    knowledge_scope: str
    follow_ups: list[str]
    flags: list[str]
    grounded: bool
    disclaimer: str = safety.DISCLAIMER
    emergency_notice: str = safety.EMERGENCY_NOTICE


def preprocess(question: str, previous_question: str | None = None) -> tuple[str, str]:
    """Return (clean question, retrieval query). Short follow-ups inherit the previous question's topic."""
    clean = re.sub(r"\s+", " ", question).strip()[:MAX_QUESTION_CHARS]
    expanded = " ".join(ABBREVIATIONS.get(w.lower().strip("?.,!"), w) for w in clean.split())
    if previous_question and len(expanded.split()) <= 8 and _FOLLOW_UP.search(expanded):
        expanded = f"{previous_question} {expanded}"
    return clean, expanded


def _confidence(selected: list[Candidate]) -> float:
    if not selected:
        return 0.0
    top = selected[0]
    return round(0.7 * top.rerank + 0.3 * min(1.0, top.semantic / SEMANTIC_CEILING), 2)


async def _retrieve(db: Session, query: str, kb: str | None) -> tuple[list[Candidate], list[Candidate]]:
    vector = (await get_embedder().embed([query]))[0]
    candidates = hybrid_search(db, query, vector, kb)
    if not candidates:
        return [], []
    scores = await get_reranker().rerank(
        query, [f"{c.document}. {c.section}. {c.content}" for c in candidates])
    for candidate, score in zip(candidates, scores):
        candidate.rerank = score
    ranked = sorted(candidates, key=lambda c: (-c.rerank, -c.hybrid))
    return candidates, [c for c in ranked[:settings.rag_final_k] if c.rerank >= RERANK_FLOOR]


async def prepare(db: Session, question: str, previous_question: str | None = None) -> Turn:
    clean, query = preprocess(question, previous_question)
    result = safety.classify(clean)
    turn = Turn(question=clean, retrieval_query=query, safety=result)

    if result.canned:  # EMERGENCY / SELF_HARM: escalate immediately, no retrieval, no LLM
        turn.fixed_answer = result.canned
        turn.notes.append("Escalation response returned without retrieval or generation.")
        return turn

    if result.category == "HOSPITAL_NAVIGATION":
        turn.kb_filter = "hospital"
    turn.candidates, turn.selected = await _retrieve(db, query, turn.kb_filter)
    turn.confidence = _confidence(turn.selected)
    if turn.kb_filter and turn.confidence < settings.rag_min_confidence:
        turn.notes.append("Low confidence in the hospital knowledge base; retried across all knowledge bases.")
        turn.kb_filter = None
        turn.candidates, turn.selected = await _retrieve(db, query, None)
        turn.confidence = _confidence(turn.selected)

    turn.prefix = safety.PREFIX.get(result.category, "")
    threshold = settings.rag_min_confidence
    if result.category == "TREATMENT_REQUEST" and result.personal:
        threshold = PERSONAL_TREATMENT_CONFIDENCE  # personal treatment questions need strong evidence

    if turn.confidence < threshold:
        turn.selected = []
        if result.category == "GENERAL_INFORMATION" and not result.health_related:
            turn.safety = safety.SafetyResult("OUT_OF_SCOPE", result.personal, False)
            turn.fixed_answer = safety.OUT_OF_SCOPE
        elif turn.prefix:
            turn.fixed_answer = f"{turn.prefix}\n\n{safety.BOOKING_HINT}"
        else:
            turn.fixed_answer = safety.INSUFFICIENT
        turn.notes.append(f"Retrieval confidence {turn.confidence} is below the {threshold} threshold; "
                          "the LLM was not called.")
        return turn

    scopes = [c.kb for c in turn.selected]
    turn.scope = max(set(scopes), key=scopes.count)
    if turn.prefix:
        turn.prefix = f"{turn.prefix}\n\n{safety.GENERAL_INFO_BRIDGE}\n\n"
    chunks = [ContextChunk(i, c.document, c.section, c.page, c.content, c.kb)
              for i, c in enumerate(turn.selected, 1)]
    turn.prompt = build_prompt(clean, chunks, settings.hospital_name)
    return turn


def _sources(turn: Turn, cited: set[int]) -> list[dict]:
    return [{"index": i, "chunk_id": c.chunk_id, "document_id": c.document_id, "document": c.document,
             "section": c.section, "page": c.page, "kb": c.kb, "version": c.version,
             "score": round(c.rerank, 2), "semantic": round(c.semantic, 2), "keyword": round(c.keyword_norm, 2),
             "snippet": c.content[:280], "cited": i in cited}
            for i, c in enumerate(turn.selected, 1)]


def _follow_ups(turn: Turn) -> list[str]:
    if not turn.selected:
        return ["When should I seek urgent care?", "How do I book an appointment?"]
    seen, out = {turn.selected[0].section}, []
    for c in turn.selected[1:]:
        if c.section and c.section not in seen:
            seen.add(c.section)
            out.append(f"What does the {c.document} say about {c.section[0].lower()}{c.section[1:]}?")
    return out[:3]


def finalize(turn: Turn, generated: str) -> RagResult:
    """Citation extraction + output safety validation."""
    if turn.fixed_answer is not None:
        return RagResult(turn.fixed_answer, [], turn.confidence, turn.safety.category, turn.scope,
                         _follow_ups(turn), [], grounded=False)
    answer, flags = safety.validate_output(generated, len(turn.selected))
    if {"diagnosis_claim", "dose_instruction", "claims_clinician"} & set(flags):
        return RagResult(answer, [], turn.confidence, turn.safety.category, turn.scope, [], flags, grounded=False)
    cited = set(safety.cited_indices(answer))
    if not cited:
        flags.append("no_citations_in_answer")
    return RagResult(f"{turn.prefix}{answer}", _sources(turn, cited), turn.confidence, turn.safety.category,
                     turn.scope, _follow_ups(turn), flags, grounded=bool(cited))


async def answer(db: Session, question: str, previous_question: str | None = None) -> tuple[Turn, RagResult]:
    turn = await prepare(db, question, previous_question)
    generated = await get_llm().generate(turn.prompt) if turn.prompt else ""
    return turn, finalize(turn, generated)


async def stream_tokens(turn: Turn) -> AsyncIterator[str]:
    """Yield display tokens for a prepared turn (fixed answers are streamed too, for a consistent UI)."""
    if turn.fixed_answer is not None:
        for piece in re.findall(r"\S+\s*", turn.fixed_answer):
            yield piece
        return
    if turn.prefix:
        yield turn.prefix
    async for token in get_llm().stream(turn.prompt):
        yield token


def trace(turn: Turn, result: RagResult, generated: str) -> dict:
    """Full pipeline trace for the admin RAG debugger."""
    selected_ids = {c.chunk_id for c in turn.selected}
    return {
        "question": turn.question,
        "retrieval_query": turn.retrieval_query,
        "safety_classification": {"category": turn.safety.category, "personal": turn.safety.personal,
                                  "strict_rules": turn.safety.strict},
        "metadata_filter": {"kb": turn.kb_filter, "is_active": True, "status": "indexed"},
        "weights": {"alpha": settings.rag_alpha, "beta": settings.rag_beta, "top_k": settings.rag_top_k,
                    "final_k": settings.rag_final_k, "min_confidence": settings.rag_min_confidence},
        "providers": {"embedding": get_embedder().name, "reranker": get_reranker().name, "llm": get_llm().name,
                      "llm_called": turn.prompt is not None},
        "retrieved": [{**c.scores(), "selected": c.chunk_id in selected_ids, "preview": c.content[:200]}
                      for c in turn.candidates],
        "reranked": [{**c.scores(), "preview": c.content[:200]} for c in turn.selected],
        "final_context": turn.prompt.user if turn.prompt else None,
        "system_prompt_rules": 14 if turn.prompt else 0,
        "llm_response": generated or None,
        "final_answer": result.answer,
        "citations": [s for s in result.sources if s["cited"]],
        "confidence": result.confidence,
        "safety_flags": result.flags,
        "notes": turn.notes,
    }
