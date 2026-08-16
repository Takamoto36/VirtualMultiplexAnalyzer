"""Step4 & Step6: 疑似蛍光（Pseudo Fluorescence）生成・合成モジュール.

マーカー強度画像（グレースケール）を任意の RGB 疑似カラーで着色し（Step4）、
複数チャネルを Merge / Overlay / Difference で合成する（Step6）。

.. note::
    ここで生成されるのは **Pseudo Fluorescence（色分離ベースの疑似蛍光）** であり、
    DeepLIIF が深層学習で生成する **Virtual IF（mpIF モダリティ）ではない**。
    DeepLIIF クラウド API は Seg 系画像のみを返し、mpIF DAPI / Marker は
    返さないため、本アプリではマーカー強度を元 IHC の DAB 成分（color
    deconvolution）から復元して着色している。可視化用途に限り有用であり、
    「DeepLIIF が生成した多重免疫蛍光画像」として提示してはならない。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

import numpy as np

logger = logging.getLogger(__name__)

MergeMode = Literal["merge", "overlay", "difference"]

#: プリセット疑似カラー（GUI の Color Picker 初期候補）。
COLOR_PRESETS: dict[str, tuple[int, int, int]] = {
    "Green": (0, 255, 0),
    "Red": (255, 0, 0),
    "Blue": (0, 0, 255),
    "Yellow": (255, 255, 0),
    "Magenta": (255, 0, 255),
    "Cyan": (0, 255, 255),
    "White": (255, 255, 255),
}


@dataclass(slots=True)
class Channel:
    """マージ対象の 1 チャネル.

    Attributes:
        name: 表示名（例: "Ki67"）。
        gray: グレースケール強度 (H, W) uint8。
        color: 疑似カラー RGB。
        visible: 表示 ON/OFF。
        alpha: 不透明度（0.0-1.0）。
    """

    name: str
    gray: np.ndarray
    color: tuple[int, int, int] = (255, 255, 255)
    visible: bool = True
    alpha: float = 1.0


def pseudo_color(gray: np.ndarray, color: tuple[int, int, int]) -> np.ndarray:
    """グレースケールを疑似カラー RGB 画像へ変換する.

    Args:
        gray: 強度画像 (H, W)。uint8 または float。
        color: 適用する RGB（各 0-255）。

    Returns:
        RGB 配列 (H, W, 3) uint8。強度に比例して指定色が発色する。
    """
    g = gray.astype(np.float64)
    if g.max() > 1.0:
        g = g / 255.0
    g = np.clip(g, 0.0, 1.0)
    rgb = np.stack([g * c for c in color], axis=-1)
    return np.clip(rgb, 0, 255).astype(np.uint8)


def merge_channels(channels: list[Channel], mode: MergeMode = "merge") -> np.ndarray:
    """複数チャネルを合成して 1 枚の RGB 画像を返す.

    Args:
        channels: 合成対象。``visible=False`` は無視される。
        mode: 合成方法。
            * ``merge``: 各チャネルの発色を加算合成（蛍光多重相当）。
            * ``overlay``: alpha ブレンドで上に重ねる。
            * ``difference``: 先頭2チャネルの差分（位置ずれ確認用）。

    Returns:
        RGB 配列 (H, W, 3) uint8。
    """
    visible = [c for c in channels if c.visible]
    if not visible:
        raise ValueError("表示対象チャネルがありません")

    h, w = visible[0].gray.shape[:2]
    if mode == "difference":
        return _difference(visible)

    acc = np.zeros((h, w, 3), dtype=np.float64)
    for ch in visible:
        colored = pseudo_color(ch.gray, ch.color).astype(np.float64) * ch.alpha
        if mode == "merge":
            acc += colored
        else:  # overlay
            acc = acc * (1 - ch.alpha) + colored
    return np.clip(acc, 0, 255).astype(np.uint8)


def _difference(channels: list[Channel]) -> np.ndarray:
    """先頭 2 チャネルの絶対差分をヒートマップ的に返す。"""
    if len(channels) < 2:
        raise ValueError("Difference には 2 チャネル以上が必要です")
    a = channels[0].gray.astype(np.float64)
    b = channels[1].gray.astype(np.float64)
    diff = np.abs(a - b)
    if diff.max() > 0:
        diff = diff / diff.max() * 255
    # 差分を赤で可視化（大きいほど明るい赤）
    out = np.zeros((*diff.shape, 3), dtype=np.uint8)
    out[..., 0] = diff.astype(np.uint8)
    return out
