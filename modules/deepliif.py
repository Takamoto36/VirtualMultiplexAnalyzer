"""Step3: DeepLIIF 推論モジュール.

ROI 画像を入力に、Virtual DAPI・Virtual Marker・Segmentation・Confidence を
得る。実行方法は 3 通りから選べる:

* ``local``: ローカルにインストールされた DeepLIIF（Python API または CLI）
* ``api``  : DeepLIIF の推論エンドポイントへ HTTP POST
* ``mock`` : モデルなしで色分離ベースの近似推論（動作確認・オフライン用）

``mock`` を用意することで、GPU やモデル重みが無い環境でも Step4 以降の
パイプライン（レジストレーション・マージ・マッチング・統計）を通しで検証
できる。実運用では ``local`` / ``api`` を選択する。
"""
from __future__ import annotations

import logging
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np

logger = logging.getLogger(__name__)

RunMode = Literal["local", "api", "mock"]


@dataclass(slots=True)
class DeepLIIFResult:
    """DeepLIIF 推論結果.

    Attributes:
        dapi: Virtual DAPI（核染色相当）グレースケール (H, W) uint8。
        marker: Virtual Marker（DAB 相当）グレースケール (H, W) uint8。
        seg: セグメンテーションラベル画像 (H, W) int（0=背景）。
        confidence: 推論の信頼度スコア（0-1）。
        positive_mask: 陽性核マスク (H, W) bool（seg のうち陽性領域）。
    """

    dapi: np.ndarray
    marker: np.ndarray
    seg: np.ndarray
    confidence: float
    positive_mask: np.ndarray
    used_mock: bool = False  # 近似(mock)フォールバックで生成された結果か


class DeepLIIFRunner:
    """DeepLIIF 推論を実行するラッパー。

    Args:
        mode: 実行方法（``local`` / ``api`` / ``mock``）。
        api_url: ``api`` モード時のエンドポイント URL。
        cli_command: ``local`` モードで呼ぶ CLI（既定 ``"deepliif"``）。
    """

    def __init__(
        self,
        mode: RunMode = "mock",
        api_url: str = "",
        cli_command: str = "deepliif",
        model_dir: str = "",
        tile_size: int = 512,
        resolution: str = "40x",
        prob_thresh: int | None = None,
        size_thresh: "int | str | None" = None,
        marker_thresh: "int | str | None" = None,
    ) -> None:
        self.mode: RunMode = mode
        # api_url 未指定なら公式クラウドエンドポイントを既定に用いる。
        self.api_url = api_url or "https://deepliif.org/api/infer"
        self.cli_command = cli_command
        self.model_dir = model_dir
        self.tile_size = tile_size
        self.resolution = resolution
        self.prob_thresh = prob_thresh
        self.size_thresh = size_thresh
        self.marker_thresh = marker_thresh

    def run(self, image: np.ndarray) -> DeepLIIFResult:
        """ROI 画像に対して推論を実行し :class:`DeepLIIFResult` を返す。"""
        if image.ndim != 3 or image.shape[-1] != 3:
            raise ValueError("入力は RGB 画像 (H, W, 3) である必要があります")

        logger.info("DeepLIIF 推論開始 mode=%s shape=%s", self.mode, image.shape)
        if self.mode == "api":
            return self._run_api(image)
        if self.mode == "local":
            return self._run_local(image)
        return self._run_mock(image)

    # ------------------------------------------------------------------
    # local: DeepLIIF CLI 経由
    # ------------------------------------------------------------------
    def _run_local(self, image: np.ndarray) -> DeepLIIFResult:
        """ローカル DeepLIIF CLI を呼び出す。失敗時は mock にフォールバック。"""
        try:
            import imageio.v3 as iio

            with tempfile.TemporaryDirectory() as td:
                tmp = Path(td)
                in_path = tmp / "input.png"
                iio.imwrite(in_path, image)
                # DeepLIIF 公式 CLI:
                #   deepliif test --input-dir <in> --output-dir <out>
                #                 --model-dir <serialized_model> --tile-size <n>
                cmd = [
                    self.cli_command, "test",
                    "--input-dir", str(tmp),
                    "--output-dir", str(tmp),
                    "--tile-size", str(self.tile_size),
                ]
                if self.model_dir:
                    cmd += ["--model-dir", self.model_dir]
                subprocess.run(cmd, check=True, capture_output=True, timeout=1800)
                return self._load_deepliif_outputs(tmp, image)
        except FileNotFoundError:
            logger.error("DeepLIIF CLI が見つかりません。mock にフォールバックします。")
        except subprocess.CalledProcessError as exc:  # pragma: no cover
            logger.error("DeepLIIF 実行エラー: %s", exc.stderr)
        except Exception as exc:  # noqa: BLE001  # pragma: no cover
            logger.error("DeepLIIF ローカル実行に失敗: %s", exc)
        return self._run_mock(image)

    def _load_deepliif_outputs(self, out_dir: Path, image: np.ndarray) -> DeepLIIFResult:
        """DeepLIIF CLI が出力した各画像を読み込んで結果に整形する。"""
        import imageio.v3 as iio

        images: dict[str, np.ndarray] = {}
        for key in ("DAPI", "Hematoxylin", "Lap2", "Marker", "DAB", "Seg"):
            for p in out_dir.glob(f"*{key}*"):
                images[key.lower()] = np.asarray(iio.imread(p))
                break
        result = self._result_from_named_images(images, image, scoring=None)
        if result is None:
            logger.warning("DeepLIIF 出力の一部が見つからず mock で補完します。")
            return self._run_mock(image)
        return result

    @staticmethod
    def _pick(images: dict, candidates: tuple, exclude: tuple = ()) -> "np.ndarray | None":
        """候補名（部分一致・優先順）でモダリティ画像を選ぶ.

        DeepLIIF の出力名はバージョンや経路により ``DAPI`` / ``Hema`` /
        ``Hematoxylin`` / ``Seg`` / ``SegRefined`` / ``SegOverlaid`` などと
        揺れるため、完全一致ではなく優先順の部分一致で拾う。

        Args:
            images: 小文字キーの画像辞書。
            candidates: 優先順の部分文字列タプル。
            exclude: これを含むキーは除外（例: overlaid は可視化用なので避ける）。
        """
        # 1) 完全一致を最優先
        for c in candidates:
            if c in images:
                return images[c]
        # 2) 部分一致（除外条件付き）
        for c in candidates:
            for k, v in images.items():
                if c in k and not any(e in k for e in exclude):
                    return v
        return None

    @staticmethod
    def _stains_from_ihc(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """元 IHC 画像を色分離し (Hematoxylin, DAB) を 0-255 uint8 で返す.

        DeepLIIF クラウド API は既定で Seg 系画像しか返さないため、
        レジストレーション基準（核染色 = Hematoxylin）と
        マーカー強度（DAB）は元画像から復元する。
        これは mock の「核検出」とは別物で、単なる染色分離である点に注意。
        """
        from skimage.color import hdx_from_rgb, separate_stains

        arr = rgb[..., :3].astype(np.float64) / 255.0
        arr = np.clip(arr, 1e-6, 1.0)
        stains = separate_stains(arr, hdx_from_rgb)
        hema, dab = stains[..., 0], stains[..., 1]

        def _norm(x: np.ndarray) -> np.ndarray:
            x = np.clip(x, 0, None)
            rng = np.ptp(x)
            if rng < 1e-9:
                return np.zeros(x.shape, np.uint8)
            return ((x - x.min()) / rng * 255).astype(np.uint8)

        return _norm(hema), _norm(dab)

    def _result_from_named_images(
        self,
        images: dict[str, np.ndarray],
        original: np.ndarray,
        scoring: dict | None = None,
    ) -> "DeepLIIFResult | None":
        """DeepLIIF の各モダリティ画像（local/api 共通）から結果を組み立てる.

        DeepLIIF クラウド API は既定で ``Seg`` / ``SegRefined`` / ``SegOverlaid``
        しか返さない（DAPI・Marker は返らない）。そこで **Seg があれば本物の
        DeepLIIF 推論結果として採用**し、欠けている DAPI/Marker は元 IHC 画像の
        色分離（Hematoxylin / DAB）で補う。こうすることで mock の核検出に
        落ちることなく、DeepLIIF のセグメンテーション品質を活かせる。

        Args:
            images: 小文字キーのモダリティ画像辞書。
            original: 入力 IHC 画像（RGB）。欠損モダリティの補完に使う。
            scoring: API が返すスコアリング（``confidence`` 概算に利用）。

        Returns:
            Seg が得られれば :class:`DeepLIIFResult`、無ければ ``None``。
        """
        # セグメンテーション: refined を最優先、overlaid（可視化用）は避ける
        seg_img = self._pick(
            images, ("segrefined", "seg_refined", "seg"), exclude=("overlaid",)
        )
        if seg_img is None:
            logger.warning(
                "Seg 画像が得られませんでした (受信キー=%s)", sorted(images.keys())
            )
            return None

        # DAPI 相当（核染色）と Marker（DAB）。API が返さない場合は元画像から復元。
        dapi = self._pick(images, ("dapi", "hema", "hematoxylin"))
        marker = self._pick(images, ("marker", "dab", "ki67"))
        if dapi is None or marker is None:
            hema_s, dab_s = self._stains_from_ihc(original)
            if dapi is None:
                dapi = hema_s
                logger.info(
                    "API が DAPI を返さないため、元IHCのヘマトキシリン成分で代替します"
                    "（レジストレーション基準に使用）。"
                )
            if marker is None:
                marker = dab_s
                logger.info("API が Marker を返さないため、元IHCの DAB 成分で代替します。")

        seg = self._labelize(seg_img)
        # DeepLIIF の Seg は色分け（陽性=赤 / 陰性=青）。色があれば色で陽性判定し、
        # グレースケール Seg の場合は Marker 強度から判定する。
        if seg_img.ndim == 3 and seg_img.shape[-1] >= 3:
            positive = self._positive_from_color_seg(seg_img, seg)
        else:
            positive = self._positive_from_marker(self._to_gray(marker), seg)

        confidence = 0.9
        if scoring:
            # スコアリングがあれば陽性率などから概算（無ければ既定値）。
            for k in ("percent_pos", "percent_positive", "prob", "confidence"):
                if isinstance(scoring.get(k), (int, float)):
                    confidence = float(min(max(scoring[k] / 100.0
                                               if scoring[k] > 1 else scoring[k], 0.0), 1.0))
                    break

        return DeepLIIFResult(
            dapi=self._to_gray(dapi), marker=self._to_gray(marker),
            seg=seg, confidence=confidence, positive_mask=positive,
        )

    @staticmethod
    def _positive_from_color_seg(seg_rgb: np.ndarray, seg: np.ndarray) -> np.ndarray:
        """色分け Seg（陽性=赤 / 陰性=青）から核ごとの陽性マスクを作る。"""
        from skimage.measure import regionprops

        rgb = seg_rgb[..., :3].astype(np.float64)
        red = rgb[..., 0]
        blue = rgb[..., 2]
        positive = np.zeros(seg.shape, dtype=bool)
        for prop in regionprops(seg):
            coords = prop.coords
            r_mean = red[coords[:, 0], coords[:, 1]].mean()
            b_mean = blue[coords[:, 0], coords[:, 1]].mean()
            if r_mean >= b_mean:  # 赤優位 → 陽性
                positive[seg == prop.label] = True
        return positive

    # ------------------------------------------------------------------
    # api: HTTP 経由
    # ------------------------------------------------------------------
    def _run_api(self, image: np.ndarray) -> DeepLIIFResult:
        """DeepLIIF クラウド API (POST /api/infer) に画像を送信して結果を取得する.

        公式仕様（deepliif.org）に準拠:
            * files: ``img``（必須）
            * params: ``resolution`` (10x/20x/40x), 任意で ``prob_thresh`` /
              ``size_thresh`` / ``marker_thresh`` / ``pil``
            * 戻り値 JSON: ``data['images']``（各モダリティの base64 PNG:
              Hematoxylin, DAPI, Lap2, Marker, Seg 等）と ``data['scoring']``。
        """
        if not self.api_url:
            logger.error("api_url が未設定のため mock にフォールバックします。")
            return self._run_mock(image)
        try:
            import base64
            import io

            import imageio.v3 as iio
            import requests
            from PIL import Image

            buf = io.BytesIO()
            iio.imwrite(buf, image, extension=".png")
            buf.seek(0)

            params: dict = {"resolution": self.resolution, "pil": True}
            if self.prob_thresh is not None:
                params["prob_thresh"] = self.prob_thresh
            if self.size_thresh is not None:
                params["size_thresh"] = self.size_thresh
            if self.marker_thresh is not None:
                params["marker_thresh"] = self.marker_thresh

            resp = requests.post(
                self.api_url,
                files={"img": ("roi.png", buf, "image/png")},
                params=params,
                timeout=600,
            )
            resp.raise_for_status()
            data = resp.json()

            # サーバがエラーを 200 で返す場合に備える
            if isinstance(data, dict) and data.get("error"):
                logger.error("DeepLIIF API がエラーを返しました: %s", data["error"])
                return self._run_mock(image)

            # base64 → ndarray へデコード（キー名は大文字小文字を無視して照合）
            raw = data.get("images", {}) or {}
            # ★診断のため、実際に返ってきたキー名を必ずログに出す
            logger.info("DeepLIIF API 応答 images キー: %s", sorted(raw.keys()))
            images: dict[str, np.ndarray] = {}
            for name, b64 in raw.items():
                try:
                    pil = Image.open(io.BytesIO(base64.b64decode(b64)))
                    images[name.lower()] = np.asarray(pil)
                except Exception:  # noqa: BLE001
                    continue

            scoring = data.get("scoring")
            result = self._result_from_named_images(images, image, scoring)
            if result is None:
                logger.warning(
                    "API 応答に必要な画像が無く mock で補完します。"
                    "受信キー=%s（dapi/hema系・marker・seg系を探しています）",
                    sorted(images.keys()),
                )
                return self._run_mock(image)
            logger.info("DeepLIIF API 応答 %s scoring=%s", resp.status_code, scoring)
            return result
        except Exception as exc:  # noqa: BLE001  # pragma: no cover
            logger.error("DeepLIIF API 呼び出しに失敗: %s", exc)
            return self._run_mock(image)

    # ------------------------------------------------------------------
    # mock: 色分離ベースの近似推論
    # ------------------------------------------------------------------
    def _run_mock(self, image: np.ndarray) -> DeepLIIFResult:
        """H-DAB 色分離で Virtual DAPI/Marker を近似生成する.

        H&E ではなく IHC（Hematoxylin + DAB）を想定し、Hematoxylin 成分を
        Virtual DAPI、DAB 成分を Virtual Marker とみなす。核セグメンテーション
        は Hematoxylin 上の Otsu + 距離変換 + Watershed で行う。あくまで近似で
        あり、正式な結果は DeepLIIF 本体を用いること。
        """
        from scipy import ndimage as ndi
        from skimage.color import hdx_from_rgb, separate_stains
        from skimage.feature import peak_local_max
        from skimage.filters import threshold_otsu
        from skimage.segmentation import watershed
        from skimage.util import img_as_float

        rgb = img_as_float(image)
        # Hematoxylin(H) / DAB(D) / 残差(X) に分離
        stains = separate_stains(rgb, hdx_from_rgb)
        hema = stains[..., 0]
        dab = stains[..., 1]

        def _norm(x: np.ndarray) -> np.ndarray:
            x = x - x.min()
            m = x.max()
            return (x / m) if m > 0 else x

        hema_n = _norm(hema)
        dab_n = _norm(dab)
        dapi = (hema_n * 255).astype(np.uint8)
        marker = (dab_n * 255).astype(np.uint8)

        # 核セグメンテーション（Hematoxylin ベース）
        try:
            thr = threshold_otsu(hema_n)
        except ValueError:
            thr = 0.5
        nuclei = hema_n > thr
        nuclei = ndi.binary_fill_holes(nuclei)
        distance = ndi.distance_transform_edt(nuclei)
        coords = peak_local_max(distance, min_distance=7, labels=nuclei)
        if len(coords) > 0:
            markers_img = np.zeros(distance.shape, dtype=int)
            for i, (r, c) in enumerate(coords, start=1):
                markers_img[r, c] = i
            seg = watershed(-distance, markers_img, mask=nuclei)
        else:
            # ピークが検出できない（低コントラスト等）場合は連結成分ラベリングで代替。
            from skimage.measure import label as _cc_label

            seg = _cc_label(nuclei)

        positive = self._positive_from_marker(marker, seg)
        confidence = float(np.clip(0.4 + 0.5 * dab_n.mean() * 5, 0.0, 0.85))
        logger.warning(
            "DeepLIIF 近似処理(mock)を使用しました（核数=%d）。"
            "深層学習ではなく色分離ベースの近似であり、定量値は参考値です。",
            int(seg.max()),
        )
        return DeepLIIFResult(
            dapi=dapi, marker=marker, seg=seg,
            confidence=confidence, positive_mask=positive, used_mock=True,
        )

    # ------------------------------------------------------------------
    # 共通ユーティリティ
    # ------------------------------------------------------------------
    @staticmethod
    def _to_gray(arr: np.ndarray) -> np.ndarray:
        """任意入力をグレースケール uint8 に変換する。"""
        if arr.ndim == 3:
            arr = arr[..., :3].mean(axis=-1)
        if arr.dtype != np.uint8:
            a = arr.astype(np.float64)
            a = (a - a.min()) / (np.ptp(a) + 1e-9) * 255
            arr = a.astype(np.uint8)
        return arr

    @staticmethod
    def _labelize(seg_img: np.ndarray) -> np.ndarray:
        """セグメンテーション画像を核ラベル画像に変換する（隣接核を分離）.

        DeepLIIF の SegRefined は密集核が連結して見えるため、単純な連結成分
        ラベリングでは複数核が 1 個に融合してしまう（DeepLIIF 自身の核数と
        大きく食い違う原因）。そこで前景マスクに距離変換 + watershed を適用し、
        接触した核を個別に分離する。
        """
        import numpy as np
        from scipy import ndimage as ndi
        from skimage.feature import peak_local_max
        from skimage.measure import label
        from skimage.segmentation import watershed

        if seg_img.ndim == 3:
            rgb = seg_img[..., :3].astype(np.float64)
            # SegRefined は 陽性=赤 / 陰性=青 / 背景=黒。前景 = 赤か青が立つ画素。
            fg = (rgb[..., 0] > 60) | (rgb[..., 2] > 60)
        else:
            fg = seg_img > (float(seg_img.max()) * 0.5)

        if not fg.any():
            return np.zeros(fg.shape, dtype=np.int32)

        # 距離変換のピークを核中心のシードにして watershed で分離
        distance = ndi.distance_transform_edt(fg)
        # min_distance は核半径の目安（20x, 0.452µm/px で核径~7µm ≒ 15px → 半径~4px）
        coords = peak_local_max(
            distance, min_distance=4, labels=fg, exclude_border=False
        )
        if len(coords) == 0:
            return label(fg).astype(np.int32)
        markers = np.zeros(distance.shape, dtype=np.int32)
        for i, (r, c) in enumerate(coords, start=1):
            markers[r, c] = i
        seg = watershed(-distance, markers, mask=fg)
        return seg.astype(np.int32)

    @staticmethod
    def _positive_from_marker(
        marker: np.ndarray, seg: np.ndarray, threshold: float = 0.35
    ) -> np.ndarray:
        """各核のマーカー平均強度から陽性核マスクを作成する。"""
        from skimage.measure import regionprops

        marker_f = marker.astype(np.float64) / 255.0
        positive = np.zeros(seg.shape, dtype=bool)
        for prop in regionprops(seg, intensity_image=marker_f):
            _mi = getattr(prop, "intensity_mean", None)
            if _mi is None:
                _mi = prop.mean_intensity
            if float(_mi) >= threshold:
                positive[seg == prop.label] = True
        return positive
