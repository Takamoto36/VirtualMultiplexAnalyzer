"""解析設定パネル（右パネル）.

Tile Size・DeepLIIF 実行方法・Registration Method・Matching Distance・マーカー
色などの設定 UI を提供する。値変更は :pyattr:`settingsChanged` で通知し、
:class:`~config.settings.AppSettings` と相互に同期する。
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from config.settings import AppSettings
from modules.merge import COLOR_PRESETS


class _ColorButton(QPushButton):
    """クリックで色選択できるボタン（現在色を背景表示）。"""

    colorChanged = Signal(tuple)

    def __init__(self, rgb: tuple[int, int, int]) -> None:
        super().__init__()
        self._rgb = tuple(rgb)
        self.setFixedHeight(26)
        self._refresh()
        self.clicked.connect(self._pick)

    def _refresh(self) -> None:
        r, g, b = self._rgb
        self.setStyleSheet(
            f"background-color: rgb({r},{g},{b}); border-radius: 4px; border: 1px solid #555;"
        )
        self.setText(f"RGB({r},{g},{b})")

    def _pick(self) -> None:
        col = QColorDialog.getColor(QColor(*self._rgb), self, "色を選択")
        if col.isValid():
            self._rgb = (col.red(), col.green(), col.blue())
            self._refresh()
            self.colorChanged.emit(self._rgb)

    def rgb(self) -> tuple[int, int, int]:
        return self._rgb

    def set_rgb(self, rgb: tuple[int, int, int]) -> None:
        self._rgb = tuple(rgb)
        self._refresh()


class SettingsPanel(QWidget):
    """右側の解析設定パネル。"""

    settingsChanged = Signal()
    runRequested = Signal()

    def __init__(self, settings: AppSettings, parent=None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._loading = False
        self._build_ui()
        self._loading = True
        self._load_from_settings()
        self._loading = False

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        # --- DeepLIIF（クラウドAPI専用） ---
        io_box = QGroupBox("DeepLIIF（クラウドAPI）")
        io_form = QFormLayout(io_box)
        # 実行方法は API 固定。mock は内部フォールバック専用として GUI には出さない。
        self.deepliif_mode = QComboBox()
        self.deepliif_mode.addItems(["api"])
        # local 専用の設定（モデルDir/タイルサイズ）は API 専用運用では非表示。
        # 属性としては保持し、設定の読み書き互換を保つ。
        self.model_dir = QLineEdit()
        self.deepliif_tile = QSpinBox()
        self.deepliif_tile.setRange(64, 2048)
        self.api_url = QLineEdit()
        self.api_url.setPlaceholderText("https://deepliif.org/api/infer")
        self.deepliif_resolution = QComboBox()
        self.deepliif_resolution.addItems(["10x", "20x", "40x"])
        io_form.addRow("推論方法", QLabel("クラウドAPI (deepliif.org)"))
        io_form.addRow("API URL", self.api_url)
        io_form.addRow("解像度", self.deepliif_resolution)
        layout.addWidget(io_box)

        # --- タイル / レジストレーション ---
        reg_box = QGroupBox("処理設定")
        reg_form = QFormLayout(reg_box)
        self.tile_size = QSpinBox()
        self.tile_size.setRange(256, 8192)
        self.tile_size.setSingleStep(256)
        self.registration_method = QComboBox()
        self.registration_method.addItems(
            ["rigid", "affine", "rigid+affine", "rigid+affine+bspline"]
        )
        self.matching_distance = QDoubleSpinBox()
        self.matching_distance.setRange(0.5, 100.0)
        self.matching_distance.setSuffix(" μm")
        reg_form.addRow("Tile Size", self.tile_size)
        reg_form.addRow("Registration", self.registration_method)
        reg_form.addRow("Matching 距離", self.matching_distance)
        layout.addWidget(reg_box)

        # --- マーカー・色 ---
        color_box = QGroupBox("マーカー・疑似蛍光カラー（色分離ベース）")
        color_form = QFormLayout(color_box)
        self.marker_a = QLineEdit()
        self.marker_b = QLineEdit()
        self.color_a = _ColorButton(tuple(self._settings.color_a))
        self.color_b = _ColorButton(tuple(self._settings.color_b))
        self.preset_a = QComboBox()
        self.preset_b = QComboBox()
        for combo in (self.preset_a, self.preset_b):
            combo.addItem("プリセット…")
            combo.addItems(list(COLOR_PRESETS.keys()))
        color_form.addRow("マーカーA", self.marker_a)
        color_form.addRow("A 色", self.color_a)
        color_form.addRow("A プリセット", self.preset_a)
        color_form.addRow("マーカーB", self.marker_b)
        color_form.addRow("B 色", self.color_b)
        color_form.addRow("B プリセット", self.preset_b)
        # Pseudo DAPI（ヘマトキシリン=全核）を青で重畳するトグル
        self.show_dapi = QCheckBox("Pseudo DAPI（全核・青）を重畳")
        self.show_dapi.setToolTip(
            "元IHCのヘマトキシリン成分（全細胞核）を青チャネルで表示。"
            "DeepLIIF の Virtual DAPI ではなく色分離由来。"
        )
        color_form.addRow("DAPI", self.show_dapi)
        layout.addWidget(color_box)

        # --- 実行 ---
        self.run_button = QPushButton("▶ 解析を実行")
        self.run_button.setMinimumHeight(38)
        layout.addWidget(self.run_button)
        layout.addWidget(QLabel("※ 2 切片の ROI を選択してから実行してください"))
        layout.addStretch(1)

        # --- シグナル接続 ---
        self.run_button.clicked.connect(self.runRequested)
        for w in (self.deepliif_mode, self.registration_method, self.deepliif_resolution):
            w.currentIndexChanged.connect(self._on_change)
        self.preset_a.currentTextChanged.connect(
            lambda name: self._apply_preset(self.color_a, name)
        )
        self.preset_b.currentTextChanged.connect(
            lambda name: self._apply_preset(self.color_b, name)
        )
        for w in (self.tile_size, self.deepliif_tile):
            w.valueChanged.connect(self._on_change)
        self.matching_distance.valueChanged.connect(self._on_change)
        for w in (self.api_url, self.model_dir, self.marker_a, self.marker_b):
            w.textChanged.connect(self._on_change)
        self.show_dapi.toggled.connect(self._on_change)
        self.color_a.colorChanged.connect(lambda _: self._on_change())
        self.color_b.colorChanged.connect(lambda _: self._on_change())

    # ------------------------------------------------------------------
    def _apply_preset(self, button: _ColorButton, name: str) -> None:
        if name in COLOR_PRESETS:
            button.set_rgb(COLOR_PRESETS[name])
            self._on_change()

    def _load_from_settings(self) -> None:
        s = self._settings
        self.deepliif_mode.setCurrentText(s.deepliif_mode)
        self.api_url.setText(s.deepliif_api_url)
        self.model_dir.setText(s.deepliif_model_dir)
        self.deepliif_tile.setValue(s.deepliif_tile_size)
        self.deepliif_resolution.setCurrentText(s.deepliif_resolution)
        self.tile_size.setValue(s.tile_size)
        self.registration_method.setCurrentText(s.registration_method)
        self.matching_distance.setValue(s.matching_distance_um)
        self.marker_a.setText(s.marker_a)
        self.marker_b.setText(s.marker_b)
        self.color_a.set_rgb(tuple(s.color_a))
        self.color_b.set_rgb(tuple(s.color_b))
        self.show_dapi.setChecked(bool(getattr(s, "show_dapi_channel", True)))

    def _on_change(self) -> None:
        """UI の変更を :class:`AppSettings` に書き戻す。"""
        if self._loading:
            return
        s = self._settings
        s.deepliif_mode = self.deepliif_mode.currentText()
        s.deepliif_api_url = self.api_url.text()
        s.deepliif_model_dir = self.model_dir.text()
        s.deepliif_tile_size = self.deepliif_tile.value()
        s.deepliif_resolution = self.deepliif_resolution.currentText()
        s.tile_size = self.tile_size.value()
        s.registration_method = self.registration_method.currentText()
        s.matching_distance_um = self.matching_distance.value()
        s.marker_a = self.marker_a.text() or "Ki67"
        s.marker_b = self.marker_b.text() or "p53"
        s.color_a = list(self.color_a.rgb())
        s.color_b = list(self.color_b.rgb())
        s.show_dapi_channel = self.show_dapi.isChecked()
        self.settingsChanged.emit()
