#!/usr/bin/env python3
"""Test artistwebsites merging and canonicalization"""

import pytest

import nowplaying.utils.websites


@pytest.mark.parametrize(
    "left,right",
    [
        ("https://www.discogs.com/artist/11136", "https://discogs.com/artist/11136"),
        ("https://petergabriel.com/", "https://petergabriel.com"),
        ("https://Example.COM/Artist", "https://example.com/Artist"),
    ],
)
def test_same_resource_collapses(left, right):
    """Two spellings of one resource yield a single entry"""
    assert nowplaying.utils.websites.merge_websites([left], [right]) == [left]


@pytest.mark.parametrize(
    "first,second",
    [
        ("http://example.com/", "https://example.com/"),
        ("https://example.com/", "http://example.com/"),
    ],
)
def test_https_wins_regardless_of_order(first, second):
    """An http spelling is upgraded when the https one also shows up"""
    assert nowplaying.utils.websites.merge_websites([first], [second]) == ["https://example.com/"]


def test_distinct_resources_survive_in_order():
    """Merging keeps everything that is genuinely different, in provider order"""
    result = nowplaying.utils.websites.merge_websites(
        ["https://musicbrainz.org/artist/8e66ea2b", "https://www.discogs.com/artist/11136"],
        ["https://discogs.com/artist/11136", "https://petergabriel.com/"],
    )
    assert result == [
        "https://musicbrainz.org/artist/8e66ea2b",
        "https://www.discogs.com/artist/11136",
        "https://petergabriel.com/",
    ]


def test_empty_and_junk_input():
    """Providers emit empty lists and occasional None"""
    assert not nowplaying.utils.websites.merge_websites(None, [], [None, "", "   "])
