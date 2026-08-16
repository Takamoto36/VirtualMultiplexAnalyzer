"""バックグラウンドワーカー.

重い処理（WSI 読込・解析パイプライン）を GUI スレッドから切り離して実行し、
進捗・完了・エラーをシグナルで通知する。これにより ProgressBar 更新と UI の
応答性を確保する。

**実装方針**: ``QObject.moveToThread`` 方式ではなく ``QThread`` 継承方式を採用する。
Python 3.14 + PySide6 + macOS の組み合わせで前者では ``run()`` が呼ばれない
事象があったため、より確実に動作する後者に統一している。
"""
from __future__ import annotations

import logging
import sys
import traceback

from PySide6.QtCore import QThread, Signal

from modules.pipeline import AnalysisPipeline, PipelineConfig, PipelineResult
from modules.roi import ROIManager

logger = logging.getLogger(__name__)


def _debug(msg: str) -> None:
    """ロガーとは独立して stderr へ直接書き出すデバッグ出力.

    ロガー経由だと Qt シグナル配線経由になるため、スレッドが動作しているか
    確認する最終手段として使用する。
    """
    print(f"[worker-debug] {msg}", file=sys.stderr, flush=True)


class PipelineWorker(QThread):
    """解析パイプラインを実行するスレッド（QThread 継承方式）.

    ROI 切り出しもスレッド内で行い、GUI スレッドが凍結しないようにする。
    """

    progress = Signal(int, str)      # (percent, message)
    finished_result = Signal(object)  # PipelineResult（QThread.finished との衝突回避）
    failed = Signal(str)             # エラーメッセージ

    def __init__(
        self,
        config: PipelineConfig,
        loader_a,
        roi_obj_a,
        loader_b,
        roi_obj_b,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._loader_a = loader_a
        self._roi_obj_a = roi_obj_a
        self._loader_b = loader_b
        self._roi_obj_b = roi_obj_b

    def run(self) -> None:  # noqa: D401
        """スレッド本体（別スレッドで自動的に呼ばれる）。"""
        _debug("PipelineWorker.run() 開始")
        try:
            # 1) ROI 切り出し（重い I/O）
            self.progress.emit(1, "ROI 切り出し中 (切片A)")
            logger.info("ROI 切り出し開始 A: %s", self._roi_obj_a.bounds)
            _debug(f"extract_image A start: {self._roi_obj_a.bounds}")
            roi_a = ROIManager.extract_image(self._loader_a, self._roi_obj_a)
            _debug(f"extract_image A done: shape={roi_a.shape}")
            logger.info("ROI 切り出し完了 A: shape=%s", roi_a.shape)

            self.progress.emit(3, "ROI 切り出し中 (切片B)")
            logger.info("ROI 切り出し開始 B: %s", self._roi_obj_b.bounds)
            _debug(f"extract_image B start: {self._roi_obj_b.bounds}")
            roi_b = ROIManager.extract_image(self._loader_b, self._roi_obj_b)
            _debug(f"extract_image B done: shape={roi_b.shape}")
            logger.info("ROI 切り出し完了 B: shape=%s", roi_b.shape)

            # 2) パイプライン本体
            _debug("AnalysisPipeline start")
            pipeline = AnalysisPipeline(self._config)
            result: PipelineResult = pipeline.run(
                roi_a, roi_b,
                progress=lambda p, m: self.progress.emit(p, m),
            )
            _debug("AnalysisPipeline done")
            self.finished_result.emit(result)
        except Exception as exc:  # noqa: BLE001
            _debug(f"EXCEPTION: {exc}")
            logger.exception("パイプライン実行エラー")
            self.failed.emit(f"{exc}\n{traceback.format_exc()}")


def run_in_thread(worker: QThread, parent) -> QThread:  # noqa: ARG001
    """QThread を起動する。互換のため関数として残す.

    QThread 継承方式では ``worker.start()`` を呼ぶだけで ``run()`` が別スレッド
    で自動実行される。``parent`` は現在は使わない（互換のため残置）。
    """
    _debug("run_in_thread: worker.start() 呼び出し")
    worker.start()
    _debug(f"run_in_thread: worker.isRunning()={worker.isRunning()}")
    return worker
