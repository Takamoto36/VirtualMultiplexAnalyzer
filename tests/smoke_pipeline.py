"""エンドツーエンドのスモークテスト（手動実行用）.

外部 WSI や DeepLIIF/OpenSlide 無しで、mock DeepLIIF → レジストレーション →
セグメンテーション → マッチング → 統計 → エクスポートまでの一連が例外なく
通ることを合成画像で確認する。CI 相当の簡易検証。
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np

from modules.deepliif import DeepLIIFRunner
from modules.export import Exporter
from modules.matching import CellMatcher
from modules.merge import Channel, merge_channels
from modules.registration import Registrar
from modules.segmentation import CellSegmenter
from modules.statistics import StatisticsCalculator
from modules.datatypes import MarkerChannel


def _synthetic_hdab(seed: int, shift: int = 0) -> np.ndarray:
    """合成 H-DAB(IHC) 風 RGB ROI 画像を作る.

    染色濃度空間（Hematoxylin=核, DAB=陽性）でガウス核を描画し、
    ``combine_stains`` で RGB へ戻すことで、mock の ``separate_stains`` に
    正しく分離される現実的な IHC 画像を生成する。
    """
    from skimage.color import combine_stains, rgb_from_hdx

    rng = np.random.default_rng(seed)
    h = w = 256
    hema = np.zeros((h, w), dtype=np.float64)  # 核（全細胞）
    dab = np.zeros((h, w), dtype=np.float64)   # 陽性シグナル
    yy, xx = np.mgrid[0:h, 0:w]
    for i in range(45):
        cy = int(rng.integers(15, h - 15)) + shift
        cx = int(rng.integers(15, w - 15)) + shift
        cy = min(max(cy, 0), h - 1)
        cx = min(max(cx, 0), w - 1)
        sigma = float(rng.uniform(3.0, 5.0))
        blob = np.exp(-(((yy - cy) ** 2 + (xx - cx) ** 2) / (2 * sigma**2)))
        hema += blob * 0.9
        if i % 3 == 0:  # 1/3 を陽性核とする
            dab += blob * 0.8
    hdx = np.stack([hema, dab, np.zeros_like(hema)], axis=-1)
    rgb = combine_stains(hdx, rgb_from_hdx)
    rgb = np.clip(rgb, 0.0, 1.0)
    return (rgb * 255).astype(np.uint8)


def main() -> None:
    print("[1] mock DeepLIIF 推論 ...")
    runner = DeepLIIFRunner(mode="mock")
    img_a = _synthetic_hdab(seed=1, shift=0)
    img_b = _synthetic_hdab(seed=1, shift=4)  # わずかに位置ずれ
    res_a = runner.run(img_a)
    res_b = runner.run(img_b)
    print("    DAPI/marker/seg shapes:",
          res_a.dapi.shape, res_a.marker.shape, res_a.seg.shape)

    print("[2] レジストレーション（DAPI 基準）...")
    reg = Registrar(method="rigid+affine")
    reg_out = reg.register(
        fixed=res_a.dapi, moving=res_b.dapi,
        moving_extra=res_b.marker, compute_field=False,
    )
    print("    metric=%.4f  method=%s" % (reg_out.metric, reg_out.method))
    warped_marker_b = reg_out.warped  # moving_extra=marker を渡したので warped が変換後marker

    print("[3] セグメンテーション（B は整列後の画像から抽出）...")
    seg = CellSegmenter(mpp=0.25)
    seg_b_reg = reg.apply_transform(res_b.seg, res_a.dapi, reg_out.transform_obj, label=True)
    pos_b_reg = reg.apply_transform(
        res_b.positive_mask, res_a.dapi, reg_out.transform_obj, label=True
    )
    cells_a = seg.extract_cells(res_a.seg, res_a.positive_mask, res_a.marker,
                                MarkerChannel.KI67)
    cells_b = seg.extract_cells(seg_b_reg, pos_b_reg, warped_marker_b,
                                MarkerChannel.P53)
    print("    cells A=%d  B=%d" % (len(cells_a), len(cells_b)))

    print("[4] マッチング ...")
    matcher = CellMatcher(max_distance_um=15.0)
    match = matcher.match(cells_a, cells_b, mpp=0.25)
    print("    matched=%d  rate=%.2f" % (len(match.pairs), match.match_rate))

    print("[5] 統計 ...")
    tab = StatisticsCalculator().compute(match, "Ki67", "p53")
    print("    both+=%d  Ki67 index=%.3f  overlap=%.3f"
          % (tab.both_positive, tab.a_index, tab.overlap_rate))

    print("[6] Merge 合成 ...")
    merged = merge_channels([
        Channel("Ki67", res_a.marker, (0, 255, 0)),
        Channel("p53", warped_marker_b, (255, 0, 0)),
    ], mode="merge")
    print("    merged shape:", merged.shape)

    print("[7] エクスポート ...")
    with tempfile.TemporaryDirectory() as d:
        exp = Exporter(Path(d))
        exp.export_csv(cells_a + cells_b, "cells.csv")
        exp.export_excel({"Ki67": cells_a, "p53": cells_b}, [tab], "report.xlsx")
        exp.export_image(merged, "merged.png")
        exp.export_json({"metric": reg_out.metric, "crosstab": tab.as_dict()},
                        "meta.json")
        produced = sorted(p.name for p in Path(d).iterdir())
        print("    出力:", produced)

    print("\nSMOKE TEST OK")


if __name__ == "__main__":
    main()
