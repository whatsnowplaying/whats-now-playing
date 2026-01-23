#!/usr/bin/env python3
"""test the trackpoller"""

import asyncio
import logging
import pathlib
import unittest.mock

import pytest  # pylint: disable=import-error
import pytest_asyncio  # pylint: disable=import-error

import nowplaying.db  # pylint: disable=import-error
import nowplaying.trackrequests  # pylint: disable=import-error


@pytest_asyncio.fixture
async def trackrequestbootstrap(bootstrap, getroot):  # pylint: disable=redefined-outer-name
    """bootstrap a configuration"""
    stopevent = asyncio.Event()
    config = bootstrap
    config.cparser.setValue("settings/input", "jsonreader")
    playlistpath = pathlib.Path(getroot).joinpath("tests", "playlists", "json", "test.json")
    config.pluginobjs["inputs"]["nowplaying.inputs.jsonreader"].load_playlists(
        getroot, playlistpath
    )
    config.cparser.sync()
    yield nowplaying.trackrequests.Requests(stopevent=stopevent, config=config, testmode=True)
    stopevent.set()
    await asyncio.sleep(2)


@pytest.mark.asyncio
async def test_trackrequest_artisttitlenoquote(trackrequestbootstrap):  # pylint: disable=redefined-outer-name
    """artist - title"""

    trackrequest = trackrequestbootstrap

    data = await trackrequest.user_track_request({"displayname": "test"}, "user", "artist - title")
    assert data["artist"] == "artist"
    assert data["title"] == "title"
    assert data["requester"] == "user"
    assert data["requestdisplayname"] == "test"


@pytest.mark.asyncio
async def test_trackrequest_artisttitlenoquotespaces(trackrequestbootstrap):  # pylint: disable=redefined-outer-name
    """artist - title"""

    trackrequest = trackrequestbootstrap

    data = await trackrequest.user_track_request(
        {"displayname": "test"}, "user", "      artist     -      title    "
    )
    assert data["artist"] == "artist"
    assert data["title"] == "title"
    assert data["requester"] == "user"
    assert data["requestdisplayname"] == "test"


@pytest.mark.asyncio
async def test_trackrequest_artisttitlenoquotecomplex(trackrequestbootstrap):  # pylint: disable=redefined-outer-name
    """artist - title"""

    trackrequest = trackrequestbootstrap

    data = await trackrequest.user_track_request(
        {"displayname": "test"},
        "user",
        "      prince and the revolution     -      purple rain    ",
    )
    assert data["artist"] == "prince and the revolution"
    assert data["title"] == "purple rain"
    assert data["requester"] == "user"
    assert data["requestdisplayname"] == "test"


@pytest.mark.asyncio
async def test_trackrequest_artisttitlequotes(trackrequestbootstrap):  # pylint: disable=redefined-outer-name
    """artist - "title" """

    trackrequest = trackrequestbootstrap

    data = await trackrequest.user_track_request(
        {"displayname": "test"}, "user", 'artist - "title"'
    )
    assert data["artist"] == "artist"
    assert data["title"] == "title"
    assert data["requester"] == "user"
    assert data["requestdisplayname"] == "test"


@pytest.mark.asyncio
async def test_trackrequest_artisttitlequotesspaces(trackrequestbootstrap):  # pylint: disable=redefined-outer-name
    """artist - "title" """

    trackrequest = trackrequestbootstrap

    data = await trackrequest.user_track_request(
        {"displayname": "test"}, "user", '    artist    -     "title"   '
    )
    assert data["artist"] == "artist"
    assert data["title"] == "title"
    assert data["requester"] == "user"
    assert data["requestdisplayname"] == "test"


@pytest.mark.asyncio
async def test_trackrequest_titlequotesartist(trackrequestbootstrap):  # pylint: disable=redefined-outer-name
    """ "title" - artist"""

    trackrequest = trackrequestbootstrap

    data = await trackrequest.user_track_request(
        {"displayname": "test"}, "user", '"title" - artist'
    )
    assert data["artist"] == "artist"
    assert data["title"] == "title"
    assert data["requester"] == "user"
    assert data["requestdisplayname"] == "test"


@pytest.mark.asyncio
async def test_trackrequest_titlequotesbyartist(trackrequestbootstrap):  # pylint: disable=redefined-outer-name
    """title by artist"""

    trackrequest = trackrequestbootstrap

    data = await trackrequest.user_track_request(
        {"displayname": "test"}, "user", '"title" by artist'
    )
    assert data["artist"] == "artist"
    assert data["title"] == "title"
    assert data["requester"] == "user"
    assert data["requestdisplayname"] == "test"


@pytest.mark.asyncio
async def test_trackrequest_quotedweirdal(trackrequestbootstrap):  # pylint: disable=redefined-outer-name
    """weird al is weird"""

    trackrequest = trackrequestbootstrap

    data = await trackrequest.user_track_request(
        {"displayname": "test"}, "user", '"Weird Al" Yankovic - This Is The Life.'
    )
    assert data["artist"] == '"Weird Al" Yankovic'
    assert data["title"] == "This Is The Life."
    assert data["requester"] == "user"
    assert data["requestdisplayname"] == "test"


@pytest.mark.asyncio
async def test_trackrequest_quotedchampagne(trackrequestbootstrap):  # pylint: disable=redefined-outer-name
    """weird al is weird"""

    trackrequest = trackrequestbootstrap

    data = await trackrequest.user_track_request(
        {"displayname": "test"}, "user", 'Evelyn "Champagne" King - "I\'m In Love"'
    )
    assert data["artist"] == 'Evelyn "Champagne" King'
    assert data["title"] == "I'm In Love"
    assert data["requester"] == "user"
    assert data["requestdisplayname"] == "test"


@pytest.mark.asyncio
async def test_trackrequest_xtcfornigel(trackrequestbootstrap):  # pylint: disable=redefined-outer-name
    """for part of the title"""

    trackrequest = trackrequestbootstrap

    data = await trackrequest.user_track_request(
        {"displayname": "test"}, "user", "xtc - making plans for nigel"
    )
    assert data["artist"] == "xtc"
    assert data["title"] == "making plans for nigel"
    assert data["requester"] == "user"
    assert data["requestdisplayname"] == "test"


@pytest.mark.asyncio
async def test_trackrequest_xtcforatnigel(trackrequestbootstrap):  # pylint: disable=redefined-outer-name
    """for @user test"""

    trackrequest = trackrequestbootstrap

    data = await trackrequest.user_track_request(
        {"displayname": "test"}, "user", "xtc - making plans for @nigel"
    )
    assert data["artist"] == "xtc"
    assert data["title"] == "making plans"
    assert data["requester"] == "user"
    assert data["requestdisplayname"] == "test"


@pytest.mark.asyncio
async def test_trackrequest_nospace(trackrequestbootstrap):  # pylint: disable=redefined-outer-name
    """artist-title"""

    trackrequest = trackrequestbootstrap

    data = await trackrequest.user_track_request({"displayname": "test"}, "user", "artist-title")
    assert data["artist"] == "artist"
    assert data["title"] == "title"
    assert data["requester"] == "user"
    assert data["requestdisplayname"] == "test"


@pytest.mark.asyncio
async def test_trackrequest_rouletterequest(trackrequestbootstrap):  # pylint: disable=redefined-outer-name
    """artist-title"""

    trackrequest = trackrequestbootstrap
    logging.debug(trackrequest.databasefile)
    trackrequest.clear_roulette_artist_dupes()
    trackrequest.config.cparser.setValue("settings/requests", True)
    trackrequest.config.cparser.sync()

    data = await trackrequest.user_roulette_request(
        {"displayname": "test", "playlist": "testlist"}, "user", "artist-title"
    )
    assert data["requester"] == "user"
    assert data["requestdisplayname"] == "test"

    data = await trackrequest.get_request({"artist": "Nine Inch Nails", "title": "15 Ghosts II"})
    assert data["requester"] == "user"
    assert data["requestdisplayname"] == "test"
    assert data["requesterimageraw"]


@pytest.mark.asyncio
async def test_trackrequest_rouletterequest_normalized(trackrequestbootstrap):  # pylint: disable=redefined-outer-name
    """artist-title"""

    trackrequest = trackrequestbootstrap
    logging.debug(trackrequest.databasefile)
    trackrequest.clear_roulette_artist_dupes()
    trackrequest.config.cparser.setValue("settings/requests", True)
    trackrequest.config.cparser.sync()

    data = await trackrequest.user_roulette_request(
        {"displayname": "test", "playlist": "testlist"}, "user", "artist-title"
    )
    assert data["requester"] == "user"
    assert data["requestdisplayname"] == "test"

    data = await trackrequest.get_request({"artist": "Níne Ínch Näíls", "title": "15 Ghosts II"})
    assert data["requester"] == "user"
    assert data["requestdisplayname"] == "test"
    assert data["requesterimageraw"]


@pytest.mark.asyncio
async def test_trackrequest_getrequest_artist(trackrequestbootstrap):  # pylint: disable=redefined-outer-name
    """artist-title"""

    trackrequest = trackrequestbootstrap
    logging.debug(trackrequest.databasefile)
    trackrequest.clear_roulette_artist_dupes()
    trackrequest.config.cparser.setValue("settings/requests", True)
    trackrequest.config.cparser.sync()
    trackrequest = trackrequestbootstrap

    data = await trackrequest.user_track_request(
        {"displayname": "test"}, "user", "Nine Inch Nails"
    )
    logging.debug(data)
    assert data["requestartist"] == "Nine Inch Nails"
    assert not data["requesttitle"]

    data = await trackrequest.get_request({"artist": "Níne Ínch Näíls", "title": "15 Ghosts II"})
    assert data["requester"] == "user"
    assert data["requestdisplayname"] == "test"
    assert data["requesterimageraw"]


@pytest.mark.asyncio
async def test_trackrequest_getrequest_title(trackrequestbootstrap):  # pylint: disable=redefined-outer-name
    """artist-title"""

    trackrequest = trackrequestbootstrap
    logging.debug(trackrequest.databasefile)
    trackrequest.clear_roulette_artist_dupes()
    trackrequest.config.cparser.setValue("settings/requests", True)
    trackrequest.config.cparser.sync()
    trackrequest = trackrequestbootstrap

    data = await trackrequest.user_track_request({"displayname": "test"}, "user", '"15 Ghosts II"')
    logging.debug(data)
    assert not data["requestartist"]
    assert data["requesttitle"] == "15 Ghosts II"

    data = await trackrequest.get_request({"artist": "Níne Ínch Näíls", "title": "15 Ghosts II"})
    assert data["requester"] == "user"
    assert data["requestdisplayname"] == "test"
    assert data["requesterimageraw"]


@pytest.mark.asyncio
async def test_trackrequest_fuzzy_artist_typo(trackrequestbootstrap):  # pylint: disable=redefined-outer-name
    """Test fuzzy matching with artist typo that normalization won't fix"""

    trackrequest = trackrequestbootstrap
    trackrequest.clear_roulette_artist_dupes()
    trackrequest.config.cparser.setValue("settings/requests", True)
    trackrequest.config.cparser.sync()

    # Add request with correct spelling
    data = await trackrequest.user_track_request(
        {"displayname": "test"}, "user", "Radiohead - Creep"
    )
    assert data["requestartist"] == "Radiohead"
    assert data["requesttitle"] == "Creep"

    # Try to match with typo in artist name - should work via fuzzy matching
    data = await trackrequest.get_request({"artist": "Radioheed", "title": "Creep"})
    assert data["requester"] == "user"
    assert data["requestdisplayname"] == "test"
    assert data["requesterimageraw"]


@pytest.mark.asyncio
async def test_trackrequest_fuzzy_title_typo(trackrequestbootstrap):  # pylint: disable=redefined-outer-name
    """Test fuzzy matching with title typo that normalization won't fix"""

    trackrequest = trackrequestbootstrap
    trackrequest.clear_roulette_artist_dupes()
    trackrequest.config.cparser.setValue("settings/requests", True)
    trackrequest.config.cparser.sync()

    # Add request with correct spelling
    data = await trackrequest.user_track_request(
        {"displayname": "test"}, "user", "Beatles - Yesterday"
    )
    assert data["requestartist"] == "Beatles"
    assert data["requesttitle"] == "Yesterday"

    # Try to match with typo in title - should work via fuzzy matching
    data = await trackrequest.get_request({"artist": "Beatles", "title": "Yestrday"})
    assert data["requester"] == "user"
    assert data["requestdisplayname"] == "test"
    assert data["requesterimageraw"]


@pytest.mark.asyncio
async def test_trackrequest_fuzzy_both_typos(trackrequestbootstrap):  # pylint: disable=redefined-outer-name
    """Test fuzzy matching with typos in both artist and title"""

    trackrequest = trackrequestbootstrap
    trackrequest.clear_roulette_artist_dupes()
    trackrequest.config.cparser.setValue("settings/requests", True)
    trackrequest.config.cparser.sync()

    # Add request with correct spelling
    data = await trackrequest.user_track_request(
        {"displayname": "test"}, "user", "Led Zeppelin - Stairway to Heaven"
    )
    assert data["requestartist"] == "Led Zeppelin"
    assert data["requesttitle"] == "Stairway to Heaven"

    # Try to match with typos in both - should work via fuzzy matching
    data = await trackrequest.get_request({"artist": "Led Zeplin", "title": "Stairway to Heavan"})
    assert data["requester"] == "user"
    assert data["requestdisplayname"] == "test"
    assert data["requesterimageraw"]


@pytest.mark.asyncio
async def test_trackrequest_fuzzy_no_match_too_different(trackrequestbootstrap):  # pylint: disable=redefined-outer-name
    """Test that fuzzy matching doesn't match when strings are too different"""

    trackrequest = trackrequestbootstrap
    trackrequest.clear_roulette_artist_dupes()
    trackrequest.config.cparser.setValue("settings/requests", True)
    trackrequest.config.cparser.sync()

    # Add request
    data = await trackrequest.user_track_request(
        {"displayname": "test"}, "user", "Pink Floyd - Comfortably Numb"
    )
    assert data["requestartist"] == "Pink Floyd"
    assert data["requesttitle"] == "Comfortably Numb"

    # Try to match with completely different artist/title - should NOT match
    data = await trackrequest.get_request({"artist": "Madonna", "title": "Like a Virgin"})
    assert data is None


@pytest.mark.asyncio
async def test_trackrequest_fuzzy_artist_only(trackrequestbootstrap):  # pylint: disable=redefined-outer-name
    """Test fuzzy matching with artist-only request"""

    trackrequest = trackrequestbootstrap
    trackrequest.clear_roulette_artist_dupes()
    trackrequest.config.cparser.setValue("settings/requests", True)
    trackrequest.config.cparser.sync()

    # Add artist-only request
    data = await trackrequest.user_track_request({"displayname": "test"}, "user", "Nirvana")
    assert data["requestartist"] == "Nirvana"
    assert not data["requesttitle"]

    # Try to match with typo in artist name - should work via fuzzy matching
    data = await trackrequest.get_request(
        {"artist": "Nirvanna", "title": "Smells Like Teen Spirit"}
    )
    assert data["requester"] == "user"
    assert data["requestdisplayname"] == "test"
    assert data["requesterimageraw"]


@pytest.mark.asyncio
async def test_trackrequest_fuzzy_with_filler_words(trackrequestbootstrap):  # pylint: disable=redefined-outer-name
    """Test fuzzy matching with filler words like 'play anything by ... please'"""

    trackrequest = trackrequestbootstrap
    trackrequest.clear_roulette_artist_dupes()
    trackrequest.config.cparser.setValue("settings/requests", True)
    trackrequest.config.cparser.sync()

    # Add request with normal format
    data = await trackrequest.user_track_request(
        {"displayname": "test"}, "user", "Nine Inch Nails"
    )
    assert data["requestartist"] == "Nine Inch Nails"
    assert not data["requesttitle"]

    # Try to match with filler words and typo - should work via fuzzy matching
    data = await trackrequest.get_request(
        {"artist": "play anything by nine inche nails please", "title": "Head Like a Hole"}
    )
    assert data["requester"] == "user"
    assert data["requestdisplayname"] == "test"
    assert data["requesterimageraw"]


@pytest.mark.asyncio
async def test_trackrequest_fuzzy_thank_you_song(trackrequestbootstrap):  # pylint: disable=redefined-outer-name
    """Test that songs with filler words in title still match (e.g., Dido - Thank You)"""

    trackrequest = trackrequestbootstrap
    trackrequest.clear_roulette_artist_dupes()
    trackrequest.config.cparser.setValue("settings/requests", True)
    trackrequest.config.cparser.sync()

    # Add request with "Thank You" in the title
    data = await trackrequest.user_track_request(
        {"displayname": "test"}, "user", "Dido - Thank You"
    )
    assert data["requestartist"] == "Dido"
    assert data["requesttitle"] == "Thank You"

    # Should match exactly despite "Thank You" being a filler phrase
    data = await trackrequest.get_request({"artist": "Dido", "title": "Thank You"})
    assert data["requester"] == "user"
    assert data["requestdisplayname"] == "test"
    assert data["requesterimageraw"]


@pytest.mark.asyncio
async def test_trackrequest_fuzzy_threshold_prevents_bad_matches(trackrequestbootstrap):  # pylint: disable=redefined-outer-name
    """Test that fuzzy matching threshold prevents very poor matches"""

    trackrequest = trackrequestbootstrap
    trackrequest.clear_roulette_artist_dupes()
    trackrequest.config.cparser.setValue("settings/requests", True)
    trackrequest.config.cparser.sync()

    # Add request for specific artist/title
    data = await trackrequest.user_track_request(
        {"displayname": "test"}, "user", "Beatles - Yesterday"
    )
    assert data["requestartist"] == "Beatles"
    assert data["requesttitle"] == "Yesterday"

    # Try to match with completely different content - should NOT match
    data = await trackrequest.get_request(
        {"artist": "Death Metal Band", "title": "Screaming Agony"}
    )
    assert data is None


@pytest.mark.asyncio
async def test_trackrequest_fuzzy_multiple_requests_picks_best(trackrequestbootstrap):  # pylint: disable=redefined-outer-name
    """Test that fuzzy matching picks the best match when multiple requests exist"""

    trackrequest = trackrequestbootstrap
    trackrequest.clear_roulette_artist_dupes()
    trackrequest.config.cparser.setValue("settings/requests", True)
    trackrequest.config.cparser.sync()

    # Add multiple requests with similar but different names
    await trackrequest.user_track_request(
        {"displayname": "test1"}, "user1", "Red Hot Chili Peppers"
    )
    await trackrequest.user_track_request(
        {"displayname": "test2"},
        "user2",
        "Red Hot Chilli Papers",  # deliberate typos
    )

    # Should match the first one (better match) not the second
    data = await trackrequest.get_request(
        {"artist": "Red Hot Chili Peppers", "title": "Under the Bridge"}
    )
    assert data["requester"] == "user1"  # Should match the exact spelling, not the typo version
    assert data["requestdisplayname"] == "test1"


@pytest.mark.asyncio
async def test_trackrequest_fuzzy_doesnt_match_partial_words(trackrequestbootstrap):  # pylint: disable=redefined-outer-name
    """Test that fuzzy matching doesn't match when only partial words are similar"""

    trackrequest = trackrequestbootstrap
    trackrequest.clear_roulette_artist_dupes()
    trackrequest.config.cparser.setValue("settings/requests", True)
    trackrequest.config.cparser.sync()

    # Add request for "Pink Floyd"
    data = await trackrequest.user_track_request({"displayname": "test"}, "user", "Pink Floyd")
    assert data["requestartist"] == "Pink Floyd"

    # Try to match with just "Pink" - should NOT match (too different)
    data = await trackrequest.get_request({"artist": "Pink", "title": "So What"})
    assert data is None


@pytest.mark.asyncio
async def test_trackrequest_fuzzy_filler_words_dont_match_real_content(trackrequestbootstrap):  # pylint: disable=redefined-outer-name
    """Test that cleaning filler words doesn't accidentally match unrelated content"""

    trackrequest = trackrequestbootstrap
    trackrequest.clear_roulette_artist_dupes()
    trackrequest.config.cparser.setValue("settings/requests", True)
    trackrequest.config.cparser.sync()

    # Add request for specific artist
    data = await trackrequest.user_track_request({"displayname": "test"}, "user", "Madonna")
    assert data["requestartist"] == "Madonna"

    # Try with lots of filler words but wrong artist - should NOT match
    data = await trackrequest.get_request(
        {"artist": "please play anything by Taylor Swift thanks", "title": "Shake It Off"}
    )
    assert data is None


@pytest.mark.asyncio
async def test_trackrequest_fuzzy_empty_cleaned_text_fallback(trackrequestbootstrap):  # pylint: disable=redefined-outer-name
    """Test behavior when cleaned text becomes empty after removing filler words"""

    trackrequest = trackrequestbootstrap
    trackrequest.clear_roulette_artist_dupes()
    trackrequest.config.cparser.setValue("settings/requests", True)
    trackrequest.config.cparser.sync()

    # Add request
    data = await trackrequest.user_track_request({"displayname": "test"}, "user", "The Beatles")
    assert data["requestartist"] == "The Beatles"

    # Try to match with text that becomes empty after cleaning - should use original
    # This tests the fallback when clean_current_artist becomes empty
    data = await trackrequest.get_request(
        {"artist": "please play anything thanks", "title": "Something"}
    )
    assert data is None  # Should not match because no meaningful content remains


@pytest.mark.asyncio
async def test_trackrequest_fuzzy_disabled_fallback(trackrequestbootstrap):  # pylint: disable=redefined-outer-name
    """Test that system works correctly when rapidfuzz is not available"""

    # Mock rapidfuzz as unavailable using unittest.mock.patch context manager
    with unittest.mock.patch("nowplaying.trackrequests.RAPIDFUZZ_AVAILABLE", False):
        trackrequest = trackrequestbootstrap
        trackrequest.clear_roulette_artist_dupes()
        trackrequest.config.cparser.setValue("settings/requests", True)
        trackrequest.config.cparser.sync()

        # Add request
        data = await trackrequest.user_track_request(
            {"displayname": "test"}, "user", "Beatles - Yesterday"
        )
        assert data["requestartist"] == "Beatles"
        assert data["requesttitle"] == "Yesterday"

        # Exact match should still work
        data = await trackrequest.get_request({"artist": "Beatles", "title": "Yesterday"})
        assert data["requester"] == "user"
        assert data["requestdisplayname"] == "test"
        assert data["requesterimageraw"]

        # Add another request to test fuzzy fallback doesn't happen
        data2 = await trackrequest.user_track_request(
            {"displayname": "test2"}, "user2", "Pink Floyd"
        )
        assert data2["requestartist"] == "Pink Floyd"

        # Fuzzy match should NOT work (would work with rapidfuzz but should fail without it)
        data = await trackrequest.get_request({"artist": "Beatle", "title": "Yesterdy"})  # typos
        assert data is None  # Should not match due to no fuzzy matching


@pytest.mark.asyncio
async def test_twofer(bootstrap, getroot):  # pylint: disable=redefined-outer-name
    """test twofers"""
    stopevent = asyncio.Event()
    config = bootstrap
    config.cparser.setValue("settings/input", "json")
    playlistpath = pathlib.Path(getroot).joinpath("tests", "playlists", "json", "test.json")
    config.pluginobjs["inputs"]["nowplaying.inputs.jsonreader"].load_playlists(
        getroot, playlistpath
    )
    config.cparser.sync()

    metadb = nowplaying.db.MetadataDB(initialize=True)
    trackrequest = nowplaying.trackrequests.Requests(
        stopevent=stopevent, config=config, testmode=True
    )

    trackrequest.clear_roulette_artist_dupes()
    trackrequest.config.cparser.setValue("settings/requests", True)
    trackrequest.config.cparser.sync()

    data = await trackrequest.twofer_request(
        {
            "displayname": "test",
        },
        "user",
        None,
    )

    assert not data

    testdata = {"artist": "myartist", "title": "mytitle1"}
    await metadb.write_to_metadb(testdata)

    data = await trackrequest.twofer_request(
        {
            "displayname": "test",
        },
        "user",
        None,
    )

    assert data["requestartist"] == "myartist"
    assert not data["requesttitle"]

    testdata = {"artist": "myartist", "title": "mytitle2"}
    data = await trackrequest.get_request(testdata)

    assert data["requester"] == "user"
    assert data["requestdisplayname"] == "test"

    data = await trackrequest.twofer_request(
        {
            "displayname": "test",
        },
        "user1",
        "mytitle3",
    )

    assert data["requestartist"] == "myartist"
    assert data["requesttitle"] == "mytitle3"

    data = await trackrequest.twofer_request(
        {
            "displayname": "test",
        },
        "user2",
        "mytitle4",
    )

    assert data["requestartist"] == "myartist"
    assert data["requesttitle"] == "mytitle4"

    testdata = {"artist": "myartist", "title": "mytitle3"}
    data = await trackrequest.get_request(testdata)
    assert data["requester"] == "user1"
    assert data["requestdisplayname"] == "test"


@pytest.mark.asyncio
async def test_gifwords_tenor_request(trackrequestbootstrap):  # pylint: disable=redefined-outer-name
    """test tenor API gifwords request"""
    trackrequest = trackrequestbootstrap

    # Mock the aiohttp session for Tenor API
    mock_response_json = {
        "results": [{"media_formats": {"gif": {"url": "https://example.com/test.gif"}}}]
    }

    mock_gif_content = b"GIF89a test gif content"

    with unittest.mock.patch("aiohttp.ClientSession") as mock_session:
        # Setup mock for JSON response
        mock_json_response = unittest.mock.MagicMock()
        mock_json_response.status = 200
        mock_json_response.json = unittest.mock.AsyncMock(return_value=mock_response_json)
        mock_json_response.__aenter__ = unittest.mock.AsyncMock(return_value=mock_json_response)
        mock_json_response.__aexit__ = unittest.mock.AsyncMock(return_value=None)

        # Setup mock for GIF binary response
        mock_gif_response = unittest.mock.MagicMock()
        mock_gif_response.status = 200
        mock_gif_response.read = unittest.mock.AsyncMock(return_value=mock_gif_content)
        mock_gif_response.__aenter__ = unittest.mock.AsyncMock(return_value=mock_gif_response)
        mock_gif_response.__aexit__ = unittest.mock.AsyncMock(return_value=None)

        # Setup mock session context manager
        mock_session_instance = unittest.mock.MagicMock()
        mock_session_instance.get = unittest.mock.MagicMock(
            side_effect=[mock_json_response, mock_gif_response]
        )
        mock_session.return_value.__aenter__ = unittest.mock.AsyncMock(
            return_value=mock_session_instance
        )
        mock_session.return_value.__aexit__ = unittest.mock.AsyncMock(return_value=None)

        # Set Tenor API key
        trackrequest.config.cparser.setValue("gifwords/tenorkey", "test_tenor_key")

        # Call the tenor request method directly
        result = await trackrequest._tenor_request("funny cat")  # pylint: disable=protected-access

        assert result["keywords"] == "funny cat"
        assert result["imageurl"] == "https://example.com/test.gif"
        assert result["image"] == mock_gif_content


@pytest.mark.asyncio
async def test_gifwords_klipy_request(trackrequestbootstrap):  # pylint: disable=redefined-outer-name
    """test klipy API gifwords request"""
    trackrequest = trackrequestbootstrap

    # Mock the aiohttp session for Klipy API (same format as Tenor)
    mock_response_json = {
        "results": [{"media_formats": {"gif": {"url": "https://example.com/klipy-test.gif"}}}]
    }

    mock_gif_content = b"GIF89a klipy test gif content"

    with unittest.mock.patch("aiohttp.ClientSession") as mock_session:
        # Setup mock for JSON response
        mock_json_response = unittest.mock.MagicMock()
        mock_json_response.status = 200
        mock_json_response.json = unittest.mock.AsyncMock(return_value=mock_response_json)
        mock_json_response.__aenter__ = unittest.mock.AsyncMock(return_value=mock_json_response)
        mock_json_response.__aexit__ = unittest.mock.AsyncMock(return_value=None)

        # Setup mock for GIF binary response
        mock_gif_response = unittest.mock.MagicMock()
        mock_gif_response.status = 200
        mock_gif_response.read = unittest.mock.AsyncMock(return_value=mock_gif_content)
        mock_gif_response.__aenter__ = unittest.mock.AsyncMock(return_value=mock_gif_response)
        mock_gif_response.__aexit__ = unittest.mock.AsyncMock(return_value=None)

        # Setup mock session context manager
        mock_session_instance = unittest.mock.MagicMock()
        mock_session_instance.get = unittest.mock.MagicMock(
            side_effect=[mock_json_response, mock_gif_response]
        )
        mock_session.return_value.__aenter__ = unittest.mock.AsyncMock(
            return_value=mock_session_instance
        )
        mock_session.return_value.__aexit__ = unittest.mock.AsyncMock(return_value=None)

        # Set Klipy API key
        trackrequest.config.cparser.setValue("gifwords/klipykey", "test_klipy_key")

        # Call the klipy request method directly
        result = await trackrequest._klipy_request("funny dog")  # pylint: disable=protected-access

        assert result["keywords"] == "funny dog"
        assert result["imageurl"] == "https://example.com/klipy-test.gif"
        assert result["image"] == mock_gif_content


@pytest.mark.asyncio
async def test_gifwords_prefers_klipy(trackrequestbootstrap):  # pylint: disable=redefined-outer-name
    """test that klipy is preferred over tenor when both keys are set"""
    trackrequest = trackrequestbootstrap

    # Mock the aiohttp session for Klipy API (same format as Tenor)
    mock_response_json = {
        "results": [{"media_formats": {"gif": {"url": "https://example.com/klipy-preferred.gif"}}}]
    }

    mock_gif_content = b"GIF89a klipy preferred"

    with unittest.mock.patch("aiohttp.ClientSession") as mock_session:
        # Setup mock for JSON response
        mock_json_response = unittest.mock.MagicMock()
        mock_json_response.status = 200
        mock_json_response.json = unittest.mock.AsyncMock(return_value=mock_response_json)
        mock_json_response.__aenter__ = unittest.mock.AsyncMock(return_value=mock_json_response)
        mock_json_response.__aexit__ = unittest.mock.AsyncMock(return_value=None)

        # Setup mock for GIF binary response
        mock_gif_response = unittest.mock.MagicMock()
        mock_gif_response.status = 200
        mock_gif_response.read = unittest.mock.AsyncMock(return_value=mock_gif_content)
        mock_gif_response.__aenter__ = unittest.mock.AsyncMock(return_value=mock_gif_response)
        mock_gif_response.__aexit__ = unittest.mock.AsyncMock(return_value=None)

        # Setup mock session context manager
        mock_session_instance = unittest.mock.MagicMock()
        mock_session_instance.get = unittest.mock.MagicMock(
            side_effect=[mock_json_response, mock_gif_response]
        )
        mock_session.return_value.__aenter__ = unittest.mock.AsyncMock(
            return_value=mock_session_instance
        )
        mock_session.return_value.__aexit__ = unittest.mock.AsyncMock(return_value=None)

        # Set both API keys
        trackrequest.config.cparser.setValue("gifwords/tenorkey", "test_tenor_key")
        trackrequest.config.cparser.setValue("gifwords/klipykey", "test_klipy_key")

        # Call the gifwords request method
        result = await trackrequest.gifwords_request(
            {"displayname": "test"}, "testuser", "test keywords"
        )

        # Should use Klipy when both are set
        assert result["imageurl"] == "https://example.com/klipy-preferred.gif"
        assert result["image"] == mock_gif_content
        assert result["requester"] == "testuser"
        assert result["keywords"] == "test keywords"
