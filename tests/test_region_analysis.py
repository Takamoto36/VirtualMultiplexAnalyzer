"""``modules.region_analysis`` の単体テスト.

タイル単位の密度相関が、領域スケールの共局在を正しく検出することを検証する。
これは細胞レベルの対応が成立しない連続切片で、正当に使える指標である。
"""
from __future__ import annotations

import numpy as np

from modules.datatypes import MarkerChannel
from modules.region_analysis import analyze_regions
from tests.conftest import make_cell


def _dense_cells(centers, positive_frac, marker, rng):
    cells = []
    for (cx, cy, n) in centers:
        for i in range(n):
            x = cx + rng.uniform(-40, 40)
            y = cy + rng.uniform(-40, 40)
            pos = i < int(n * positive_frac)
            cells.append(make_cell(x, y, positive=pos, marker=marker))
    return cells


def test_region_detects_positive_colocalization() -> None:
    """A と B の陽性密度が同じ領域で高いとき、正の相関を検出する。"""
    rng = np.random.default_rng(0)
    # 3 領域: 陽性割合が高/中/低で A も B も揃う → 正相関
    a_centers = [(150, 150, 60), (450, 150, 60), (150, 450, 60)]
    b_centers = [(150, 150, 60), (450, 150, 60), (150, 450, 60)]
    cells_a = []
    cells_b = []
    for (ca, cb, frac) in zip(a_centers, b_centers, (0.8, 0.5, 0.1)):
        cells_a += _dense_cells([ca], frac, MarkerChannel.KI67, rng)
        cells_b += _dense_cells([cb], frac, MarkerChannel.P53, rng)

    res = analyze_regions(cells_a, cells_b, shape=(600, 600), mpp=1.0,
                          tile_um=150.0, min_cells_per_tile=3,
                          marker_a="Ki67", marker_b="p53")
    assert res.n_tiles >= 3
    assert res.pearson_r > 0.5


def test_region_detects_anticolocalization() -> None:
    """A 高の領域で B 低（住み分け）なら負の相関を検出する。"""
    rng = np.random.default_rng(1)
    cells_a, cells_b = [], []
    for (ca, cb, fa, fb) in [
        ((150, 150, 60), (150, 150, 60), 0.9, 0.1),
        ((450, 150, 60), (450, 150, 60), 0.7, 0.3),
        ((150, 450, 60), (150, 450, 60), 0.1, 0.9),
    ]:
        cells_a += _dense_cells([ca], fa, MarkerChannel.KI67, rng)
        cells_b += _dense_cells([cb], fb, MarkerChannel.P53, rng)

    res = analyze_regions(cells_a, cells_b, shape=(600, 600), mpp=1.0,
                          tile_um=150.0, min_cells_per_tile=3)
    assert res.pearson_r < 0.0


def test_region_density_units() -> None:
    """密度が cells/mm^2 で計算される（100um タイルに 1 陽性 → 100 cells/mm^2）。"""
    # 1 タイル =100um=100px(mpp=1)。面積 = 0.01 mm^2。1 陽性 → 100 /mm^2。
    a = [make_cell(50, 50, positive=True, marker=MarkerChannel.KI67)]
    b = [make_cell(50, 50, positive=True, marker=MarkerChannel.P53)]
    res = analyze_regions(a, b, shape=(100, 100), mpp=1.0, tile_um=100.0,
                          min_cells_per_tile=1)
    assert np.isclose(res.a_density_map.max(), 100.0)


def test_region_empty_is_safe() -> None:
    """細胞が無くても例外を出さず nan 相関を返す。"""
    res = analyze_regions([], [], shape=(200, 200), mpp=1.0)
    assert res.n_tiles == 0
    assert res.pearson_r != res.pearson_r  # nan
    assert "評価不能" in res.summary()
