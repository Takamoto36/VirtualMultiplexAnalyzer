"""Step7: 細胞セグメンテーションモジュール.

DeepLIIF のセグメンテーション結果（ラベル画像）から各細胞の重心・面積・
周囲長・円形度・陽性/陰性を抽出し、:class:`~modules.datatypes.Cell` の
リストとして返す。mpp（μm/px）が既知なら面積・周囲長を物理単位に換算する。
"""
from __future__ import annotations

import logging
from typing import Optional

import numpy as np

from .datatypes import Cell, MarkerChannel

logger = logging.getLogger(__name__)


class CellSegmenter:
    """セグメンテーションラベル画像から細胞特徴量を抽出するクラス。"""

    def __init__(self, mpp: Optional[float] = None) -> None:
        """
        Args:
            mpp: 1 画素あたりのマイクロメートル。``None`` なら画素単位で算出。
        """
        self.mpp = mpp

    def extract_cells(
        self,
        seg: np.ndarray,
        positive_mask: np.ndarray,
        marker_image: Optional[np.ndarray] = None,
        marker: MarkerChannel = MarkerChannel.OTHER,
        min_area_px: int = 20,
    ) -> list[Cell]:
        """ラベル画像から細胞リストを生成する.

        Args:
            seg: ラベル画像 (H, W) int（0=背景）。
            positive_mask: 陽性核マスク (H, W) bool。
            marker_image: マーカー強度画像（平均強度算出用、任意）。
            marker: この切片のマーカー種別。
            min_area_px: これ未満の面積[px]の領域はノイズとして除外。

        Returns:
            :class:`Cell` のリスト。
        """
        from skimage.measure import regionprops

        intensity = None
        if marker_image is not None:
            intensity = marker_image.astype(np.float64)

        cells: list[Cell] = []
        props = regionprops(seg, intensity_image=intensity)
        px_area = (self.mpp ** 2) if self.mpp else 1.0
        px_len = self.mpp if self.mpp else 1.0

        for prop in props:
            if prop.area < min_area_px:
                continue
            perimeter_px = float(prop.perimeter) if prop.perimeter else 0.0
            circularity = (
                4 * np.pi * prop.area / (perimeter_px ** 2) if perimeter_px > 0 else 0.0
            )
            cy, cx = prop.centroid  # regionprops は (row, col)=(y, x)
            # 陽性判定: 核領域内で陽性マスクが過半数を占めるか
            region_mask = seg == prop.label
            positive = bool(positive_mask[region_mask].mean() >= 0.5)
            if intensity is not None:
                _mi = getattr(prop, "intensity_mean", None)
                mean_int = float(_mi if _mi is not None else prop.mean_intensity)
            else:
                mean_int = 0.0

            cells.append(
                Cell(
                    centroid_px=(float(cx), float(cy)),
                    area_um2=float(prop.area) * px_area,
                    perimeter_um=perimeter_px * px_len,
                    circularity=float(np.clip(circularity, 0.0, 1.0)),
                    positive=positive,
                    marker=marker,
                    mean_intensity=mean_int,
                    label=int(prop.label),
                )
            )

        logger.info(
            "細胞抽出 marker=%s 総数=%d 陽性=%d",
            marker.value, len(cells), sum(c.positive for c in cells),
        )
        return cells
