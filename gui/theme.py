"""GUI テーマモジュール.

ダークモード・ライトモード両対応のスタイルシート（QSS）を提供する。外部
依存を増やさないよう、必要十分な QSS を内蔵する。macOS / Windows いずれでも
自然に見えるよう、ネイティブに近い配色・角丸・余白としている。
"""
from __future__ import annotations

DARK_QSS = """
* { font-size: 13px; }
QMainWindow, QWidget { background-color: #1e1e1e; color: #e0e0e0; }
QMenuBar, QMenu { background-color: #252526; color: #e0e0e0; }
QMenu::item:selected { background-color: #094771; }
QToolBar { background-color: #252526; border: none; spacing: 4px; padding: 4px; }
QStatusBar { background-color: #007acc; color: #ffffff; }
QGroupBox {
    border: 1px solid #3c3c3c; border-radius: 6px; margin-top: 10px; padding-top: 8px;
}
QGroupBox::title { subcontrol-origin: margin; left: 10px; color: #9cdcfe; }
QPushButton {
    background-color: #0e639c; color: white; border: none; border-radius: 4px;
    padding: 6px 12px;
}
QPushButton:hover { background-color: #1177bb; }
QPushButton:pressed { background-color: #094771; }
QPushButton:disabled { background-color: #3c3c3c; color: #888; }
QListWidget, QTreeWidget, QTableWidget, QPlainTextEdit, QTextEdit {
    background-color: #252526; border: 1px solid #3c3c3c; border-radius: 4px;
    selection-background-color: #094771;
}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background-color: #3c3c3c; border: 1px solid #555; border-radius: 4px; padding: 4px;
}
QComboBox::drop-down { border: none; }
QProgressBar {
    border: 1px solid #3c3c3c; border-radius: 4px; text-align: center;
    background-color: #252526;
}
QProgressBar::chunk { background-color: #0e639c; border-radius: 3px; }
QTabBar::tab {
    background: #2d2d2d; color: #ccc; padding: 6px 12px; border-top-left-radius: 4px;
    border-top-right-radius: 4px;
}
QTabBar::tab:selected { background: #1e1e1e; color: #fff; }
QSplitter::handle { background-color: #3c3c3c; }
QScrollBar:vertical { background: #252526; width: 12px; }
QScrollBar::handle:vertical { background: #555; border-radius: 6px; min-height: 20px; }
"""

LIGHT_QSS = """
* { font-size: 13px; }
QMainWindow, QWidget { background-color: #f5f5f5; color: #1e1e1e; }
QMenuBar, QMenu { background-color: #ffffff; color: #1e1e1e; }
QMenu::item:selected { background-color: #cce8ff; }
QToolBar { background-color: #ffffff; border: none; spacing: 4px; padding: 4px; }
QStatusBar { background-color: #007acc; color: #ffffff; }
QGroupBox {
    border: 1px solid #d0d0d0; border-radius: 6px; margin-top: 10px; padding-top: 8px;
    background-color: #ffffff;
}
QGroupBox::title { subcontrol-origin: margin; left: 10px; color: #0a5aa5; }
QPushButton {
    background-color: #007acc; color: white; border: none; border-radius: 4px;
    padding: 6px 12px;
}
QPushButton:hover { background-color: #1a8cff; }
QPushButton:pressed { background-color: #005a9e; }
QPushButton:disabled { background-color: #cccccc; color: #888; }
QListWidget, QTreeWidget, QTableWidget, QPlainTextEdit, QTextEdit {
    background-color: #ffffff; border: 1px solid #d0d0d0; border-radius: 4px;
    selection-background-color: #cce8ff;
}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background-color: #ffffff; border: 1px solid #c0c0c0; border-radius: 4px; padding: 4px;
}
QProgressBar {
    border: 1px solid #d0d0d0; border-radius: 4px; text-align: center; background-color: #ffffff;
}
QProgressBar::chunk { background-color: #007acc; border-radius: 3px; }
QTabBar::tab { background: #e8e8e8; color: #333; padding: 6px 12px; }
QTabBar::tab:selected { background: #ffffff; color: #000; }
QSplitter::handle { background-color: #d0d0d0; }
"""


def apply_theme(app, theme: str = "dark") -> None:
    """QApplication にテーマを適用する。

    Args:
        app: QApplication インスタンス。
        theme: ``"dark"`` または ``"light"``。
    """
    app.setStyleSheet(DARK_QSS if theme == "dark" else LIGHT_QSS)
