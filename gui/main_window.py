"""メインウィンドウ.

仕様の 4 ペイン構成（左: WSI 一覧 / 中央: WSI 表示 / 右: 解析設定 / 下: ログ）
を ``QDockWidget`` と ``QSplitter`` で構成する。ドラッグ&ドロップでの WSI 読込、
最近使ったファイル、Undo/Redo、進捗表示、解析パイプライン起動を統括する。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QActionGroup, QKeySequence, QUndoCommand, QUndoStack
from PySide6.QtWidgets import (
    QDockWidget,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from config.logging_config import build_qt_log_handler
from config.settings import AppSettings
from modules.datatypes import ROI
from modules.pipeline import PipelineConfig, PipelineResult
from modules.roi import ROIManager
from modules.wsi_loader import WSILoader, WSILoadError

from .panels import LogPanel, WSIListPanel
from .settings_panel import SettingsPanel
from .viewer import WSIViewer
from .workers import PipelineWorker, run_in_thread

logger = logging.getLogger(__name__)


@dataclass
class WSIDocument:
    """1 枚の WSI と付随情報（サムネイル・ROI・ローダ）を束ねる。"""

    name: str
    loader: WSILoader
    thumbnail: np.ndarray
    roi_manager: ROIManager = field(default_factory=ROIManager)

    @property
    def metadata(self):
        return self.loader.metadata


class _AddROICommand(QUndoCommand):
    """ROI 追加の Undo/Redo コマンド。"""

    def __init__(self, window: "MainWindow", doc_index: int, roi: ROI) -> None:
        super().__init__(f"Add ROI {roi.name}")
        self._window = window
        self._doc_index = doc_index
        self._roi = roi

    def redo(self) -> None:
        self._window.documents[self._doc_index].roi_manager.add(self._roi)
        self._window.refresh_views()

    def undo(self) -> None:
        self._window.documents[self._doc_index].roi_manager.remove(self._roi.id)
        self._window.refresh_views()


class MainWindow(QMainWindow):
    """アプリのメインウィンドウ。"""

    def __init__(self, settings: AppSettings) -> None:
        super().__init__()
        self.settings = settings
        self.documents: list[WSIDocument] = []
        self.current_index: int = -1
        self.undo_stack = QUndoStack(self)
        self._thread = None  # 実行中スレッドの保持

        self.setWindowTitle("Virtual Multiplex Pathology Analyzer")
        self.resize(1400, 900)
        self.setAcceptDrops(True)

        self._build_central()
        self._build_docks()
        self._build_menu()
        self._build_statusbar()
        self._attach_log_panel()

        logger.info("メインウィンドウ初期化完了")

    # ------------------------------------------------------------------
    # レイアウト構築
    # ------------------------------------------------------------------
    def _build_central(self) -> None:
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        self.viewer = WSIViewer()
        self.viewer.roiSelected.connect(self._on_roi_drawn)
        layout.addWidget(self.viewer)
        self.setCentralWidget(central)

    def _build_docks(self) -> None:
        # 左: WSI 一覧
        self.wsi_list = WSIListPanel()
        self.wsi_list.addFilesRequested.connect(self.open_files_dialog)
        self.wsi_list.wsiSelected.connect(self.show_wsi)
        left_dock = QDockWidget("WSI 一覧", self)
        left_dock.setWidget(self.wsi_list)
        self.addDockWidget(Qt.LeftDockWidgetArea, left_dock)

        # 右: 解析設定
        self.settings_panel = SettingsPanel(self.settings)
        self.settings_panel.runRequested.connect(self.run_analysis)
        self.settings_panel.settingsChanged.connect(self._save_settings_silent)
        right_dock = QDockWidget("解析設定", self)
        right_dock.setWidget(self.settings_panel)
        self.addDockWidget(Qt.RightDockWidgetArea, right_dock)

        # 下: ログ
        self.log_panel = LogPanel()
        bottom_dock = QDockWidget("ログ", self)
        bottom_dock.setWidget(self.log_panel)
        self.addDockWidget(Qt.BottomDockWidgetArea, bottom_dock)

    def _build_menu(self) -> None:
        menubar = self.menuBar()

        # ファイル
        file_menu = menubar.addMenu("ファイル")
        open_act = QAction("WSI を開く…", self)
        open_act.setShortcut(QKeySequence.Open)
        open_act.triggered.connect(self.open_files_dialog)
        file_menu.addAction(open_act)

        self.recent_menu = file_menu.addMenu("最近使ったファイル")
        self._rebuild_recent_menu()

        file_menu.addSeparator()
        export_act = QAction("結果をエクスポート…", self)
        export_act.triggered.connect(self.export_results_dialog)
        file_menu.addAction(export_act)

        file_menu.addSeparator()
        quit_act = QAction("終了", self)
        quit_act.setShortcut(QKeySequence.Quit)
        quit_act.triggered.connect(self.close)
        file_menu.addAction(quit_act)

        # 編集（Undo/Redo）
        edit_menu = menubar.addMenu("編集")
        undo_act = self.undo_stack.createUndoAction(self, "元に戻す")
        undo_act.setShortcut(QKeySequence.Undo)
        redo_act = self.undo_stack.createRedoAction(self, "やり直す")
        redo_act.setShortcut(QKeySequence.Redo)
        edit_menu.addAction(undo_act)
        edit_menu.addAction(redo_act)

        # 表示
        view_menu = menubar.addMenu("表示")
        self.roi_mode_act = QAction("ROI 選択モード", self, checkable=True)
        self.roi_mode_act.toggled.connect(self.viewer.set_roi_mode)
        # 起動時から ROI 選択モードを ON にしておく（本アプリの主目的のため）
        self.roi_mode_act.setChecked(True)
        view_menu.addAction(self.roi_mode_act)

        # 拡大・縮小・全体表示（メニュー + ショートカット）
        zoom_in_act = QAction("拡大", self)
        zoom_in_act.setShortcuts([QKeySequence("Ctrl++"), QKeySequence("Ctrl+=")])
        zoom_in_act.triggered.connect(self.viewer.zoom_in)
        zoom_out_act = QAction("縮小", self)
        zoom_out_act.setShortcut(QKeySequence("Ctrl+-"))
        zoom_out_act.triggered.connect(self.viewer.zoom_out)
        fit_act = QAction("全体表示", self)
        fit_act.setShortcut(QKeySequence("Ctrl+0"))
        fit_act.triggered.connect(self.viewer.fit_to_view)
        # 解析結果（Pseudo Fluorescence）を再表示する
        self.show_result_act = QAction("結果を再表示", self)
        self.show_result_act.setToolTip("直近の解析結果（Pseudo Fluorescence 合成画像）を表示")
        self.show_result_act.triggered.connect(self._show_last_result)
        self.show_result_act.setEnabled(False)
        view_menu.addSeparator()
        view_menu.addAction(zoom_in_act)
        view_menu.addAction(zoom_out_act)
        view_menu.addAction(fit_act)
        view_menu.addAction(self.show_result_act)

        theme_act = QAction("テーマ切替 (Dark/Light)", self)
        theme_act.triggered.connect(self._toggle_theme)
        view_menu.addAction(theme_act)

        # 目立つ位置のツールバー（メニューは見落とされがちなので併設）
        toolbar = QToolBar("ビュー", self)
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        toolbar.addAction(zoom_in_act)
        toolbar.addAction(zoom_out_act)
        toolbar.addAction(fit_act)
        toolbar.addAction(self.show_result_act)
        toolbar.addSeparator()
        toolbar.addAction(self.roi_mode_act)
        toolbar.addSeparator()

        # ROI プリセット（自由/2000px/4000px）— 排他選択
        self.roi_preset_group = QActionGroup(self)
        self.roi_preset_group.setExclusive(True)
        self.roi_free_act = QAction("自由選択", self, checkable=True)
        self.roi_2k_act = QAction("2000×2000", self, checkable=True)
        self.roi_2k_act.setToolTip("約 0.9 × 0.9 mm。DAPI 基準の推奨サイズ")
        self.roi_4k_act = QAction("4000×4000", self, checkable=True)
        self.roi_4k_act.setToolTip("約 1.8 × 1.8 mm。DeepLIIF API 上限ぎりぎり")
        for a in (self.roi_free_act, self.roi_2k_act, self.roi_4k_act):
            self.roi_preset_group.addAction(a)
            toolbar.addAction(a)
        # 既定: 2000×2000（安全側）
        self.roi_2k_act.setChecked(True)
        self.roi_free_act.triggered.connect(lambda: self._apply_roi_preset(None))
        self.roi_2k_act.triggered.connect(lambda: self._apply_roi_preset(2000))
        self.roi_4k_act.triggered.connect(lambda: self._apply_roi_preset(4000))
        # プリセット状態を保持（切替時／WSI切替時に viewer へ反映するため）
        self._roi_preset_level0: "int | None" = 2000

        # ヘルプ
        help_menu = menubar.addMenu("ヘルプ")
        about_act = QAction("バージョン情報", self)
        about_act.triggered.connect(self._show_about)
        help_menu.addAction(about_act)

    def _build_statusbar(self) -> None:
        self.progress = QProgressBar()
        self.progress.setMaximumWidth(280)
        self.progress.setVisible(False)
        self.status_label = QLabel("準備完了")
        self.statusBar().addWidget(self.status_label, 1)
        self.statusBar().addPermanentWidget(self.progress)

    def _attach_log_panel(self) -> None:
        """ロギング出力を下部ログパネルへ流し込む。"""
        handler = build_qt_log_handler(self.log_panel.append_log)
        logging.getLogger().addHandler(handler)

    # ------------------------------------------------------------------
    # ドラッグ & ドロップ
    # ------------------------------------------------------------------
    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        paths = [Path(u.toLocalFile()) for u in event.mimeData().urls()]
        self.load_files([p for p in paths if p.is_file()])

    # ------------------------------------------------------------------
    # ファイル読込（Step1）
    # ------------------------------------------------------------------
    def open_files_dialog(self) -> None:
        """ファイル選択ダイアログから WSI を読み込む。"""
        files, _ = QFileDialog.getOpenFileNames(
            self, "WSI を選択",
            filter="WSI (*.ndpi *.svs *.tif *.tiff *.vsi);;すべて (*.*)",
        )
        if files:
            self.load_files([Path(f) for f in files])

    def load_files(self, paths: list[Path]) -> None:
        """複数 WSI を読み込みドキュメントに追加する。"""
        for path in paths:
            try:
                loader = WSILoader(path)
                thumb = loader.get_thumbnail(self.settings.thumbnail_size)
                doc = WSIDocument(name=path.name, loader=loader, thumbnail=thumb)
                self.documents.append(doc)
                self.settings.add_recent(str(path))
                logger.info("WSI 読込: %s", path.name)
            except WSILoadError as exc:
                QMessageBox.warning(self, "読込エラー", str(exc))
                logger.error("WSI 読込失敗: %s", exc)
        self._save_settings_silent()
        self._rebuild_recent_menu()
        self.refresh_views()
        if self.documents:
            self.show_wsi(len(self.documents) - 1)

    def show_wsi(self, index: int) -> None:
        """指定 WSI のサムネイルを中央ビューへ表示する。"""
        if not (0 <= index < len(self.documents)):
            return
        self.current_index = index
        doc = self.documents[index]
        self.viewer.set_image(doc.thumbnail)
        self.viewer.clear_rois()
        # サムネイル座標系で ROI を重畳（レベル0→サムネイルスケール変換）
        scale = doc.thumbnail.shape[1] / doc.metadata.width
        for roi in doc.roi_manager:
            self.viewer.draw_roi(
                int(roi.x * scale), int(roi.y * scale),
                int(roi.width * scale), int(roi.height * scale), roi.name,
            )
        self.status_label.setText(f"{doc.name} を表示中")
        # WSI ごとにサムネイル倍率が違うので、プリセット px を再計算して反映
        self._apply_roi_preset(self._roi_preset_level0)

    def _apply_roi_preset(self, size_level0_px: "int | None") -> None:
        """ROI プリセット（レベル0[px]）をビューアのシーン座標へ変換して適用する.

        Args:
            size_level0_px: レベル0 でのサイズ [px]。``None`` で自由選択。
        """
        self._roi_preset_level0 = size_level0_px
        if size_level0_px is None or self.current_index < 0:
            self.viewer.set_fixed_roi_size(None)
            return
        doc = self.documents[self.current_index]
        scale = doc.thumbnail.shape[1] / doc.metadata.width  # thumb per level0
        scene_px = float(size_level0_px) * scale
        self.viewer.set_fixed_roi_size(scene_px)

    # ------------------------------------------------------------------
    # ROI（Step2）
    # ------------------------------------------------------------------
    def _on_roi_drawn(self, x: int, y: int, w: int, h: int) -> None:
        """ビューアでの選択（サムネイル座標）をレベル0 ROI に変換して登録。"""
        if self.current_index < 0:
            return
        doc = self.documents[self.current_index]
        scale = doc.metadata.width / doc.thumbnail.shape[1]
        roi = ROI(
            x=int(x * scale), y=int(y * scale),
            width=int(w * scale), height=int(h * scale),
        )
        self.undo_stack.push(_AddROICommand(self, self.current_index, roi))
        logger.info("ROI 追加: %s %s", roi.name, roi.bounds)

    # ------------------------------------------------------------------
    # 解析実行（Step3-9）
    # ------------------------------------------------------------------
    def run_analysis(self) -> None:
        """設定された ROI で解析パイプラインを起動する。"""
        logger.info("解析ボタンがクリックされました")
        docs_with_roi = [d for d in self.documents if len(d.roi_manager) > 0]
        if len(docs_with_roi) < 2:
            logger.warning("ROI 不足: 解析中止")
            QMessageBox.information(
                self, "ROI が不足", "2 枚以上の WSI にそれぞれ ROI を設定してください。"
            )
            return

        doc_a, doc_b = docs_with_roi[0], docs_with_roi[1]
        roi_obj_a = doc_a.roi_manager.rois[0]
        roi_obj_b = doc_b.roi_manager.rois[0]
        logger.info("解析対象: A=%s ROI=%s / B=%s ROI=%s",
                    doc_a.name, roi_obj_a.bounds, doc_b.name, roi_obj_b.bounds)

        # DeepLIIF クラウドAPIの上限（4096×4096）を超える ROI は事前に警告する
        API_MAX = 4096
        oversized = [
            (doc_a.name, roi_obj_a.width, roi_obj_a.height),
            (doc_b.name, roi_obj_b.width, roi_obj_b.height),
        ]
        big = [(n, w, h) for (n, w, h) in oversized if w > API_MAX or h > API_MAX]
        if big and self.settings.deepliif_mode == "api":
            msg = "\n".join(f"・{n}: {w}×{h} px" for (n, w, h) in big)
            ret = QMessageBox.warning(
                self,
                "ROI サイズが大きすぎます",
                "DeepLIIF クラウド API の上限は 4096×4096 px です。\n"
                "以下の ROI はサイズ超過で API が失敗し、mock（近似）に落ちる可能性があります:\n\n"
                f"{msg}\n\n"
                "ツールバーの「2000×2000」または「4000×4000」プリセットで引き直すことを推奨します。\n"
                "このまま実行しますか？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if ret != QMessageBox.Yes:
                logger.info("ユーザがキャンセル: サイズ超過警告")
                return

        config = PipelineConfig(
            deepliif_mode=self.settings.deepliif_mode,
            deepliif_api_url=self.settings.deepliif_api_url,
            deepliif_model_dir=self.settings.deepliif_model_dir,
            deepliif_tile_size=self.settings.deepliif_tile_size,
            deepliif_resolution=self.settings.deepliif_resolution,
            registration_method=self.settings.registration_method,
            registration_scale=getattr(self.settings, "registration_scale", 0.5),
            region_tile_um=getattr(self.settings, "region_tile_um", 100.0),
            show_dapi_channel=getattr(self.settings, "show_dapi_channel", True),
            color_dapi=tuple(getattr(self.settings, "color_dapi", [0, 120, 255])),
            matching_distance_um=self.settings.matching_distance_um,
            mpp=doc_a.metadata.mpp,
            marker_a=self.settings.marker_a,
            marker_b=self.settings.marker_b,
            color_a=tuple(self.settings.color_a),
            color_b=tuple(self.settings.color_b),
        )

        # クリック直後の視覚フィードバック（凍って見える問題を解消）
        self.progress.setVisible(True)
        self.progress.setValue(0)
        self.status_label.setText("ROI 切り出し中...")
        self.settings_panel.run_button.setEnabled(False)
        logger.info("ワーカー起動: ROI 切り出しはワーカースレッド内で実行")

        # ROI 切り出し + パイプライン全部をワーカーで（メインスレッドは凍らない）
        worker = PipelineWorker(
            config,
            loader_a=doc_a.loader, roi_obj_a=roi_obj_a,
            loader_b=doc_b.loader, roi_obj_b=roi_obj_b,
        )
        worker.progress.connect(self._on_progress)
        worker.finished_result.connect(self._on_analysis_done)
        worker.failed.connect(self._on_analysis_failed)
        self._thread = run_in_thread(worker, self)
    def _show_last_result(self) -> None:
        """直近の解析結果（Pseudo Fluorescence 合成画像）を再表示する。"""
        result = getattr(self, "_last_result", None)
        if result is None or getattr(result, "merged_rgb", None) is None:
            QMessageBox.information(
                self, "結果なし", "再表示できる解析結果がありません。先に解析を実行してください。"
            )
            return
        self.viewer.set_image(result.merged_rgb)
        self._showing_result = True
        self.status_label.setText("解析結果（Pseudo Fluorescence）を表示中")

    def _on_progress(self, pct: int, msg: str) -> None:
        self.progress.setValue(pct)
        self.status_label.setText(msg)

    def _on_analysis_done(self, result: PipelineResult) -> None:
        self.progress.setVisible(False)
        self.settings_panel.run_button.setEnabled(True)
        self._last_result = result
        ct = result.crosstab
        self.status_label.setText(
            f"解析完了: {ct.marker_a}+/{ct.marker_b}+={ct.both_positive} "
            f"(n={ct.total}, 一致率={result.matching.match_rate*100:.1f}%)"
        )
        if result.merged_rgb is not None:
            self.viewer.set_image(result.merged_rgb)
            self._showing_result = True
            self.show_result_act.setEnabled(True)

        # Matching 妥当性の診断結果を必ず提示する（誤解を防ぐため）
        diag_text = ""
        diag = getattr(result, "diagnostics", None)
        if diag is not None and getattr(diag, "observed", None) is not None:
            diag_text = "\n\n【Cell Matching 妥当性】\n" + diag.summary()
            if not diag.is_distinguishable:
                diag_text += (
                    "\n\n⚠ 連続切片では Ki67 切片と p53 切片が同一細胞を"
                    "含むとは限りません。共陽性率は参考値として扱ってください。"
                )

        # 領域レベル（タイル単位）の共局在 — 連続切片で正当な指標
        region_text = ""
        region = getattr(result, "region", None)
        if region is not None and getattr(region, "n_tiles", 0) >= 3:
            region_text = (
                f"\n\n【領域レベル共局在（タイル {region.tile_um:.0f} μm, "
                f"n={region.n_tiles}）】\n"
                f"{region.marker_a}密度 vs {region.marker_b}密度: "
                f"Pearson r={region.pearson_r:.3f} / Spearman ρ={region.spearman_rho:.3f}\n"
                "（連続切片ではこちらが妥当な共局在指標です）"
            )

        QMessageBox.information(
            self, "解析完了",
            f"対応細胞数: {ct.total}\n"
            f"{ct.marker_a}+ Index: {ct.a_index:.3f}\n"
            f"{ct.marker_b}+ Index: {ct.b_index:.3f}\n"
            f"共陽性 Overlap: {ct.overlap_rate:.3f}"
            f"{diag_text}"
            f"{region_text}",
        )

    def _on_analysis_failed(self, message: str) -> None:
        self.progress.setVisible(False)
        self.settings_panel.run_button.setEnabled(True)
        QMessageBox.critical(self, "解析エラー", message[:2000])

    # ------------------------------------------------------------------
    # エクスポート（Step10）
    # ------------------------------------------------------------------
    def export_results_dialog(self) -> None:
        """直近の解析結果を各種フォーマットで保存する。"""
        if not getattr(self, "_last_result", None):
            QMessageBox.information(self, "結果なし", "先に解析を実行してください。")
            return
        out_dir = QFileDialog.getExistingDirectory(self, "出力先フォルダを選択")
        if not out_dir:
            return
        from modules.export import Exporter
        from modules.visualization import (
            cell_overlay,
            density_heatmap,
            matching_distance_figure,
            merged_figure,
            region_correlation_figure,
        )

        result: PipelineResult = self._last_result
        diag = getattr(result, "diagnostics", None)
        region = getattr(result, "region", None)
        exporter = Exporter(out_dir)
        try:
            exporter.export_csv(result.cells_a, "cells_a.csv")
            exporter.export_csv(result.cells_b, "cells_b.csv")
            exporter.export_excel(
                {self.settings.marker_a: result.cells_a, self.settings.marker_b: result.cells_b},
                [result.crosstab],
                diagnostics=diag,
            )
            img_path = exporter.export_image(result.merged_rgb, "merged.tif")
            figs = [
                merged_figure(result.merged_rgb),
                density_heatmap(
                    np.array([c.centroid_px for c in result.cells_a]) if result.cells_a else np.empty((0, 2)),
                    result.merged_rgb.shape[:2],
                ),
                cell_overlay(result.merged_rgb, result.cells_a, show_ids=False),
            ]
            # Cell Matching 妥当性の図（観測 vs ランダム対照 + 閾値感度）
            if diag is not None and getattr(diag, "observed", None) is not None:
                figs.append(
                    matching_distance_figure(diag.observed, diag.control, diag.rows)
                )
            if region is not None and getattr(region, "n_tiles", 0) >= 3:
                figs.append(region_correlation_figure(region))
            exporter.export_pdf(figs, "report.pdf")
            exporter.export_pptx([img_path], [result.crosstab])
            json_payload = {
                "registration": result.registration.transform_params,
                "method": result.registration.method,
                "metric": result.registration.metric,
                "match_rate": result.matching.match_rate,
            }
            if diag is not None and hasattr(diag, "as_summary_dict"):
                json_payload["matching_validity"] = diag.as_summary_dict()
                json_payload["threshold_sensitivity"] = diag.threshold_rows_dicts()
            if region is not None and hasattr(region, "as_dict"):
                json_payload["region_correlation"] = region.as_dict()
            exporter.export_json(json_payload, "registration.json")
            QMessageBox.information(self, "エクスポート完了", f"保存先:\n{out_dir}")
            logger.info("エクスポート完了: %s", out_dir)
        except Exception as exc:  # noqa: BLE001
            logger.exception("エクスポート失敗")
            QMessageBox.critical(self, "エクスポートエラー", str(exc))

    # ------------------------------------------------------------------
    # その他 UI
    # ------------------------------------------------------------------
    def refresh_views(self) -> None:
        """一覧・ビューを最新状態に更新する。"""
        self.wsi_list.refresh(self.documents)
        if 0 <= self.current_index < len(self.documents):
            self.show_wsi(self.current_index)

    def _rebuild_recent_menu(self) -> None:
        self.recent_menu.clear()
        if not self.settings.recent_files:
            act = QAction("(なし)", self)
            act.setEnabled(False)
            self.recent_menu.addAction(act)
            return
        for path in self.settings.recent_files:
            act = QAction(Path(path).name, self)
            act.setToolTip(path)
            act.triggered.connect(lambda _=False, p=path: self.load_files([Path(p)]))
            self.recent_menu.addAction(act)

    def _toggle_theme(self) -> None:
        from PySide6.QtWidgets import QApplication

        from .theme import apply_theme

        self.settings.theme = "light" if self.settings.theme == "dark" else "dark"
        apply_theme(QApplication.instance(), self.settings.theme)
        self._save_settings_silent()

    def _show_about(self) -> None:
        QMessageBox.about(
            self, "バージョン情報",
            "Virtual Multiplex Pathology Analyzer\n"
            "連続切片 WSI の定量解析ツール（研究用）\n\n"
            "細胞検出・陽性/陰性判定: DeepLIIF クラウド API の\n"
            "セグメンテーション結果（SegRefined）に基づく。\n\n"
            "表示される蛍光様画像は Pseudo Fluorescence\n"
            "（元 IHC の色分離ベース）であり、DeepLIIF が生成する\n"
            "Virtual IF（mpIF）ではありません。\n\n"
            "Python 3.11+ / PySide6",
        )

    def _save_settings_silent(self) -> None:
        try:
            self.settings.save()
        except Exception:  # noqa: BLE001
            logger.warning("設定保存に失敗しました。")

    def closeEvent(self, event) -> None:  # noqa: N802
        self._save_settings_silent()
        for doc in self.documents:
            doc.loader.close()
        super().closeEvent(event)
