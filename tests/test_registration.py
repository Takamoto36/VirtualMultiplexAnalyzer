"""``modules.registration`` の単体テスト.

レジストレーションで求めた変換を B 切片のセグメンテーションへ適用すると、
ずれた連続切片でも Cell Matching の一致率が改善することを検証する
（＝レジストレーション結果がマッチングに正しく反映されていることの確認）。
"""
from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("SimpleITK")

from modules.matching import CellMatcher
from modules.registration import Registrar
from modules.segmentation import CellSegmenter
from modules.datatypes import MarkerChannel


def _scene(centers, shift=(0, 0), size=192, r=6):
    """指定重心にガウス核を配置した (dapi, seg, posmask, marker) を作る。"""
    h = w = size
    dapi = np.zeros((h, w), np.float64)
    seg = np.zeros((h, w), np.int32)
    yy, xx = np.mgrid[0:h, 0:w]
    for i, (cy, cx) in enumerate(centers, start=1):
        cy2, cx2 = cy + shift[0], cx + shift[1]
        blob = np.exp(-(((yy - cy2) ** 2 + (xx - cx2) ** 2) / (2 * r**2)))
        dapi += blob
        seg[(yy - cy2) ** 2 + (xx - cx2) ** 2 <= r * r] = i
    dapi = np.clip(dapi / dapi.max() * 255, 0, 255).astype(np.uint8)
    posmask = seg > 0
    marker = (posmask * 200).astype(np.uint8)
    return dapi, seg, posmask, marker


def test_apply_transform_improves_match_rate() -> None:
    """8px ずらした B 切片を登録・warp すると一致率が未整列より改善する。"""
    centers = [(40, 40), (60, 120), (120, 60), (140, 140), (90, 90)]
    shift = (8, 8)  # B 切片は右下に 8px ずれている

    dapi_a, seg_a, pos_a, mk_a = _scene(centers, shift=(0, 0))
    dapi_b, seg_b, pos_b, mk_b = _scene(centers, shift=shift)

    seg = CellSegmenter(mpp=1.0)
    cells_a = seg.extract_cells(seg_a, pos_a, mk_a, MarkerChannel.KI67, min_area_px=5)

    # 未整列のずれは ≈11.3px。整列後の残差は数 px。閾値 8px で before/after を分離する。
    matcher = CellMatcher(max_distance_um=8.0)

    # --- 未整列の B でマッチング（ずれ > 閾値 → ほぼ対応しない）---
    cells_b_raw = seg.extract_cells(seg_b, pos_b, mk_b, MarkerChannel.P53, min_area_px=5)
    rate_before = matcher.match(cells_a, cells_b_raw, mpp=1.0).match_rate

    # --- レジストレーションして B を A 座標系へ warp ---
    reg = Registrar(method="rigid").register(
        fixed=dapi_a, moving=dapi_b, moving_extra=mk_b, compute_field=False
    )
    seg_b_reg = Registrar(method="rigid").apply_transform(
        seg_b, dapi_a, reg.transform_obj, label=True
    )
    pos_b_reg = Registrar(method="rigid").apply_transform(
        pos_b, dapi_a, reg.transform_obj, label=True
    )
    cells_b_reg = seg.extract_cells(
        seg_b_reg, pos_b_reg, reg.warped.astype(np.uint8), MarkerChannel.P53, min_area_px=5
    )
    rate_after = matcher.match(cells_a, cells_b_reg, mpp=1.0).match_rate

    # 登録により一致率が明確に改善する（未整列ではほぼ対応せず、整列後は大半が対応）
    assert rate_before <= 0.2
    assert rate_after >= 0.8
    assert rate_after > rate_before


def test_apply_transform_requires_transform() -> None:
    """transform が None なら明確に例外。"""
    reg = Registrar(method="rigid")
    with pytest.raises(ValueError):
        reg.apply_transform(np.zeros((8, 8), np.int32), np.zeros((8, 8), np.uint8), None,
                            label=True)


def test_apply_transform_preserves_label_dtype() -> None:
    """ラベル画像を warp しても整数 dtype と値域が保たれる（新規ラベルを作らない）。"""
    dapi_a, seg_a, _, mk_a = _scene([(40, 40), (100, 100)], shift=(0, 0))
    dapi_b, seg_b, _, mk_b = _scene([(40, 40), (100, 100)], shift=(5, 0))
    reg = Registrar(method="rigid").register(fixed=dapi_a, moving=dapi_b, moving_extra=mk_b)
    warped = Registrar(method="rigid").apply_transform(
        seg_b, dapi_a, reg.transform_obj, label=True
    )
    assert np.issubdtype(warped.dtype, np.integer)
    # warp 後のラベル集合は元のラベル集合の部分集合（線形補間による中間値が出ない）
    assert set(np.unique(warped)).issubset(set(np.unique(seg_b)))
