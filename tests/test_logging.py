"""``config.logging_config.build_qt_log_handler`` のスレッド安全性テスト.

バックグラウンドスレッドから logger.info(...) が呼ばれても、GUI 側の
コールバックがハング／クラッシュせずメインスレッドで受け取れることを検証する。
本テストは、実際にユーザ環境で「ワーカーが 0% で止まる」現象の根本原因である
「バックグラウンドスレッドから直接 GUI ウィジェットを触ってハング」を回帰させないため。
"""
from __future__ import annotations

import logging
import os
import threading

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from config.logging_config import build_qt_log_handler  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_background_thread_log_does_not_hang(qapp) -> None:
    """バックグラウンドスレッドから logger を叩いても、
    コールバックはメインスレッド上でキュー実行される。"""
    received: list[str] = []
    caller_thread_ids: list[int] = []

    def _cb(msg: str) -> None:
        received.append(msg)
        caller_thread_ids.append(threading.get_ident())

    handler = build_qt_log_handler(_cb)
    logger = logging.getLogger("test_bg_log")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

    def _bg() -> None:
        # ワーカースレッドから複数回ログを出す（本番の worker.run と同じ状況）
        for i in range(5):
            logger.info("bg-log-%d", i)

    main_tid = threading.get_ident()
    t = threading.Thread(target=_bg, daemon=True)
    t.start()
    t.join(timeout=3.0)  # 3 秒でハングを検知
    assert not t.is_alive(), "worker thread hung while emitting logs"

    # Qt イベントループを回してキュー接続のコールバックを消化
    QTimer.singleShot(50, qapp.quit)
    qapp.exec()

    assert len(received) == 5, f"想定5件だが受信は {received}"
    # 全てメインスレッドで受信されていること（GUI 安全）
    for tid in caller_thread_ids:
        assert tid == main_tid, "callback was invoked from wrong thread"

    logger.removeHandler(handler)


def test_qt_handler_does_not_crash_on_callback_exception(qapp) -> None:
    """コールバックが例外を投げてもロガーが落ちない。"""
    def _bad_cb(msg: str) -> None:
        raise RuntimeError("boom")

    handler = build_qt_log_handler(_bad_cb)
    logger = logging.getLogger("test_bad_cb")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

    # ここで落ちないこと
    logger.info("hello")
    QTimer.singleShot(30, qapp.quit)
    qapp.exec()

    logger.removeHandler(handler)
