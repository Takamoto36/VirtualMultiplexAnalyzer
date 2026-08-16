"""領域レベル（タイル単位）の共局在解析モジュール.

連続切片では細胞レベルの 1:1 対応は成立しない（``match_diagnostics`` 参照）。
そこで解析単位を **細胞ペアからタイル（小領域）へ引き上げる**。各タイルで
マーカー A・B の陽性細胞密度を求め、タイル間で両密度が相関するかを見る。
「同じ組織領域で Ki67 と p53 がともに高いか」という、連続切片でも正当に
答えられる問いに変換する。

これは病理学的に自然な単位でもある（腫瘍胞巣・上皮バンドなどの領域単位）。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

from .datatypes import Cell

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RegionResult:
    """タイル単位の密度相関の結果.

    Attributes:
        tile_um: タイル 1 辺の長さ[μm]。
        a_density: 各タイルのマーカー A 陽性密度 [cells/mm^2]（有効タイルのみ）。
        b_density: 各タイルのマーカー B 陽性密度 [cells/mm^2]。
        pearson_r: 陽性密度の Pearson 相関係数。
        spearman_rho: Spearman 順位相関。
        n_tiles: 相関に用いた有効タイル数（両切片に細胞が存在するタイル）。
        a_density_map: A 陽性密度の 2D マップ（可視化用, 行=y, 列=x）。
        b_density_map: B 陽性密度の 2D マップ。
        marker_a: マーカー A 名。
        marker_b: マーカー B 名。
    """

    tile_um: float
    a_density: np.ndarray
    b_density: np.ndarray
    pearson_r: float
    spearman_rho: float
    n_tiles: int
    a_density_map: np.ndarray
    b_density_map: np.ndarray
    marker_a: str = "A"
    marker_b: str = "B"

    def summary(self) -> str:
        if self.n_tiles < 3:
            return f"領域相関: 有効タイル {self.n_tiles} 個（少なすぎて評価不能）"
        return (
            f"領域レベル共局在（タイル {self.tile_um:.0f} μm, n={self.n_tiles}）: "
            f"{self.marker_a}密度 vs {self.marker_b}密度 "
            f"Pearson r={self.pearson_r:.3f}, Spearman ρ={self.spearman_rho:.3f}"
        )

    def as_dict(self) -> dict:
        return {
            "tile_um": self.tile_um,
            "n_tiles": self.n_tiles,
            "pearson_r": round(self.pearson_r, 4),
            "spearman_rho": round(self.spearman_rho, 4),
            "marker_a": self.marker_a,
            "marker_b": self.marker_b,
        }


def _positive_counts_grid(
    cells: list[Cell], shape: tuple[int, int], tile_px: int
) -> tuple[np.ndarray, np.ndarray]:
    """タイルごとの (陽性細胞数, 総細胞数) グリッドを返す.

    Returns:
        (pos_grid, total_grid) いずれも (n_rows, n_cols) の 2D 配列。
    """
    h, w = shape
    n_rows = max(1, int(np.ceil(h / tile_px)))
    n_cols = max(1, int(np.ceil(w / tile_px)))
    pos = np.zeros((n_rows, n_cols), dtype=float)
    tot = np.zeros((n_rows, n_cols), dtype=float)
    for c in cells:
        x, y = c.centroid_px
        r = min(int(y // tile_px), n_rows - 1)
        col = min(int(x // tile_px), n_cols - 1)
        tot[r, col] += 1
        if c.positive:
            pos[r, col] += 1
    return pos, tot


def analyze_regions(
    cells_a: list[Cell],
    cells_b: list[Cell],
    shape: tuple[int, int],
    mpp: float,
    tile_um: float = 100.0,
    min_cells_per_tile: int = 5,
    marker_a: str = "A",
    marker_b: str = "B",
) -> RegionResult:
    """タイル単位で A・B の陽性密度相関を計算する.

    Args:
        cells_a: マーカー A（例 Ki67）の細胞（A 座標系）。
        cells_b: マーカー B（例 p53）の細胞。**レジストレーションで A 座標系へ
            整列済み**であること（パイプラインではそうなっている）。
        shape: 解析領域のサイズ (H, W)[px]。通常は ROI サイズ。
        mpp: μm/pixel。
        tile_um: タイル 1 辺[μm]。既定 100 μm（≈1 視野の一部）。
        min_cells_per_tile: 密度を評価する最小総細胞数（疎なタイルの除外）。
        marker_a: マーカー A 名。
        marker_b: マーカー B 名。

    Returns:
        :class:`RegionResult`。
    """
    from scipy.stats import pearsonr, spearmanr

    tile_px = max(1, int(round(tile_um / mpp)))
    pa, ta = _positive_counts_grid(cells_a, shape, tile_px)
    pb, tb = _positive_counts_grid(cells_b, shape, tile_px)

    # タイル面積[mm^2]（密度 = 陽性数 / 面積）
    tile_area_mm2 = (tile_px * mpp / 1000.0) ** 2
    a_map = pa / tile_area_mm2
    b_map = pb / tile_area_mm2

    # 両切片に十分な細胞があるタイルのみを相関対象にする
    valid = (ta >= min_cells_per_tile) & (tb >= min_cells_per_tile)
    a_vals = a_map[valid]
    b_vals = b_map[valid]

    if a_vals.size >= 3 and np.ptp(a_vals) > 0 and np.ptp(b_vals) > 0:
        pear = float(pearsonr(a_vals, b_vals)[0])
        spear = float(spearmanr(a_vals, b_vals)[0])
    else:
        pear = float("nan")
        spear = float("nan")

    result = RegionResult(
        tile_um=float(tile_um),
        a_density=a_vals,
        b_density=b_vals,
        pearson_r=pear,
        spearman_rho=spear,
        n_tiles=int(a_vals.size),
        a_density_map=a_map,
        b_density_map=b_map,
        marker_a=marker_a,
        marker_b=marker_b,
    )
    logger.info("%s", result.summary())
    return result
