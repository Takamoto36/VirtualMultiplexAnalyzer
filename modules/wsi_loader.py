"""Step1: WSI 読込モジュール.

Hamamatsu NanoZoomer の ``.ndpi`` を主対象に、OpenSlide 経由で WSI を開き
メタデータ（倍率・Pixel Size・幅・高さ）とサムネイルを取得する。将来的な
``.svs`` / ``.tif`` / ``.vsi`` 対応を見据え、読込処理は :class:`WSILoader`
の背後に隠蔽する。OpenSlide が未インストールの環境でも import 自体は成功
するよう遅延インポートとし、通常画像は tifffile / Pillow でフォールバック
読込する。
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import numpy as np

from .datatypes import WSIMetadata

logger = logging.getLogger(__name__)

# OpenSlide は C ライブラリ（libopenslide）に依存するため、存在チェックを
# 遅延させる。import 失敗はアプリ起動を止めず、実読込時に案内する。
try:  # pragma: no cover - 環境依存
    import openslide  # type: ignore

    _HAS_OPENSLIDE = True
except Exception:  # noqa: BLE001
    openslide = None  # type: ignore
    _HAS_OPENSLIDE = False


#: OpenSlide がネイティブ対応する拡張子。
OPENSLIDE_SUFFIXES = {".ndpi", ".svs", ".vsi", ".mrxs", ".scn", ".tiff", ".tif", ".svslide"}


class WSILoadError(RuntimeError):
    """WSI 読込に失敗した際に送出される例外。"""


class WSILoader:
    """1 枚の WSI を保持し、領域読込・サムネイル生成を担うクラス.

    OpenSlide が利用可能な場合はそちらを、そうでなければ Pillow/tifffile を
    用いる。いずれの経路でも公開 API（:meth:`metadata`・:meth:`read_region`・
    :meth:`get_thumbnail`）は同一挙動になるよう実装している。
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        if not self.path.exists():
            raise WSILoadError(f"ファイルが存在しません: {self.path}")
        self._slide = None  # type: ignore[assignment]
        self._fallback_array: Optional[np.ndarray] = None
        self._metadata: Optional[WSIMetadata] = None
        self._open()

    # ------------------------------------------------------------------
    # 内部: オープン処理
    # ------------------------------------------------------------------
    def _open(self) -> None:
        """バックエンドを選択して画像を開く。"""
        suffix = self.path.suffix.lower()
        if _HAS_OPENSLIDE and suffix in OPENSLIDE_SUFFIXES:
            try:
                self._slide = openslide.OpenSlide(str(self.path))  # type: ignore[union-attr]
                self._metadata = self._read_openslide_metadata()
                logger.info("OpenSlide で読込: %s", self.path.name)
                return
            except Exception as exc:  # noqa: BLE001
                logger.warning("OpenSlide 読込に失敗、フォールバックへ: %s", exc)

        # フォールバック: 通常画像として読込（研究時の動作確認・小画像用）
        self._open_fallback()

    def _open_fallback(self) -> None:
        """OpenSlide を使わずに読み込む（通常画像・環境未整備時）。"""
        arr: Optional[np.ndarray] = None
        try:
            import tifffile  # type: ignore

            if self.path.suffix.lower() in {".tif", ".tiff"}:
                arr = tifffile.imread(str(self.path))
        except Exception:  # noqa: BLE001
            arr = None

        if arr is None:
            try:
                from PIL import Image

                Image.MAX_IMAGE_PIXELS = None  # 大きな画像も許可
                with Image.open(self.path) as im:
                    arr = np.asarray(im.convert("RGB"))
            except Exception as exc:  # noqa: BLE001
                raise WSILoadError(
                    "この画像を読み込めませんでした。OpenSlide の導入が必要な"
                    f"形式の可能性があります: {self.path.name} ({exc})"
                ) from exc

        if arr.ndim == 2:  # グレースケール -> RGB
            arr = np.stack([arr] * 3, axis=-1)
        if arr.shape[-1] == 4:  # RGBA -> RGB
            arr = arr[..., :3]
        self._fallback_array = arr.astype(np.uint8, copy=False)
        h, w = arr.shape[:2]
        self._metadata = WSIMetadata(
            path=str(self.path), width=int(w), height=int(h),
            level_count=1, vendor="fallback",
        )
        logger.info("フォールバック読込: %s (%dx%d)", self.path.name, w, h)

    def _read_openslide_metadata(self) -> WSIMetadata:
        """OpenSlide プロパティからメタデータを抽出する。"""
        props = self._slide.properties  # type: ignore[union-attr]

        def _f(key: str) -> Optional[float]:
            try:
                return float(props.get(key)) if props.get(key) else None
            except (TypeError, ValueError):
                return None

        mpp_x = _f(openslide.PROPERTY_NAME_MPP_X)  # type: ignore[union-attr]
        mpp_y = _f(openslide.PROPERTY_NAME_MPP_Y)  # type: ignore[union-attr]
        mag = _f(openslide.PROPERTY_NAME_OBJECTIVE_POWER)  # type: ignore[union-attr]
        w, h = self._slide.dimensions  # type: ignore[union-attr]
        return WSIMetadata(
            path=str(self.path),
            width=int(w),
            height=int(h),
            level_count=int(self._slide.level_count),  # type: ignore[union-attr]
            magnification=mag,
            mpp_x=mpp_x,
            mpp_y=mpp_y,
            vendor=props.get(openslide.PROPERTY_NAME_VENDOR),  # type: ignore[union-attr]
        )

    # ------------------------------------------------------------------
    # 公開 API
    # ------------------------------------------------------------------
    @property
    def metadata(self) -> WSIMetadata:
        """読込済み WSI のメタデータを返す。"""
        assert self._metadata is not None
        return self._metadata

    def read_region(
        self, location: tuple[int, int], level: int, size: tuple[int, int]
    ) -> np.ndarray:
        """指定領域を RGB 配列 (H, W, 3) uint8 で取得する.

        Args:
            location: レベル0基準の左上座標 (x, y)。
            level: 読み出すピラミッドレベル。
            size: 取得サイズ (width, height)（level のスケールでの画素数）。
        """
        if self._slide is not None:
            region = self._slide.read_region(location, level, size)  # type: ignore[union-attr]
            return np.asarray(region.convert("RGB"))

        # フォールバック: 単一レベルのため location/size をそのまま切り出す
        assert self._fallback_array is not None
        x, y = location
        w, h = size
        return self._fallback_array[y : y + h, x : x + w].copy()

    def get_thumbnail(self, max_size: int = 1024) -> np.ndarray:
        """長辺 ``max_size`` 以下のサムネイルを RGB 配列で返す。"""
        if self._slide is not None:
            thumb = self._slide.get_thumbnail((max_size, max_size))  # type: ignore[union-attr]
            return np.asarray(thumb.convert("RGB"))

        assert self._fallback_array is not None
        from skimage.transform import resize

        h, w = self._fallback_array.shape[:2]
        scale = min(1.0, max_size / max(h, w))
        if scale >= 1.0:
            return self._fallback_array.copy()
        new_h, new_w = int(h * scale), int(w * scale)
        out = resize(self._fallback_array, (new_h, new_w), preserve_range=True, anti_aliasing=True)
        return out.astype(np.uint8)

    def close(self) -> None:
        """リソースを解放する。"""
        if self._slide is not None:
            self._slide.close()  # type: ignore[union-attr]
            self._slide = None
        self._fallback_array = None

    def __enter__(self) -> "WSILoader":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
