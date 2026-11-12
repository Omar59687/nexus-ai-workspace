"""Deterministic, page-aware chunking with bounded overlap and source spans."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from bisect import bisect_right

from nexus_ai.documents.types import ExtractionResult, SourceChunk


_HEADING = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.*?)\s*#*\s*$")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")


@dataclass(frozen=True)
class ChunkingConfig:
    max_chars: int = 1_200
    overlap_chars: int = 120
    max_chunks: int = 100_000

    def __post_init__(self) -> None:
        if type(self.max_chars) is not int or not 1 <= self.max_chars <= 4_000:
            raise ValueError("max_chars must be between 1 and 4000")
        if type(self.overlap_chars) is not int or not 0 <= self.overlap_chars < self.max_chars:
            raise ValueError("overlap_chars must be from zero to less than max_chars")
        if type(self.max_chunks) is not int or self.max_chunks <= 0:
            raise ValueError("max_chunks must be a positive integer")


class SourceAwareChunker:
    version = "source-aware-v1"

    def __init__(self, config: ChunkingConfig = ChunkingConfig()) -> None:
        self.config = config

    def chunk(
        self,
        extraction: ExtractionResult,
        *,
        document_id: str,
        version_id: str,
        source_path: str,
        source_sha256: str,
    ) -> tuple[SourceChunk, ...]:
        chunks: list[SourceChunk] = []
        for page in extraction.pages:
            text = page.text
            if not text:
                continue
            line_starts = [0, *(m.end() for m in re.finditer(r"\r\n|\r|\n", text))]
            heading_positions = _heading_positions(text, line_starts) if extraction.media_type == "text/markdown" else []
            start = 0
            while start < len(text):
                hard_end = min(start + self.config.max_chars, len(text))
                end = _prefer_line_boundary(text, start, hard_end)
                if end <= start:
                    end = hard_end
                body = text[start:end]
                page_id = "none" if page.page_number is None else str(page.page_number)
                text_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
                material = "\0".join((document_id, version_id, self.version, page_id,
                                      str(start), str(end), text_hash))
                chunk_id = hashlib.sha256(material.encode("utf-8")).hexdigest()
                start_line = bisect_right(line_starts, start) if extraction.offsets_reliable else None
                end_line = bisect_right(line_starts, end - 1) if extraction.offsets_reliable else None
                heading_path = _heading_at(start, heading_positions)
                chunks.append(SourceChunk(
                    chunk_id=chunk_id,
                    document_id=document_id,
                    version_id=version_id,
                    source_path=source_path,
                    source_sha256=source_sha256,
                    extractor_name=extraction.extractor_name,
                    extractor_version=extraction.extractor_version,
                    page_number=page.page_number,
                    start_char=start if extraction.offsets_reliable else None,
                    end_char=end if extraction.offsets_reliable else None,
                    start_line=start_line,
                    end_line=end_line,
                    text=body,
                    heading_path=heading_path,
                    offsets_reliable=extraction.offsets_reliable,
                    chunker_version=self.version,
                ))
                if len(chunks) > self.config.max_chunks:
                    raise ValueError("document exceeds max_chunks")
                if end == len(text):
                    break
                desired = max(start + 1, end - self.config.overlap_chars)
                next_boundaries = [boundary for boundary in line_starts if desired <= boundary < end]
                start = next_boundaries[0] if next_boundaries else desired
        if not chunks:
            raise ValueError("document contains no extractable text")
        return tuple(chunks)


def _prefer_line_boundary(text: str, start: int, hard_end: int) -> int:
    if hard_end == len(text):
        return hard_end
    # Prefer blank paragraph endings, then any line ending. This leaves complete
    # Markdown table rows and headings together unless a single line is oversized.
    blank = [m.end() for m in re.finditer(r"(?:\r\n|\r|\n)[ \t]*(?:\r\n|\r|\n)", text[start:hard_end])]
    if blank:
        return start + blank[-1]
    lines = [m.end() for m in re.finditer(r"\r\n|\r|\n", text[start:hard_end])]
    return start + lines[-1] if lines else hard_end


def _heading_positions(text: str, line_starts: list[int]) -> list[tuple[int, tuple[str, ...]]]:
    headings: list[tuple[int, str]] = []
    positions: list[tuple[int, tuple[str, ...]]] = [(0, ())]
    fence_char: str | None = None
    fence_size = 0
    for start, end in zip(line_starts, (*line_starts[1:], len(text))):
        line = text[start:end].rstrip("\r\n")
        fence = _FENCE.match(line)
        if fence_char:
            if fence and fence.group(1)[0] == fence_char and len(fence.group(1)) >= fence_size and not fence.group(2).strip():
                fence_char = None
            continue
        if fence:
            marker, rest = fence.groups()
            if marker[0] == "~" or "`" not in rest:
                fence_char, fence_size = marker[0], len(marker)
            continue
        match = _HEADING.match(line)
        if not match:
            continue
        level, title = len(match.group(1)), match.group(2).strip()
        while headings and headings[-1][0] >= level:
            headings.pop()
        headings.append((level, title))
        positions.append((start, tuple(value for _, value in headings)))
    return positions


def _heading_at(offset: int, positions: list[tuple[int, tuple[str, ...]]]) -> tuple[str, ...]:
    matches = [path for start, path in positions if start <= offset]
    return matches[-1] if matches else ()
