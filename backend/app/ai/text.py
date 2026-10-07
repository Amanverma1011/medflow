"""Shared lexical primitives for the local embedder, reranker, extractive composer and evaluation."""
import re

STOPWORDS = frozenset("""
a about above after again all am an and any are as at be because been before being below between both but by can
could did do does doing down during each few for from further had has have having he her here hers him his how i if
in into is it its itself just me more most my myself no nor not now of off on once only or other our ours out over
own s same she should so some such t than that the their theirs them then there these they this those through to
too under until up very was we were what when where which while who whom why will with would you your yours
tell say says said please know want need get also may might much many there's what's
""".split())

_WORD = re.compile(r"[a-z0-9]+")
_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")


def stem(word: str) -> str:
    """Crude suffix stripper. Only needs to be consistent between query and document."""
    if len(word) <= 3 or word.isdigit():
        return word
    if word.endswith("ies"):
        word = word[:-3] + "y"
    elif word.endswith("s") and not word.endswith(("ss", "us", "is")):
        word = word[:-1]
    for suffix in ("ing", "ed"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            word = word[: -len(suffix)]
            if len(word) > 3 and word[-1] == word[-2] and word[-1] not in "aeiouls":
                word = word[:-1]  # stopped -> stop
            break
    if len(word) > 3 and word.endswith("e"):
        word = word[:-1]  # take/taking, dose/doses, prescribe/prescribed
    return word


def tokens(text: str) -> list[str]:
    return [stem(w) for w in _WORD.findall(text.lower()) if w not in STOPWORDS]


def bigrams(toks: list[str]) -> list[str]:
    return [f"{a}_{b}" for a, b in zip(toks, toks[1:])]


def sentences(text: str) -> list[str]:
    """Split prose and markdown bullets into sentence-like units; headings are dropped."""
    out: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        line = re.sub(r"^([-*•]|\d+[.)])\s+", "", line)
        out.extend(s.strip() for s in _SENTENCE.split(line) if s.strip())
    return out
