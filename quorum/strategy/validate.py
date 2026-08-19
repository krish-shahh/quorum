"""Spec validation — the generate -> validate -> retry loop's backend half
(Track 2, Feature A). A generated YAML spec is checked here before a human
(or a retry loop) ever sees it; Pydantic's own ``ValidationError.errors()``
already produces LLM-readable messages, so there's no separate error
formatting layer to keep in sync with the schema.

``kind`` is ``Literal["strategy"]`` for now — widened to include
``"screen"`` once ``quorum/screen/schema.py`` exists (Feature B).
"""

from __future__ import annotations

import re
from typing import Any, Dict, Literal, Optional

import yaml
from pydantic import ValidationError

from .schema import load_strategy

_FENCE_RE = re.compile(r"^```(?:yaml)?\n([\s\S]*?)\n```$")


def strip_code_fence(text: str) -> str:
    """Strip a ```yaml ... ``` (or bare ``` ... ```) fence if the model
    wrapped its output in one — cheap enough to always run, a no-op on
    already-bare YAML."""
    match = _FENCE_RE.match(text.strip())
    return match.group(1) if match else text


def validate_spec_text(
    kind: Literal["strategy"],
    text: str,
    expected_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Validate raw YAML `text` against `kind`'s closed grammar.

    Returns ``{"ok": True, "cleaned_text": ...}`` on success, or
    ``{"ok": False, "cleaned_text": ..., "errors": [...]}`` on any failure
    — malformed YAML, a non-mapping document, a schema violation, or an
    `expected_id` mismatch are all folded into the same shape rather than
    raised, so a retry loop always gets a structured result back.
    """
    cleaned = strip_code_fence(text)

    try:
        raw = yaml.safe_load(cleaned)
    except yaml.YAMLError as e:
        return {"ok": False, "cleaned_text": cleaned, "errors": [f"invalid YAML: {e}"]}

    if not isinstance(raw, dict):
        return {
            "ok": False, "cleaned_text": cleaned,
            "errors": ["spec must be a YAML mapping, not a list or scalar"],
        }

    if kind != "strategy":
        raise ValueError(f"unknown spec kind: {kind!r}")

    try:
        spec = load_strategy(raw)
    except ValidationError as e:
        errors = [f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in e.errors()]
        return {"ok": False, "cleaned_text": cleaned, "errors": errors}

    if expected_id is not None and spec.strategy_id != expected_id:
        return {
            "ok": False, "cleaned_text": cleaned,
            "errors": [f"strategy_id '{spec.strategy_id}' does not match expected id '{expected_id}'"],
        }

    return {"ok": True, "cleaned_text": cleaned}
