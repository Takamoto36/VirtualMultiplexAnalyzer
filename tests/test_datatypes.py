"""``modules.datatypes`` と ``config.settings`` の単体テスト.

データ構造の派生プロパティ（mpp・circularity 保持・ROI 命名）と、
設定の保存/読込ラウンドトリップを検証する。
"""
from __future__ import annotations

from pathlib import Path

from config.settings import AppSettings
from modules.datatypes import ROI, MarkerChannel, WSIMetadata
from tests.conftest import make_cell


def test_roi_auto_name() -> None:
    """name 未指定なら ROI_<id> が自動採番される。"""
    roi = ROI(x=10, y=20, width=30, height=40)
    assert roi.name.startswith("ROI_")
    assert roi.bounds == (10, 20, 30, 40)


def test_roi_as_dict() -> None:
    """as_dict に座標キーが揃う。"""
    roi = ROI(0, 0, 5, 5, name="tumor")
    d = roi.as_dict()
    assert d["name"] == "tumor"
    assert d["width"] == 5 and d["height"] == 5


def test_metadata_mpp_average() -> None:
    """mpp は縦横の平均を返す。"""
    meta = WSIMetadata("a.ndpi", 100, 100, mpp_x=0.4, mpp_y=0.6)
    assert abs(meta.mpp - 0.5) < 1e-9


def test_metadata_mpp_none() -> None:
    """mpp 未知なら None。"""
    meta = WSIMetadata("a.ndpi", 100, 100)
    assert meta.mpp is None


def test_cell_as_row_positive_int() -> None:
    """as_row の positive は 0/1 の int。"""
    row = make_cell(1, 2, positive=True, marker=MarkerChannel.KI67).as_row()
    assert row["positive"] == 1
    assert row["marker"] == "Ki67"
    assert row["centroid_x"] == 1


def test_settings_roundtrip(tmp_path: Path) -> None:
    """AppSettings の保存→読込で値が保たれる。"""
    cfg = AppSettings()
    cfg.matching_distance_um = 7.5
    cfg.marker_a = "ER"
    cfg.add_recent("/data/sample.ndpi")

    path = tmp_path / "settings.json"
    cfg.save(path)
    loaded = AppSettings.load(path)

    assert loaded.matching_distance_um == 7.5
    assert loaded.marker_a == "ER"
    assert "/data/sample.ndpi" in loaded.recent_files


def test_settings_recent_dedup_and_limit(tmp_path: Path) -> None:
    """最近使ったファイルは重複排除され先頭に来る。"""
    cfg = AppSettings()
    cfg.add_recent("/a.ndpi")
    cfg.add_recent("/b.ndpi")
    cfg.add_recent("/a.ndpi")  # 再追加で先頭へ
    assert cfg.recent_files[0] == "/a.ndpi"
    assert cfg.recent_files.count("/a.ndpi") == 1
