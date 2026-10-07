"""Provider abstraction for LLMs, embeddings and rerankers.

The application only ever talks to the three base classes below. Swapping a
vendor (or pointing at a local model server) means adding a subclass and
changing the factory at the bottom of this file.
"""
import hashlib
import json
import math
import re
from abc import ABC, abstractmethod
from collections import Counter
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from functools import lru_cache

import httpx

from app.ai.text import bigrams, sentences, tokens
from app.core.config import settings

TIMEOUT = httpx.Timeout(60.0, connect=10.0)


@dataclass
class ContextChunk:
    index: int  # 1-based citation number
    document: str
    section: str
    page: int
    text: str
    kb: str = "medical"


@dataclass
class Prompt:
    system: str
    user: str
    question: str = ""
    context: list[ContextChunk] = field(default_factory=list)


class ProviderError(RuntimeError):
    pass


# --------------------------------------------------------------------------- embeddings
class EmbeddingProvider(ABC):
    name: str
    dimension: int

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class LocalHashEmbedding(EmbeddingProvider):
    """Deterministic feature-hashing embedder (unigrams + bigrams, signed, L2-normalised).

    It is a real vector-space model, so pgvector search behaves normally, but it only
    captures lexical overlap, not meaning. It exists so the full pipeline runs with no
    API key; configure EMBEDDING_* for semantic quality.
    """

    def __init__(self, dimension: int):
        self.dimension = dimension
        self.name = f"local-hash-{dimension}"

    def _one(self, text: str) -> list[float]:
        toks = tokens(text)
        vec = [0.0] * self.dimension
        for feature, count in Counter(toks + bigrams(toks)).items():
            h = int.from_bytes(hashlib.blake2b(feature.encode(), digest_size=8).digest(), "little")
            weight = (1 + math.log(count)) * (0.6 if "_" in feature else 1.0)
            vec[h % self.dimension] += weight if (h >> 40) & 1 else -weight
        norm = math.sqrt(sum(v * v for v in vec))
        if norm == 0:  # cosine distance is undefined for a zero vector
            vec[0], norm = 1.0, 1.0
        return [v / norm for v in vec]

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._one(t) for t in texts]


class OpenAICompatibleEmbedding(EmbeddingProvider):
    def __init__(self, base_url: str, api_key: str, model: str, dimension: int):
        self.base_url, self.api_key, self.name, self.dimension = base_url.rstrip("/"), api_key, model, dimension

    async def embed(self, texts: list[str]) -> list[list[float]]:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            r = await client.post(f"{self.base_url}/embeddings", json={"model": self.name, "input": texts},
                                  headers={"Authorization": f"Bearer {self.api_key}"})
        if r.status_code >= 400:
            raise ProviderError(f"Embedding provider returned HTTP {r.status_code}")
        vectors = [d["embedding"] for d in sorted(r.json()["data"], key=lambda d: d["index"])]
        if vectors and len(vectors[0]) != self.dimension:
            raise ProviderError(f"Embedding model returned {len(vectors[0])} dimensions but VECTOR_DIMENSION "
                                f"is {self.dimension}")
        return vectors


# --------------------------------------------------------------------------- LLMs
class LLMProvider(ABC):
    name: str
    is_demo: bool = False

    @abstractmethod
    async def generate(self, prompt: Prompt) -> str: ...

    @abstractmethod
    def stream(self, prompt: Prompt) -> AsyncIterator[str]: ...


class OpenAICompatibleLLM(LLMProvider):
    def __init__(self, base_url: str, api_key: str, model: str):
        self.base_url, self.api_key, self.name = base_url.rstrip("/"), api_key, model

    def _request(self, prompt: Prompt, stream: bool) -> dict:
        return {"model": self.name, "stream": stream, "temperature": 0.1,
                "messages": [{"role": "system", "content": prompt.system},
                             {"role": "user", "content": prompt.user}]}

    @property
    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}"}

    async def generate(self, prompt: Prompt) -> str:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            r = await client.post(f"{self.base_url}/chat/completions", json=self._request(prompt, False),
                                  headers=self._headers)
        if r.status_code >= 400:
            raise ProviderError(f"LLM provider returned HTTP {r.status_code}")
        return r.json()["choices"][0]["message"]["content"] or ""

    async def stream(self, prompt: Prompt) -> AsyncIterator[str]:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            async with client.stream("POST", f"{self.base_url}/chat/completions",
                                     json=self._request(prompt, True), headers=self._headers) as r:
                if r.status_code >= 400:
                    raise ProviderError(f"LLM provider returned HTTP {r.status_code}")
                async for line in r.aiter_lines():
                    if not line.startswith("data:") or line.strip() == "data: [DONE]":
                        continue
                    choices = json.loads(line[5:]).get("choices") or [{}]
                    if token := (choices[0].get("delta") or {}).get("content"):
                        yield token


_CARE = re.compile(r"\b(seek|urgent|emergency|immediately|call|contact your|see a doctor|medical attention)\b", re.I)


class ExtractiveLLM(LLMProvider):
    """Demo fallback used when no LLM key is configured.

    It does not generate language. It selects the sentences from the retrieved
    context that best match the question and cites each one, so every statement
    is traceable to a source by construction.
    """

    name = "extractive-demo"
    is_demo = True

    def _compose(self, prompt: Prompt) -> str:
        q = set(tokens(prompt.question))
        scored: list[tuple[float, int, int, str]] = []  # (score, citation, order, sentence)
        for chunk in prompt.context:
            for order, sent in enumerate(sentences(chunk.text)):
                if len(sent) < 25:
                    continue
                overlap = len(q & set(tokens(sent))) / (len(q) or 1)
                # earlier chunks were ranked higher by the reranker; use that as a tie-breaker
                scored.append((overlap - 0.02 * chunk.index, chunk.index, order, sent))
        if not scored:
            return "I couldn't find enough information in the approved knowledge base to answer that reliably."
        ranked = sorted(scored, key=lambda s: -s[0])
        lead_chunk = ranked[0][1]
        lead = sorted([s for s in ranked if s[1] == lead_chunk][:2], key=lambda s: s[2])
        used = {s[3] for s in lead}
        more = [s for s in ranked if s[3] not in used and s[0] > 0][:3]
        used |= {s[3] for s in more}
        care = [s for s in scored if s[3] not in used and _CARE.search(s[3])][:2]

        def cite(items) -> str:
            return "\n".join(f"- {s[3]} [{s[1]}]" for s in items)

        medical = any(c.kb == "medical" for c in prompt.context)
        parts = ["**Short answer**\n\n" + " ".join(f"{s[3]} [{s[1]}]" for s in lead)]
        if more:
            parts.append(("**What this means**" if medical else "**Details**") + "\n\n" + cite(more))
        if care and medical:
            parts.append("**When to seek medical care**\n\n" + cite(care))
        return "\n\n".join(parts)

    async def generate(self, prompt: Prompt) -> str:
        return self._compose(prompt)

    async def stream(self, prompt: Prompt) -> AsyncIterator[str]:
        for piece in re.findall(r"\S+\s*", self._compose(prompt)):
            yield piece


# --------------------------------------------------------------------------- rerankers
class Reranker(ABC):
    name: str

    @abstractmethod
    async def rerank(self, query: str, documents: list[str]) -> list[float]:
        """Return one relevance score in [0, 1] per document, in input order."""


class LexicalReranker(Reranker):
    """Query-term coverage + phrase coverage + term density.

    ponytail: lexical, not a cross-encoder. Subclass Reranker for a hosted or
    local cross-encoder when answer quality on paraphrased questions matters.
    """

    name = "lexical-coverage"

    async def rerank(self, query: str, documents: list[str]) -> list[float]:
        q = tokens(query)
        terms, phrases = set(q), set(bigrams(q))
        if not terms:
            return [0.0] * len(documents)
        scores = []
        for doc in documents:
            d = tokens(doc)
            counts, doc_phrases = Counter(d), set(bigrams(d))
            coverage = sum(1 for t in terms if t in counts) / len(terms)
            density = sum(min(counts[t], 3) for t in terms) / (3 * len(terms))
            phrase = (sum(1 for p in phrases if p in doc_phrases) / len(phrases)) if phrases else coverage
            scores.append(round(0.6 * coverage + 0.25 * phrase + 0.15 * density, 4))
        return scores


# --------------------------------------------------------------------------- factories
@lru_cache
def get_embedder() -> EmbeddingProvider:
    if settings.remote_embeddings:
        return OpenAICompatibleEmbedding(settings.embedding_base_url, settings.embedding_api_key,
                                         settings.embedding_model, settings.vector_dimension)
    return LocalHashEmbedding(settings.vector_dimension)


@lru_cache
def get_llm() -> LLMProvider:
    if settings.llm_enabled:
        return OpenAICompatibleLLM(settings.llm_base_url, settings.llm_api_key, settings.llm_model)
    return ExtractiveLLM()


@lru_cache
def get_reranker() -> Reranker:
    return LexicalReranker()
