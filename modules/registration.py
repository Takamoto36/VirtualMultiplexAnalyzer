"""Step5: 非剛体レジストレーションモジュール.

連続切片間の位置合わせを SimpleITK で実装する。位置合わせには Virtual DAPI
または Hematoxylin を用い、DAB（マーカー）画像そのものでは合わせない
（染色対象が異なり、対応点にならないため）。

手順は Rigid → Affine → B-Spline の多段最適化とし、得られた合成変換と
（任意で）変位場を保存できるようにする。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Literal, Optional

import numpy as np

logger = logging.getLogger(__name__)

try:  # pragma: no cover - 環境依存
    import SimpleITK as sitk  # type: ignore

    _HAS_SITK = True
except Exception:  # noqa: BLE001
    sitk = None  # type: ignore
    _HAS_SITK = False

RegMethod = Literal["rigid", "affine", "bspline", "rigid+affine", "rigid+affine+bspline"]


@dataclass(slots=True)
class RegistrationResult:
    """レジストレーション結果.

    Attributes:
        warped: 位置合わせ後の moving 画像（fixed と同サイズ）。
        transform_params: 合成変換のパラメータ（JSON 保存用）。
        metric: 最終的な類似度指標値（小さいほど良い）。
        displacement_field: 変位場 (H, W, 2) or ``None``。
        method: 実行した手法。
    """

    warped: np.ndarray
    transform_params: dict
    metric: float
    displacement_field: Optional[np.ndarray] = None
    method: str = ""
    transform_obj: object = field(default=None, repr=False)


class Registrar:
    """SimpleITK による多段レジストレーションを担うクラス。"""

    def __init__(self, method: RegMethod = "rigid+affine+bspline") -> None:
        if not _HAS_SITK:
            raise RuntimeError(
                "SimpleITK が見つかりません。`pip install SimpleITK` を実行してください。"
            )
        self.method = method

    # ------------------------------------------------------------------
    def __init__(self, method: str = "rigid+affine+bspline", estimate_scale: float = 1.0) -> None:
        """レジストレーションの構成.

        Args:
            method: 変換段の組み合わせ（例 ``"rigid+affine+bspline"``）。
            estimate_scale: 変換推定に使う縮小率（0<scale<=1）。例えば 0.25 なら
                1/4 に縮小した画像で変換を推定し、その変換をフル解像度に適用する。
                b-spline は計算量が画素数にほぼ比例するため、0.25 で約 16 倍高速化
                できる一方、位置合わせ精度の低下はごくわずか（変換は物理座標で
                表現され解像度非依存のため）。
        """
        self.method = method
        self.estimate_scale = float(estimate_scale)

    @staticmethod
    def _downscale(arr: np.ndarray, scale: float) -> np.ndarray:
        """変換推定用に画像を縮小する（scale>=1 ならそのまま）。"""
        if scale >= 0.999:
            return arr
        import cv2

        h, w = arr.shape[:2]
        nh, nw = max(1, int(h * scale)), max(1, int(w * scale))
        interp = cv2.INTER_AREA
        return cv2.resize(arr, (nw, nh), interpolation=interp)

    def register(
        self,
        fixed: np.ndarray,
        moving: np.ndarray,
        moving_extra: Optional[np.ndarray] = None,
        compute_field: bool = True,
    ) -> RegistrationResult:
        """fixed に moving を合わせ込む.

        Args:
            fixed: 基準グレースケール画像（Virtual DAPI 等）。
            moving: 位置合わせ対象グレースケール画像（Virtual DAPI 等）。
            moving_extra: 求めた変換を適用したい別画像（Virtual Marker 等）。
                ``None`` の場合は ``moving`` 自身にのみ適用する。
            compute_field: 変位場を計算するか。
        """
        # --- 変換推定は（必要なら）縮小画像で行い高速化する ---
        # SimpleITK の変換は物理座標系で表現されるため、縮小画像で推定した変換を
        # フル解像度画像へそのまま適用できる。縮小画像には元画像と同じ物理範囲を
        # 表すよう spacing を設定する。
        scale = self.estimate_scale
        f_small = self._downscale(fixed, scale)
        m_small = self._downscale(moving, scale)
        f_est = self._to_sitk(f_small)
        m_est = self._to_sitk(m_small)
        if scale < 0.999:
            # 縮小画像の spacing = 1/scale（元画像 1px 相当の物理長）
            sp = (1.0 / scale, 1.0 / scale)
            f_est.SetSpacing(sp)
            m_est.SetSpacing(sp)

        transform = sitk.Transform(2, sitk.sitkIdentity)
        steps = self.method.split("+")

        if "rigid" in steps:
            transform = self._rigid(f_est, m_est, transform)
        if "affine" in steps:
            transform = self._affine(f_est, m_est, transform)
        if "bspline" in steps:
            transform = self._bspline(f_est, m_est, transform)

        # --- 変換の適用はフル解像度で行う（spacing=1 の元グリッド）---
        f_img = self._to_sitk(fixed)
        target = moving_extra if moving_extra is not None else moving
        warped = self._resample(self._to_sitk(target), f_img, transform)
        warped_arr = sitk.GetArrayFromImage(warped)

        metric = self._final_metric(f_est, m_est, transform)
        field = self._displacement_field(transform, f_img) if compute_field else None

        logger.info(
            "レジストレーション完了 method=%s metric=%.4f estimate_scale=%.2f",
            self.method, metric, scale,
        )
        return RegistrationResult(
            warped=warped_arr.astype(np.float32),
            transform_params=self._transform_to_dict(transform),
            metric=float(metric),
            displacement_field=field,
            method=self.method,
            transform_obj=transform,
        )

    # ------------------------------------------------------------------
    # 各段の最適化
    # ------------------------------------------------------------------
    def _base_method(self) -> "sitk.ImageRegistrationMethod":
        """共通の最適化設定を持つレジストレーション法を生成する。"""
        R = sitk.ImageRegistrationMethod()
        R.SetMetricAsMattesMutualInformation(numberOfHistogramBins=50)
        R.SetMetricSamplingStrategy(R.RANDOM)
        R.SetMetricSamplingPercentage(0.2, seed=42)
        R.SetInterpolator(sitk.sitkLinear)
        R.SetOptimizerAsGradientDescent(
            learningRate=1.0, numberOfIterations=200,
            convergenceMinimumValue=1e-6, convergenceWindowSize=10,
        )
        R.SetOptimizerScalesFromPhysicalShift()
        R.SetShrinkFactorsPerLevel([4, 2, 1])
        R.SetSmoothingSigmasPerLevel([2, 1, 0])
        R.SmoothingSigmasAreSpecifiedInPhysicalUnitsOn()
        return R

    def _rigid(self, fixed, moving, init) -> "sitk.Transform":
        """剛体（回転＋並進）位置合わせ。"""
        initial = sitk.CenteredTransformInitializer(
            fixed, moving, sitk.Euler2DTransform(),
            sitk.CenteredTransformInitializerFilter.GEOMETRY,
        )
        R = self._base_method()
        R.SetInitialTransform(initial, inPlace=False)
        out = R.Execute(fixed, moving)
        return sitk.CompositeTransform([init, out]) if not init.IsLinear() else out

    def _affine(self, fixed, moving, init) -> "sitk.Transform":
        """アフィン位置合わせ（初期変換 init を前段に合成）。"""
        moving_pre = self._resample(moving, fixed, init)
        R = self._base_method()
        R.SetInitialTransform(sitk.AffineTransform(2), inPlace=False)
        out = R.Execute(fixed, moving_pre)
        return sitk.CompositeTransform([init, out])

    def _bspline(self, fixed, moving, init) -> "sitk.Transform":
        """B-Spline による非剛体位置合わせ。"""
        moving_pre = self._resample(moving, fixed, init)
        mesh = [8, 8]
        bspline = sitk.BSplineTransformInitializer(fixed, mesh)
        R = self._base_method()
        R.SetInitialTransformAsBSpline(bspline, inPlace=True, scaleFactors=[1, 2, 4])
        R.SetOptimizerAsLBFGS2(numberOfIterations=100)
        out = R.Execute(fixed, moving_pre)
        return sitk.CompositeTransform([init, out])

    # ------------------------------------------------------------------
    # ユーティリティ
    # ------------------------------------------------------------------
    @staticmethod
    def _to_sitk(arr: np.ndarray) -> "sitk.Image":
        """NumPy 配列（グレー/RGB）を float32 の SimpleITK 画像に変換する。"""
        if arr.ndim == 3:
            arr = arr[..., :3].mean(axis=-1)
        return sitk.GetImageFromArray(arr.astype(np.float32))

    @staticmethod
    def _resample(moving, reference, transform) -> "sitk.Image":
        """変換を適用して reference グリッドにリサンプルする。"""
        return sitk.Resample(
            moving, reference, transform, sitk.sitkLinear, 0.0, moving.GetPixelID()
        )

    def apply_transform(
        self,
        image: np.ndarray,
        reference: np.ndarray,
        transform: object,
        label: bool = False,
    ) -> np.ndarray:
        """既に求めた変換を任意画像へ適用し reference グリッドへ warp する.

        レジストレーションで得た ``transform`` を、セグメンテーションラベルや
        陽性マスクなど「moving 側の別画像」に適用して fixed 座標系に載せ替える。
        Cell Matching を正しい共通座標で行うために用いる。

        Args:
            image: warp 対象（(H, W) ラベル/マスク/グレースケール）。
            reference: 出力グリッドを与える fixed 画像（例: 切片A の DAPI）。
            transform: :meth:`register` が返した ``transform_obj``。
            label: ラベル/マスクなら ``True``（最近傍補間で値を保持）。

        Returns:
            fixed グリッドへ warp した配列（入力 dtype を保持）。
        """
        if transform is None:
            raise ValueError("transform が None です。先に register() を実行してください。")
        ref_img = self._to_sitk(reference)
        src = self._to_sitk(image)
        interp = sitk.sitkNearestNeighbor if label else sitk.sitkLinear
        out = sitk.Resample(src, ref_img, transform, interp, 0.0, src.GetPixelID())
        arr = sitk.GetArrayFromImage(out)
        # 入力 dtype（int ラベル / bool マスク / uint8）へ復元
        if np.issubdtype(image.dtype, np.integer):
            return np.rint(arr).astype(image.dtype)
        if image.dtype == bool:
            return arr > 0.5
        return arr.astype(image.dtype)

    def _final_metric(self, fixed, moving, transform) -> float:
        """最終変換における類似度指標（MI の符号反転）を評価する。"""
        try:
            R = sitk.ImageRegistrationMethod()
            R.SetMetricAsMattesMutualInformation(50)
            R.SetInterpolator(sitk.sitkLinear)
            R.SetMetricSamplingStrategy(R.REGULAR)
            R.SetMetricSamplingPercentage(0.3)
            return float(R.MetricEvaluate(fixed, self._resample(moving, fixed, transform)))
        except Exception:  # noqa: BLE001
            # 相互情報量の評価に失敗した場合は、有限値の代替指標（正規化 MSE）を返す。
            try:
                warped = self._resample(moving, fixed, transform)
                a = sitk.GetArrayFromImage(fixed).astype("float64")
                b = sitk.GetArrayFromImage(warped).astype("float64")
                denom = (a.max() - a.min()) or 1.0
                mse = float(np.mean(((a - b) / denom) ** 2))
                return mse
            except Exception:  # noqa: BLE001  # pragma: no cover
                return float("nan")

    @staticmethod
    def _displacement_field(transform, reference) -> "Optional[np.ndarray]":
        """合成変換から変位場 (H, W, 2) を生成する。"""
        try:
            filt = sitk.TransformToDisplacementFieldFilter()
            filt.SetReferenceImage(reference)
            field_img = filt.Execute(transform)
            return sitk.GetArrayFromImage(field_img)
        except Exception:  # noqa: BLE001  # pragma: no cover
            return None

    @staticmethod
    def _transform_to_dict(transform) -> dict:
        """変換を JSON 保存可能な辞書に変換する。"""
        try:
            return {
                "type": transform.GetName(),
                "parameters": list(transform.GetParameters()),
                "fixed_parameters": list(transform.GetFixedParameters()),
            }
        except Exception:  # noqa: BLE001  # pragma: no cover
            return {"type": "composite"}
