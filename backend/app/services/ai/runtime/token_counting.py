"""Token counter for ContextManagerCapability.

Uses tiktoken's cl100k_base encoding (OpenAI/Anthropic-equivalent for
counting purposes). Falls back to a 4-chars/token heuristic if tiktoken
is unavailable or fails on a message shape.
"""
import json
from typing import Any

import tiktoken

_ENCODER = tiktoken.get_encoding("cl100k_base")


def tiktoken_counter(messages: list[Any]) -> int:
    """Estimate total tokens across a list of pydantic-ai messages.

    Each message may be a string, dict, or pydantic-ai ModelMessage object.
    Serializes each message and counts tokens in the resulting string.
    """
    total = 0
    for msg in messages:
        if isinstance(msg, str):
            text = msg
        elif isinstance(msg, dict):
            text = json.dumps(msg, default=str)
        else:
            try:
                text = json.dumps(msg.model_dump(mode="json"), default=str)
            except Exception:
                text = str(msg)
        try:
            total += len(_ENCODER.encode(text))
        except Exception:
            total += len(text) // 4
    return total
