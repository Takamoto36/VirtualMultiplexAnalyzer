#!/usr/bin/env python3
"""生成AI画像から、デモ用の疑似 WSI（ピラミッド TIFF）を作成する。

Virtual Multiplex Pathology Analyzer の README / GitHub 掲載用スクリーンショットを
撮るための入力データを用意するためのユーティリティ。

**入力は生成 AI が作成した合成病理画像であり、患者検体画像ではない。**
本スクリプトは以下を行う:

1. 入力 PNG を指定倍率でアップサンプル（既定 4 倍）
   - 元画像は核の等価直径がおよそ 5 px（≒10x 相当）。4 倍にすることで
     核が 20 px 前後となり、40x 学習の DeepLIIF が想定する見えに近づく。
     DeepLIIF は 10x 入力に対して tile 128 を 512 へ内部拡大するため、
     処理内容は実質同じで、こちらで明示的に行うだけである。
2. 任意でウォーターマーク（SYNTHETIC — NOT PATIENT DATA）を焼き込む
3. mpp（µm/pixel）を TIFF の解像度タグに埋め込む
4. タイル化 + ピラミッド（サブ解像度）付き TIFF として保存し、
   OpenSlide / tifffile のどちらからも WSI として扱えるようにする

使用例::

    python tools/make_demo_wsi.py \
        --ki67 "Ki67免疫染色の扁平上皮組織像.png" \
        --p53  "p53免疫染色の扁平上皮組織像.png" \
        --outdir demo_data --scale 4 --mpp 0.30

    # スクリーンショットに合成画像であることを常に写し込みたい場合
    python tools/make_demo_wsi.py ... --watermark
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path

import cv2
import numpy as np
import tifffile
from PIL import Image, ImageDraw, ImageFont

Image.MAX_IMAGE_PIXELS = None

WATERMARK_TEXT = "SYNTHETIC IMAGE - NOT PATIENT DATA"

# ウォーターマーク描画に使うフォント候補（環境差を吸収する）
_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    """利用可能な太字フォントを読み込む。見つからなければ既定フォント。"""
    for path in _FONT_CANDIDATES:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def upsample(img: np.ndarray, scale: int) -> np.ndarray:
    """Lanczos 補間で拡大する。scale=1 なら何もしない。"""
    if scale == 1:
        return img
    h, w = img.shape[:2]
    return cv2.resize(
        img, (w * scale, h * scale), interpolation=cv2.INTER_LANCZOS4
    )


def add_watermark(img: np.ndarray, tile_px: int = 1600) -> np.ndarray:
    """画像全面に薄いウォーターマークを繰り返し描画する。

    どこを切り出しても文言が写り込むよう、tile_px 間隔で敷き詰める。
    """
    pil = Image.fromarray(img).convert("RGBA")
    overlay = Image.new("RGBA", pil.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    font_size = max(18, tile_px // 26)
    font = _load_font(font_size)

    # 文字列の描画サイズを測る
    bbox = draw.textbbox((0, 0), WATERMARK_TEXT, font=font)
    text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]

    step_x = max(text_w + font_size * 2, tile_px)
    step_y = tile_px

    for y in range(0, pil.height + step_y, step_y):
        # 行ごとに半ステップずらして市松状に配置する
        offset = (y // step_y % 2) * (step_x // 2)
        for x in range(-step_x, pil.width + step_x, step_x):
            draw.text(
                (x + offset, y),
                WATERMARK_TEXT,
                font=font,
                fill=(200, 30, 30, 46),
            )

    # 全体を軽く回転させて、意図せず消しにくくする
    overlay = overlay.rotate(
        -20, resample=Image.BICUBIC, center=(pil.width // 2, pil.height // 2)
    )
    out = Image.alpha_composite(pil, overlay).convert("RGB")
    return np.asarray(out)


def write_pyramid_tiff(
    img: np.ndarray,
    path: Path,
    mpp: float,
    tile: int = 512,
    levels: int = 4,
    compression: str = "deflate",
    quality: int = 92,
) -> None:
    """タイル化ピラミッド TIFF として保存し、mpp を解像度タグに埋め込む。

    互換性のための設計方針:

    - 既定は deflate + predictor。zlib は標準ライブラリなので追加依存が要らず、
      tifffile / OpenSlide / Pillow のいずれからも読める。
      （jpeg 圧縮は tifffile 側の読み込みに ``imagecodecs`` が必要になるため
      既定にしない。）
    - ピラミッドは SubIFD ではなく**連続した通常 IFD** として書く。
      OpenSlide の generic-tiff ドライバはこの形式を想定している。
    - 4 GB 未満なら BigTIFF にしない。古いリーダとの互換性のため。

    Args:
        img: RGB uint8 画像。
        path: 出力先。
        mpp: 1 ピクセルあたりのマイクロメートル。
        tile: タイル一辺のピクセル数。
        levels: 追加で作るサブ解像度の段数（各段 1/2）。
        compression: 'deflate' / 'lzw' / 'jpeg' / 'none'。
        quality: JPEG 品質（compression='jpeg' のときのみ）。
    """
    # TIFF の解像度タグは「単位長あたりのピクセル数」。cm 単位で入れる。
    px_per_cm = 10_000.0 / mpp
    resolution = (px_per_cm, px_per_cm)

    # JPEG-in-TIFF には imagecodecs が要る。無ければ deflate に落とす。
    if compression == "jpeg":
        try:
            import imagecodecs  # noqa: F401
        except ImportError:
            print(
                "  注意: imagecodecs 未導入のため deflate 圧縮に切り替えます。"
                "（`pip install imagecodecs` で jpeg が使えます）"
            )
            compression = "deflate"

    opts: dict = {"tile": (tile, tile), "photometric": "rgb"}
    if compression in (None, "none"):
        opts["compression"] = None
    else:
        opts["compression"] = compression
        if compression == "jpeg":
            opts["compressionargs"] = {"level": quality}
        else:
            # 横方向差分。自然画像でも 4 割ほど小さくなる。
            opts["predictor"] = True

    # BigTIFF は必要なときだけ使う
    use_bigtiff = img.nbytes > 3_500_000_000

    with tifffile.TiffWriter(path, bigtiff=use_bigtiff) as tif:
        tif.write(
            img,
            resolution=resolution,
            resolutionunit="CENTIMETER",
            description=(
                f"Synthetic demo image (AI-generated, not patient data). "
                f"MPP={mpp:.4f} um/px"
            ),
            **opts,
        )
        down = img
        for _ in range(levels):
            h, w = down.shape[:2]
            if min(h, w) // 2 < tile:
                break
            down = cv2.resize(
                down, (max(1, w // 2), max(1, h // 2)),
                interpolation=cv2.INTER_AREA,
            )
            tif.write(down, subfiletype=1, **opts)


def verify(path: Path, expect_mpp: float) -> None:
    """書き出した TIFF が実際に読めるかを確認して結果を表示する。"""
    try:
        with tifffile.TiffFile(path) as tf:
            series = tf.series[0]
            shapes = [lv.shape for lv in series.levels]
            page = tf.pages[0]
            xres = page.tags["XResolution"].value
            mpp = 10_000.0 / (xres[0] / xres[1])
            _ = page.asarray()  # 実際にデコードできるか
        print(
            f"  tifffile : OK  levels={len(shapes)}  "
            f"mpp={mpp:.4f}（期待値 {expect_mpp:.4f}）"
        )
    except Exception as exc:  # noqa: BLE001
        print(f"  tifffile : NG  {type(exc).__name__}: {exc}")

    try:
        import openslide

        with openslide.OpenSlide(str(path)) as sl:
            print(
                f"  OpenSlide: OK  dims={sl.dimensions}  "
                f"levels={sl.level_count}"
            )
    except ImportError:
        print("  OpenSlide: 未導入（スキップ）")
    except Exception as exc:  # noqa: BLE001
        print(f"  OpenSlide: NG  {type(exc).__name__}: {exc}")


def process(
    src: Path,
    dst: Path,
    scale: int,
    mpp: float,
    watermark: bool,
    compression: str,
) -> None:
    """1 枚を読み込み、拡大・ウォーターマーク・保存・検証まで行う。"""
    img = np.asarray(Image.open(src).convert("RGB"))
    print(f"  入力  : {src.name}  {img.shape[1]}x{img.shape[0]}")

    img = upsample(img, scale)
    if watermark:
        img = add_watermark(img)

    write_pyramid_tiff(img, dst, mpp=mpp, compression=compression)
    size_mb = dst.stat().st_size / 1e6
    fov_mm = (img.shape[1] * mpp / 1000.0, img.shape[0] * mpp / 1000.0)
    print(
        f"  出力  : {dst.name}  {img.shape[1]}x{img.shape[0]}  "
        f"{size_mb:.1f} MB  視野 {fov_mm[0]:.2f} x {fov_mm[1]:.2f} mm"
    )
    verify(dst, mpp)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ki67", required=True, type=Path, help="Ki67 合成画像 PNG")
    p.add_argument("--p53", required=True, type=Path, help="p53 合成画像 PNG")
    p.add_argument("--outdir", default=Path("demo_data"), type=Path)
    p.add_argument("--scale", default=4, type=int, help="アップサンプル倍率")
    p.add_argument(
        "--mpp", default=0.30, type=float,
        help="出力画像の µm/pixel（既定 0.30 = 40x 相当）",
    )
    p.add_argument(
        "--watermark", action="store_true",
        help="SYNTHETIC の透かしを焼き込む",
    )
    p.add_argument(
        "--compression", default="deflate",
        choices=["deflate", "lzw", "jpeg", "none"],
        help="TIFF 圧縮方式（既定 deflate。jpeg は imagecodecs が必要）",
    )
    args = p.parse_args()

    args.outdir.mkdir(parents=True, exist_ok=True)
    suffix = "_wm" if args.watermark else ""

    print(
        f"倍率 x{args.scale} / mpp {args.mpp} µm/px / "
        f"圧縮 {args.compression} / 透かし {args.watermark}"
    )
    for src, name in [(args.ki67, "Ki67"), (args.p53, "p53")]:
        dst = args.outdir / f"demo_synthetic_{name}{suffix}.tif"
        process(
            src, dst, args.scale, args.mpp, args.watermark, args.compression
        )

    print(f"\n完了: {args.outdir.resolve()}")
    print(
        "注意: これらは生成 AI による合成画像であり、患者検体画像ではありません。"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
