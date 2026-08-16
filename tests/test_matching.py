"""Cell Matching のテスト。"""
from __future__ import annotations

import numpy as np

from modules.datatypes import Cell, MarkerChannel
from modules.matching import CellMatcher


def _cell(x, y, positive=False, marker=MarkerChannel.KI67):
    return Cell(
        centroid_px=(x, y), area_um2=50.0, perimeter_um=25.0,
        circularity=0.9, positive=positive, marker=marker,
    )


def test_exact_overlap_matches_all():
    """完全に一致する座標なら全細胞が対応する。"""
    a = [_cell(10, 10), _cell(20, 20), _cell(30, 30)]
    b = [_cell(10, 10), _cell(20, 20), _cell(30, 30)]
    result = CellMatcher(max_distance_um=1.0).match(a, b, mpp=1.0)
    assert len(result.pairs) == 3
    assert result.match_rate == 1.0
    assert not result.unmatched_a


def test_distance_threshold_filters():
    """距離閾値を超えるペアは対応しない。"""
    a = [_cell(0, 0)]
    b = [_cell(100, 100)]
    result = CellMatcher(max_distance_um=5.0).match(a, b, mpp=1.0)
    assert len(result.pairs) == 0
    assert len(result.unmatched_a) == 1
    assert len(result.unmatched_b) == 1


def test_mpp_scaling():
    """mpp により px 距離が μm に換算される。"""
    a = [_cell(0, 0)]
    b = [_cell(10, 0)]  # 10px 離れている
    # mpp=0.5 -> 10px = 5μm。閾値 6μm なら対応する。
    r_ok = CellMatcher(max_distance_um=6.0).match(a, b, mpp=0.5)
    assert len(r_ok.pairs) == 1
    # 閾値 4μm なら対応しない。
    r_ng = CellMatcher(max_distance_um=4.0).match(a, b, mpp=0.5)
    assert len(r_ng.pairs) == 0


def test_mutual_nearest_neighbor():
    """相互最近傍でない対応は採用されない。"""
    a = [_cell(0, 0), _cell(1, 0)]
    b = [_cell(0.5, 0)]  # a[0], a[1] 双方から最近傍だが b は 1 つ
    result = CellMatcher(max_distance_um=5.0).match(a, b, mpp=1.0)
    # b は 1 つしか使われない
    assert len(result.pairs) == 1


def test_empty_input():
    """片側が空でも例外なく空結果を返す。"""
    result = CellMatcher().match([], [_cell(0, 0)], mpp=1.0)
    assert result.match_rate == 0.0
    assert len(result.pairs) == 0
