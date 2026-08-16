"""解析パイプライン統括モジュール.

Step3（DeepLIIF）〜Step9（統計）を 1 本のパイプラインとして統括する。GUI の
ワーカースレッドからはこの :class:`AnalysisPipeline` を呼ぶだけで、2 切片の
ROI 画像ペアに対する解析一式を実行できる。各ステップの進捗はコールバックで
通知する。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np

from .datatypes import Cell, MarkerChannel
from .deepliif import DeepLIIFResult, DeepLIIFRunner
from .matching import CellMatcher, MatchingResult
from .merge import Channel, merge_channels
from .registration import Registrar, RegistrationResult
from .segmentation import CellSegmenter
from .statistics import CrossTab, StatisticsCalculator

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[int, str], None]


@dataclass(slots=True)
class PipelineConfig:
    """パイプライン実行パラメータ。"""

    deepliif_mode: str = "mock"
    deepliif_api_url: str = ""
    deepliif_model_dir: str = ""
    deepliif_tile_size: int = 512
    deepliif_resolution: str = "40x"
    registration_method: str = "rigid+affine+bspline"
    registration_scale: float = 0.5  # 変換推定の縮小率（0.5=1/2, 高速化）
    region_tile_um: float = 100.0     # 領域レベル解析のタイル1辺[μm]
    show_dapi_channel: bool = True    # Pseudo DAPI（ヘマトキシリン=全核）を青で重畳
    color_dapi: tuple = (0, 120, 255)
    matching_distance_um: float = 10.0
    mpp: Optional[float] = None
    marker_a: str = "Ki67"
    marker_b: str = "p53"
    color_a: tuple[int, int, int] = (0, 255, 0)
    color_b: tuple[int, int, int] = (255, 0, 0)


@dataclass(slots=True)
class PipelineResult:
    """パイプライン全体の成果物。"""

    deepliif_a: DeepLIIFResult
    deepliif_b: DeepLIIFResult
    registration: RegistrationResult
    cells_a: list[Cell]
    cells_b: list[Cell]
    matching: MatchingResult
    crosstab: CrossTab
    #: Cell Matching の妥当性診断（連続切片では「近い≠同一細胞」を検証する）
    diagnostics: object = None
    #: 領域レベル（タイル単位）の密度相関（連続切片で正当な共局在指標）
    region: object = None
    merged_rgb: np.ndarray = field(repr=False, default=None)  # type: ignore[assignment]


class AnalysisPipeline:
    """2 切片 ROI ペアに対する解析パイプライン。"""

    def __init__(self, config: PipelineConfig) -> None:
        self.config = config

    def run(
        self,
        roi_a: np.ndarray,
        roi_b: np.ndarray,
        progress: Optional[ProgressCallback] = None,
    ) -> PipelineResult:
        """ROI 画像ペアを解析し :class:`PipelineResult` を返す.

        Args:
            roi_a: 基準切片 ROI（例: Ki67）RGB 画像。
            roi_b: 対応先切片 ROI（例: p53）RGB 画像。
            progress: (percent, message) を受け取る進捗コールバック。
        """
        cfg = self.config

        def _p(pct: int, msg: str) -> None:
            logger.info("[pipeline %d%%] %s", pct, msg)
            if progress:
                progress(pct, msg)

        # Step3: DeepLIIF 推論
        _p(5, "DeepLIIF 推論 (切片A)")
        runner = DeepLIIFRunner(
            mode=cfg.deepliif_mode,
            api_url=cfg.deepliif_api_url,
            model_dir=cfg.deepliif_model_dir,
            tile_size=cfg.deepliif_tile_size,
            resolution=cfg.deepliif_resolution,
        )
        res_a = runner.run(roi_a)
        _p(20, "DeepLIIF 推論 (切片B)")
        res_b = runner.run(roi_b)
        if res_a.used_mock or res_b.used_mock:
            logger.warning(
                "⚠ DeepLIIF APIを使用できず近似処理(mock)で継続しました。"
                "結果は参考値です（API URL・ネットワーク・画像サイズをご確認ください）。"
            )
            _p(22, "⚠ 近似処理(mock)を使用（参考値）")

        # Step5: レジストレーション（Virtual DAPI 基準）
        _p(40, "非剛体レジストレーション")
        registrar = Registrar(
            method=cfg.registration_method,
            estimate_scale=getattr(cfg, "registration_scale", 1.0),
        )
        reg = registrar.register(
            fixed=res_a.dapi, moving=res_b.dapi,
            moving_extra=res_b.marker, compute_field=True,
        )
        # 求めた変換を B 側のセグメンテーション・陽性マスク・マーカーにも適用し、
        # 切片A の座標系へ載せ替える（＝Cell Matching を共通座標で行うため）。
        seg_b_reg = registrar.apply_transform(
            res_b.seg, res_a.dapi, reg.transform_obj, label=True
        )
        posmask_b_reg = registrar.apply_transform(
            res_b.positive_mask, res_a.dapi, reg.transform_obj, label=True
        )
        marker_b_reg = reg.warped.astype(np.uint8)  # マーカーは既に warp 済み

        # Step7: セグメンテーション & 細胞抽出（B は整列後の画像から抽出）
        _p(60, "細胞セグメンテーション")
        segmenter = CellSegmenter(mpp=cfg.mpp)
        cells_a = segmenter.extract_cells(
            res_a.seg, res_a.positive_mask, res_a.marker,
            marker=self._marker(cfg.marker_a),
        )
        cells_b = segmenter.extract_cells(
            seg_b_reg, posmask_b_reg, marker_b_reg,
            marker=self._marker(cfg.marker_b),
        )

        # Step8: Cell Matching
        _p(75, "細胞対応付け (Cell Matching)")
        matcher = CellMatcher(max_distance_um=cfg.matching_distance_um)
        matching = matcher.match(cells_a, cells_b, mpp=cfg.mpp)

        # Step9: 統計
        _p(88, "定量統計解析")
        stats = StatisticsCalculator()
        crosstab = stats.compute(matching, marker_a=cfg.marker_a, marker_b=cfg.marker_b)

        # Step8b: Matching 妥当性診断（連続切片では必須の検証）
        _p(92, "Cell Matching 妥当性診断")
        from .match_diagnostics import diagnose

        diagnostics = diagnose(
            cells_a, cells_b, mpp=cfg.mpp or 1.0,
            marker_a=cfg.marker_a, marker_b=cfg.marker_b,
        )
        if not diagnostics.is_distinguishable:
            logger.warning(
                "⚠ Cell Matching が偶然と区別できません。"
                "共陽性率などの細胞レベル指標は解釈に注意してください。"
            )

        # Step8c: 領域レベル（タイル単位）の密度相関
        # 連続切片で正当に評価できる共局在指標。細胞レベルが偶然と区別できなくても
        # 「同じ組織領域で両マーカーがともに高いか」は答えられる。
        _p(93, "領域レベル密度相関解析")
        from .region_analysis import analyze_regions

        region = analyze_regions(
            cells_a, cells_b, shape=res_a.seg.shape, mpp=cfg.mpp or 1.0,
            tile_um=getattr(cfg, "region_tile_um", 100.0),
            marker_a=cfg.marker_a, marker_b=cfg.marker_b,
        )

        # Step6: Pseudo Fluorescence 合成（可視化用・色分離ベース）
        _p(95, "Pseudo Fluorescence 合成（色分離ベース／DeepLIIF の mpIF ではない）")
        channels = [
            Channel(cfg.marker_a, res_a.marker, cfg.color_a),
            Channel(cfg.marker_b, reg.warped.astype(np.uint8), cfg.color_b),
        ]
        # 3 色目: Pseudo DAPI（= 元IHCのヘマトキシリン成分＝全核）。
        # DeepLIIF が生成する Virtual DAPI ではなく、色分離由来の全核染色相当。
        if getattr(cfg, "show_dapi_channel", True) and res_a.dapi is not None:
            channels.append(
                Channel("Pseudo DAPI (Hematoxylin)", res_a.dapi,
                        tuple(getattr(cfg, "color_dapi", (0, 120, 255))))
            )
        merged = merge_channels(channels, mode="merge")

        _p(100, "完了")
        return PipelineResult(
            deepliif_a=res_a, deepliif_b=res_b, registration=reg,
            cells_a=cells_a, cells_b=cells_b, matching=matching,
            crosstab=crosstab, diagnostics=diagnostics, region=region, merged_rgb=merged,
        )

    @staticmethod
    def _marker(name: str) -> MarkerChannel:
        """マーカー名文字列を :class:`MarkerChannel` に変換する。"""
        try:
            return MarkerChannel(name)
        except ValueError:
            return MarkerChannel.OTHER
