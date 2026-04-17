"""Unit tests for benchmarks.matching shared helpers."""

from tests.benchmarks.matching import align_by_name, f1, fuzzy_ratio


def test_fuzzy_ratio_identical():
    assert fuzzy_ratio("Buffer Preparation", "Buffer Preparation") == 1.0


def test_fuzzy_ratio_case_insensitive():
    assert fuzzy_ratio("Buffer Prep", "buffer prep") == 1.0


def test_fuzzy_ratio_similar():
    assert fuzzy_ratio("Buffer Prep", "Buffer Preparation") >= 0.7


def test_fuzzy_ratio_different():
    assert fuzzy_ratio("Buffer Prep", "Centrifugation") < 0.5


def test_fuzzy_ratio_empty_strings():
    assert fuzzy_ratio("", "") == 1.0
    assert fuzzy_ratio("", "foo") == 0.0
    assert fuzzy_ratio("foo", "") == 0.0


def test_align_by_name_perfect():
    expected = [{"name": "A"}, {"name": "B"}]
    actual = [{"name": "A"}, {"name": "B"}]
    aligned = align_by_name(expected, actual, "name")
    assert len(aligned) == 2
    assert all(e is not None and a is not None for e, a in aligned)


def test_align_by_name_with_step_name_key():
    expected = [{"step_name": "A"}, {"step_name": "B"}]
    actual = [{"step_name": "A"}]
    aligned = align_by_name(expected, actual, "step_name")
    assert aligned[0][1] is not None
    assert aligned[1][1] is None


def test_align_by_name_fuzzy_above_threshold():
    expected = [{"name": "Buffer Preparation"}]
    actual = [{"name": "Buffer Prep"}]
    aligned = align_by_name(expected, actual, "name", threshold=0.7)
    assert aligned[0][1] is not None


def test_align_by_name_no_match_below_threshold():
    expected = [{"name": "Filtration"}]
    actual = [{"name": "Incubation"}]
    aligned = align_by_name(expected, actual, "name", threshold=0.7)
    assert aligned[0][1] is None


def test_align_by_name_greedy_ambiguous():
    expected = [{"name": "Buffer Prep"}, {"name": "Buffer Preparation"}]
    actual = [{"name": "Buffer Prep"}]
    aligned = align_by_name(expected, actual, "name", threshold=0.7)
    assert aligned[0][1] is not None  # first wins
    assert aligned[1][1] is None      # second is missed


def test_f1_perfect():
    assert f1(n_matched=3, n_expected=3, n_actual=3) == 1.0


def test_f1_all_missed():
    assert f1(n_matched=0, n_expected=3, n_actual=0) == 0.0


def test_f1_recall_half():
    # recall 0.5, precision 1.0 -> F1 ≈ 0.667
    val = f1(n_matched=1, n_expected=2, n_actual=1)
    assert 0.65 < val < 0.68


def test_f1_precision_half():
    # recall 1.0, precision 0.5 -> F1 ≈ 0.667
    val = f1(n_matched=1, n_expected=1, n_actual=2)
    assert 0.65 < val < 0.68


def test_f1_both_empty():
    # Nothing expected, nothing found — trivially perfect
    assert f1(n_matched=0, n_expected=0, n_actual=0) == 1.0
