# RAG pipeline

The Medical Assistant is a **Medical Information & Navigation Assistant**. It answers from hospital-approved documents, cites what it used, and refuses or escalates when it should not answer. Code: `backend/app/rag/` and `backend/app/ai/`.

```text
User question
   → Query preprocessing        normalise, expand abbreviations, attach topic for short follow-ups
   → Safety classification      10 categories; emergencies stop here
   → Embedding generation       EmbeddingProvider
   → Vector search              pgvector, cosine distance, HNSW index
   → Keyword search             PostgreSQL full-text (tsvector + GIN)
   → Metadata filtering         active + indexed documents, optional knowledge base
   → Hybrid scoring, top-K      α × semantic + β × keyword
   → Reranking                  top 20 → top 5
   → Confidence gate            below threshold: refuse, do not call the LLM
   → Context construction       numbered passages with document, section, page
   → LLM                        LLMProvider (generate or stream)
   → Citation extraction        [n] markers mapped to sources
   → Safety validation          block diagnosis claims, dosing instructions, bad citations
   → Final response
```

## Ingestion

`rag/ingest.py`: **upload → validate → extract → clean → chunk → metadata → embed → store → index**.

- **Validation** checks the extension allow-list (PDF, DOCX, TXT, MD), size (10 MB), and the file's actual content: PDF magic bytes, a valid DOCX zip, UTF-8 for text. Filenames are sanitised before storage.
- **Extraction** uses `pypdf` (per page), `python-docx` (headings become sections) or plain decoding.
- **Cleaning** normalises whitespace, removes control characters and metadata comments, and re-joins words hyphenated across PDF lines.
- **Chunking** is section-aware. Paragraphs are packed to about 900 characters and never cross a heading; consecutive chunks in a section share a sentence-aligned overlap of about 150 characters.
- **Embedding text** is `document name. section. content`, so short chunks keep their topic.
- **Storage:** `documents` → `document_chunks` (content, page, section, JSONB metadata, generated `tsvector`) → `document_embeddings` (`vector(384)`).

Chunk metadata:

```json
{ "document_id": 7, "document_name": "Hospital Hypertension Guide", "page": 1, "section": "Monitoring blood pressure",
  "source_type": "hospital_guideline", "kb": "medical", "uploaded_at": "2026-10-06T14:42:41", "version": "2.1" }
```

Failures are recorded on the document (`status = failed`, with the error) rather than raised, and are visible in the admin UI. Document statuses: `uploaded`, `processing`, `indexed`, `failed`, `archived`.

## Retrieval

`rag/retrieval.py`

- **Semantic:** `embedding <=> :query` (cosine distance) over an HNSW index; similarity is `1 − distance`, clamped to `[0, 1]`.
- **Keyword:** `ts_rank_cd` against a query that ORs the stemmed terms, so a long natural-language question still matches.
- **Metadata filter:** only `is_active` documents with `status = 'indexed'`, optionally one knowledge base. Deactivating a document removes it from answers immediately.
- **Hybrid:** `hybrid = RAG_ALPHA × semantic + RAG_BETA × (keyword / max keyword in the candidate set)`; the top `RAG_TOP_K` (20) go to the reranker.

Hospital-navigation questions search the `hospital` knowledge base first and fall back to all documents if confidence is low.

## Reranking

`Reranker` is an interface. The default `LexicalReranker` scores query-term coverage (60%), phrase coverage (25%) and term density (15%). The top `RAG_FINAL_K` (5) with a score of at least 0.2 enter the context. To use a cross-encoder, subclass `Reranker` and return it from `get_reranker()`.

## Confidence and hallucination protection

`confidence = 0.7 × top rerank score + 0.3 × min(1, top semantic similarity / 0.5)`

Below `RAG_MIN_CONFIDENCE` (0.42) **the LLM is not called**. The user gets one of:

- *"I can only help with healthcare and hospital-related questions."* when the question is not health-related;
- *"I couldn't find enough information in the hospital's approved knowledge base to answer that reliably…"* otherwise.

Personal treatment requests need a stricter 0.75.

## Generation

The system prompt (`rag/prompt.py`) carries the fourteen rules from the product specification, a calm and concise style guide, and a three-part answer structure: **Short answer**, **What this means**, **When to seek medical care**. Retrieved text is explicitly marked as reference material, not instructions.

With no LLM configured, `ExtractiveLLM` composes the same structure by selecting the sentences from the context that best match the question, each with its citation. It cannot produce a statement that is not in a retrieved passage.

Streaming uses Server-Sent Events: `meta` (classification and sources), `token` (repeated), then `done` with the validated final answer, which replaces the streamed text in the UI.

## Citations

Answers cite passages as `[1]`, `[2]`. After generation, markers are checked against the passages actually supplied; any that point at nothing are removed. Each source returned to the client includes document, section, page, knowledge base, version and its semantic, keyword and rerank scores, with `cited: true` for those referenced in the text. `GET /api/rag/sources/{chunk_id}` returns the passage behind a citation.

## Safety layer

`ai/safety.py` is deliberately rule-based: safety decisions must be deterministic, auditable, and independent of an LLM being available.

| Category | Behaviour |
|---|---|
| `EMERGENCY` | Short escalation to emergency care. No retrieval, no LLM. The escalation (not the message) is audited. |
| `SELF_HARM` | Supportive escalation to emergency or crisis services. No retrieval, no LLM. |
| `HIGH_RISK` (dose changes) | Refusal and prescriber guidance, then general information if evidence is strong. |
| `DIAGNOSIS_REQUEST` | "I can't diagnose you…", then general information. |
| `TREATMENT_REQUEST` | "I can't recommend a treatment…"; general information only with strong evidence. |
| `MEDICATION_INFORMATION`, `SYMPTOM_INFORMATION`, `GENERAL_INFORMATION` | Grounded answer with citations. |
| `HOSPITAL_NAVIGATION` | Grounded answer from the hospital knowledge base. |
| `OUT_OF_SCOPE` | Polite refusal. |

An informational question such as *"What are the warning signs of a stroke?"* is answered; *"My father's face is drooping"* is escalated.

The **output validator** runs on every generated answer and replaces it with a safe fallback if it contains a diagnosis claim ("you have …"), a dosing instruction ("take 500 mg …") or a claim to be a clinician.

## Observability

`POST /api/rag/debug` (super admin, and the *RAG Debugger* page) returns the full trace for a question: the retrieval query, safety classification, metadata filter, every candidate with semantic, keyword, hybrid and rerank scores, the exact context sent to the LLM, the raw LLM response, the final answer, citations, confidence and safety flags.

## Evaluation

`python scripts/evaluate_rag.py --details`, or the *Evaluation* tab of the RAG Debugger. The dataset is `data/sample/rag_eval.json` (24 cases: `question`, `expected_source`, `expected_answer`, plus expected safety behaviour).

| Group | Metrics |
|---|---|
| Retrieval | Recall@K, Precision@K, MRR, NDCG@K, at document level against `expected_source` |
| Generation | Groundedness, citation correctness, answer relevance, hallucination rate |
| Safety | Pass rate over expected category, required phrase, and "must not ground" |

Generation metrics are **lexical proxies**: a sentence counts as supported when at least 60% of its content words appear in the evidence. That is exact for the extractive mode and a conservative lower bound for a real LLM, which paraphrases. For paraphrase-aware scoring, add an LLM judge.

Measured on the bundled knowledge base in demo mode (local embedder, lexical reranker, extractive answers):

| Retrieval (16 cases) | | Generation (16 cases) | | Safety (14 cases) | |
|---|---|---|---|---|---|
| Recall@5 | 1.00 | Groundedness | 1.00 | Pass rate | 1.00 |
| Precision@5 | 0.65 | Citation correctness | 1.00 | | |
| MRR | 1.00 | Answer relevance | 0.74 | | |
| NDCG@5 | 0.68 | Hallucination rate | 0.00 | | |

Read these with care. Recall and MRR are high partly because the evaluation questions share vocabulary with the documents, which suits a lexical embedder; expect lower retrieval scores on paraphrased questions until a semantic embedding model is configured. Groundedness and citation correctness are 1.0 by construction in extractive mode. Precision@5 of 0.65 means roughly a third of the context passages come from neighbouring documents, and answer relevance of 0.74 reflects that a two-sentence extract does not always include every expected key term.
