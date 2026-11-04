"""Knowledge-base retrieval: dense (embeddings), keyword (BM25) and hybrid.

The server embeds the client's message and ranks FAQ chunks by cosine
similarity. Keyword ranking (BM25 over question + "also asked" paraphrases +
answer) catches what embeddings miss on short or very specific messages
("¿y la seña?", "USDT", "celíaco"), and works for chunks that were added to the
source but not embedded yet. Hybrid fuses both rankings with reciprocal rank
fusion (RRF), which needs no score calibration between the two.

RETRIEVAL_MODE=dense (default) | hybrid. Benchmark: scripts/eval_retrieval.py.
"""
from __future__ import annotations

import logging
import math
import re
import unicodedata
from collections import Counter
from typing import Any, Iterable

log = logging.getLogger(__name__)

_STOPWORDS = set(
    """
    a al algo algun alguna como con cual cuales cuando de del el ella en entre es esa ese eso esta este esto
    fue ha hay la las le les lo los me mi mis muy no nos o para pero por que se si sin sobre su sus te tu tus
    un una unos y ya yo vos usted ustedes hola gracias tienen tenes tiene puedo quiero
    the an and are as at be by can do does for from have how i if in is it me my of on or our so that this to
    we what when where which who will with you your hi hello thanks
    o os as um uma uns umas da das do dos em na nas no nos com por para que e eu voce voces tem ola obrigado
    """.split()
)
_TOKEN = re.compile(r"[a-z0-9]+")


def fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", (text or "").lower())
    return text.encode("ascii", "ignore").decode("ascii")


def _stem(token: str) -> str:
    # Plural/singular is the main mismatch ("fechas"/"fecha", "dates"/"date").
    if len(token) > 4 and token.endswith("es") and not token.endswith("ees"):
        return token[:-2]
    if len(token) > 3 and token.endswith("s"):
        return token[:-1]
    return token


def tokenize(text: str) -> list[str]:
    return [_stem(t) for t in _TOKEN.findall(fold(text)) if t not in _STOPWORDS]


def doc_text(row: dict[str, Any]) -> str:
    """Question and paraphrases weigh double: they say what the chunk answers."""
    head = " ".join([str(row.get("question") or ""), *[str(a) for a in row.get("also_asked") or []]])
    return f"{head} {head} {row.get('answer') or ''}"


class BM25:
    def __init__(self, rows: list[dict[str, Any]], k1: float = 1.4, b: float = 0.6) -> None:
        self.rows = rows
        self.k1, self.b = k1, b
        self.docs = [Counter(tokenize(doc_text(r))) for r in rows]
        self.lengths = [sum(d.values()) for d in self.docs]
        self.avg = (sum(self.lengths) / len(self.lengths)) if self.lengths else 0.0
        df: Counter[str] = Counter()
        for d in self.docs:
            df.update(d.keys())
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}

    def scores(self, query: str) -> list[float]:
        terms = tokenize(query)
        out = []
        for doc, length in zip(self.docs, self.lengths):
            s = 0.0
            for t in terms:
                tf = doc.get(t)
                if not tf:
                    continue
                denom = tf + self.k1 * (1 - self.b + self.b * length / (self.avg or 1.0))
                s += self.idf[t] * tf * (self.k1 + 1) / denom
            out.append(s)
        return out


_BM25_CACHE: dict[int, BM25] = {}


def bm25_for(rows: list[dict[str, Any]]) -> BM25:
    """One BM25 per rows list (the runtime keeps the same list for its lifetime)."""
    key = id(rows)
    cached = _BM25_CACHE.get(key)
    if cached is None or cached.rows is not rows:
        cached = BM25(rows)
        _BM25_CACHE.clear()
        _BM25_CACHE[key] = cached
    return cached


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


_warned_dims: set[tuple[int, int]] = set()


def dense_scores(query_vectors: Iterable[list[float]], rows: list[dict[str, Any]]) -> list[float]:
    """Best cosine per row over several query vectors (plain and contextual query)."""
    best = [0.0] * len(rows)
    for vec in query_vectors:
        for i, row in enumerate(rows):
            emb = row.get("embedding")
            if not emb:
                continue
            if len(emb) != len(vec) and (len(vec), len(emb)) not in _warned_dims:
                # Vectors from different models are not comparable: retrieval is noise.
                _warned_dims.add((len(vec), len(emb)))
                log.error(
                    "Embedding size mismatch: query %d vs index %d. OPENAI_EMBED_MODEL must be the "
                    "model that built faq_cloud_index.jsonl (see its embed_model field).",
                    len(vec),
                    len(emb),
                )
            best[i] = max(best[i], cosine(vec, emb))
    return best


def rrf(rankings: list[list[int]], k: int = 60) -> dict[int, float]:
    fused: dict[int, float] = {}
    for ranking in rankings:
        for rank, idx in enumerate(ranking):
            fused[idx] = fused.get(idx, 0.0) + 1.0 / (k + rank + 1)
    return fused


def rank(
    rows: list[dict[str, Any]],
    queries: list[str],
    query_vectors: list[list[float]] | None,
    top_k: int,
    mode: str = "dense",
) -> list[dict[str, Any]]:
    """Top-k rows as {"score": ..., **row}. `score` stays the cosine when there is one."""
    dense = dense_scores(query_vectors, rows) if query_vectors else None
    if mode == "dense" and dense is not None:
        order = sorted(range(len(rows)), key=lambda i: dense[i], reverse=True)
        return [{"score": dense[i], **rows[i]} for i in order[:top_k]]

    bm = bm25_for(rows)
    keyword = [max(s) for s in zip(*(bm.scores(q) for q in queries))] if queries else [0.0] * len(rows)
    kw_order = [i for i in sorted(range(len(rows)), key=lambda i: keyword[i], reverse=True) if keyword[i] > 0]
    if dense is None:
        return [{"score": keyword[i], **rows[i]} for i in kw_order[:top_k]]
    dense_order = sorted(range(len(rows)), key=lambda i: dense[i], reverse=True)
    fused = rrf([dense_order, kw_order])
    order = sorted(fused, key=lambda i: fused[i], reverse=True)
    return [{"score": dense[i], **rows[i]} for i in order[:top_k]]
