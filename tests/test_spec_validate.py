"""Regression coverage for quorum/strategy/validate.py — the backend half
of Track 2's generate -> validate -> retry loop. A generated YAML spec must
never reach a human (or a retry attempt) without going through here first,
so this exercises every branch a real generation attempt can hit: valid
dict, malformed YAML, a non-mapping document, a schema violation, and a
strategy_id/expected_id mismatch — plus the fenced-input case a model
wrapping its output in ```yaml``` produces despite being told not to.
"""

from pathlib import Path

import pytest
import yaml

from quorum.strategy.validate import strip_code_fence, validate_spec_text

pytestmark = pytest.mark.unit

_GOLDEN_PATH = Path(__file__).resolve().parents[1] / "strategies" / "regime_gate.yaml"
_GOLDEN_TEXT = _GOLDEN_PATH.read_text()


class TestStripCodeFence:
    def test_strips_a_yaml_fence(self):
        fenced = f"```yaml\n{_GOLDEN_TEXT.strip()}\n```"
        assert strip_code_fence(fenced) == _GOLDEN_TEXT.strip()

    def test_strips_a_bare_fence(self):
        fenced = f"```\n{_GOLDEN_TEXT.strip()}\n```"
        assert strip_code_fence(fenced) == _GOLDEN_TEXT.strip()

    def test_leaves_unfenced_text_unchanged(self):
        assert strip_code_fence(_GOLDEN_TEXT) == _GOLDEN_TEXT


class TestValidateSpecText:
    def test_valid_strategy_passes(self):
        result = validate_spec_text("strategy", _GOLDEN_TEXT)
        assert result["ok"] is True

    def test_fenced_valid_strategy_passes(self):
        fenced = f"```yaml\n{_GOLDEN_TEXT.strip()}\n```"
        result = validate_spec_text("strategy", fenced)
        assert result["ok"] is True
        assert result["cleaned_text"] == _GOLDEN_TEXT.strip()

    def test_malformed_yaml_fails_with_an_error(self):
        result = validate_spec_text("strategy", "strategy_id: [unclosed")
        assert result["ok"] is False
        assert "invalid YAML" in result["errors"][0]

    def test_non_mapping_document_fails(self):
        result = validate_spec_text("strategy", "- just\n- a\n- list\n")
        assert result["ok"] is False
        assert "mapping" in result["errors"][0]

    def test_schema_violation_reports_pydantic_errors(self):
        raw = yaml.safe_load(_GOLDEN_TEXT)
        del raw["universe"]
        result = validate_spec_text("strategy", yaml.dump(raw))
        assert result["ok"] is False
        assert any("universe" in e for e in result["errors"])

    def test_unknown_universe_tag_reports_resolve_tags_error(self):
        raw = yaml.safe_load(_GOLDEN_TEXT)
        raw["universe"]["tags"] = ["not_a_real_tag"]
        result = validate_spec_text("strategy", yaml.dump(raw))
        assert result["ok"] is False
        assert any("unknown universe tag" in e for e in result["errors"])

    def test_id_mismatch_fails_even_when_schema_valid(self):
        result = validate_spec_text("strategy", _GOLDEN_TEXT, expected_id="some_other_strategy")
        assert result["ok"] is False
        assert "does not match expected id" in result["errors"][0]

    def test_matching_expected_id_passes(self):
        result = validate_spec_text("strategy", _GOLDEN_TEXT, expected_id="regime_gate")
        assert result["ok"] is True
