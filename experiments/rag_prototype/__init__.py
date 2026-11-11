"""Offline retrieval experiment for caller-supplied text and vectors."""

import math
import os
import re
import stat
import unicodedata
from bisect import bisect_right
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path


_TEXT_SUFFIXES = {".txt", ".md"}
_LINE_END = re.compile(r"\r\n|\r|\n")
_HEADING = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*)|$)")
_CLOSING_HASHES = re.compile(r"(?:^|[ \t]+)#+[ \t]*$")
_FENCE = re.compile(r"^ {0,3}(\x60{3,}|~{3,})(.*)$")
_ARABIC_TRANSLATION = str.maketrans(
    {"آ": "ا", "أ": "ا", "إ": "ا", "ـ": None, **dict.fromkeys(map(chr, range(0x064B, 0x0653)))}
)


@dataclass(frozen=True)
class Document:
    source: str
    document_id: str
    version_id: str
    text: str


@dataclass(frozen=True)
class Chunk:
    source: str
    document_id: str
    version_id: str
    chunk_id: str
    start_char: int
    end_char: int
    start_line: int
    end_line: int
    heading_path: tuple[str, ...]
    text: str


@dataclass(frozen=True)
class ChunkHit:
    chunk: Chunk
    score: float


@dataclass(frozen=True)
class RankedItem:
    item_id: str
    score: float


@dataclass(frozen=True)
class RetrievalMetrics:
    precision: float
    recall: float
    mrr: float
    ndcg: float


def _positive_integer(value: int, name: str) -> None:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{name} must be a positive integer")


def _validate_top_k(top_k: int) -> None:
    if type(top_k) is not int or top_k < 0:
        raise ValueError("top_k must be a non-negative integer")


def _stable_id(kind: str, *parts: str) -> str:
    digest = sha256()
    for part in (kind, *parts):
        data = part.encode("utf-8")
        digest.update(str(len(data)).encode("ascii"))
        digest.update(b":")
        digest.update(data)
    return digest.hexdigest()


def _check_suffix(path: Path) -> None:
    if path.suffix.lower() not in _TEXT_SUFFIXES:
        raise ValueError("Unsupported suffix: use UTF-8 .txt or .md (PDF/DOCX unsupported)")


def read_document(root: str | Path, path: str | Path, *, max_bytes: int) -> Document:
    """Read a relative, regular UTF-8 file under root with a strict byte limit."""
    _positive_integer(max_bytes, "max_bytes")
    relative = Path(path)
    if relative.anchor or ".." in relative.parts:
        raise ValueError("path must be relative to root and contain no '..' components")
    _check_suffix(relative)
    directory = Path(root).resolve(strict=True)
    if not directory.is_dir():
        raise ValueError("root must be a directory")
    resolved = (directory / relative).resolve(strict=True)
    if not resolved.is_relative_to(directory):
        raise ValueError("resolved path is outside root")
    _check_suffix(resolved)
    if not stat.S_ISREG(resolved.stat().st_mode):
        raise ValueError("source must be a regular file")

    # These flags narrow the window for leaf changes where the OS provides them.
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    with os.fdopen(os.open(resolved, flags), "rb", buffering=0) as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("source must be a regular file")
        if info.st_size > max_bytes:
            raise ValueError("source exceeds the byte limit")
        data = bytearray()
        while block := stream.read(min(65536, max_bytes - len(data) + 1)):
            data.extend(block)
            if len(data) > max_bytes:
                raise ValueError("source exceeds the byte limit")

    text = data.decode("utf-8")
    source = resolved.relative_to(directory).as_posix()
    document_id = _stable_id("document", source)
    version_id = _stable_id("version", document_id, sha256(data).hexdigest())
    return Document(source, document_id, version_id, text)


def _heading_sections(text: str, line_starts: Sequence[int]) -> list[tuple[int, tuple[str, ...]]]:
    sections: list[tuple[int, tuple[str, ...]]] = [(0, ())]
    headings: list[tuple[int, str]] = []
    fence: tuple[str, int] | None = None
    for start, end in zip(line_starts, (*line_starts[1:], len(text))):
        line = text[start:end].rstrip("\r\n")
        marker = _FENCE.match(line)
        if fence is not None:
            if marker:
                run, rest = marker.groups()
                if run[0] == fence[0] and len(run) >= fence[1] and not rest.strip():
                    fence = None
            continue
        if marker:
            run, rest = marker.groups()
            if run[0] == "~" or "`" not in rest:
                fence = (run[0], len(run))
                continue
        heading = _HEADING.match(line)
        if heading:
            marks, label = heading.groups()
            level = len(marks)
            while headings and headings[-1][0] >= level:
                headings.pop()
            headings.append((level, _CLOSING_HASHES.sub("", label or "").strip()))
            section = (start, tuple(title for _, title in headings))
            if start == 0:
                sections[0] = section
            else:
                sections.append(section)
    return sections


def chunk_document(document: Document, *, max_chars: int) -> tuple[Chunk, ...]:
    """Split source into bounded contiguous chunks, preferring line boundaries."""
    _positive_integer(max_chars, "max_chars")
    text = document.text
    line_starts = [0, *(match.end() for match in _LINE_END.finditer(text))]
    sections = [(0, ())]
    if Path(document.source).suffix.lower() == ".md":
        sections = _heading_sections(text, line_starts)

    chunks = []
    for (start, heading_path), (section_end, _) in zip(sections, (*sections[1:], (len(text), ()))):
        while start < section_end:
            end = min(start + max_chars, section_end)
            if end < section_end:
                boundary = line_starts[bisect_right(line_starts, end) - 1]
                if boundary > start:
                    end = boundary
            chunk_id = _stable_id(
                "chunk-v1", document.version_id, str(max_chars), str(start), str(end)
            )
            chunks.append(
                Chunk(
                    document.source,
                    document.document_id,
                    document.version_id,
                    chunk_id,
                    start,
                    end,
                    bisect_right(line_starts, start),
                    bisect_right(line_starts, end - 1),
                    heading_path,
                    text[start:end],
                )
            )
            start = end
    return tuple(chunks)


def tokenize(text: str, *, normalize_arabic: bool = False) -> tuple[str, ...]:
    """Case-fold Unicode letter and number tokens, retaining attached marks by default."""
    if normalize_arabic:
        text = text.translate(_ARABIC_TRANSLATION)
    tokens = []
    current = []
    for char in text.casefold():
        category = unicodedata.category(char)[0]
        if category in ("L", "N") or (category == "M" and current):
            current.append(char)
        elif current:
            tokens.append("".join(current))
            current = []
    if current:
        tokens.append("".join(current))
    return tuple(tokens)


class BM25Index:
    """In-memory BM25 with k1=1.2 and b=0.75."""

    def __init__(self, chunks: Iterable[Chunk], *, normalize_arabic: bool = False):
        self._normalize_arabic = normalize_arabic
        self._entries = []
        document_frequencies: Counter[str] = Counter()
        seen = set()
        total_length = 0
        for chunk in chunks:
            if chunk.chunk_id in seen:
                raise ValueError(f"duplicate chunk ID: {chunk.chunk_id}")
            seen.add(chunk.chunk_id)
            tokens = tokenize(chunk.text, normalize_arabic=normalize_arabic)
            terms = Counter(tokens)
            self._entries.append((chunk, terms, len(tokens)))
            document_frequencies.update(terms.keys())
            total_length += len(tokens)
        count = len(self._entries)
        self._avg_length = total_length / count if count else 0
        self._idf = {
            term: math.log1p((count - frequency + 0.5) / (frequency + 0.5))
            for term, frequency in document_frequencies.items()
        }

    def search(
        self,
        query: str,
        *,
        top_k: int,
        source: str | None = None,
        document_id: str | None = None,
        version_id: str | None = None,
        heading_path: tuple[str, ...] | None = None,
    ) -> tuple[ChunkHit, ...]:
        """Return positive scores with optional exact metadata filters."""
        _validate_top_k(top_k)
        if not top_k or not self._avg_length:
            return ()
        query_terms = sorted(set(tokenize(query, normalize_arabic=self._normalize_arabic)))
        query_terms = [term for term in query_terms if term in self._idf]
        if not query_terms:
            return ()

        hits = []
        for chunk, terms, length in self._entries:
            if (
                (source is not None and chunk.source != source)
                or (document_id is not None and chunk.document_id != document_id)
                or (version_id is not None and chunk.version_id != version_id)
                or (heading_path is not None and chunk.heading_path != heading_path)
            ):
                continue
            length_penalty = 1.2 * (0.25 + 0.75 * length / self._avg_length)
            score = math.fsum(
                self._idf[term] * (2.2 * terms[term]) / (terms[term] + length_penalty)
                for term in query_terms
                if term in terms
            )
            if score > 0:
                hits.append(ChunkHit(chunk, score))
        hits.sort(key=lambda hit: (-hit.score, hit.chunk.chunk_id))
        return tuple(hits[:top_k])


def _unit_vector(vector: Sequence[float], name: str) -> tuple[float, ...]:
    if len(vector) == 0:
        raise ValueError(f"{name} must have at least one dimension")
    try:
        finite = all(math.isfinite(value) for value in vector)
    except (OverflowError, TypeError) as exc:
        raise ValueError(f"{name} must contain finite numbers") from exc
    if not finite:
        raise ValueError(f"{name} must contain finite numbers")
    scale = max(abs(value) for value in vector)
    if scale == 0:
        raise ValueError(f"{name} must have a non-zero norm")
    scaled = tuple(value / scale for value in vector)
    norm = math.hypot(*scaled)
    return tuple(value / norm for value in scaled)


def _rank_items(items: Iterable[RankedItem], top_k: int) -> tuple[RankedItem, ...]:
    ranked = sorted(items, key=lambda hit: (-hit.score, hit.item_id))
    return tuple(ranked[:top_k])


def exact_cosine(
    query: Sequence[float], vectors: Mapping[str, Sequence[float]], *, top_k: int
) -> tuple[RankedItem, ...]:
    """Rank supplied vectors with an exhaustive cosine similarity calculation."""
    _validate_top_k(top_k)
    unit_query = _unit_vector(query, "query")
    hits = []
    for item_id, vector in vectors.items():
        if len(vector) != len(unit_query):
            raise ValueError(f"vector {item_id!r} has a different dimension from the query")
        unit_vector = _unit_vector(vector, f"vector {item_id!r}")
        similarity = math.fsum(a * b for a, b in zip(unit_query, unit_vector))
        hits.append(RankedItem(item_id, min(1.0, max(-1.0, similarity))))
    return _rank_items(hits, top_k)


def _ensure_unique(ranking: Sequence[str]) -> None:
    if len(set(ranking)) != len(ranking):
        raise ValueError("ranking contains a duplicate item ID")


def reciprocal_rank_fusion(
    rankings: Iterable[Sequence[str]], *, top_k: int, rank_constant: int = 60
) -> tuple[RankedItem, ...]:
    """Fuse ordered ID lists using 1 / (rank_constant + one-based rank)."""
    _validate_top_k(top_k)
    _positive_integer(rank_constant, "rank_constant")
    contributions: dict[str, list[float]] = defaultdict(list)
    for ranking in rankings:
        _ensure_unique(ranking)
        for rank, item_id in enumerate(ranking, start=1):
            contributions[item_id].append(1 / (rank_constant + rank))
    hits = (RankedItem(item_id, math.fsum(scores)) for item_id, scores in contributions.items())
    return _rank_items(hits, top_k)


def retrieval_metrics(
    ranking: Sequence[str], relevance: Mapping[str, int], *, k: int
) -> RetrievalMetrics:
    """Compute per-query metrics at k from unique IDs and non-negative relevance grades."""
    _positive_integer(k, "k")
    _ensure_unique(ranking)
    if any(type(grade) is not int or grade < 0 for grade in relevance.values()):
        raise ValueError("relevance grades must be non-negative integers")
    relevant_grades = sorted((grade for grade in relevance.values() if grade > 0), reverse=True)
    if not relevant_grades:
        return RetrievalMetrics(0.0, 0.0, 0.0, 0.0)

    retrieved = [relevance.get(item_id, 0) for item_id in ranking[:k]]
    matches = [rank for rank, grade in enumerate(retrieved, start=1) if grade > 0]

    # Scaling both DCGs by the same power of two avoids overflow for large grades.
    max_grade = relevant_grades[0]
    scaled_one = math.ldexp(1.0, -max_grade)

    def dcg(grades: Sequence[int]) -> float:
        return math.fsum(
            (math.ldexp(1.0, grade - max_grade) - scaled_one) / math.log2(rank + 1)
            for rank, grade in enumerate(grades, start=1)
        )

    return RetrievalMetrics(
        precision=len(matches) / k,
        recall=len(matches) / len(relevant_grades),
        mrr=1 / matches[0] if matches else 0.0,
        ndcg=dcg(retrieved) / dcg(relevant_grades[:k]),
    )


def mean_retrieval_metrics(
    queries: Iterable[tuple[Sequence[str], Mapping[str, int]]], *, k: int
) -> RetrievalMetrics:
    """Macro-average per-query results, including no-answer fixtures."""
    _positive_integer(k, "k")
    results = [retrieval_metrics(ranking, relevance, k=k) for ranking, relevance in queries]
    if not results:
        return RetrievalMetrics(0.0, 0.0, 0.0, 0.0)
    count = len(results)
    return RetrievalMetrics(
        precision=math.fsum(result.precision for result in results) / count,
        recall=math.fsum(result.recall for result in results) / count,
        mrr=math.fsum(result.mrr for result in results) / count,
        ndcg=math.fsum(result.ndcg for result in results) / count,
    )


def ensure_disjoint_documents(dev: Iterable[Chunk], holdout: Iterable[Chunk]) -> None:
    """Reject document overlap between two splits, including across versions."""
    dev_documents = {chunk.document_id for chunk in dev}
    if dev_documents.intersection(chunk.document_id for chunk in holdout):
        raise ValueError("dev and holdout share a document")
