"""Unit tests for batch_record_scoring (no LLM)."""

from tests.benchmarks.batch_record_scoring import (
    RunScoreDetails,
    RunScores,
    _fuzzy_match,
    _numeric_equal,
    _unit_equal,
)


def test_run_scores_defaults():
    s = RunScores(fixture_name="t")
    assert s.overall == 0.0
    assert not s.passed


def test_run_scores_perfect():
    s = RunScores(
        fixture_name="t",
        step_completeness=1.0,
        param_accuracy=1.0,
        timestamps=1.0,
        signatures=1.0,
        deviations=1.0,
        na_correctness=1.0,
        notes_preservation=1.0,
        run_metadata=1.0,
    )
    assert s.overall == 1.0
    assert s.passed


def test_run_scores_weighted_sum():
    # step_completeness 20% + param_accuracy 25% = 45%
    s = RunScores(
        fixture_name="t",
        step_completeness=1.0,
        param_accuracy=1.0,
    )
    assert abs(s.overall - 0.45) < 1e-6


def test_fuzzy_match_aliased():
    assert _fuzzy_match("Buffer Prep", "buffer prep") == 1.0


def test_numeric_equal():
    assert _numeric_equal(100.0, 104.9)
    assert not _numeric_equal(100.0, 110.0)
    assert _numeric_equal(7.00, 7.01)
    assert not _numeric_equal(7.00, 7.05)


def test_unit_equal():
    assert _unit_equal("°C", "C")
    assert _unit_equal("μm", "um")
    assert not _unit_equal("g", "mg")
    assert _unit_equal(None, None)
    assert not _unit_equal("mL", None)


# ── score_run tests ──


from tests.benchmarks.batch_record_scoring import score_run


def _mk_expected(execution_data: dict, run_name: str = "t") -> dict:
    return {"run_name": run_name, "execution_data": execution_data}


def _mk_protocol_graph(step_ids: list[str]) -> dict:
    return {
        "nodes": [
            {"id": sid, "type": "unitOp", "position": {"x": 0, "y": 0},
             "data": {"label": sid, "paramSchema": {"type": "object", "properties": {}}}}
            for sid in step_ids
        ],
        "edges": [],
    }


def test_score_run_step_completeness_perfect():
    actual_ed = {"node-a": {"status": "completed", "results": {}, "notes": "", "timestamps": [], "signatures": [], "deviations": []}}
    expected = _mk_expected({"node-a": {"status": "completed", "results": {}, "notes": "", "timestamps": [], "signatures": [], "deviations": []}})
    protocol = _mk_protocol_graph(["node-a"])
    scores = score_run(actual_ed, {"run_name": "t"}, expected, protocol, "t")
    assert scores.step_completeness == 1.0
    assert scores.details.steps_expected == 1
    assert scores.details.steps_found == 1


def test_score_run_step_completeness_missing():
    actual_ed = {"node-a": {"status": "completed", "results": {}, "notes": ""}}
    expected = _mk_expected({
        "node-a": {"status": "completed", "results": {}, "notes": ""},
        "node-b": {"status": "completed", "results": {}, "notes": ""},
    })
    protocol = _mk_protocol_graph(["node-a", "node-b"])
    scores = score_run(actual_ed, {"run_name": "t"}, expected, protocol, "t")
    # F1 recall 0.5, precision 1.0 -> 0.667
    assert 0.65 < scores.step_completeness < 0.7
    assert "node-b" in scores.details.steps_missed


def test_score_run_param_accuracy_perfect():
    actual_ed = {"node-a": {"status": "completed", "results": {"ph": 7.2, "vol_ml": 500}, "notes": ""}}
    expected = _mk_expected({"node-a": {"status": "completed", "results": {"ph": 7.2, "vol_ml": 500}, "notes": ""}})
    protocol = _mk_protocol_graph(["node-a"])
    scores = score_run(actual_ed, {"run_name": "t"}, expected, protocol, "t")
    assert scores.param_accuracy == 1.0


def test_score_run_param_accuracy_wrong_value():
    actual_ed = {"node-a": {"status": "completed", "results": {"ph": 9.0}, "notes": ""}}
    expected = _mk_expected({"node-a": {"status": "completed", "results": {"ph": 7.2}, "notes": ""}})
    protocol = _mk_protocol_graph(["node-a"])
    scores = score_run(actual_ed, {"run_name": "t"}, expected, protocol, "t")
    assert scores.param_accuracy == 0.0
    assert scores.details.param_value_mismatches


def test_score_run_na_correctness_perfect():
    actual_ed = {"node-a": {"status": "na", "na_reason": "not done"}}
    expected = _mk_expected({"node-a": {"status": "na", "na_reason": "not done"}})
    protocol = _mk_protocol_graph(["node-a"])
    scores = score_run(actual_ed, {"run_name": "t"}, expected, protocol, "t")
    assert scores.na_correctness == 1.0


def test_score_run_na_correctness_wrong():
    actual_ed = {"node-a": {"status": "completed", "results": {}, "notes": ""}}
    expected = _mk_expected({"node-a": {"status": "na", "na_reason": "not done"}})
    protocol = _mk_protocol_graph(["node-a"])
    scores = score_run(actual_ed, {"run_name": "t"}, expected, protocol, "t")
    assert scores.na_correctness == 0.0
    assert scores.details.na_mismatches
