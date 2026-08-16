"""解析ロジックのパッケージ.

GUI から独立して単体テスト・スクリプト利用できるよう、各ステップを
モジュール化している。主要クラス/関数をここで再エクスポートする。
"""
from __future__ import annotations

from .datatypes import Cell, MarkerChannel, MatchPair, ROI, WSIMetadata
from .deepliif import DeepLIIFResult, DeepLIIFRunner
from .export import Exporter
from .matching import CellMatcher, MatchingResult
from .merge import COLOR_PRESETS, Channel, merge_channels, pseudo_color
from .pipeline import AnalysisPipeline, PipelineConfig, PipelineResult
from .registration import Registrar, RegistrationResult
from .roi import ROIManager
from .segmentation import CellSegmenter
from .statistics import CrossTab, StatisticsCalculator
from .wsi_loader import WSILoader, WSILoadError

__all__ = [
    "Cell", "MarkerChannel", "MatchPair", "ROI", "WSIMetadata",
    "DeepLIIFResult", "DeepLIIFRunner",
    "Exporter",
    "CellMatcher", "MatchingResult",
    "COLOR_PRESETS", "Channel", "merge_channels", "pseudo_color",
    "AnalysisPipeline", "PipelineConfig", "PipelineResult",
    "Registrar", "RegistrationResult",
    "ROIManager",
    "CellSegmenter",
    "CrossTab", "StatisticsCalculator",
    "WSILoader", "WSILoadError",
]
