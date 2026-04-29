"""LLM output sanitization: strip <think> blocks, wrap bare JSON, etc."""
import re

_THINK_PATTERN = re.compile(r"<think>.*?</think>", re.DOTALL)
_THOUGHT_HEADER_PATTERN = re.compile(
    r"\*{0,2}(?:Thought Process|Internal Reasoning|My Reasoning|Analysis|Planning)"
    r"[:\*]*\s*\n.*?(?=\n---|\n\*{0,2}(?:Answer|Response)[:\*]|\Z)",
    re.DOTALL | re.IGNORECASE,
)
_BARE_JSON_PATTERN = re.compile(r"(?<!\`\`\`)([\{\[]\s*\".{20,}?[\}\]])", re.DOTALL)


def sanitize_output(text: str) -> str:
    """Clean up LLM output: strip reasoning tags, wrap bare JSON in code fences.

    Returns original ``text`` if sanitization would empty it (avoids blank
    responses on all-thinking outputs).
    """
    # Strip <think>...</think> blocks
    cleaned = _THINK_PATTERN.sub("", text).strip()

    # Strip bold "Thought Process:" / "Internal Reasoning:" sections
    cleaned = _THOUGHT_HEADER_PATTERN.sub("", cleaned).strip()

    # Strip leading "---" or "**Answer:**" wrappers left behind
    cleaned = re.sub(r"^---\s*\n", "", cleaned)
    cleaned = re.sub(
        r"^\*{0,2}Answer\*{0,2}[:\s]*\n?", "", cleaned, flags=re.IGNORECASE
    )
    if not cleaned:
        return text

    # Wrap bare JSON blocks in code fences for readability
    def _wrap_json(m: re.Match) -> str:
        json_str = m.group(1)
        # Skip if already inside a code fence
        prefix = cleaned[: m.start()]
        if prefix.count("```") % 2 == 1:
            return m.group(0)
        return f"\n```json\n{json_str}\n```\n"

    cleaned = _BARE_JSON_PATTERN.sub(_wrap_json, cleaned)
    return cleaned.strip()
