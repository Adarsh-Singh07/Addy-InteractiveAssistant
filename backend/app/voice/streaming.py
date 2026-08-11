"""
Sentence buffer for the STT→LLM→TTS streaming pipeline.

WHY THIS EXISTS
===============
LLM tokens stream in one-by-one. Deepgram TTS REST API needs a complete
sentence (or at least a sensible phrase) to synthesize.

Sending individual tokens to TTS would result in:
  - Terrible audio quality (choppy, unnatural)
  - Excessive API calls (one per token)
  - High latency accumulation

Strategy: buffer tokens until a sentence boundary is detected,
then fire a TTS request for that sentence.

Sentence boundaries: . ? ! \n (followed by whitespace or end of input)

Tradeoff: we wait a few more tokens before starting TTS.
The "first audio" latency target is:
  speech_end → (STT latency) → (LLM first sentence) → (TTS request) → first audio

For short first sentences ("Yes.", "Sure."), this is fast.
For longer first sentences, consider lowering sentence_min_chars.
"""

from __future__ import annotations

import re

# Sentence-ending patterns
_SENTENCE_END = re.compile(r"([.!?।\n])\s*$")
# Minimum chars before we consider a boundary a real sentence
_MIN_SENTENCE_CHARS = 20


class SentenceBuffer:
    """
    Accumulates LLM tokens and yields complete sentences.

    Usage:
        buf = SentenceBuffer()
        for token in llm_stream:
            sentence = buf.push(token)
            if sentence:
                # synthesize sentence via TTS
        remainder = buf.flush()
        if remainder:
            # synthesize remaining text
    """

    def __init__(self, min_chars: int = _MIN_SENTENCE_CHARS) -> None:
        self._buffer = ""
        self._min_chars = min_chars

    def push(self, token: str) -> str | None:
        """
        Add a token to the buffer.
        Returns a complete sentence if a boundary was reached, else None.
        """
        self._buffer += token

        # Only check for sentence boundary if we have enough chars
        if len(self._buffer) < self._min_chars:
            return None

        if _SENTENCE_END.search(self._buffer):
            sentence = self._buffer.strip()
            self._buffer = ""
            return sentence if sentence else None

        return None

    def flush(self) -> str | None:
        """Return any remaining buffered text (end of stream)."""
        remainder = self._buffer.strip()
        self._buffer = ""
        return remainder if remainder else None

    def reset(self) -> None:
        """Clear buffer (called on barge-in interruption)."""
        self._buffer = ""

    @property
    def pending(self) -> str:
        """Current buffered text (for debugging)."""
        return self._buffer
