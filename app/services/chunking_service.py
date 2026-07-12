"""Splits cleaned_text into clause-aware chunks, each carrying char_start/
char_end offsets into cleaned_text — the backbone of every citation feature
in later sprints. Never break that invariant here.

Strategy: detect section/clause heading lines first (numbered sections,
"Section N"/"Article N", ALL-CAPS headings) and treat the text between
headings as candidate chunks. Oversized sections are sub-split into
overlapping word windows. Documents with no detectable structure fall back
to paragraph-based chunking.
"""
import re

HEADING_PATTERN = re.compile(
    r"^(?:"
    r"(?:Section|Article)\s+[\dIVXLC]+[.:]?.*"
    r"|\d+(?:\.\d+)*\.\s+[A-Z].*"
    r"|[A-Z][A-Z0-9 ,&/'\-]{4,}"
    r")$",
    re.MULTILINE,
)

# Many real contracts write "1. Confidentiality. <body text...>" as a single
# running paragraph rather than a heading on its own line. HEADING_PATTERN
# above matches to end-of-line (i.e. the whole paragraph) to correctly find
# the *section boundary*, but that's too long for section_label. This
# second pattern trims a heading match down to just the short title.
LABEL_TRIM_PATTERN = re.compile(
    r"^("
    r"(?:Section|Article)\s+[\dIVXLC]+[.:]\s*[A-Za-z][^.\n]{0,60}\."
    r"|\d+(?:\.\d+)*\.\s*[A-Za-z][^.\n]{0,60}\."
    r")"
)

MAX_CHUNK_WORDS = 500
OVERLAP_WORDS = 60


def chunk_document(cleaned_text: str) -> list[dict]:
    chunks: list[dict] = []
    for section_label, section_text, base_offset in _split_into_sections(cleaned_text):
        for text, char_start, char_end in _split_oversized(section_text, base_offset):
            chunks.append(
                {
                    "text": text,
                    "char_start": char_start,
                    "char_end": char_end,
                    "section_label": section_label,
                    "token_count": len(text.split()),
                }
            )
    for index, chunk in enumerate(chunks):
        chunk["chunk_index"] = index
    return chunks


def _split_into_sections(text: str) -> list[tuple[str | None, str, int]]:
    matches = list(HEADING_PATTERN.finditer(text))
    if not matches:
        return _split_into_paragraphs(text)

    sections: list[tuple[str | None, str, int]] = []

    if matches[0].start() > 0:
        preamble = text[: matches[0].start()]
        if preamble.strip():
            sections.append((None, preamble, 0))

    for i, match in enumerate(matches):
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections.append((_short_label(match.group()), text[start:end], start))

    return sections


def _short_label(heading_match_text: str) -> str:
    first_line = heading_match_text.split("\n", 1)[0].strip()
    trimmed = LABEL_TRIM_PATTERN.match(first_line)
    if trimmed:
        return trimmed.group(1).strip()
    return first_line[:100].strip()


def _split_into_paragraphs(text: str) -> list[tuple[str | None, str, int]]:
    sections: list[tuple[str | None, str, int]] = []
    search_from = 0
    for para in re.split(r"\n\s*\n", text):
        if not para.strip():
            continue
        start = text.index(para, search_from)
        sections.append((None, para, start))
        search_from = start + len(para)
    return sections or [(None, text, 0)]


def _split_oversized(section_text: str, base_offset: int) -> list[tuple[str, int, int]]:
    tokens = list(re.finditer(r"\S+", section_text))
    if len(tokens) <= MAX_CHUNK_WORDS:
        return [(section_text, base_offset, base_offset + len(section_text))]

    windows: list[tuple[str, int, int]] = []
    step = MAX_CHUNK_WORDS - OVERLAP_WORDS
    i = 0
    while True:
        window_tokens = tokens[i : i + MAX_CHUNK_WORDS]
        start = window_tokens[0].start()
        end = window_tokens[-1].end()
        windows.append((section_text[start:end], base_offset + start, base_offset + end))
        if i + MAX_CHUNK_WORDS >= len(tokens):
            break
        i += step
    return windows
