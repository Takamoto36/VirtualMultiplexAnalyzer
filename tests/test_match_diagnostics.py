"""``modules.match_diagnostics`` の単体テスト.

診断が「本当に同一細胞が対応している場合」と「たまたま近くにいるだけの場合」を
区別できることを検証する。これが区別できなければ、連続切片の Cell Matching が
意味を持つかを判定できない。
"""
from __future__ import annotations

import numpy as np
import pytest

from modules.datatypes import MarkerChannel
from modules.match_diagnostics import (
    diagnose,
    nn_distances,
    random_control_distances,
    threshold_sensitivity,
)
from tests.conftest import make_cell


def _cells(coords, positive=False, marker=MarkerChannel.KI67):
    return [make_cell(float(x), float(y), positive=positive, marker=marker)
            for x, y in coords]


def test_true_correspondence_is_distinguishable() -> None:
    """同一細胞がわずかにずれて存在する場合、観測は帰無モデルと明確に分離する。"""
    rng = np.random.default_rng(0)
    base = rng.uniform(0, 500, size=(200, 2))
    cells_a = _cells(base)
    # B は各細胞が 1 px 以内にずれただけ = 真の対応がある
    cells_b = _cells(base + rng.normal(0, 0.5, size=base.shape))

    diag = diagnose(cells_a, cells_b, mpp=1.0)
    assert diag.is_distinguishable, diag.summary()
    assert np.median(diag.observed) < np.median(diag.control)
    assert diag.separation > 0.5


def test_random_positions_are_not_distinguishable() -> None:
    """B が A と無関係なランダム配置なら、観測は帰無モデルと区別できない。"""
    rng = np.random.default_rng(1)
    cells_a = _cells(rng.uniform(0, 500, size=(200, 2)))
    cells_b = _cells(rng.uniform(0, 500, size=(200, 2)))  # 独立ランダム

    diag = diagnose(cells_a, cells_b, mpp=1.0)
    assert not diag.is_distinguishable, diag.summary()
    assert abs(diag.separation) < 0.2


def test_nn_distances_basic() -> None:
    """最近傍距離が μm 換算され、A の細胞数だけ返る。"""
    cells_a = _cells([(0, 0), (10, 0)])
    cells_b = _cells([(3, 0)])
    d = nn_distances(cells_a, cells_b, mpp=2.0)  # 1px = 2um
    assert d.shape == (2,)
    assert np.isclose(d[0], 6.0)   # 3px * 2um
    assert np.isclose(d[1], 14.0)  # 7px * 2um


def test_empty_inputs_are_safe() -> None:
    """空入力でも例外を出さず、診断不能として扱う。"""
    assert nn_distances([], [], 1.0).size == 0
    assert random_control_distances([], [], 1.0).size == 0
    diag = diagnose([], [], mpp=1.0)
    assert diag.separation == 0.0
    assert "診断不能" in diag.summary()


def test_threshold_sensitivity_is_monotonic_in_pairs() -> None:
    """閾値を広げるとペア数は単調非減少になる。"""
    rng = np.random.default_rng(2)
    base = rng.uniform(0, 200, size=(60, 2))
    cells_a = _cells(base)
    cells_b = _cells(base + rng.normal(0, 2.0, size=base.shape),
                     marker=MarkerChannel.P53)

    rows = threshold_sensitivity(cells_a, cells_b, mpp=1.0,
                                 thresholds_um=[1.0, 3.0, 5.0, 10.0])
    pairs = [r.n_pairs for r in rows]
    assert pairs == sorted(pairs), f"ペア数が単調でない: {pairs}"
    assert rows[-1].threshold_um == 10.0


def test_control_is_reproducible() -> None:
    """同じ seed なら帰無分布は再現する。"""
    rng = np.random.default_rng(3)
    a = _cells(rng.uniform(0, 100, size=(30, 2)))
    b = _cells(rng.uniform(0, 100, size=(30, 2)))
    d1 = random_control_distances(a, b, mpp=1.0, seed=42)
    d2 = random_control_distances(a, b, mpp=1.0, seed=42)
    assert np.allclose(d1, d2)
