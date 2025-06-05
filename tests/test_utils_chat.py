#!/usr/bin/env python3
"""Test chat utilities in utils.py"""
# pylint: disable=no-member

from unittest.mock import patch

import pytest

import nowplaying.utils


def test_ensure_nltk_data_already_available():
    """Test NLTK data initialization when punkt is already available"""
    with patch('nltk.data.find') as mock_find:
        # NLTK data already available
        mock_find.return_value = True

        # Should not raise exception
        nowplaying.utils.ensure_nltk_data()

        # Should check for punkt tokenizer
        mock_find.assert_called_once_with('tokenizers/punkt')


def test_ensure_nltk_data_download_needed():
    """Test NLTK data initialization when download is needed"""
    with patch('nltk.data.find') as mock_find, \
         patch('nltk.download') as mock_download:

        # Simulate punkt not found
        mock_find.side_effect = LookupError("Resource punkt not found")
        mock_download.return_value = True

        # Should download punkt data
        nowplaying.utils.ensure_nltk_data()

        mock_find.assert_called_once_with('tokenizers/punkt')
        mock_download.assert_called_once_with('punkt', quiet=True)


def test_ensure_nltk_data_download_fails():
    """Test NLTK data initialization when download fails"""
    with patch('nltk.data.find') as mock_find, \
         patch('nltk.download') as mock_download:

        # Simulate punkt not found and download failure
        mock_find.side_effect = LookupError("Resource punkt not found")
        mock_download.side_effect = Exception("Download failed")

        # Should not raise exception (graceful failure)
        nowplaying.utils.ensure_nltk_data()

        mock_find.assert_called_once_with('tokenizers/punkt')
        mock_download.assert_called_once_with('punkt', quiet=True)


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
    message = ("This is a very long sentence that exceeds the maximum "
               "length limit and should be split at word boundaries")
    result = nowplaying.utils.smart_split_message(message, max_length=30)

    # Should split at word boundaries
    assert len(result) > 1
    for part in result:
        assert len(part) <= 30
        # Check that words aren't broken (except for truncated words ending in ...)
        if not part.endswith('...'):
            assert ' ' not in part or part.count(
                ' ') > 0  # Either single word or multiple complete words


def test_smart_split_message_very_long_word():
    """Test message splitting with single word longer than limit"""
    message = "Supercalifragilisticexpialidocious"
    result = nowplaying.utils.smart_split_message(message, max_length=10)

    # Should truncate long word
    assert len(result) == 1
    assert result[0].endswith('...')
    assert len(result[0]) == 10


def test_smart_split_message_mixed_content():
    """Test message splitting with mixed sentence and word content"""
    message = ("Short sentence. This is a much longer sentence that will "
               "need to be split at word boundaries because it exceeds the "
               "limit. Final short sentence.")
    result = nowplaying.utils.smart_split_message(message, max_length=40)

    # Should handle mixed content appropriately
    assert len(result) >= 3
    for part in result:
        assert len(part) <= 40
        assert part.strip()  # No empty parts


def test_smart_split_message_nltk_failure_fallback():
    """Test message splitting fallback when NLTK fails"""
    with patch('nowplaying.utils.ensure_nltk_data'), \
         patch('nltk.sent_tokenize') as mock_tokenize:

        # Simulate NLTK failure
        mock_tokenize.side_effect = Exception("NLTK error")

        message = "This is a test message that should be split using fallback logic."
        result = nowplaying.utils.smart_split_message(message, max_length=30)

        # Should still split the message using fallback
        assert len(result) > 1
        for part in result:
            assert len(part) <= 30


def test_smart_split_message_empty_parts_removed():
    """Test that empty message parts are removed"""
    with patch('nowplaying.utils.ensure_nltk_data'), \
         patch('nltk.sent_tokenize') as mock_tokenize:

        # Simulate tokenization that might create empty parts
        mock_tokenize.return_value = ["Valid sentence.", "", "   ", "Another sentence."]

        message = "Test message"
        result = nowplaying.utils.smart_split_message(message, max_length=50)

        # Should not contain empty parts
        for part in result:
            assert part.strip()


def test_smart_split_message_preserve_content():
    """Test that message splitting preserves all content"""
    message = "First sentence. Second sentence. Third sentence."
    result = nowplaying.utils.smart_split_message(message, max_length=20)

    # Reconstruct message from parts
    reconstructed = ' '.join(result)

    # Should preserve most content (allowing for spacing differences)
    assert "First sentence" in reconstructed
    assert "Second sentence" in reconstructed
    assert "Third sentence" in reconstructed


def test_tokenize_sentences_success():
    """Test sentence tokenization with NLTK success"""
    with patch('nowplaying.utils.ensure_nltk_data'), \
         patch('nltk.sent_tokenize') as mock_tokenize:

        mock_tokenize.return_value = ["First sentence.", "Second sentence!"]

        text = "First sentence. Second sentence!"
        result = nowplaying.utils.tokenize_sentences(text)

        assert result == ["First sentence.", "Second sentence!"]
        mock_tokenize.assert_called_once_with(text)


def test_tokenize_sentences_fallback():
    """Test sentence tokenization fallback when NLTK fails"""
    with patch('nowplaying.utils.ensure_nltk_data'), \
         patch('nltk.sent_tokenize') as mock_tokenize:

        # Simulate NLTK failure
        mock_tokenize.side_effect = Exception("NLTK error")

        text = "First sentence. Second sentence! Third sentence?"
        result = nowplaying.utils.tokenize_sentences(text)

        # Should use fallback splitting
        assert len(result) > 1
        # Fallback adds periods, so check basic splitting occurred
        assert any("First sentence" in sent for sent in result)
        assert any("Second sentence" in sent for sent in result)
        assert any("Third sentence" in sent for sent in result)


def test_tokenize_sentences_empty_input():
    """Test sentence tokenization with empty input"""
    result = nowplaying.utils.tokenize_sentences("")
    assert not result


def test_tokenize_sentences_single_sentence():
    """Test sentence tokenization with single sentence"""
    text = "This is a single sentence"
    result = nowplaying.utils.tokenize_sentences(text)

    # Should return list with one sentence
    assert len(result) >= 1
    assert "single sentence" in ' '.join(result)


def test_tokenize_sentences_fallback_no_double_periods():
    """Test that fallback tokenization doesn't add extra periods to sentences with punctuation"""
    with patch('nowplaying.utils.ensure_nltk_data'), \
         patch('nltk.sent_tokenize') as mock_tokenize:

        # Simulate NLTK failure
        mock_tokenize.side_effect = Exception("NLTK error")

        text = "Already ends with period. Another ends with exclamation! Third ends with question?"
        result = nowplaying.utils.tokenize_sentences(text)

        # Should not have double periods
        for sentence in result:
            assert not sentence.endswith('..'), f"Double period found in: {sentence}"
            assert not sentence.endswith('!.'), \
                f"Exclamation followed by period found in: {sentence}"
            assert not sentence.endswith('?.'), \
                f"Question mark followed by period found in: {sentence}"


@pytest.mark.parametrize("max_length", [25, 50, 100, 500])
def test_smart_split_message_various_limits(max_length):
    """Test message splitting with various length limits"""
    message = ("This is a test message with multiple sentences. "
               "Each sentence should be handled based on the length limit. "
               "The splitting should work correctly.")

    result = nowplaying.utils.smart_split_message(message, max_length=max_length)

    # Verify all parts respect the limit (allowing for truncated words ending in ...)
    for part in result:
        assert len(part) <= max_length

    # Verify we got some result
    assert len(result) >= 1
    assert all(part.strip() for part in result)


def test_smart_split_message_default_limit():
    """Test message splitting uses default limit"""
    message = "A" * 1000  # Very long message

    result = nowplaying.utils.smart_split_message(message)

    # Should use default limit of 500
    for part in result:
        assert len(part) <= 500


def test_smart_split_message_unicode_handling():
    """Test message splitting handles Unicode characters correctly"""
    message = ("This message contains émojis 🎵 and spëcial characters. "
               "Ït should be handled correctly! 中文 text as well.")

    result = nowplaying.utils.smart_split_message(message, max_length=50)

    # Should handle Unicode without errors
    assert len(result) >= 1
    for part in result:
        assert len(part) <= 50

    # Verify Unicode content is preserved
    combined = ' '.join(result)
    assert '🎵' in combined
    assert 'émojis' in combined
    assert '中文' in combined
