"""``modules.statistics`` の単体テスト.

マッチング結果からのクロス集計と各種指標（Index・オーバーラップ率など）が
正しく計算されることを検証する。
"""
from __future__ import annotations

import math

from modules.datatypes import MatchPair
from modules.matching import MatchingResult
from modules.statistics import CrossTab, StatisticsCalculator
from tests.conftest import make_cell


def _result_from_pairs(pairs: list[MatchPair]) -> MatchingResult:
    """テスト用に対応ペアだけを持つ ``MatchingResult`` を作る。"""
    return MatchingResult(pairs=pairs, unmatched_a=[], unmatched_b=[], match_rate=1.0)


def test_crosstab_counts() -> None:
    """4 象限のカウントが正しく集計される。"""
    pairs = [
        # both positive
        MatchPair(make_cell(0, 0, True), make_cell(0, 0, True), 1.0),
        # A+ B-
        MatchPair(make_cell(1, 1, True), make_cell(1, 1, False), 1.0),
        # A- B+
        MatchPair(make_cell(2, 2, False), make_cell(2, 2, True), 1.0),
        # both negative
        MatchPair(make_cell(3, 3, False), make_cell(3, 3, False), 1.0),
    ]
    tab = StatisticsCalculator().compute(_result_from_pairs(pairs), "Ki67", "p53")

    assert tab.both_positive == 1
    assert tab.a_pos_b_neg == 1
    assert tab.a_neg_b_pos == 1
    assert tab.both_negative == 1
    assert tab.total == 4


def test_index_and_rates() -> None:
    """Index・オーバーラップ率・共陽性率が定義どおり計算される。"""
    pairs = [
        MatchPair(make_cell(0, 0, True), make_cell(0, 0, True), 1.0),
        MatchPair(make_cell(1, 1, True), make_cell(1, 1, False), 1.0),
        MatchPair(make_cell(2, 2, False), make_cell(2, 2, True), 1.0),
        MatchPair(make_cell(3, 3, False), make_cell(3, 3, False), 1.0),
    ]
    tab = StatisticsCalculator().compute(_result_from_pairs(pairs))

    # A+ = both(1) + a_only(1) = 2, total = 4 -> 0.5
    assert math.isclose(tab.a_index, 0.5)
    assert math.isclose(tab.b_index, 0.5)
    # Jaccard: both(1) / (both1 + aonly1 + bonly1) = 1/3
    assert math.isclose(tab.overlap_rate, 1 / 3)
    # co-positive: both(1) / total(4)
    assert math.isclose(tab.co_positive_rate, 0.25)


def test_unmatched_pairs_ignored() -> None:
    """cell_b が None のペアは集計対象外。"""
    pairs = [
        MatchPair(make_cell(0, 0, True), make_cell(0, 0, True), 1.0),
        MatchPair(make_cell(9, 9, True), None, float("inf")),
    ]
    tab = StatisticsCalculator().compute(_result_from_pairs(pairs))
    assert tab.total == 1
    assert tab.both_positive == 1


def test_empty_result_no_division_error() -> None:
    """空でもゼロ除算せず 0.0 を返す。"""
    tab = StatisticsCalculator().compute(_result_from_pairs([]))
    assert tab.total == 0
    assert tab.a_index == 0.0
    assert tab.overlap_rate == 0.0


def test_as_dict_contains_metrics() -> None:
    """as_dict に指標キーが含まれる。"""
    tab = CrossTab("Ki67", "p53", both_positive=2, total=4)
    d = tab.as_dict()
    for key in ("a_index", "b_index", "overlap_rate", "co_positive_rate"):
        assert key in d
