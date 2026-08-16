"""ログ設定モジュール.

処理時間・エラー・DeepLIIF ログ・Registration ログを、ファイルと GUI 下部の
ログパネル双方へ出力するための設定を提供する。GUI 連携用に Qt シグナルへ
ログを流す :class:`QtLogHandler` も定義する（PySide6 が無い環境では import
されないよう遅延読込）。
"""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .settings import user_config_dir

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def log_file_path() -> Path:
    """ログファイルのパス（設定ディレクトリ配下）。"""
    log_dir = user_config_dir() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / "app.log"


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """ルートロガーをファイル + コンソール出力に設定する。

    Args:
        level: ログレベル。

    Returns:
        設定済みのルートロガー。
    """
    root = logging.getLogger()
    root.setLevel(level)

    # 二重登録を避ける
    if getattr(root, "_vmpa_configured", False):
        return root

    fmt = logging.Formatter(LOG_FORMAT, DATE_FORMAT)

    file_handler = RotatingFileHandler(
        log_file_path(), maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)

    root._vmpa_configured = True  # type: ignore[attr-defined]
    logging.getLogger(__name__).info("ロギング初期化: %s", log_file_path())
    return root


def build_qt_log_handler(emit_callback):
    """GUI ログパネルへ流すためのハンドラを生成する.

    **スレッド安全性**:
        バックグラウンドスレッド（QThread ワーカー等）から GUI ウィジェット
        （QPlainTextEdit 等）を直接触ると PySide6 は暗黙的にハング／クラッシュ
        することがある。これを避けるため、ハンドラは内部で :class:`QObject`
        の Signal を持ち、``emit_callback`` へは Qt の自動接続経由で呼び出す。
        バックグラウンド → メインスレッドへ自動的にキュー接続されるので、
        ワーカースレッドから ``logger.info(...)`` が呼ばれても安全。

    Args:
        emit_callback: ``str`` を受け取り GUI へ追記するコールバック。

    Returns:
        :class:`logging.Handler` インスタンス。
    """
    from PySide6.QtCore import QObject, Qt, Signal

    class _Bridge(QObject):
        # str を運ぶシグナル。connect 時に Qt.AutoConnection でスレッド越えを吸収。
        emitted = Signal(str)

    class _CallbackHandler(logging.Handler):
        def __init__(self) -> None:
            super().__init__()
            self._bridge = _Bridge()
            self._bridge.emitted.connect(emit_callback, Qt.QueuedConnection)

        def emit(self, record: logging.LogRecord) -> None:  # noqa: D401
            try:
                self._bridge.emitted.emit(self.format(record))
            except Exception:  # noqa: BLE001
                pass

    handler = _CallbackHandler()
    handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
    return handler
