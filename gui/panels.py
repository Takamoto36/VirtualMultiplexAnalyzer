"""左パネル（WSI 一覧）と下パネル（ログ）の実装.

* :class:`WSIListPanel`: 読込済み WSI と各 WSI の ROI をツリー表示する。
* :class:`LogPanel`: ロギング出力を表示する読み取り専用テキストパネル。
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QPlainTextEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)


class WSIListPanel(QWidget):
    """読込済み WSI と ROI をツリー表示する左パネル。"""

    #: WSI 選択時に画像インデックスを通知。
    wsiSelected = Signal(int)
    #: ROI 選択時に (wsi_index, roi_id) を通知。
    roiSelected = Signal(int, str)
    addFilesRequested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["WSI / ROI"])
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        layout.addWidget(self.tree)

        self.add_button = QPushButton("＋ WSI を追加")
        layout.addWidget(self.add_button)
        self.add_button.clicked.connect(self.addFilesRequested)
        self.tree.itemClicked.connect(self._on_item_clicked)

    def refresh(self, documents) -> None:
        """ドキュメント一覧からツリーを再構築する.

        Args:
            documents: ``(name, metadata, roi_list)`` を持つオブジェクトの列。
        """
        self.tree.clear()
        for idx, doc in enumerate(documents):
            top = QTreeWidgetItem([doc.name])
            top.setData(0, 0x0100, ("wsi", idx))  # Qt.UserRole
            meta = doc.metadata
            info = f"{meta.width}×{meta.height}"
            if meta.magnification:
                info += f"  {meta.magnification:g}×"
            if meta.mpp:
                info += f"  {meta.mpp:.3f} μm/px"
            child_info = QTreeWidgetItem([info])
            child_info.setForeground(0, QColor("#888"))
            top.addChild(child_info)
            for roi in doc.roi_manager:
                roi_item = QTreeWidgetItem([f"⬛ {roi.name}"])
                roi_item.setData(0, 0x0100, ("roi", idx, roi.id))
                top.addChild(roi_item)
            self.tree.addTopLevelItem(top)
            top.setExpanded(True)

    def _on_item_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        data = item.data(0, 0x0100)
        if not data:
            return
        if data[0] == "wsi":
            self.wsiSelected.emit(data[1])
        elif data[0] == "roi":
            self.roiSelected.emit(data[1], data[2])


class LogPanel(QPlainTextEdit):
    """アプリログを表示する読み取り専用パネル（下パネル）。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setMaximumBlockCount(5000)  # メモリ肥大化防止
        self.setPlaceholderText("処理ログがここに表示されます…")

    def append_log(self, text: str) -> None:
        """1 行追記して最下部へスクロールする。"""
        self.appendPlainText(text)
        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())
