"""Source-preserving windows for judging and displaying search evidence."""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class SourcePassage:
    text: str
    start: int
    end: int


def sentences(content: str) -> list[SourcePassage]:
    # Keep source offsets, including punctuation; newlines also delimit list items.
    return [SourcePassage(m.group(), m.start(), m.end()) for m in re.finditer(
        r'.+?(?:[。！？!?]+|(?<=\.)\s+|\n+|$)', content, re.DOTALL)]


def source_window(content: str, fragment: str, *, width: int = 650) -> SourcePassage | None:
    position = content.find(fragment)
    if position < 0 or not fragment:
        return None
    units = sentences(content)
    first = next((i for i, unit in enumerate(units) if unit.end > position), 0)
    last = next((i for i, unit in enumerate(units) if unit.end >= position + len(fragment)), len(units) - 1)
    start, end = units[first].start, units[last].end
    # Very long unpunctuated source material must still have bounded input.
    if end - start > width:
        start = max(start, position - min(80, width // 4))
        end = min(end, max(start + width, position + len(fragment)))
    else:
        while first > 0 and end - units[first - 1].start <= width:
            first -= 1
            start = units[first].start
        while last + 1 < len(units) and units[last + 1].end - start <= width:
            last += 1
            end = units[last].end
    return SourcePassage(content[start:end], start, end)


def evidence_windows(passage: SourcePassage, *, width: int = 260) -> list[SourcePassage]:
    """Overlapping complete-sentence windows; scores choose the quote, not position."""
    if '\n\n' in passage.text:
        paragraph_windows = []
        cursor = passage.start
        for paragraph in passage.text.split('\n\n'):
            if paragraph.strip():
                paragraph_windows.extend(evidence_windows(SourcePassage(paragraph,
                    cursor, cursor + len(paragraph)), width=width))
            cursor += len(paragraph) + 2
        return paragraph_windows
    units = sentences(passage.text)
    # A question and its immediately following response form one evidence unit.
    # Otherwise a model can select a restatement of the query and leave the
    # actual answer just outside the display boundary.
    combined: list[SourcePassage] = []
    index = 0
    while index < len(units):
        first = units[index]
        last = first
        while last.text.rstrip().endswith(('?', '？')) and index + 1 < len(units):
            index += 1
            last = units[index]
        combined.append(SourcePassage(passage.text[first.start:last.end], first.start, last.end))
        index += 1
    units = combined
    windows: list[SourcePassage] = []
    for i, unit in enumerate(units):
        end = unit.end
        for following in units[i + 1:]:
            heading = following.text.strip()
            if (following.text.endswith('\n') and 0 < len(heading) <= 32
                    and not re.search(r'[。！？.!?，,；;：:]$', heading)):
                break
            if following.end - unit.start > width:
                break
            end = following.end
        # Don't silently cut the answer off in a long sentence.
        value = SourcePassage(passage.text[unit.start:end], passage.start + unit.start,
            passage.start + end)
        if value.text.strip() and (not windows or value.end != windows[-1].end):
            windows.append(value)
    return windows or [passage]
