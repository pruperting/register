"""Local GPT-family reference-token accounting; never sends document content out.

cl100k_base is a reference BPE encoding, NOT a Gemini tokenizer. The
Docker image pre-populates TIKTOKEN_CACHE_DIR during build, so runtime
compression performs no model/API/download calls. Do not silently fall
back to a chars/4 estimate if this tokenizer is missing.
"""
from __future__ import annotations
from functools import lru_cache

ENCODING_NAME = "cl100k_base"

@lru_cache(maxsize=1)
def get_encoder():
    try:
        import tiktoken
    except ImportError as exc:
        raise RuntimeError("tiktoken is not installed; rebuild the Register Docker image for Stage 5") from exc
    try:
        return tiktoken.get_encoding(ENCODING_NAME)
    except Exception as exc:
        raise RuntimeError("cl100k_base tokenizer vocabulary unavailable; rebuild image to cache it before runtime") from exc

def count_tokens(text: str) -> int:
    """Exact local BPE token count for the specified *reference* encoding."""
    return len(get_encoder().encode(text, disallowed_special=())) if text else 0
