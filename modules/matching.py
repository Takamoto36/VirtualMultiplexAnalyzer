"""Step8: Cell Matching モジュール.

2 切片間で細胞を対応付ける。位置合わせ後の重心座標に対し KDTree による
最近傍探索を行い、距離閾値（μm 単位）以内のペアを対応候補とする。相互
最近傍（mutual nearest neighbor）を満たすもののみ採用することで、多対一の
誤対応を抑制する。一致率・未対応細胞も報告する。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
from scipy.spatial import cKDTree

from .datatypes import Cell, MatchPair

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class MatchingResult:
    """マッチング結果のまとめ.

    Attributes:
        pairs: 成立した対応ペア。
        unmatched_a: 対応先が見つからなかった A 側細胞。
        unmatched_b: 対応先が見つからなかった B 側細胞。
        match_rate: 一致率（対応ペア数 / min(|A|, |B|)）。
    """

    pairs: list[MatchPair]
    unmatched_a: list[Cell]
    unmatched_b: list[Cell]
    match_rate: float


class CellMatcher:
    """KDTree 最近傍による細胞対応付けクラス。"""

    def __init__(self, max_distance_um: float = 10.0, mutual: bool = True) -> None:
        """
        Args:
            max_distance_um: 対応とみなす重心間距離の上限[μm]。
            mutual: 相互最近傍のみ採用するか。
        """
        self.max_distance_um = max_distance_um
        self.mutual = mutual

    def match(
        self, cells_a: list[Cell], cells_b: list[Cell], mpp: float | None = None
    ) -> MatchingResult:
        """A 側と B 側の細胞を対応付ける.

        Args:
            cells_a: 基準切片の細胞（例: Ki67）。
            cells_b: 対応先切片の細胞（例: p53）。
            mpp: μm/px。重心が px 座標のとき距離を μm に換算するために使用。
                ``None`` の場合は座標をそのまま μm とみなす。

        Returns:
            :class:`MatchingResult`。
        """
        if not cells_a or not cells_b:
            logger.warning("片側の細胞が空のためマッチングをスキップします。")
            return MatchingResult([], list(cells_a), list(cells_b), 0.0)

        scale = mpp if mpp else 1.0
        coords_a = np.array([c.centroid_px for c in cells_a]) * scale
        coords_b = np.array([c.centroid_px for c in cells_b]) * scale

        tree_b = cKDTree(coords_b)
        dist_ab, idx_ab = tree_b.query(coords_a, k=1)

        matched_b_used: set[int] = set()
        pairs: list[MatchPair] = []
        matched_a_flags = [False] * len(cells_a)

        if self.mutual:
            tree_a = cKDTree(coords_a)
            _, idx_ba = tree_a.query(coords_b, k=1)

        for ai, (d, bi) in enumerate(zip(dist_ab, idx_ab)):
            if d > self.max_distance_um:
                continue
            if self.mutual and idx_ba[bi] != ai:
                continue  # 相互最近傍でない
            if bi in matched_b_used:
                continue  # 既に使用済み
            pairs.append(MatchPair(cell_a=cells_a[ai], cell_b=cells_b[bi], distance_um=float(d)))
            matched_b_used.add(int(bi))
            matched_a_flags[ai] = True

        unmatched_a = [c for c, ok in zip(cells_a, matched_a_flags) if not ok]
        unmatched_b = [c for i, c in enumerate(cells_b) if i not in matched_b_used]
        denom = min(len(cells_a), len(cells_b))
        match_rate = len(pairs) / denom if denom else 0.0

        logger.info(
            "Cell Matching: 対応=%d 未対応A=%d 未対応B=%d 一致率=%.1f%%",
            len(pairs), len(unmatched_a), len(unmatched_b), match_rate * 100,
        )
        return MatchingResult(pairs, unmatched_a, unmatched_b, match_rate)
