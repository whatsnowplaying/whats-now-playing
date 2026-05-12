#!/usr/bin/env python3
"""Guess game text matching and scoring functions"""

import re
import string

import normality

# Letter frequency groups for scoring
COMMON_LETTERS = set("eaiotusnr")
UNCOMMON_LETTERS = set(string.ascii_lowercase) - COMMON_LETTERS - set("qxzj")
RARE_LETTERS = set("qxzj")

# Characters to always reveal (don't blank out)
AUTO_REVEAL_CHARS = set(" -'&()[]{}.,!?;:0123456789")

# Common words that might be auto-revealed (if configured)
COMMON_WORDS = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "but",
    "in",
    "on",
    "at",
    "to",
    "for",
    "of",
    "with",
    "by",
    "from",
    "feat",
    "ft",
    "featuring",
    "remix",
    "mix",
    "edit",
    "version",
    "remaster",
    "remastered",
}


def normalize_for_matching(text: str) -> str:
    """
    Normalize text for guess matching.
    Treats &, 'n', 'n, and 'and' as equivalent.
    Uses normality module for proper Unicode normalization.

    Args:
        text: Text to normalize

    Returns:
        Normalized text for matching
    """
    # Replace & with 'and' for consistent matching (before normality processing)
    normalized = text.replace("&", "and")

    # Handle 'n' and 'n as abbreviations for 'and' (rock 'n' roll, rock 'n roll, rock n roll)
    normalized = normalized.replace(" 'n' ", " and ")
    normalized = normalized.replace(" 'n ", " and ")
    normalized = normalized.replace(" n ", " and ")

    # Remove apostrophes and hyphens before normality processing
    # Apostrophes: "I'm" becomes "Im" not "I m"
    # Hyphens: "Alt-J" becomes "AltJ" not "Alt J"
    normalized = normalized.replace("\u0027", "")  # Apostrophe (U+0027)
    normalized = normalized.replace("\u2018", "")  # Left single quotation mark (U+2018)
    normalized = normalized.replace("\u2019", "")  # Right single quotation mark (U+2019)
    normalized = normalized.replace("ʼ", "")  # Modifier letter apostrophe (U+02BC)
    normalized = normalized.replace("`", "")  # Grave accent (U+0060)
    normalized = normalized.replace("´", "")  # Acute accent (U+00B4)
    normalized = normalized.replace("-", "")  # Regular hyphen
    normalized = normalized.replace("‐", "")  # Hyphen (U+2010)
    normalized = normalized.replace("‑", "")  # Non-breaking hyphen (U+2011)
    normalized = normalized.replace("–", "")  # En dash (U+2013)
    normalized = normalized.replace("—", "")  # Em dash (U+2014)
    normalized = normalized.replace("−", "")  # Minus sign (U+2212)

    # Use normality to handle Unicode normalization, case folding, and punctuation removal
    # This handles various other punctuation, quotes, brackets, etc.
    normalized = normality.normalize(normalized, lowercase=True, collapse=True)

    # normality may return None for empty/invalid strings
    if normalized is None:
        return ""

    # After normality, fix any remaining cases like "o connor" -> "oconnor"
    # This handles cases where normality inserted spaces for unhandled punctuation.
    # Pattern: known Irish/Scottish name prefixes ("o", "d", "mc", "mac") + space + word.
    # Restricts to these common prefixes to avoid over-merging unrelated words.
    normalized = re.sub(r"\b(o|d|mc|mac)\s+([a-z]{2,})", r"\1\2", normalized)

    # Strip remaining censoring characters that normality might preserve
    normalized = normalized.replace("*", "")
    normalized = normalized.replace("_", "")

    # Remove spaces between digits to handle cases like "10,000" -> "10000"
    normalized = re.sub(r"(\d)\s+(\d)", r"\1\2", normalized)

    return normalized.strip()


def find_concatenated_sequence(guess: str, words: list[str]) -> tuple[int, int] | None:
    """
    Find a consecutive window of words that concatenate to equal guess.

    Used to match initialisms like "rundmc" against ["rund", "m", "c"],
    which arises when "Run‐D.M.C." normalizes differently from "run-dmc"
    (hyphens removed directly vs dots-as-spaces via normality).

    Args:
        guess: Single normalized guess word (no spaces)
        words: List of normalized words to search through

    Returns:
        (start_index, window_size) tuple if found, None otherwise
    """
    max_window = min(len(guess), len(words))
    for window_size in range(2, max_window + 1):
        for i in range(len(words) - window_size + 1):
            if "".join(words[i : i + window_size]) == guess:
                return (i, window_size)
    return None


def phrase_in_guess(phrase: str, guess: str) -> bool:
    """Check if phrase appears as complete tokens (word boundaries) in guess.

    Prevents false positives where a short phrase is a substring of a
    longer word (e.g. track 'rift' matching inside 'drifter').
    """
    return bool(re.search(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", guess))


def is_word_match(guess: str, text: str) -> bool:
    """
    Check if guess matches as a complete word in text (not just substring).

    Also handles the case where consecutive words in text concatenate to
    form the guess (e.g. "rundmc" matching "rund m c" from "Run‐D.M.C.").

    Args:
        guess: The normalized guess text
        text: The normalized text to search in

    Returns:
        True if guess is found as a complete word with word boundaries
    """
    if not guess or not text:
        return False

    if phrase_in_guess(guess, text):
        return True

    # Also match if consecutive words in text concatenate to form the guess.
    # This handles initialisms: "run-dmc" → "rundmc", "Run‐D.M.C." → "rund m c"
    return find_concatenated_sequence(guess, text.split()) is not None


def build_word_alignment(original_words: list[str], normalized_words: list[str]) -> list[int]:
    """
    Build a mapping from normalized-word index → original-word index.

    When one original word (e.g. "Run‐D.M.C.,") normalizes to multiple words
    ("rund", "m", "c"), each resulting normalized word maps back to that same
    original index.  This corrects the index drift that would otherwise cause
    reveals to uncover the wrong letters.

    Falls back to 1:1 index mapping when per-word normalization is inconsistent
    with the full-string normalization (e.g. " n " → "and" only fires on the
    full string).

    Args:
        original_words: Words from the original un-normalized text
        normalized_words: Words from the fully normalized text

    Returns:
        alignment list where alignment[i] is the original-word index for
        normalized_words[i]
    """
    alignment: list[int] = []
    for orig_idx, orig_word in enumerate(original_words):
        norm = normalize_for_matching(orig_word)
        parts = norm.split() if norm else []
        for _ in parts:
            alignment.append(orig_idx)

    # If per-word normalization produces a different count than the full-string
    # normalization (e.g. " n "→"and" or Irish-prefix merges), fall back to a
    # simple 1:1 index mapping to avoid invalid lookups.
    if len(alignment) != len(normalized_words):
        alignment = [min(i, len(original_words) - 1) for i in range(len(normalized_words))]

    return alignment


def reveal_matching_word_letters(
    guess_normalized: str,
    original_text: str,
    normalized_text: str,
    revealed_letters: set[str],
) -> None:
    """
    Reveal letters from the word(s) in original_text that match guess_normalized.

    This handles accented characters - when a user guesses "sinead", it reveals
    all letters from "Sinéad" including the "é". Also handles multi-word guesses
    like "road to" matching in "the road to mandalay".

    Args:
        guess_normalized: The normalized guess text (may be multiple words)
        original_text: The original text (may contain accents, special chars)
        normalized_text: The normalized version of original_text
        revealed_letters: Set to add revealed letters to (modified in place)
    """
    # Split both texts into words
    original_words = original_text.split()
    normalized_words = normalized_text.split()
    guess_words = guess_normalized.split()

    # Build alignment so normalized-word indices map to correct original words
    # even when one original word normalizes to multiple normalized words.
    alignment = build_word_alignment(original_words, normalized_words)

    # Handle single-word guesses (original behavior)
    if len(guess_words) == 1:
        reveal_single_word_match(
            guess_normalized, original_words, normalized_words, alignment, revealed_letters
        )
        return

    # Handle multi-word guesses by finding the sequence
    reveal_multi_word_match(
        guess_words, original_words, normalized_words, alignment, revealed_letters
    )


def reveal_single_word_match(  # pylint: disable=too-many-arguments
    guess_normalized: str,
    original_words: list[str],
    normalized_words: list[str],
    alignment: list[int],
    revealed_letters: set[str],
) -> None:
    """Helper to reveal letters for single-word guesses."""
    for i, norm_word in enumerate(normalized_words):
        if not is_word_match(guess_normalized, norm_word):
            continue
        orig_idx = alignment[i]
        for char in original_words[orig_idx]:
            if char.isalpha():
                revealed_letters.add(char.lower())

    # Also reveal letters from a concatenated-word sequence match.
    # e.g. guess "rundmc" matches normalized_words ["rund", "m", "c"]
    seq = find_concatenated_sequence(guess_normalized, normalized_words)
    if seq is not None:
        start, count = seq
        orig_indices = {alignment[j] for j in range(start, min(start + count, len(alignment)))}
        for orig_idx in orig_indices:
            for char in original_words[orig_idx]:
                if char.isalpha():
                    revealed_letters.add(char.lower())


def reveal_multi_word_match(
    guess_words: list[str],
    original_words: list[str],
    normalized_words: list[str],
    alignment: list[int],
    revealed_letters: set[str],
) -> None:
    """Helper to reveal letters for multi-word guesses."""
    for i in range(len(normalized_words) - len(guess_words) + 1):
        sequence = normalized_words[i : i + len(guess_words)]
        if sequence != guess_words:
            continue
        # Reveal all original words that contributed to this normalized sequence.
        # Using a set of orig_indices handles the case where multiple normalized
        # words came from the same original word (e.g. "Run‐D.M.C." → 3 words).
        orig_indices = {alignment[j] for j in range(i, min(i + len(guess_words), len(alignment)))}
        for orig_idx in orig_indices:
            for char in original_words[orig_idx]:
                if char.isalpha():
                    revealed_letters.add(char.lower())


def mask_text(text: str, revealed_letters: set[str], auto_reveal_words: bool = False) -> str:
    """
    Mask text with blanks for unrevealed letters.

    Args:
        text: Original text to mask
        revealed_letters: Set of letters that have been guessed
        auto_reveal_words: If True, auto-reveal common words

    Returns:
        Masked text with _ for unrevealed letters
    """
    if not text:
        return ""

    masked = []
    words = text.split()

    for word in words:
        if auto_reveal_words and word.lower() in COMMON_WORDS:
            # Reveal entire common word
            masked.append(word)
        else:
            # Mask individual characters
            masked_word = ""
            for char in word:
                char_lower = char.lower()
                if char in AUTO_REVEAL_CHARS:
                    # Always reveal spaces, punctuation, numbers
                    masked_word += char
                elif char_lower in revealed_letters:
                    # Revealed letter - show it with original case
                    masked_word += char
                elif char.isalpha():
                    # Unrevealed letter - blank it out
                    masked_word += "_"
                else:
                    # Other characters (should be covered by AUTO_REVEAL_CHARS)
                    masked_word += char
            masked.append(masked_word)

    return " ".join(masked)


def calculate_difficulty(track: str, artist: str, revealed_letters: set[str]) -> float:
    """
    Calculate the difficulty of the current game as percentage of letters still hidden.

    Returns:
        Float between 0.0 and 1.0 representing percentage of unrevealed letters
    """
    combined = track + artist

    # Count letters only (not spaces, punctuation, etc)
    total_letters = sum(1 for char in combined if char.isalpha())
    if total_letters == 0:
        return 0.0

    # Count unrevealed letters
    unrevealed_count = sum(
        1 for char in combined if char.isalpha() and char.lower() not in revealed_letters
    )

    return unrevealed_count / total_letters
