"""Step9: 定量統計解析モジュール.

対応付けられた細胞ペアから、2 マーカー（例: Ki67 と p53）の共陽性・単陽性・
共陰性のクロス集計と各種指標（陽性率・オーバーラップ率・Index）を算出する。
ROI 単位・全体の両方に対応する。
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass

from .matching import MatchingResult

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class CrossTab:
    """2 マーカーのクロス集計結果.

    Attributes:
        marker_a: マーカー A 名（例: "Ki67"）。
        marker_b: マーカー B 名（例: "p53"）。
        both_positive: A+ かつ B+ の細胞数。
        a_pos_b_neg: A+ B- の数。
        a_neg_b_pos: A- B+ の数。
        both_negative: A- B- の数。
        total: 対応が成立したペア総数。
    """

    marker_a: str
    marker_b: str
    both_positive: int = 0
    a_pos_b_neg: int = 0
    a_neg_b_pos: int = 0
    both_negative: int = 0
    total: int = 0

    # --- 指標 ---------------------------------------------------------
    @property
    def a_positive_total(self) -> int:
        """マーカー A 陽性数。"""
        return self.both_positive + self.a_pos_b_neg

    @property
    def b_positive_total(self) -> int:
        """マーカー B 陽性数。"""
        return self.both_positive + self.a_neg_b_pos

    @property
    def a_index(self) -> float:
        """マーカー A の陽性率（Index）。"""
        return self.a_positive_total / self.total if self.total else 0.0

    @property
    def b_index(self) -> float:
        """マーカー B の陽性率（Index）。"""
        return self.b_positive_total / self.total if self.total else 0.0

    @property
    def overlap_rate(self) -> float:
        """共陽性のオーバーラップ率（Jaccard: A+∩B+ / A+∪B+）。"""
        union = self.both_positive + self.a_pos_b_neg + self.a_neg_b_pos
        return self.both_positive / union if union else 0.0

    @property
    def co_positive_rate(self) -> float:
        """全対応細胞に占める共陽性率。"""
        return self.both_positive / self.total if self.total else 0.0

    def as_dict(self) -> dict:
        """指標を含む辞書表現（CSV/Excel 出力用）。"""
        d = asdict(self)
        d.update(
            {
                "a_positive_total": self.a_positive_total,
                "b_positive_total": self.b_positive_total,
                "a_index": round(self.a_index, 4),
                "b_index": round(self.b_index, 4),
                "overlap_rate": round(self.overlap_rate, 4),
                "co_positive_rate": round(self.co_positive_rate, 4),
            }
        )
        return d


class StatisticsCalculator:
    """マッチング結果からクロス集計・指標を計算するクラス。"""

    def compute(
        self,
        result: MatchingResult,
        marker_a: str = "Ki67",
        marker_b: str = "p53",
    ) -> CrossTab:
        """対応ペアから 2 マーカーのクロス集計を計算する.

        Args:
            result: :class:`~modules.matching.MatchingResult`。
            marker_a: A 側マーカー名。
            marker_b: B 側マーカー名。
        """
        tab = CrossTab(marker_a=marker_a, marker_b=marker_b)
        for pair in result.pairs:
            if pair.cell_b is None:
                continue
            a_pos = pair.cell_a.positive
            b_pos = pair.cell_b.positive
            if a_pos and b_pos:
                tab.both_positive += 1
            elif a_pos and not b_pos:
                tab.a_pos_b_neg += 1
            elif not a_pos and b_pos:
                tab.a_neg_b_pos += 1
            else:
                tab.both_negative += 1
            tab.total += 1

        logger.info(
            "統計: %s+/%s+=%d, %s+only=%d, %s+only=%d, both-=%d (n=%d)",
            marker_a, marker_b, tab.both_positive,
            marker_a, tab.a_pos_b_neg, marker_b, tab.a_neg_b_pos,
            tab.both_negative, tab.total,
        )
        return tab
