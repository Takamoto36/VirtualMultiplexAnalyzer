"""Step10: エクスポートモジュール.

解析結果を各種フォーマットで保存する:

* CSV / Excel : 細胞テーブル・統計サマリー（pandas / openpyxl）
* PNG / TIFF  : マージ画像・可視化 Figure
* PDF         : 図表をまとめたレポート（matplotlib PdfPages）
* PowerPoint  : スライドレポート（python-pptx）
* JSON        : レジストレーション情報・設定

いずれのパスも :mod:`pathlib` で扱い、OS 差異を吸収する。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Iterable, Optional

import numpy as np
import pandas as pd

from .datatypes import Cell
from .statistics import CrossTab

logger = logging.getLogger(__name__)


class Exporter:
    """解析成果物を出力するユーティリティクラス。"""

    def __init__(self, output_dir: str | Path) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # 表データ
    # ------------------------------------------------------------------
    def cells_to_dataframe(self, cells: Iterable[Cell]) -> pd.DataFrame:
        """細胞リストを DataFrame に変換する。"""
        return pd.DataFrame([c.as_row() for c in cells])

    def export_csv(self, cells: Iterable[Cell], filename: str = "cells.csv") -> Path:
        """細胞テーブルを CSV 保存する。"""
        path = self.output_dir / filename
        self.cells_to_dataframe(cells).to_csv(path, index=False, encoding="utf-8-sig")
        logger.info("CSV 保存: %s", path)
        return path

    def export_excel(
        self,
        cells_by_marker: dict[str, list[Cell]],
        crosstabs: list[CrossTab],
        filename: str = "analysis.xlsx",
        diagnostics: object = None,
    ) -> Path:
        """細胞テーブル（マーカー別シート）と統計サマリーを Excel 保存する.

        ``diagnostics`` を渡すと Cell Matching 妥当性シートと閾値感度分析シートを
        追加する。統計サマリーが単独で独り歩きして誤読されるのを防ぐため、
        妥当性の但し書きを必ず同梱する設計。
        """
        path = self.output_dir / filename
        with pd.ExcelWriter(path, engine="openpyxl") as writer:
            summary_rows = [ct.as_dict() for ct in crosstabs]
            if summary_rows:
                df = pd.DataFrame(summary_rows)
                # 妥当性の要点を統計サマリーにも列として付す（誤読防止）
                if diagnostics is not None and hasattr(diagnostics, "as_summary_dict"):
                    d = diagnostics.as_summary_dict()
                    df["matching_distinguishable_from_chance"] = d[
                        "distinguishable_from_chance"
                    ]
                    df["matching_separation"] = d["separation"]
                    df["matching_note"] = d["interpretation"]
                df.to_excel(writer, sheet_name="Summary", index=False)
            for marker, cells in cells_by_marker.items():
                sheet = marker.replace("/", "_")[:31] or "cells"
                self.cells_to_dataframe(cells).to_excel(writer, sheet_name=sheet, index=False)
            # Cell Matching 妥当性シート
            if diagnostics is not None and hasattr(diagnostics, "as_summary_dict"):
                pd.DataFrame([diagnostics.as_summary_dict()]).to_excel(
                    writer, sheet_name="Matching_Validity", index=False
                )
                rows = diagnostics.threshold_rows_dicts()
                if rows:
                    pd.DataFrame(rows).to_excel(
                        writer, sheet_name="Threshold_Sensitivity", index=False
                    )
        logger.info("Excel 保存: %s", path)
        return path

    # ------------------------------------------------------------------
    # 画像
    # ------------------------------------------------------------------
    def export_image(self, array: np.ndarray, filename: str = "merged.png") -> Path:
        """RGB 配列を PNG/TIFF などで保存する。"""
        import imageio.v3 as iio

        path = self.output_dir / filename
        iio.imwrite(path, array)
        logger.info("画像保存: %s", path)
        return path

    def export_figure(self, figure, filename: str = "figure.png", dpi: int = 200) -> Path:
        """matplotlib Figure を保存する。"""
        path = self.output_dir / filename
        figure.savefig(path, dpi=dpi, bbox_inches="tight", facecolor="#1e1e1e")
        logger.info("Figure 保存: %s", path)
        return path

    # ------------------------------------------------------------------
    # PDF レポート
    # ------------------------------------------------------------------
    def export_pdf(self, figures: list, filename: str = "report.pdf") -> Path:
        """複数 Figure を 1 つの PDF レポートにまとめる。"""
        from matplotlib.backends.backend_pdf import PdfPages

        path = self.output_dir / filename
        with PdfPages(path) as pdf:
            for fig in figures:
                pdf.savefig(fig, facecolor="#1e1e1e")
        logger.info("PDF 保存: %s (%d 図)", path, len(figures))
        return path

    # ------------------------------------------------------------------
    # PowerPoint レポート
    # ------------------------------------------------------------------
    def export_pptx(
        self,
        image_paths: list[Path],
        crosstabs: list[CrossTab],
        title: str = "Virtual Multiplex Pathology Analysis",
        filename: str = "report.pptx",
    ) -> Path:
        """画像と統計サマリーを PowerPoint にまとめる。"""
        from pptx import Presentation
        from pptx.util import Inches, Pt

        prs = Presentation()
        prs.slide_width = Inches(13.333)
        prs.slide_height = Inches(7.5)

        # タイトルスライド
        slide = prs.slides.add_slide(prs.slide_layouts[0])
        slide.shapes.title.text = title
        if slide.placeholders and len(slide.placeholders) > 1:
            slide.placeholders[1].text = "Virtual Multiplex Pathology Analyzer"

        # 画像スライド
        blank = prs.slide_layouts[6]
        for img in image_paths:
            s = prs.slides.add_slide(blank)
            s.shapes.add_picture(str(img), Inches(0.5), Inches(0.5), height=Inches(6.0))

        # 統計スライド
        if crosstabs:
            s = prs.slides.add_slide(prs.slide_layouts[5])
            s.shapes.title.text = "Quantitative Summary"
            rows, cols = len(crosstabs) + 1, 7
            table = s.shapes.add_table(
                rows, cols, Inches(0.5), Inches(1.5), Inches(12), Inches(0.4 * rows)
            ).table
            headers = ["A", "B", "A+B+", "A+ Index", "B+ Index", "Overlap", "n"]
            for j, h in enumerate(headers):
                table.cell(0, j).text = h
            for i, ct in enumerate(crosstabs, start=1):
                vals = [
                    ct.marker_a, ct.marker_b, str(ct.both_positive),
                    f"{ct.a_index:.3f}", f"{ct.b_index:.3f}",
                    f"{ct.overlap_rate:.3f}", str(ct.total),
                ]
                for j, v in enumerate(vals):
                    cell = table.cell(i, j)
                    cell.text = v
                    cell.text_frame.paragraphs[0].font.size = Pt(11)

        path = self.output_dir / filename
        prs.save(path)
        logger.info("PowerPoint 保存: %s", path)
        return path

    # ------------------------------------------------------------------
    # JSON
    # ------------------------------------------------------------------
    def export_json(self, data: dict, filename: str = "registration.json") -> Path:
        """レジストレーション情報・設定などを JSON 保存する。"""
        path = self.output_dir / filename

        def _default(o):
            if isinstance(o, np.ndarray):
                return o.tolist()
            if isinstance(o, (np.floating, np.integer)):
                return o.item()
            return str(o)

        path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False, default=_default), encoding="utf-8"
        )
        logger.info("JSON 保存: %s", path)
        return path
