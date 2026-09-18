#!/usr/bin/env python3
"""sentence and message splitting

Two callers want opposite things, so there are two entry points:

* :func:`tokenize_sentences` finds sentence boundaries in provider biography
  prose, for deriving ``artistshortbio`` from ``artistlongbio``.
* :func:`smart_split_message` breaks rendered Jinja template output into
  platform-sized chat messages. That text is machine-generated -- pipes,
  emoji, URLs, deliberate newlines -- so it breaks on structure first and
  only falls back to sentences.

Message splitting works in offsets rather than strings: each level proposes
byte positions where a break is allowed, and every part is handed back as a
slice of the original. Rejoining pieces with a separator of our own choosing
is what corrupts text, because the separator we pick is rarely the one that
was there -- pysbd ends a sentence after "told Exclaim!" and a space appears
where the original had none.
"""

import dataclasses
import re

import pysbd

# Scheme-qualified or bare-domain links. Break positions falling inside one
# are discarded, so a link only ever splits when it is itself longer than the
# whole message limit.
_URL = re.compile(r"(?:[a-z][a-z0-9+.-]*://|www\.)\S+", re.IGNORECASE)

_PARAGRAPH = re.compile(r"\n[ \t]*\n\s*")
_LINE = re.compile(r"\n")
# Separators DJs use to build one-line announcements.
_INLINE_SEPARATOR = re.compile(r"\s+(?=[|•·]\s)")
_LEADING_SEPARATOR = re.compile(r"^[|•·]\s*")
_WHITESPACE = re.compile(r"\s+")


def _segmenter() -> pysbd.Segmenter:
    """Build a segmenter.

    pysbd.Segmenter.segment() stores the input on the instance for
    sentences_with_char_spans(), so a shared instance is not reentrant. The
    constructor costs well under a microsecond, so there is nothing to gain
    by caching one.

    clean=False keeps the original text untouched, which both callers need:
    _generate_short_bio tells a complete final sentence from a truncated one
    by its last character, and offsets have to stay meaningful.
    """
    return pysbd.Segmenter(language="en", clean=False)


def tokenize_sentences(text: str) -> list[str]:
    """Split prose into sentences.

    Punctuation is preserved exactly as written and nothing is appended, so a
    caller can tell a complete final sentence from one truncated mid-way.
    """
    if not text or not text.strip():
        return []
    return [sentence for sentence in (s.strip() for s in _segmenter().segment(text)) if sentence]


def _paragraph_breaks(text: str, start: int, end: int) -> list[int]:
    return [match.end() for match in _PARAGRAPH.finditer(text, start, end)]


def _line_breaks(text: str, start: int, end: int) -> list[int]:
    return [match.end() for match in _LINE.finditer(text, start, end)]


def _separator_breaks(text: str, start: int, end: int) -> list[int]:
    return [match.end() for match in _INLINE_SEPARATOR.finditer(text, start, end)]


def _sentence_breaks(text: str, start: int, end: int) -> list[int]:
    """Offsets between sentences, or nothing if they cannot be mapped back."""
    chunk = text[start:end]
    sentences = _segmenter().segment(chunk)
    if "".join(sentences) != chunk:
        # pysbd normalizes some whitespace, and a position we cannot trust is
        # worse than none -- the word level below is exact.
        return []
    breaks: list[int] = []
    cursor = start
    for sentence in sentences[:-1]:
        cursor += len(sentence)
        breaks.append(cursor)
    return breaks


def _word_breaks(text: str, start: int, end: int) -> list[int]:
    return [match.end() for match in _WHITESPACE.finditer(text, start, end)]


def _starts_a_line(text: str, position: int) -> bool:
    """Whether the whitespace run before position contains a newline.

    Tells a line-leading marker from an inline one without guessing at the
    character. A break from _line_breaks or _paragraph_breaks has a newline
    behind it; one from _separator_breaks has only spaces, because its regex
    consumes just the whitespace ahead of the delimiter. Scanning the whole
    run rather than a single character matters for the paragraph level, whose
    trailing \\s* can leave spaces between the newline and the break.
    """
    index = position - 1
    while index >= 0 and text[index].isspace():
        if text[index] == "\n":
            return True
        index -= 1
    return False


_LEVELS = (
    _paragraph_breaks,
    _line_breaks,
    _separator_breaks,
    _sentence_breaks,
    _word_breaks,
)


@dataclasses.dataclass(frozen=True)
class _Splitter:
    """The parts of a split that stay fixed for the whole recursion."""

    text: str
    max_length: int
    urls: list[tuple[int, int]]

    def breaks(self, level: int, start: int, end: int) -> list[int]:
        """Break offsets this level offers inside (start, end), URLs excluded."""
        return sorted(
            {
                position
                for position in _LEVELS[level](self.text, start, end)
                if start < position < end
                and not any(begin < position < finish for begin, finish in self.urls)
            }
        )

    def split(self, start: int, end: int, level: int = 0) -> list[tuple[int, int]]:
        """Cover [start, end) with spans no longer than max_length."""
        if end - start <= self.max_length:
            return [(start, end)]

        while level < len(_LEVELS):
            if breaks := self.breaks(level, start, end):
                return self.pack(start, end, breaks, level + 1)
            level += 1

        # Nothing left to break on, so slice. Losing the tail would drop content.
        return [(at, min(at + self.max_length, end)) for at in range(start, end, self.max_length)]

    def pack(
        self, start: int, end: int, breaks: list[int], next_level: int
    ) -> list[tuple[int, int]]:
        """Greedily merge adjacent pieces, breaking any that still do not fit."""
        bounds = [start, *breaks, end]
        spans: list[tuple[int, int]] = []
        span_start = start
        index = 1

        while index < len(bounds):
            reach = index
            while reach < len(bounds) and bounds[reach] - span_start <= self.max_length:
                reach += 1
            if reach > index:
                spans.append((span_start, bounds[reach - 1]))
                span_start = bounds[reach - 1]
                index = reach
                continue
            # This piece alone is over the limit; break it at a finer level and
            # keep packing into its tail, so a short piece after it can still join.
            pieces = self.split(span_start, bounds[index], next_level)
            spans.extend(pieces[:-1])
            span_start = pieces[-1][0]
            index += 1

        if span_start < end:
            spans.append((span_start, end))
        return spans


def smart_split_message(message: str, max_length: int = 500) -> list[str]:
    """Split a rendered template into messages that fit a platform's limit.

    Breaks on paragraphs, then lines, then inline separators, then sentences,
    then words, and slices a run with no break point rather than dropping its
    tail.

    Every part is within max_length -- that one is absolute, because a part
    over the limit is rejected outright and the caller reports the whole
    announcement as failed. Parts are otherwise slices of the input, give or
    take surrounding whitespace and a leading field separator.

    Breaks avoid landing inside a URL or a BetterTTV-style ``:text:`` emote
    code, but max_length wins where they conflict: a URL longer than the whole
    limit is sliced, since the alternative is not sending it at all. An emote
    code containing a space -- the kaomoji-style BTTV globals -- can also be
    broken; recognising those would mean knowing the channel's emote list.
    """
    if len(message) <= max_length:
        return [message]
    urls = [(match.start(), match.end()) for match in _URL.finditer(message)]
    spans = _Splitter(message, max_length, urls).split(0, len(message))

    parts: list[str] = []
    for position, (begin, finish) in enumerate(spans):
        part = message[begin:finish].strip()
        # An inline delimiter joins fields on one line, so once the break puts
        # them in separate messages it has no job left and a continuation
        # opening on a bare "|" reads as a rendering fault. A line-leading
        # bullet is different: it marks its item, and dropping just the first
        # one leaves a message whose items are inconsistently marked.
        if position and not _starts_a_line(message, begin):
            part = _LEADING_SEPARATOR.sub("", part)
        if part:
            parts.append(part)
    return parts
