"""Pure source-span splitters; structural heuristics, never semantic inference."""

from __future__ import annotations

import re
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from typing import Protocol

from w_agent.knowledge_context import _text


@dataclass(frozen=True, slots=True)
class KnowledgeTextSpan:
    """Half-open original-text Unicode and UTF-8 byte offsets."""

    char_start: int
    char_end: int
    byte_start: int
    byte_end: int

    def __post_init__(self) -> None:
        if (any(type(value) is not int for value in (self.char_start, self.char_end, self.byte_start, self.byte_end))
                or not 0 <= self.char_start < self.char_end or not 0 <= self.byte_start < self.byte_end):
            raise ValueError("invalid knowledge text span")


class KnowledgeSpanSplitter(Protocol):
    """Replaceable trusted pure span producer; never transforms original text."""

    def split_spans(self, text: str) -> tuple[KnowledgeTextSpan, ...]: ...


@dataclass(frozen=True, slots=True)
class StructureKnowledgeSpanSplitter:
    """Prefer paragraph, then sentence endings in the latter half of a window.

    Hard fallback is Unicode-character aligned, not grapheme/token aligned.
    overlap_chars is a maximum exact-codepoint suffix, shortened only to ensure
    forward progress. Its conservative bound reserves half the UTF-8 window
    even for four-byte codepoints. No language/model/embedding calls occur.
    """

    max_chunk_bytes: int = 4096
    overlap_chars: int = 0

    def __post_init__(self) -> None:
        if type(self.max_chunk_bytes) is not int or not 4 <= self.max_chunk_bytes <= 1024 * 1024:
            raise ValueError("knowledge chunk size must be between 4 bytes and 1 MiB")
        if type(self.overlap_chars) is not int or not 0 <= self.overlap_chars <= min(1024, self.max_chunk_bytes // 8):
            raise ValueError("overlap must fit the bounded half-window character budget")

    def split_spans(self, text: str) -> tuple[KnowledgeTextSpan, ...]:
        _text(text, 1024 * 1024, empty=True)
        if not text.strip():
            return ()
        byte_offsets = [0]
        for char in text:
            byte_offsets.append(byte_offsets[-1] + len(char.encode("utf-8")))
        paragraphs = [match.end() for match in re.finditer(r"(?:\r?\n)[ \t]*(?:\r?\n)+", text)]
        sentences = [match.end() for match in re.finditer(r"[。！？]|[.!?](?:[ \t]+|(?=\r?\n|$))", text)]
        spans = []
        start = previous_end = 0
        output_bytes = 0
        while start < len(text):
            hard_end = bisect_right(byte_offsets, byte_offsets[start] + self.max_chunk_bytes) - 1
            end = hard_end
            if hard_end < len(text):
                minimum = max(previous_end + 1, bisect_left(byte_offsets, byte_offsets[start] + self.max_chunk_bytes // 2))
                for boundaries in (paragraphs, sentences):
                    position = bisect_right(boundaries, hard_end) - 1
                    if position >= 0 and boundaries[position] >= minimum:
                        end = boundaries[position]
                        break
            if end <= previous_end or end <= start:
                raise ValueError("knowledge spans must make forward progress")
            if text[start:end].strip():
                spans.append(KnowledgeTextSpan(start, end, byte_offsets[start], byte_offsets[end]))
                output_bytes += byte_offsets[end] - byte_offsets[start]
                if len(spans) > 1024 or output_bytes > 16 * 1024 * 1024:
                    raise ValueError("knowledge span expansion exceeds limit")
            if end == len(text):
                break
            previous_end = end
            start = end - min(self.overlap_chars, end - start - 1)
        return tuple(spans)

    def split(self, text: str) -> tuple[str, ...]:
        """Adapt existing KnowledgeTextSplitter; spans remain authoritative."""
        return tuple(text[span.char_start:span.char_end] for span in self.split_spans(text))
