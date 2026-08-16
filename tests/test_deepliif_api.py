"""``modules.deepliif`` の単体テスト.

mock モードの出力妥当性と、api モードが公式 deepliif.org 形式
（base64 の images + scoring）を正しくパースし、色分け Seg から
陽性/陰性核を判定できることを検証する。ネットワークは requests.post を
モックして遮断する。
"""
from __future__ import annotations

import base64
import io
from unittest import mock

import numpy as np
import pytest
from PIL import Image
from skimage.measure import regionprops

from modules.deepliif import DeepLIIFRunner


def _b64png(arr: np.ndarray) -> str:
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def _fake_response() -> dict:
    """DAPI/Marker と、赤=陽性2核・青=陰性3核の色分け Seg を持つ疑似応答。"""
    h = w = 128
    dapi = (np.random.rand(h, w) * 255).astype("uint8")
    marker = np.zeros((h, w), "uint8")
    seg = np.zeros((h, w, 3), "uint8")
    for (y0, x0) in ((20, 20), (80, 80)):  # 陽性（赤）
        seg[y0:y0 + 15, x0:x0 + 15] = (255, 0, 0)
        marker[y0:y0 + 15, x0:x0 + 15] = 240
    for (y0, x0) in ((20, 80), (60, 30), (95, 40)):  # 陰性（青）
        seg[y0:y0 + 15, x0:x0 + 15] = (0, 0, 255)
    return {
        "images": {"DAPI": _b64png(dapi), "Marker": _b64png(marker), "Seg": _b64png(seg)},
        "scoring": {"percent_positive": 40},
    }


class _FakeResp:
    status_code = 200

    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:  # noqa: D401
        return None

    def json(self) -> dict:
        return self._payload


def test_api_parses_official_response() -> None:
    """公式形式の応答から 5 核・陽性 2 核・信頼度 0.40 を復元する。"""
    payload = _fake_response()
    rgb = (np.random.rand(128, 128, 3) * 255).astype("uint8")
    with mock.patch("requests.post", return_value=_FakeResp(payload)) as m:
        res = DeepLIIFRunner(mode="api", api_url="https://deepliif.org/api/infer").run(rgb)

    # 送信パラメータの確認（resolution が付与される）
    _, kwargs = m.call_args
    assert kwargs["params"]["resolution"] == "40x"
    assert "img" in kwargs["files"]

    n_labels = len(np.unique(res.seg)) - 1
    pos = sum(1 for p in regionprops(res.seg)
              if res.positive_mask[res.seg == p.label].any())
    assert n_labels == 5
    assert pos == 2
    assert abs(res.confidence - 0.40) < 1e-6


def test_api_seg_only_response_does_not_fall_back_to_mock() -> None:
    """実際の deepliif.org 応答（Seg / SegOverlaid / SegRefined のみ）を処理できる.

    クラウド API は既定で DAPI・Marker を返さない。それでも mock に落ちず、
    SegRefined から核と陽性/陰性を復元し、DAPI/Marker は元 IHC の色分離で
    補完されることを確認する（本番で mock 降下していた不具合の回帰テスト）。
    """
    h = w = 128
    seg_refined = np.zeros((h, w, 3), "uint8")
    seg_overlaid = np.full((h, w, 3), 128, "uint8")   # 選ばれてはいけない
    seg_plain = np.zeros((h, w, 3), "uint8")          # SegRefined を優先すべき
    for (y0, x0) in ((20, 20), (80, 80)):             # 陽性（赤）2 核
        seg_refined[y0:y0 + 15, x0:x0 + 15] = (255, 0, 0)
    for (y0, x0) in ((20, 80), (60, 30), (95, 40)):   # 陰性（青）3 核
        seg_refined[y0:y0 + 15, x0:x0 + 15] = (0, 0, 255)

    payload = {
        "deepliifVersion": "1.2.6",
        "images": {
            "Seg": _b64png(seg_plain),
            "SegOverlaid": _b64png(seg_overlaid),
            "SegRefined": _b64png(seg_refined),
        },
        "scoring": {"num_pos": 46, "num_neg": 48, "num_total": 94, "percent_pos": 48.9},
    }
    rgb = (np.random.rand(h, w, 3) * 255).astype("uint8")
    with mock.patch("requests.post", return_value=_FakeResp(payload)):
        res = DeepLIIFRunner(mode="api").run(rgb)

    assert not res.used_mock, "Seg のみの応答でも mock に落ちてはいけない"
    n_labels = len(np.unique(res.seg)) - 1
    pos = sum(1 for p in regionprops(res.seg)
              if res.positive_mask[res.seg == p.label].any())
    assert n_labels == 5, f"SegRefined を使うべき (labels={n_labels})"
    assert pos == 2
    # DAPI/Marker は元 IHC から補完され、入力と同サイズのグレースケール
    assert res.dapi.shape == (h, w)
    assert res.marker.shape == (h, w)
    # scoring の percent_pos から confidence を得る
    assert abs(res.confidence - 0.489) < 1e-3


def test_api_error_field_falls_back_to_mock() -> None:
    """200 でも error フィールドがあれば mock にフォールバックする。"""
    payload = {"error": "image too large"}
    rgb = (np.random.rand(64, 64, 3) * 255).astype("uint8")
    with mock.patch("requests.post", return_value=_FakeResp(payload)):
        res = DeepLIIFRunner(mode="api").run(rgb)
    assert res.used_mock


def test_api_missing_images_falls_back_to_mock() -> None:
    """必要画像が欠けた応答では mock にフォールバックし、例外を投げない。"""
    payload = {"images": {}, "scoring": {}}
    rgb = (np.random.rand(64, 64, 3) * 255).astype("uint8")
    with mock.patch("requests.post", return_value=_FakeResp(payload)):
        res = DeepLIIFRunner(mode="api").run(rgb)
    # mock 由来でも DeepLIIFResult の形は満たす
    assert res.dapi.shape == (64, 64)
    assert res.seg.shape == (64, 64)


def test_mock_outputs_shapes() -> None:
    """mock モードは入力と同サイズの DAPI/Marker/Seg を返す。"""
    rgb = (np.random.rand(96, 96, 3) * 255).astype("uint8")
    res = DeepLIIFRunner(mode="mock").run(rgb)
    assert res.dapi.shape == (96, 96)
    assert res.marker.shape == (96, 96)
    assert res.seg.shape == (96, 96)
    assert res.positive_mask.dtype == bool


def test_run_rejects_non_rgb() -> None:
    """非 RGB 入力は明確に例外。"""
    with pytest.raises(ValueError):
        DeepLIIFRunner(mode="mock").run(np.zeros((10, 10), "uint8"))
