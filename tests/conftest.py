"""pytest 共通フィクスチャ・ヘルパー.

ロジックモジュールの単体テストで再利用する ``Cell`` 生成ヘルパーなどを提供する。
GUI や外部依存（OpenSlide / DeepLIIF / SimpleITK）を必要としないため、
これらが未インストールの環境でもロジックテストは実行できる。
"""
from __future__ import annotations

from modules.datatypes import Cell, MarkerChannel


def make_cell(
    x: float,
    y: float,
    positive: bool = False,
    marker: MarkerChannel = MarkerChannel.KI67,
    area_um2: float = 50.0,
) -> Cell:
    """テスト用に最小限の :class:`~modules.datatypes.Cell` を生成する.

    Args:
        x: 重心 x[px]。
        y: 重心 y[px]。
        positive: マーカー陽性か。
        marker: 由来マーカー。
        area_um2: 面積[μm^2]。

    Returns:
        指定した重心・陽性を持つ ``Cell``。
    """
    return Cell(
        centroid_px=(x, y),
        area_um2=area_um2,
        perimeter_um=25.0,
        circularity=0.9,
        positive=positive,
        marker=marker,
        mean_intensity=200.0 if positive else 20.0,
    )
