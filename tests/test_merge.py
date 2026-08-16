"""``modules.merge`` の単体テスト.

疑似カラー変換とチャネル合成（merge / overlay / difference）の
出力形状・値域・基本的な合成挙動を検証する。
"""
from __future__ import annotations

import numpy as np
import pytest

from modules.merge import (
    COLOR_PRESETS,
    Channel,
    merge_channels,
    pseudo_color,
)


def test_pseudo_color_shape_and_dtype() -> None:
    """(H,W) -> (H,W,3) uint8 に変換される。"""
    gray = np.full((4, 5), 255, dtype=np.uint8)
    out = pseudo_color(gray, (0, 255, 0))
    assert out.shape == (4, 5, 3)
    assert out.dtype == np.uint8


def test_pseudo_color_applies_color() -> None:
    """最大強度で指定色そのものになる（緑なら G のみ 255）。"""
    gray = np.full((2, 2), 255, dtype=np.uint8)
    out = pseudo_color(gray, (0, 255, 0))
    assert np.all(out[..., 0] == 0)
    assert np.all(out[..., 1] == 255)
    assert np.all(out[..., 2] == 0)


def test_pseudo_color_zero_is_black() -> None:
    """強度 0 は黒。"""
    gray = np.zeros((3, 3), dtype=np.uint8)
    out = pseudo_color(gray, (255, 0, 0))
    assert np.all(out == 0)


def test_merge_additive() -> None:
    """緑チャネル + 赤チャネルの merge は黄色になる。"""
    green = Channel("G", np.full((2, 2), 255, np.uint8), COLOR_PRESETS["Green"])
    red = Channel("R", np.full((2, 2), 255, np.uint8), COLOR_PRESETS["Red"])
    out = merge_channels([green, red], mode="merge")
    assert np.all(out[..., 0] == 255)  # R
    assert np.all(out[..., 1] == 255)  # G
    assert np.all(out[..., 2] == 0)   # B


def test_invisible_channel_skipped() -> None:
    """visible=False のチャネルは無視される。"""
    green = Channel("G", np.full((2, 2), 255, np.uint8), COLOR_PRESETS["Green"])
    red = Channel(
        "R", np.full((2, 2), 255, np.uint8), COLOR_PRESETS["Red"], visible=False
    )
    out = merge_channels([green, red], mode="merge")
    assert np.all(out[..., 0] == 0)   # 赤は無効
    assert np.all(out[..., 1] == 255)


def test_no_visible_channel_raises() -> None:
    """表示チャネルが無ければ例外。"""
    hidden = Channel(
        "G", np.zeros((2, 2), np.uint8), COLOR_PRESETS["Green"], visible=False
    )
    with pytest.raises(ValueError):
        merge_channels([hidden], mode="merge")


def test_difference_requires_two() -> None:
    """difference は 2 チャネル未満で例外。"""
    only = Channel("G", np.zeros((2, 2), np.uint8), COLOR_PRESETS["Green"])
    with pytest.raises(ValueError):
        merge_channels([only], mode="difference")


def test_difference_shape() -> None:
    """difference 出力は (H,W,3) uint8。"""
    a = Channel("A", np.zeros((3, 3), np.uint8), COLOR_PRESETS["Green"])
    b = Channel("B", np.full((3, 3), 255, np.uint8), COLOR_PRESETS["Red"])
    out = merge_channels([a, b], mode="difference")
    assert out.shape == (3, 3, 3)
    assert out.dtype == np.uint8
