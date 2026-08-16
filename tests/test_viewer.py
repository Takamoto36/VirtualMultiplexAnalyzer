"""``gui.viewer.WSIViewer`` の回帰テスト.

WSI 切替（``set_image``）で内部シーンが ``clear()`` されたあと、
プリセット ROI モードで ``mouseMoveEvent`` が来ても
「C++ オブジェクト削除済み」の RuntimeError で落ちないことを検証する。
本テストは、実際にユーザ環境で起きた以下のクラッシュに対する回帰テスト::

    RuntimeError: libshiboken: Internal C++ object
      (PySide6.QtWidgets.QGraphicsRectItem) already deleted.
"""
from __future__ import annotations

import os

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QPoint, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from gui.viewer import WSIViewer  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _move_event(view: WSIViewer, x: int, y: int) -> QMouseEvent:
    pos = view.viewport().rect().center() if (x, y) == (0, 0) else QPoint(x, y)
    return QMouseEvent(
        QEvent.MouseMove, pos, Qt.NoButton, Qt.NoButton, Qt.NoModifier
    )


def test_preview_rect_survives_scene_clear(qapp) -> None:
    """set_image() 後の mouseMoveEvent でクラッシュしないこと。"""
    view = WSIViewer()
    view.resize(200, 200)
    img = (np.random.rand(120, 120, 3) * 255).astype("uint8")
    view.set_image(img)
    view.set_roi_mode(True)
    view.set_fixed_roi_size(20.0)

    # 1 回動かしてプレビュー矩形を作らせる
    view.mouseMoveEvent(_move_event(view, 50, 50))
    assert view._preview_item is not None

    # ここで別 WSI に切替（scene.clear() 相当）→ 内部の C++ item は破棄される
    view.set_image((np.random.rand(120, 120, 3) * 255).astype("uint8"))
    assert view._preview_item is None  # 参照も無効化されていること

    # 直後に mouseMoveEvent が来てもクラッシュせず、プレビューを作り直せる
    view.mouseMoveEvent(_move_event(view, 60, 60))
    assert view._preview_item is not None


def test_leave_after_clear_does_not_crash(qapp) -> None:
    """set_image 後の leaveEvent もクラッシュしない。"""
    view = WSIViewer()
    view.resize(200, 200)
    view.set_image((np.random.rand(80, 80, 3) * 255).astype("uint8"))
    view.set_roi_mode(True)
    view.set_fixed_roi_size(15.0)
    view.mouseMoveEvent(_move_event(view, 40, 40))
    view.set_image((np.random.rand(80, 80, 3) * 255).astype("uint8"))
    # 例外を出さずに通ることのみを確認
    view.leaveEvent(QEvent(QEvent.Leave))
