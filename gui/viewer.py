"""WSI 表示ビューア.

:class:`WSIViewer` は ``QGraphicsView`` を継承し、ホイールズーム・ドラッグ
パン・ラバーバンドによる ROI 選択を提供する。選択された矩形は表示座標から
画像座標へ変換して :pyattr:`roiSelected` シグナルで通知する。
"""
from __future__ import annotations

import logging

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
)

logger = logging.getLogger(__name__)


def ndarray_to_qpixmap(array: np.ndarray) -> QPixmap:
    """RGB/グレースケール NumPy 配列を ``QPixmap`` に変換する。"""
    arr = np.ascontiguousarray(array)
    if arr.ndim == 2:
        arr = np.stack([arr] * 3, axis=-1)
    if arr.dtype != np.uint8:
        a = arr.astype(np.float64)
        a = (a - a.min()) / (np.ptp(a) + 1e-9) * 255
        arr = a.astype(np.uint8)
    h, w = arr.shape[:2]
    if arr.shape[-1] == 4:
        arr = arr[..., :3]
    image = QImage(arr.data, w, h, 3 * w, QImage.Format_RGB888)
    return QPixmap.fromImage(image.copy())


class WSIViewer(QGraphicsView):
    """ズーム・パン・ROI 選択に対応した画像ビューア。"""

    #: ROI 確定時に (x, y, w, h) を画像座標で通知。
    roiSelected = Signal(int, int, int, int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._pixmap_item: QGraphicsPixmapItem | None = None
        self._rubber_origin: QPointF | None = None
        self._rubber_item: QGraphicsRectItem | None = None
        self._roi_items: list[QGraphicsRectItem] = []
        self._scale_factor = 1.0
        self._roi_mode = False
        # 固定サイズ ROI（プリセット）用。値は「シーン(=サムネイル)座標」でのサイズ。
        # None のとき、従来通りドラッグで自由選択。
        self._fixed_roi_size: float | None = None
        self._preview_item: QGraphicsRectItem | None = None
        self.setMouseTracking(True)

        self.setRenderHint(QPainter.Antialiasing)
        self.setRenderHint(QPainter.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)

    # ------------------------------------------------------------------
    def set_image(self, array: np.ndarray) -> None:
        """表示画像を差し替え、全体が収まるようフィットする。"""
        self._scene.clear()
        self._roi_items.clear()
        # scene.clear() で C++ 側が破棄されるので、参照も明示的に無効化する。
        # （そうしないと次のマウス移動で「削除済みオブジェクト」参照エラーになる）
        self._preview_item = None
        self._rubber_item = None
        self._rubber_origin = None
        pixmap = ndarray_to_qpixmap(array)
        self._pixmap_item = self._scene.addPixmap(pixmap)
        self._scene.setSceneRect(QRectF(pixmap.rect()))
        self.resetTransform()
        self._scale_factor = 1.0
        self.fitInView(self._pixmap_item, Qt.KeepAspectRatio)

    def set_roi_mode(self, enabled: bool) -> None:
        """ROI 選択モード（ラバーバンド）の ON/OFF を切り替える。"""
        self._roi_mode = enabled
        self.setDragMode(
            QGraphicsView.NoDrag if enabled else QGraphicsView.ScrollHandDrag
        )
        self.setCursor(Qt.CrossCursor if enabled else Qt.ArrowCursor)
        # モードOFF時はプレビューを消す
        if not enabled and self._preview_item is not None:
            self._scene.removeItem(self._preview_item)
            self._preview_item = None

    def set_fixed_roi_size(self, size_scene_px: "float | None") -> None:
        """固定サイズ ROI プリセットを設定する.

        Args:
            size_scene_px: シーン（サムネイル）座標系での 1 辺サイズ [px]。
                ``None`` を渡すと自由選択（ドラッグ）モードに戻る。
        """
        self._fixed_roi_size = size_scene_px
        # モードを切り替えたらプレビューを掃除
        if self._preview_item is not None:
            self._scene.removeItem(self._preview_item)
            self._preview_item = None

    def draw_roi(self, x: int, y: int, w: int, h: int, name: str = "") -> None:
        """確定済み ROI を矩形として重畳描画する。"""
        rect = QGraphicsRectItem(QRectF(x, y, w, h))
        rect.setPen(QPen(QColor("#ffcc00"), 0))
        rect.setBrush(QBrush(QColor(255, 204, 0, 40)))
        self._scene.addItem(rect)
        self._roi_items.append(rect)

    def clear_rois(self) -> None:
        """描画済み ROI 矩形をすべて消去する。"""
        for item in self._roi_items:
            self._scene.removeItem(item)
        self._roi_items.clear()

    # ------------------------------------------------------------------
    # ズーム
    # ------------------------------------------------------------------
    def wheelEvent(self, event) -> None:  # noqa: N802
        """ホイール操作.

        - 単独ホイール（マウス／トラックパッド2本指スクロール）: 上下スクロール
          （画面パン相当）。誤ズームを避けるため、修飾キーなしではズームしない。
        - ``Cmd`` (macOS) / ``Ctrl`` (Win/Linux) + ホイール: ズーム。
          Qt 上では両方とも :pyattr:`Qt.ControlModifier` として扱われる。
        """
        if event.modifiers() & Qt.ControlModifier:
            self._zoom_by(1.25 if event.angleDelta().y() > 0 else 0.8)
            event.accept()
            return
        super().wheelEvent(event)

    def _zoom_by(self, factor: float) -> None:
        """指定倍率で拡大縮小する。倍率レンジを 0.02x – 60x に制限。"""
        new_scale = self._scale_factor * factor
        if 0.02 < new_scale < 60:
            self.scale(factor, factor)
            self._scale_factor = new_scale

    def zoom_in(self) -> None:
        """1 段階拡大。"""
        self._zoom_by(1.25)

    def zoom_out(self) -> None:
        """1 段階縮小。"""
        self._zoom_by(0.8)

    def fit_to_view(self) -> None:
        """全体表示（表示リセット + フィット）。"""
        if self._pixmap_item is not None:
            self.resetTransform()
            self._scale_factor = 1.0
            self.fitInView(self._pixmap_item, Qt.KeepAspectRatio)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        """キーボードショートカット.

        - ``Cmd/Ctrl + =`` または ``+``: 拡大
        - ``Cmd/Ctrl + -``: 縮小
        - ``Cmd/Ctrl + 0``: 全体表示
        """
        if event.modifiers() & Qt.ControlModifier:
            key = event.key()
            if key in (Qt.Key_Plus, Qt.Key_Equal):
                self.zoom_in(); event.accept(); return
            if key == Qt.Key_Minus:
                self.zoom_out(); event.accept(); return
            if key == Qt.Key_0:
                self.fit_to_view(); event.accept(); return
        super().keyPressEvent(event)

    # ------------------------------------------------------------------
    # ROI ラバーバンド / 固定サイズ配置
    # ------------------------------------------------------------------
    def _clamp_rect_to_scene(self, rect: QRectF) -> QRectF:
        """ROI 矩形をシーン（画像）範囲内にクリップする。"""
        if self._pixmap_item is None:
            return rect
        bounds = self._pixmap_item.boundingRect()
        x = max(bounds.left(), min(rect.x(), bounds.right() - rect.width()))
        y = max(bounds.top(), min(rect.y(), bounds.bottom() - rect.height()))
        # サイズが画像より大きい場合は画像全体にフィット
        w = min(rect.width(), bounds.width())
        h = min(rect.height(), bounds.height())
        return QRectF(x, y, w, h)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self._roi_mode and event.button() == Qt.LeftButton:
            scene_pt = self.mapToScene(event.pos())
            if self._fixed_roi_size is not None:
                # 固定サイズモード: クリック中心に矩形を確定
                s = float(self._fixed_roi_size)
                rect = self._clamp_rect_to_scene(
                    QRectF(scene_pt.x() - s / 2, scene_pt.y() - s / 2, s, s)
                )
                r = rect.toRect()
                if r.width() > 0 and r.height() > 0:
                    self.roiSelected.emit(
                        max(0, r.x()), max(0, r.y()), r.width(), r.height()
                    )
                return
            # 自由選択モード（ラバーバンド開始）
            self._rubber_origin = scene_pt
            self._rubber_item = QGraphicsRectItem()
            self._rubber_item.setPen(QPen(QColor("#00e0ff"), 0, Qt.DashLine))
            self._rubber_item.setBrush(QBrush(QColor(0, 224, 255, 30)))
            self._scene.addItem(self._rubber_item)
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        # 固定サイズプレビュー: マウス位置に矩形を追従表示
        if self._roi_mode and self._fixed_roi_size is not None:
            scene_pt = self.mapToScene(event.pos())
            s = float(self._fixed_roi_size)
            rect = self._clamp_rect_to_scene(
                QRectF(scene_pt.x() - s / 2, scene_pt.y() - s / 2, s, s)
            )
            # 既存の preview_item が C++ 側で破棄済みなら作り直す
            try:
                if self._preview_item is None:
                    raise RuntimeError("no preview")
                self._preview_item.setRect(rect)
            except RuntimeError:
                self._preview_item = QGraphicsRectItem()
                self._preview_item.setPen(QPen(QColor("#00e0ff"), 0, Qt.DashLine))
                self._preview_item.setBrush(QBrush(QColor(0, 224, 255, 40)))
                self._scene.addItem(self._preview_item)
                self._preview_item.setRect(rect)
            return

        if self._roi_mode and self._rubber_origin and self._rubber_item:
            try:
                current = self.mapToScene(event.pos())
                rect = QRectF(self._rubber_origin, current).normalized()
                self._rubber_item.setRect(rect)
            except RuntimeError:
                # ラバーバンドが途中で破棄されたら安全に初期化
                self._rubber_item = None
                self._rubber_origin = None
            return
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        """マウスがビューから外れたらプレビューを消す。"""
        if self._preview_item is not None:
            try:
                self._scene.removeItem(self._preview_item)
            except RuntimeError:
                pass  # 既に C++ 側で破棄されていれば無視
            self._preview_item = None
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._roi_mode and self._rubber_origin and self._rubber_item:
            rect = self._rubber_item.rect().toRect()
            self._scene.removeItem(self._rubber_item)
            self._rubber_item = None
            self._rubber_origin = None
            if rect.width() > 5 and rect.height() > 5:
                self.roiSelected.emit(
                    max(0, rect.x()), max(0, rect.y()), rect.width(), rect.height()
                )
            return
        super().mouseReleaseEvent(event)
