"""Step10: 可視化モジュール.

matplotlib を用いて Merged 画像・Heatmap・Registration Error Map・Cell ID
オーバーレイなどの Figure を生成する。GUI へは Figure を渡し、Export では
そのまま画像/PDF に保存する。
"""
from __future__ import annotations

import logging
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


def _new_axes(figsize=(6, 6)):
    """余白のない画像表示用 Figure/Axes を生成する。"""
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=figsize)
    ax.set_axis_off()
    fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
    return fig, ax


def merged_figure(merged_rgb: np.ndarray, title: str = "Pseudo Fluorescence (stain-deconvolution based)"):
    """マージ済み RGB 画像の Figure を返す。"""
    fig, ax = _new_axes()
    ax.imshow(merged_rgb)
    ax.set_title(title, color="white", fontsize=10, loc="left", pad=6)
    return fig


def density_heatmap(
    centroids: np.ndarray, shape: tuple[int, int], sigma: float = 15.0, title: str = "Density Heatmap"
):
    """細胞重心の密度ヒートマップを生成する.

    Args:
        centroids: 重心座標 (N, 2) = (x, y)[px]。
        shape: 出力画像サイズ (H, W)。
        sigma: ガウス平滑化の標準偏差[px]。
    """
    import matplotlib.pyplot as plt
    from scipy.ndimage import gaussian_filter

    h, w = shape
    grid = np.zeros((h, w), dtype=np.float64)
    if len(centroids):
        xs = np.clip(centroids[:, 0].astype(int), 0, w - 1)
        ys = np.clip(centroids[:, 1].astype(int), 0, h - 1)
        np.add.at(grid, (ys, xs), 1.0)
        grid = gaussian_filter(grid, sigma=sigma)

    fig, ax = _new_axes()
    im = ax.imshow(grid, cmap="inferno")
    ax.set_title(title, color="white", fontsize=10, loc="left", pad=6)
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.02)
    return fig


def registration_error_map(
    displacement_field: Optional[np.ndarray], title: str = "Registration Error Map"
):
    """変位場の大きさ（位置合わせ誤差）をカラーマップ表示する.

    Args:
        displacement_field: (H, W, 2) の変位場。``None`` なら空図を返す。
    """
    import matplotlib.pyplot as plt

    fig, ax = _new_axes()
    if displacement_field is None:
        ax.text(0.5, 0.5, "変位場なし", ha="center", va="center", color="white")
        return fig
    magnitude = np.linalg.norm(displacement_field, axis=-1)
    im = ax.imshow(magnitude, cmap="viridis")
    ax.set_title(title, color="white", fontsize=10, loc="left", pad=6)
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.02, label="displacement [px]")
    return fig


def cell_overlay(
    background_rgb: np.ndarray,
    cells,
    show_ids: bool = True,
    positive_color: str = "#ffffff",
    negative_color: str = "#8e8e93",
    title: Optional[str] = None,
    marker: Optional[str] = None,
    section_note: str = "",
    legend: bool = True,
):
    """背景画像に細胞重心と（任意で）ID を重畳表示する.

    背景は通常 Pseudo Fluorescence の Merge 画像であり、そのチャネル色
    （既定では赤・緑・青）と点の色が紛れないよう、陽性=白塗り・陰性=灰色の
    輪郭という無彩色で描く。どの切片の検出結果かをタイトルと凡例に明記する。

    Args:
        background_rgb: 背景 RGB 画像。
        cells: :class:`~modules.datatypes.Cell` のリスト。
        show_ids: セル ID を描画するか（クリック対応表示の下地）。
        positive_color: 陽性細胞の点の色。
        negative_color: 陰性細胞の点の色。
        title: 図タイトル。``None`` なら ``marker`` から自動生成する。
        marker: この細胞群を検出した切片のマーカー名（例: "Ki67"）。
        section_note: タイトルに添える補足（例: "registered to Ki67"）。
        legend: 凡例を描くか。
    """
    from matplotlib.lines import Line2D

    fig, ax = _new_axes()
    ax.imshow(background_rgb)
    n_pos = n_neg = 0
    for cell in cells:
        x, y = cell.centroid_px
        if cell.positive:
            n_pos += 1
            ax.plot(x, y, "o", markersize=3.2, markerfacecolor=positive_color,
                    markeredgecolor="black", markeredgewidth=0.4)
        else:
            n_neg += 1
            ax.plot(x, y, "o", markersize=3.0, markerfacecolor="none",
                    markeredgecolor=negative_color, markeredgewidth=0.6)
        if show_ids:
            ax.text(x + 2, y - 2, cell.id[:4], color="white", fontsize=5)

    if title is None:
        if marker:
            title = f"Cell detection - {marker} section"
            if section_note:
                title += f" ({section_note})"
        else:
            title = "Cell Overlay"
    ax.set_title(title, color="white", fontsize=10, loc="left", pad=6)
    # _new_axes は上余白 0 のため、そのままではタイトルが図外に切れる
    fig.subplots_adjust(top=0.955)

    if legend:
        label = marker or "marker"
        handles = [
            Line2D([], [], linestyle="none", marker="o", markersize=6,
                   markerfacecolor=positive_color, markeredgecolor="black",
                   label=f"{label}-positive (n={n_pos})"),
            Line2D([], [], linestyle="none", marker="o", markersize=6,
                   markerfacecolor="none", markeredgecolor=negative_color,
                   label=f"{label}-negative (n={n_neg})"),
        ]
        leg = ax.legend(handles=handles, loc="lower right", fontsize=7,
                        facecolor="black", edgecolor="#666666", framealpha=0.75)
        for text in leg.get_texts():
            text.set_color("white")
    return fig


def matching_distance_figure(
    observed: np.ndarray,
    control: np.ndarray,
    rows: "list | None" = None,
    title: str = "Cell Matching validity",
):
    """マッチング距離の観測分布と帰無モデル（ランダム対照）を比較する Figure.

    連続切片では「距離が近い」ことが「同一細胞」を意味しないため、観測された
    最近傍距離分布が、同密度のランダム配置から得られる分布と区別できるかを
    可視化する。右パネルには距離閾値ごとの一致率・共陽性率の感度分析を描く。

    Args:
        observed: 観測された最近傍距離[μm]。
        control: 帰無モデルの最近傍距離[μm]。
        rows: :class:`modules.match_diagnostics.ThresholdRow` のリスト（任意）。
        title: 図のタイトル。

    Returns:
        matplotlib Figure。
    """
    import matplotlib.pyplot as plt

    ncols = 2 if rows else 1
    fig, axes = plt.subplots(1, ncols, figsize=(6.5 * ncols, 4.2))
    axes = np.atleast_1d(axes)
    fig.patch.set_facecolor("#1e1e1e")

    ax = axes[0]
    ax.set_facecolor("#1e1e1e")
    if observed.size and control.size:
        hi = float(np.percentile(np.concatenate([observed, control]), 99))
        bins = np.linspace(0, max(hi, 1e-3), 40)
        ax.hist(control, bins=bins, alpha=0.55, label="Random control (null)",
                color="#888888", density=True)
        ax.hist(observed, bins=bins, alpha=0.75, label="Observed",
                color="#00e0ff", density=True)
        ax.axvline(float(np.median(control)), color="#bbbbbb", ls="--", lw=1)
        ax.axvline(float(np.median(observed)), color="#00e0ff", ls="--", lw=1)
    ax.set_xlabel("Nearest-neighbor distance (um)", color="white")
    ax.set_ylabel("Density", color="white")
    ax.set_title(title, color="white", fontsize=10, loc="left")
    ax.tick_params(colors="white")
    leg = ax.legend(facecolor="#2a2a2a", edgecolor="none", fontsize=8)
    for t in leg.get_texts():
        t.set_color("white")

    if rows:
        ax2 = axes[1]
        ax2.set_facecolor("#1e1e1e")
        th = [r.threshold_um for r in rows]
        ax2.plot(th, [r.match_rate for r in rows], "o-", color="#00e0ff",
                 label="Match rate")
        ax2.plot(th, [r.co_positive_rate for r in rows], "s-", color="#ff7070",
                 label="Co-positive rate")
        ax2.plot(th, [r.overlap_rate for r in rows], "^-", color="#7CFC00",
                 label="Overlap (Jaccard)")
        ax2.set_xlabel("Matching distance threshold (um)", color="white")
        ax2.set_ylabel("Rate", color="white")
        ax2.set_title("Threshold sensitivity", color="white", fontsize=10, loc="left")
        ax2.tick_params(colors="white")
        ax2.grid(alpha=0.2)
        leg2 = ax2.legend(facecolor="#2a2a2a", edgecolor="none", fontsize=8)
        for t in leg2.get_texts():
            t.set_color("white")

    fig.tight_layout()
    return fig


def region_correlation_figure(region, title: str = "Region-level co-localization"):
    """タイル単位の密度相関を可視化する（散布図 + 両密度マップ）.

    Args:
        region: :class:`modules.region_analysis.RegionResult`。
        title: 図タイトル。

    Returns:
        matplotlib Figure。
    """
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 3, figsize=(15, 4.4))
    fig.patch.set_facecolor("#1e1e1e")
    for ax in axes:
        ax.set_facecolor("#1e1e1e")
        ax.tick_params(colors="white")

    # 散布図: A 密度 vs B 密度
    ax = axes[0]
    if region.a_density.size:
        ax.scatter(region.a_density, region.b_density, c="#00e0ff", s=18, alpha=0.8,
                   edgecolors="white", linewidths=0.3)
    ax.set_xlabel(f"{region.marker_a} density (cells/mm2)", color="white")
    ax.set_ylabel(f"{region.marker_b} density (cells/mm2)", color="white")
    r_txt = ("r=nan" if region.pearson_r != region.pearson_r
             else f"r={region.pearson_r:.3f}, rho={region.spearman_rho:.3f}")
    ax.set_title(f"{title}\n{r_txt} (n={region.n_tiles} tiles, {region.tile_um:.0f}um)",
                 color="white", fontsize=9, loc="left")
    ax.grid(alpha=0.2)

    # 密度マップ A / B
    for ax, dmap, name, cmap in (
        (axes[1], region.a_density_map, region.marker_a, "Reds"),
        (axes[2], region.b_density_map, region.marker_b, "Greens"),
    ):
        im = ax.imshow(dmap, cmap=cmap, interpolation="nearest")
        ax.set_title(f"{name} positive density", color="white", fontsize=9, loc="left")
        ax.set_xticks([]); ax.set_yticks([])
        cb = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
        cb.ax.tick_params(colors="white")

    fig.tight_layout()
    return fig
