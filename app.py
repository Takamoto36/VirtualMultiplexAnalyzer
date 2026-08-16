"""Virtual Multiplex Pathology Analyzer — アプリケーションエントリポイント.

連続切片 WSI（Ki67 / p53 など）を対象に、ROI 選択 → DeepLIIF 推論 → Virtual IF
生成 → 非剛体レジストレーション → Pseudo Merge → 細胞対応付け → 定量解析 →
CSV/Excel/PDF/PowerPoint 出力までを GUI のみで実行できる、クロスプラット
フォーム（Windows / macOS）対応の病理画像解析ソフトウェア（研究用）。

実行方法::

    python app.py
"""
from __future__ import annotations

import logging
import sys

from config.logging_config import setup_logging
from config.settings import AppSettings


def main() -> int:
    """アプリを起動する。終了コードを返す。"""
    setup_logging(logging.INFO)
    logger = logging.getLogger(__name__)

    # 高 DPI 対応（Qt 読込前に設定）
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    try:  # Qt6 では基本的に有効だが明示しておく
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )
    except Exception:  # noqa: BLE001
        pass

    app = QApplication(sys.argv)
    app.setApplicationName("VirtualMultiplexAnalyzer")
    app.setOrganizationName("Takamoto36")

    settings = AppSettings.load()

    from gui.theme import apply_theme

    apply_theme(app, settings.theme)

    # 遅延 import（GUI 依存を main 実行時に限定）
    from gui.main_window import MainWindow

    window = MainWindow(settings)
    window.show()
    logger.info("アプリ起動")

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
