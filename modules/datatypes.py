"""共有データ型モジュール.

各解析モジュール間で受け渡すデータ構造（ROI・WSIメタデータ・細胞・
マッチング結果など）を ``dataclass`` として定義する。GUI とビジネス
ロジックの両方から参照される「共通言語」であり、循環インポートを避ける
ため依存を持たない軽量モジュールとして分離している。
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


def _new_id() -> str:
    """短い一意 ID を生成する（GUI 表示・CSV 出力用）。"""
    return uuid.uuid4().hex[:8]


class MarkerChannel(str, Enum):
    """マーカーチャネルの種別。将来の任意枚数対応を見据えて文字列 Enum とする。"""

    KI67 = "Ki67"
    P53 = "p53"
    ER = "ER"
    PR = "PR"
    HER2 = "HER2"
    PDL1 = "PD-L1"
    CD8 = "CD8"
    FOXP3 = "FOXP3"
    OTHER = "Other"


@dataclass(slots=True)
class WSIMetadata:
    """WSI（Whole Slide Image）1 枚分のメタデータ.

    Attributes:
        path: 画像ファイルの絶対パス。
        width: レベル0（最大解像度）の幅[px]。
        height: レベル0の高さ[px]。
        level_count: ピラミッドのレベル数。
        magnification: 対物倍率（例: 40.0）。取得できない場合は ``None``。
        mpp_x: 1 ピクセルあたりのマイクロメートル（横）。
        mpp_y: 1 ピクセルあたりのマイクロメートル（縦）。
        vendor: ベンダー名（Hamamatsu 等）。
    """

    path: str
    width: int
    height: int
    level_count: int = 1
    magnification: Optional[float] = None
    mpp_x: Optional[float] = None
    mpp_y: Optional[float] = None
    vendor: Optional[str] = None

    @property
    def mpp(self) -> Optional[float]:
        """代表的な mpp（縦横平均）。μm 単位の計算に用いる。"""
        vals = [v for v in (self.mpp_x, self.mpp_y) if v]
        return sum(vals) / len(vals) if vals else None


@dataclass(slots=True)
class ROI:
    """関心領域（Region Of Interest）.

    座標はすべてレベル0（最大解像度）基準の画素で保持する。表示レベルに
    依存しない絶対座標にすることで、ズーム状態と切り離して扱える。
    """

    x: int
    y: int
    width: int
    height: int
    name: str = ""
    id: str = field(default_factory=_new_id)

    def __post_init__(self) -> None:
        if not self.name:
            self.name = f"ROI_{self.id}"

    @property
    def bounds(self) -> tuple[int, int, int, int]:
        """(x, y, width, height) のタプルを返す。"""
        return (self.x, self.y, self.width, self.height)

    def as_dict(self) -> dict:
        """JSON シリアライズ用の辞書表現。"""
        return {
            "id": self.id,
            "name": self.name,
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
        }


@dataclass(slots=True)
class Cell:
    """セグメンテーションで得られた 1 細胞（核）の形態・陽性情報.

    Attributes:
        centroid_px: 重心座標 (x, y)[px]（ROI ローカル座標）。
        area_um2: 面積[μm^2]。mpp 不明時は px^2。
        perimeter_um: 周囲長[μm]。
        circularity: 円形度 4πA/P^2（1 に近いほど円形）。
        positive: マーカー陽性か否か。
        marker: 由来マーカーチャネル。
        mean_intensity: 核内マーカー平均強度（0-255 想定）。
        label: セグメンテーションラベル値。
    """

    centroid_px: tuple[float, float]
    area_um2: float
    perimeter_um: float
    circularity: float
    positive: bool = False
    marker: MarkerChannel = MarkerChannel.OTHER
    mean_intensity: float = 0.0
    label: int = 0
    id: str = field(default_factory=_new_id)

    def as_row(self) -> dict:
        """pandas DataFrame 化のための 1 行辞書。"""
        return {
            "cell_id": self.id,
            "marker": self.marker.value,
            "centroid_x": self.centroid_px[0],
            "centroid_y": self.centroid_px[1],
            "area_um2": self.area_um2,
            "perimeter_um": self.perimeter_um,
            "circularity": self.circularity,
            "mean_intensity": self.mean_intensity,
            "positive": int(self.positive),
        }


@dataclass(slots=True)
class MatchPair:
    """2 切片間で対応付けられた細胞ペア.

    Attributes:
        cell_a: 基準切片側の細胞。
        cell_b: 対応先切片側の細胞（対応なしの場合 ``None``）。
        distance_um: 重心間距離[μm]。
    """

    cell_a: Cell
    cell_b: Optional[Cell]
    distance_um: float = float("inf")

    @property
    def matched(self) -> bool:
        """対応が成立しているか。"""
        return self.cell_b is not None
