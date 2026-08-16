"""Cell Matching の妥当性診断モジュール.

連続切片（例: Ki67 切片と p53 切片）では、切片厚（3-4 μm）と核径（5-10 μm）が
同程度のため、**「距離が近い」ことは「同一細胞である」ことを意味しない**。
Matching 距離を 10 μm に設定すると、核径程度の範囲内には必ず「何らかの核」が
見つかるため、高い一致率は自動的に達成されてしまう。

本モジュールは、その対応付けが偶然以上のものかをデータで検証する手段を提供する。

主な機能:
    * :func:`nn_distances` — 閾値なしの最近傍距離分布（観測値）
    * :func:`random_control_distances` — 同密度のランダム点過程に対する最近傍距離
      （帰無モデル）。観測分布がこれと区別できなければ、対応付けは偶然と
      同等であり「同一細胞の同定」とは呼べない。
    * :func:`threshold_sensitivity` — 距離閾値を変えたときの一致率・共陽性率の
      感度分析。指標が閾値に強く依存するなら、その指標は頑健でない。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
from scipy.spatial import cKDTree

from .datatypes import Cell
from .matching import CellMatcher
from .statistics import StatisticsCalculator

logger = logging.getLogger(__name__)


def _coords_um(cells: list[Cell], mpp: float) -> np.ndarray:
    """細胞重心を μm 単位の (N, 2) 配列に変換する。"""
    if not cells:
        return np.empty((0, 2), dtype=float)
    return np.array([c.centroid_px for c in cells], dtype=float) * float(mpp)


def nn_distances(cells_a: list[Cell], cells_b: list[Cell], mpp: float) -> np.ndarray:
    """A の各細胞から B の最近傍細胞までの距離[μm]を返す（閾値なし）.

    Args:
        cells_a: 切片 A の細胞（レジストレーション後の座標系）。
        cells_b: 切片 B の細胞（同上）。
        mpp: μm/pixel。

    Returns:
        長さ ``len(cells_a)`` の距離配列[μm]。B が空なら空配列。
    """
    pa, pb = _coords_um(cells_a, mpp), _coords_um(cells_b, mpp)
    if len(pa) == 0 or len(pb) == 0:
        return np.empty(0, dtype=float)
    dist, _ = cKDTree(pb).query(pa, k=1)
    return np.asarray(dist, dtype=float)


def random_control_distances(
    cells_a: list[Cell],
    cells_b: list[Cell],
    mpp: float,
    n_repeat: int = 10,
    seed: int = 0,
) -> np.ndarray:
    """帰無モデル: B を同密度のランダム点過程に置き換えた最近傍距離[μm].

    B 細胞の外接矩形内に、B と同数の点を一様ランダムに配置し、A からの最近傍
    距離を求める。これを ``n_repeat`` 回繰り返して結合する。

    観測分布（:func:`nn_distances`）がこの帰無分布より **有意に小さくなければ**、
    「A の細胞の近くに B の細胞がある」ことは細胞密度から予想される以上の
    情報を持たない。すなわち同一細胞の同定はできていない。

    Args:
        cells_a: 切片 A の細胞。
        cells_b: 切片 B の細胞（密度と配置範囲の参照に使う）。
        mpp: μm/pixel。
        n_repeat: ランダム配置の反復回数。
        seed: 乱数シード（再現性のため）。

    Returns:
        結合された距離配列[μm]。
    """
    pa, pb = _coords_um(cells_a, mpp), _coords_um(cells_b, mpp)
    if len(pa) == 0 or len(pb) == 0:
        return np.empty(0, dtype=float)

    lo, hi = pb.min(axis=0), pb.max(axis=0)
    span = np.maximum(hi - lo, 1e-6)  # 退化した範囲を回避
    rng = np.random.default_rng(seed)

    out: list[np.ndarray] = []
    for _ in range(n_repeat):
        rand_b = lo + rng.random((len(pb), 2)) * span
        dist, _ = cKDTree(rand_b).query(pa, k=1)
        out.append(np.asarray(dist, dtype=float))
    return np.concatenate(out)


@dataclass(slots=True)
class ThresholdRow:
    """距離閾値ごとの指標。"""

    threshold_um: float
    n_pairs: int
    match_rate: float
    both_positive: int
    co_positive_rate: float
    overlap_rate: float
    median_distance_um: float

    def as_dict(self) -> dict:
        return {
            "threshold_um": self.threshold_um,
            "n_pairs": self.n_pairs,
            "match_rate": self.match_rate,
            "both_positive": self.both_positive,
            "co_positive_rate": self.co_positive_rate,
            "overlap_rate": self.overlap_rate,
            "median_distance_um": self.median_distance_um,
        }


@dataclass(slots=True)
class MatchDiagnostics:
    """マッチング診断の総合結果.

    Attributes:
        observed: 観測された最近傍距離[μm]。
        control: 帰無モデル（ランダム配置）の最近傍距離[μm]。
        separation: 観測と帰無の分離度。中央値の差を帰無の中央値で割った値。
            0 に近いほど「偶然と区別できない」。
        rows: 閾値ごとの感度分析。
    """

    observed: np.ndarray
    control: np.ndarray
    separation: float
    rows: list[ThresholdRow] = field(default_factory=list)

    @property
    def is_distinguishable(self) -> bool:
        """観測が帰無モデルと実質的に区別できるか（経験的に separation > 0.2）。"""
        return self.separation > 0.2

    def as_summary_dict(self) -> dict:
        """エクスポート用の要約辞書（1 行）。"""
        obs_med = float(np.median(self.observed)) if self.observed.size else float("nan")
        ctl_med = float(np.median(self.control)) if self.control.size else float("nan")
        return {
            "observed_median_um": round(obs_med, 3),
            "random_control_median_um": round(ctl_med, 3),
            "separation": round(self.separation, 4),
            "distinguishable_from_chance": self.is_distinguishable,
            "interpretation": (
                "対応付けに情報あり（観測が帰無より近い）"
                if self.is_distinguishable
                else "偶然と区別できない：共陽性率など細胞レベル指標は"
                "同一細胞の共発現の証拠にならない"
            ),
        }

    def threshold_rows_dicts(self) -> list[dict]:
        """閾値感度分析の各行を辞書化する。"""
        return [r.as_dict() for r in self.rows]

    def summary(self) -> str:
        """人間可読な要約を返す。"""
        if self.observed.size == 0 or self.control.size == 0:
            return "診断不能（細胞が検出されていません）"
        obs_med = float(np.median(self.observed))
        ctl_med = float(np.median(self.control))
        verdict = (
            "観測分布は帰無モデルより明確に近く、対応付けに情報がある"
            if self.is_distinguishable
            else "観測分布は帰無モデルと区別しにくい。"
            "「距離が近い」ことは細胞密度から予想される以上の意味を持たず、"
            "同一細胞の同定とは言えない"
        )
        return (
            f"最近傍距離 中央値: 観測={obs_med:.2f} μm / ランダム対照={ctl_med:.2f} μm\n"
            f"分離度={self.separation:.3f} → {verdict}"
        )


def threshold_sensitivity(
    cells_a: list[Cell],
    cells_b: list[Cell],
    mpp: float,
    thresholds_um: "list[float] | None" = None,
    marker_a: str = "A",
    marker_b: str = "B",
) -> list[ThresholdRow]:
    """距離閾値を変えたときの一致率・共陽性率の感度分析を行う.

    指標が閾値に強く依存するなら、その指標は閾値の恣意的選択に左右されており
    頑健でない。逆に広い範囲で安定なら、その指標は信頼できる。

    Args:
        cells_a: 切片 A の細胞。
        cells_b: 切片 B の細胞（整列後）。
        mpp: μm/pixel。
        thresholds_um: 試す閾値[μm]。既定は 1〜15 μm。
        marker_a: マーカー A 名（統計のラベル）。
        marker_b: マーカー B 名。

    Returns:
        :class:`ThresholdRow` のリスト。
    """
    if thresholds_um is None:
        thresholds_um = [1.0, 2.0, 3.0, 4.0, 5.0, 7.5, 10.0, 12.5, 15.0]

    calc = StatisticsCalculator()
    rows: list[ThresholdRow] = []
    for t in thresholds_um:
        res = CellMatcher(max_distance_um=t).match(cells_a, cells_b, mpp=mpp)
        tab = calc.compute(res, marker_a, marker_b)
        dists = [p.distance_um for p in res.pairs if p.cell_b is not None]
        med = float(np.median(dists)) if dists else float("nan")
        rows.append(
            ThresholdRow(
                threshold_um=float(t),
                n_pairs=len(res.pairs),
                match_rate=float(res.match_rate),
                both_positive=int(tab.both_positive),
                co_positive_rate=float(tab.co_positive_rate),
                overlap_rate=float(tab.overlap_rate),
                median_distance_um=med,
            )
        )
    return rows


def diagnose(
    cells_a: list[Cell],
    cells_b: list[Cell],
    mpp: float,
    thresholds_um: "list[float] | None" = None,
    marker_a: str = "A",
    marker_b: str = "B",
    seed: int = 0,
) -> MatchDiagnostics:
    """マッチングの妥当性を総合診断する.

    Returns:
        :class:`MatchDiagnostics`。細胞が空なら分離度 0 の空診断を返す。
    """
    observed = nn_distances(cells_a, cells_b, mpp)
    control = random_control_distances(cells_a, cells_b, mpp, seed=seed)

    if observed.size == 0 or control.size == 0:
        return MatchDiagnostics(observed, control, separation=0.0, rows=[])

    obs_med = float(np.median(observed))
    ctl_med = float(np.median(control))
    separation = (ctl_med - obs_med) / ctl_med if ctl_med > 0 else 0.0

    rows = threshold_sensitivity(cells_a, cells_b, mpp, thresholds_um, marker_a, marker_b)
    diag = MatchDiagnostics(observed, control, float(separation), rows)
    logger.info("Matching 診断: %s", diag.summary().replace("\n", " | "))
    return diag
