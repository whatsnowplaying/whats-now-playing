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
        ("HTTP://example.com/", "https://example.com/"),
        ("example.com/", "https://example.com/"),
    ],
)
def test_https_wins_over_any_other_spelling(first, second):
    """Whatever the other spelling is -- http, HTTP, scheme-less -- https wins"""
    assert nowplaying.utils.websites.merge_websites([first], [second]) == ["https://example.com/"]


@pytest.mark.parametrize(
    "left,right",
    [
        # paths are case-sensitive; wikidata puts a capital in one
        ("https://www.wikidata.org/wiki/Q175195", "https://www.wikidata.org/wiki/q175195"),
        ("https://example.com/Artist", "https://example.com/artist"),
    ],
)
def test_path_case_is_significant(left, right):
    """Only the host folds case, so differing paths stay separate entries"""
    assert nowplaying.utils.websites.merge_websites([left], [right]) == [left, right]


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
