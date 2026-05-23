"""LLM output sanitization: strip <think> blocks, wrap bare JSON, etc."""

import logging
import re

_THINK_PATTERN = re.compile(r"<think>.*?</think>", re.DOTALL)

# Strip a model's reasoning-preamble section, e.g.
#   **Thought Process:**
#   ...reasoning...
#   ---
#   <the actual answer>
# Two guards keep this from eating legitimate content:
#  1. The header must be a whole line on its own (`^...$`, MULTILINE), so a
#     real section header that merely *contains* one of these words —
#     "Runs & Planning", "Risk Analysis" — is never matched.
#  2. A real terminator must follow (a `---` rule or an "Answer:"/"Response:"
#     header). Without one we strip nothing: a runaway match to end-of-text
#     would silently delete the actual answer.
# Only unambiguous reasoning-leak phrases are listed — words like "Analysis"
# and "Planning" are ordinary section titles in scientific writing.
_THOUGHT_HEADER_PATTERN = re.compile(
    r"^\*{0,2}(?:Thought Process|Internal Reasoning|My Reasoning|"
    r"Chain of Thought)[:\*]*[ \t]*$\n"
    r".*?(?=\n---|\n\*{0,2}(?:Answer|Response)[:\*])",
    re.DOTALL | re.IGNORECASE | re.MULTILINE,
)
_BARE_JSON_PATTERN = re.compile(r"(?<!\`\`\`)([\{\[]\s*\".{20,}?[\}\]])", re.DOTALL)

logger = logging.getLogger(__name__)

# Strip `](/protocols/<anything>)` from markdown links whose path is NOT
# a canonical /{org-slug}/protocols/{slug} form. Models occasionally
# hallucinate a UUID-only path; this is the server-side backstop.
# Canonical /{org}/protocols/{slug} links pass through because the
# pattern anchors on `](/protocols/` — a leading org segment breaks the
# match.
_BARE_PROTOCOL_LINK = re.compile(r"\]\(/protocols/[^)\s]+\)")


def _strip_bare_protocol_link(match: "re.Match[str]", text: str) -> str:
    """Replace `](/protocols/...)` with `]` ONLY if the match is not inside
    an open fenced code block. Mirrors the `_wrap_json` fenced-code guard.
    Emits a single warning per strip so we can monitor hallucination rate
    in production (the only signal that the prompt + tool-result fix is
    working)."""
    prefix = text[: match.start()]
    if prefix.count("```") % 2 == 1:
        # Inside a fenced block — leave as-is.
        return match.group(0)
    logger.warning(
        "chat: stripped bare /protocols/... link from agent output (%r)",
        match.group(0),
    )
    return "]"


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
    cleaned = _BARE_PROTOCOL_LINK.sub(
        lambda m: _strip_bare_protocol_link(m, cleaned), cleaned
    )
    return cleaned.strip()
