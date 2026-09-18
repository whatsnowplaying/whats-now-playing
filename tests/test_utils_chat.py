#!/usr/bin/env python3
"""Test chat utilities in utils.py"""
# pylint: disable=no-member

import pytest

import nowplaying.utils


def test_smart_split_message_short_message():
    """Test message splitting with message shorter than limit"""
    message = "This is a short message"
    result = nowplaying.utils.smart_split_message(message, max_length=100)

    assert result == [message]


def test_smart_split_message_sentence_boundaries():
    """Test message splitting at sentence boundaries"""
    message = "First sentence. Second sentence! Third sentence?"
    result = nowplaying.utils.smart_split_message(message, max_length=20)

    # Should split at sentence boundaries
    assert len(result) == 3
    assert "First sentence." in result[0]
    assert "Second sentence!" in result[1]
    assert "Third sentence?" in result[2]


def test_smart_split_message_word_boundaries():
    """Test message splitting at word boundaries for long sentences"""
    message = (
        "This is a very long sentence that exceeds the maximum "
        "length limit and should be split at word boundaries"
    )
    result = nowplaying.utils.smart_split_message(message, max_length=30)

    assert len(result) > 1
    for part in result:
        assert len(part) <= 30


def test_smart_split_message_very_long_word():
    """A word with no break point is sliced across parts, not truncated"""
    message = "Supercalifragilisticexpialidocious"
    result = nowplaying.utils.smart_split_message(message, max_length=10)

    assert all(len(part) <= 10 for part in result)
    # Every character survives: dropping the tail would lose content silently
    assert "".join(result) == message


@pytest.mark.parametrize("max_length", [10, 50, 137])
def test_smart_split_message_unbreakable_run_loses_nothing(max_length):
    """A long run with no whitespace must not be truncated to a single part"""
    message = "A" * 300
    result = nowplaying.utils.smart_split_message(message, max_length=max_length)

    assert all(len(part) <= max_length for part in result)
    assert "".join(result) == message


def test_smart_split_message_mixed_content():
    """Test message splitting with mixed sentence and word content"""
    message = (
        "Short sentence. This is a much longer sentence that will "
        "need to be split at word boundaries because it exceeds the "
        "limit. Final short sentence."
    )
    result = nowplaying.utils.smart_split_message(message, max_length=40)

    assert len(result) >= 3
    for part in result:
        assert len(part) <= 40
        assert part.strip()


def test_smart_split_message_preserve_content():
    """Test that message splitting preserves all content"""
    message = "First sentence. Second sentence. Third sentence."
    result = nowplaying.utils.smart_split_message(message, max_length=20)

    reconstructed = " ".join(result)

    assert "First sentence" in reconstructed
    assert "Second sentence" in reconstructed
    assert "Third sentence" in reconstructed


def test_smart_split_message_breaks_on_newline_first():
    """A rendered template's own line breaks outrank sentence punctuation"""
    message = "\n".join(f"Line {index} of the announcement text here." for index in range(8))
    result = nowplaying.utils.smart_split_message(message, max_length=120)

    assert len(result) > 1
    # Every part must start at a line boundary, never mid-line
    for part in result:
        assert part.startswith("Line ")


def test_smart_split_message_keeps_newlines_within_a_part():
    """Lines packed into one message keep their newline, not a space"""
    message = "\n".join(f"Line {index} of the announcement text here." for index in range(8))
    result = nowplaying.utils.smart_split_message(message, max_length=120)

    # 120 chars fits more than one 40-char line, so at least one part is multi-line
    assert any("\n" in part for part in result)
    for part in result:
        assert " Line " not in part, f"newline collapsed into a space: {part!r}"


def test_smart_split_message_breaks_on_blank_line():
    """A blank line is a stronger boundary than a single newline"""
    first = "Now playing something with a reasonably long title here."
    second = "And a second paragraph that also runs on for a while."
    result = nowplaying.utils.smart_split_message(f"{first}\n\n{second}", max_length=60)

    assert result == [first, second]


def test_smart_split_message_breaks_on_pipe_separator():
    """Pipe-delimited announcements break at the pipe, not mid-field"""
    message = (
        "Now playing: Some Artist - Some Title | Album: Some Record "
        "| Label: Some Label | Year: 1996 | Requested by someone"
    )
    result = nowplaying.utils.smart_split_message(message, max_length=60)

    assert len(result) > 1
    for part in result:
        assert len(part) <= 60


@pytest.mark.parametrize(
    "url",
    [
        "https://example.bandcamp.com/album/some-very-long-album-name-here",
        "https://www.discogs.com/artist/1234567-Some-Artist-With-A-Long-Name",
        "www.example.com/a/fairly/long/path/that/keeps/going/for/a/while",
        # a query string: pysbd reads '?' as terminal punctuation
        "https://www.youtube.com/watch?v=Dv1ADnLpLbM&list=PLsomething",
        "https://ex.com/p?q=1&r=2#frag.Next",
    ],
)
@pytest.mark.parametrize("max_length", [100, 200, 500])
def test_smart_split_message_never_breaks_a_url(url, max_length):
    """A split link is useless, so a URL shorter than the limit stays whole"""
    filler = "Now playing a track by an artist you should really look up right now. "
    message = f"{filler * 4}{url} {filler * 4}"
    result = nowplaying.utils.smart_split_message(message, max_length=max_length)

    assert any(url in part for part in result), f"URL was broken across parts: {result}"


def test_smart_split_message_oversized_url_is_sliced_within_the_limit():
    """A URL longer than the limit has to be broken: the platform rejects an over-long part"""
    url = "https://example.com/" + ("segment/" * 20)
    message = f"Check out {url} now"
    result = nowplaying.utils.smart_split_message(message, max_length=50)

    assert all(len(part) <= 50 for part in result)
    assert "".join(result).replace(" ", "") == message.replace(" ", "")


@pytest.mark.parametrize(
    "code",
    [
        # BetterTTV and similar extensions render :text: shortcodes; a code broken
        # across two messages renders as literal text in both
        ":tf:",
        ":Kappa:",
        ":PogChamp:",
        # Punctuation-bearing BTTV globals
        "D:",
        "o.O",
        "(ditto)",
        "M&Mjc",
        "-_-",
        ":z",
        # Kick's own emote markup
        "[emote:1234:kappa]",
        # Plain Twitch/BTTV word codes
        "monkaS",
        "KEKW",
        "5Head",
    ],
)
def test_smart_split_message_never_breaks_an_emote_code(code):
    """Emote codes have no whitespace, so they must survive every split point"""
    # One unbroken clause, so no line/pipe/sentence boundary can absorb the split
    # and the word level is actually exercised
    text = (
        f"now playing a really rather long unbroken clause of text {code} and it keeps going after"
    )

    for max_length in range(20, 121, 2):
        parts = nowplaying.utils.smart_split_message(text, max_length)
        assert any(code in part for part in parts), (
            f"emote {code!r} was broken at max_length={max_length}: {parts}"
        )


@pytest.mark.parametrize("code", [":tf:", "D:", "o.O", "(ditto)", "-_-"])
def test_tokenize_sentences_does_not_split_at_an_emote_code(code):
    """A colon or period inside an emote code is not a sentence boundary"""
    text = f"Great set {code} next track please."

    assert nowplaying.utils.tokenize_sentences(text) == [text]


@pytest.mark.parametrize("max_length", [25, 50, 100, 500])
def test_smart_split_message_various_limits(max_length):
    """Test message splitting with various length limits"""
    message = (
        "This is a test message with multiple sentences. "
        "Each sentence should be handled based on the length limit. "
        "The splitting should work correctly."
    )

    result = nowplaying.utils.smart_split_message(message, max_length=max_length)

    for part in result:
        assert len(part) <= max_length

    assert len(result) >= 1
    assert all(part.strip() for part in result)


def test_smart_split_message_default_limit():
    """Test message splitting uses default limit"""
    message = "A" * 1000  # Very long message

    result = nowplaying.utils.smart_split_message(message)

    for part in result:
        assert len(part) <= 500


def test_smart_split_message_unicode_handling():
    """Test message splitting handles Unicode characters correctly"""
    message = (
        "This message contains émojis 🎵 and spëcial characters. "
        "Ït should be handled correctly! 中文 text as well."
    )

    result = nowplaying.utils.smart_split_message(message, max_length=50)

    assert len(result) >= 1
    for part in result:
        assert len(part) <= 50

    combined = " ".join(result)
    assert "🎵" in combined
    assert "émojis" in combined
    assert "中文" in combined


def test_tokenize_sentences_empty_input():
    """Test sentence tokenization with empty input"""
    result = nowplaying.utils.tokenize_sentences("")
    assert not result


@pytest.mark.parametrize("text", ["", "   ", "\n\n", "\t"])
def test_tokenize_sentences_blank_input(text):
    """Blank text yields no sentences rather than an empty-string sentence"""
    assert nowplaying.utils.tokenize_sentences(text) == []


def test_tokenize_sentences_single_sentence():
    """Test sentence tokenization with single sentence"""
    text = "This is a single sentence"
    result = nowplaying.utils.tokenize_sentences(text)

    assert len(result) >= 1
    assert "single sentence" in " ".join(result)


def test_tokenize_sentences_preserves_punctuation():
    """Punctuation must survive verbatim: _generate_short_bio reads the last character"""
    result = nowplaying.utils.tokenize_sentences("Ends with a period. Ends with a bang!")

    assert result == ["Ends with a period.", "Ends with a bang!"]


def test_tokenize_sentences_does_not_invent_punctuation():
    """A truncated final sentence stays truncated, so callers can detect it"""
    result = nowplaying.utils.tokenize_sentences("A complete sentence. A truncated one that")

    assert result[-1] == "A truncated one that"


@pytest.mark.parametrize(
    "text,expected",
    [
        # A sentence ending in a year is the most common shape in artist bios
        ("Born in Detroit in 1975. He later moved to London.", 2),
        ("The remix runs 3.5 minutes. Critics loved it.", 2),
        ("Produced by J. Dilla in Detroit. The result was Donuts.", 2),
        ("Born in St. Louis in 1975. He later moved to London.", 2),
        ("Signed to Warp Records Inc. in 1996. Then Rephlex.", 2),
        ("Tom Jenkinson, a.k.a. Squarepusher, plays bass. He tours rarely.", 2),
        ("Released in Dec. 1996 on Warp. It charted.", 2),
        ('He called it "genius." Critics agreed.', 2),
        ("The album... was never finished. A shame.", 2),
    ],
)
def test_tokenize_sentences_bio_abbreviations(text, expected):
    """Sentence counts on the abbreviation shapes that actually occur in bios"""
    assert len(nowplaying.utils.tokenize_sentences(text)) == expected


@pytest.mark.parametrize(
    "message",
    [
        # pysbd ends a sentence after 'Exclaim!' mid-sentence; rejoining pieces
        # with a space of our own choosing put one where the original had none
        'Hopkins told Exclaim!, "Now that Singularity is done, I can look ahead" '
        "and the interview went on for quite a while after that point in time.",
        "Hawtin first presented ENTER., his experimental event at Space in Ibiza, "
        "during the summer of 2012 and it ran for several seasons afterwards.",
        "See (https://example.com/some/path) for the full discography and tour dates now",
        'Link: "https://example.com/x" here and more text to force a word level split',
        "Now playing: Artist - Title | Album: Record | Label: Some Label | Year: 1996",
    ],
)
@pytest.mark.parametrize("max_length", [30, 40, 60, 100])
def test_smart_split_message_parts_are_slices_of_the_input(message, max_length):
    """Every part must appear verbatim in the input: no invented separators"""
    result = nowplaying.utils.smart_split_message(message, max_length)

    for part in result:
        assert part in message, f"part is not a substring of the input: {part!r}"


@pytest.mark.parametrize("max_length", [20, 40, 60, 137, 500])
def test_smart_split_message_every_part_within_limit(max_length):
    """The platform rejects an over-long part, so the limit is not advisory"""
    message = (
        "Now playing: Some Artist - Some Title\n"
        "| Bandcamp: https://example.bandcamp.com/album/a-record\n"
        "| Discogs: https://www.discogs.com/artist/45-Aphex-Twin\n"
        "Richard was born in Limerick in 1971. He released his debut in 1991. " + "x" * 200
    )
    result = nowplaying.utils.smart_split_message(message, max_length)

    assert result
    for part in result:
        assert len(part) <= max_length, f"part of {len(part)} exceeds {max_length}: {part!r}"


def test_smart_split_message_packs_after_an_oversized_piece():
    """A short tail following an over-long piece should ride along, not start a new message"""
    message = "x" * 130 + "\nshort tail\nanother short tail"
    result = nowplaying.utils.smart_split_message(message, 60)

    # The 'x' run fills two parts and leaves a 10-character remainder. That
    # remainder has to keep absorbing the short lines instead of closing the
    # message, or Kick sends an extra part and sleeps a second before it.
    assert len(result) == 3, result
    assert result[-1] == "xxxxxxxxxx\nshort tail\nanother short tail"


@pytest.mark.parametrize("delimiter", ["|", "•", "·"])
def test_smart_split_message_drops_a_dangling_separator(delimiter):
    """A continuation opening on a bare delimiter reads as a rendering fault"""
    message = (
        f"Now playing: Some Artist - Some Title {delimiter} Album: Some Record "
        f"{delimiter} Label: Some Label {delimiter} Year: 1996 {delimiter} Requested by someone"
    )
    result = nowplaying.utils.smart_split_message(message, max_length=60)

    assert len(result) > 1
    for part in result[1:]:
        assert not part.startswith(delimiter), f"continuation opens on a delimiter: {part!r}"


def test_smart_split_message_keeps_a_leading_separator_the_author_wrote():
    """Only a continuation loses its delimiter; the start of the message is the author's"""
    message = "| Leading pipe is part of the text here and this runs well past the limit for sure"
    result = nowplaying.utils.smart_split_message(message, max_length=40)

    assert result[0].startswith("|")


def test_smart_split_message_limit_wins_over_url_integrity():
    """A URL longer than the whole limit is sliced: an over-limit part is never sent"""
    message = f"see https://example.com/{'z' * 80} now"
    result = nowplaying.utils.smart_split_message(message, max_length=40)

    assert all(len(part) <= 40 for part in result)
    assert len(result) > 1


@pytest.mark.parametrize("marker", ["•", "·", "|"])
@pytest.mark.parametrize("max_length", [90, 120, 200])
def test_smart_split_message_keeps_line_leading_markers(marker, max_length):
    """A bullet marks its own line, so a continuation must not lose the first one"""
    message = "\n".join(f"{marker} Track {n}: Some Fairly Long Artist Name" for n in range(1, 9))
    result = nowplaying.utils.smart_split_message(message, max_length)

    assert len(result) > 1
    for part in result:
        for line in part.split("\n"):
            assert line.startswith(marker), f"line lost its marker: {line!r} in {part!r}"


@pytest.mark.parametrize("marker", ["•", "·", "|"])
def test_smart_split_message_marks_lines_consistently_within_a_part(marker):
    """Marking item 4 but not item 3 in the same message reads worse than no marking"""
    message = "\n".join(f"{marker} Track {n}: Some Fairly Long Artist Name" for n in range(1, 9))

    for part in nowplaying.utils.smart_split_message(message, 90):
        marked = [line.startswith(marker) for line in part.split("\n")]
        assert all(marked) or not any(marked), f"inconsistent markers within a part: {part!r}"


def test_smart_split_message_keeps_bullets_after_a_blank_line():
    """The paragraph level's trailing whitespace must not look like an inline delimiter"""
    message = (
        "Intro line that is long enough to matter here.\n\n"
        "   • First item here\n   • Second item goes here too"
    )
    result = nowplaying.utils.smart_split_message(message, 50)

    assert any(part.lstrip().startswith("•") for part in result[1:])
