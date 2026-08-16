"""Step2: ROI 選択・管理モジュール.

複数の :class:`~modules.datatypes.ROI` を保持し、追加・削除・取得、および
:class:`~modules.wsi_loader.WSILoader` からの ROI 画像切り出しを担当する。
GUI 側のドラッグ選択結果（レベル0座標）を受け取る想定。
"""
from __future__ import annotations

import logging
from typing import Iterator, Optional

import numpy as np

from .datatypes import ROI
from .wsi_loader import WSILoader

logger = logging.getLogger(__name__)


class ROIManager:
    """1 枚の WSI に紐づく複数 ROI を管理するコンテナ。"""

    def __init__(self) -> None:
        self._rois: list[ROI] = []

    def __iter__(self) -> Iterator[ROI]:
        return iter(self._rois)

    def __len__(self) -> int:
        return len(self._rois)

    @property
    def rois(self) -> list[ROI]:
        """保持している ROI のリスト（コピー）。"""
        return list(self._rois)

    def add(self, roi: ROI) -> ROI:
        """ROI を追加して返す。"""
        self._rois.append(roi)
        logger.debug("ROI 追加: %s %s", roi.name, roi.bounds)
        return roi

    def remove(self, roi_id: str) -> bool:
        """ID 指定で ROI を削除する。削除できたら ``True``。"""
        before = len(self._rois)
        self._rois = [r for r in self._rois if r.id != roi_id]
        return len(self._rois) != before

    def get(self, roi_id: str) -> Optional[ROI]:
        """ID 指定で ROI を取得する。"""
        return next((r for r in self._rois if r.id == roi_id), None)

    def clear(self) -> None:
        """全 ROI を削除する。"""
        self._rois.clear()

    @staticmethod
    def extract_image(loader: WSILoader, roi: ROI, level: int = 0) -> np.ndarray:
        """指定 ROI に対応する画像を切り出す.

        Args:
            loader: 対象 WSI の読込オブジェクト。
            roi: 切り出す領域（レベル0座標）。
            level: 読み出すレベル（既定はフル解像度）。

        Returns:
            RGB 配列 (H, W, 3) uint8。
        """
        # OpenSlide の read_region は location=level0 座標・size=level スケール。
        scale = 1
        if loader._slide is not None:  # noqa: SLF001
            scale = loader._slide.level_downsamples[level]  # type: ignore[union-attr]
        size = (int(roi.width / scale), int(roi.height / scale))
        return loader.read_region((roi.x, roi.y), level, size)
