"""設定管理モジュール.

Tile Size・DeepLIIF 実行方法・Registration Method・Matching Distance・色設定・
自動保存などのアプリ設定を保持し、ユーザーごとの設定ディレクトリへ JSON で
永続化する。設定ディレクトリは OS 標準の場所を用い、``pathlib`` で扱うことで
Windows / macOS の差異を吸収する。
"""
from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

APP_NAME = "VirtualMultiplexAnalyzer"


def user_config_dir() -> Path:
    """OS 標準のユーザー設定ディレクトリを返す（存在しなければ作成）。

    * Windows: ``%APPDATA%\\VirtualMultiplexAnalyzer``
    * macOS  : ``~/Library/Application Support/VirtualMultiplexAnalyzer``
    * Linux  : ``~/.config/VirtualMultiplexAnalyzer``
    """
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    path = base / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass
class AppSettings:
    """アプリ全体の設定値.

    仕様書「設定」節に対応。すべて JSON へシリアライズ可能な素の型で保持する。
    """

    tile_size: int = 2048
    deepliif_mode: str = "api"  # api（既定）/ local / mock（内部フォールバック）
    deepliif_api_url: str = "https://deepliif.org/api/infer"
    deepliif_model_dir: str = ""      # local モードのシリアライズ済みモデルディレクトリ
    deepliif_tile_size: int = 512     # 40x=512, 20x=256, 10x=128 が公式推奨
    deepliif_resolution: str = "40x"  # api モードの resolution (10x/20x/40x)
    registration_method: str = "rigid+affine+bspline"
    registration_scale: float = 0.5  # 変換推定の縮小率（0.5=1/2, 高速化）
    region_tile_um: float = 100.0     # 領域レベル解析のタイル1辺[μm]
    show_dapi_channel: bool = True    # Pseudo DAPI（ヘマトキシリン=全核, 青）を重畳
    color_dapi: list = field(default_factory=lambda: [0, 120, 255])
    matching_distance_um: float = 10.0
    color_a: list = field(default_factory=lambda: [0, 255, 0])   # 例: Ki67 -> Green
    color_b: list = field(default_factory=lambda: [255, 0, 0])   # 例: p53  -> Red
    marker_a: str = "Ki67"
    marker_b: str = "p53"
    theme: str = "dark"  # dark / light
    autosave: bool = True
    autosave_interval_sec: int = 300
    recent_files: list = field(default_factory=list)
    max_recent: int = 10
    thumbnail_size: int = 1024

    # ------------------------------------------------------------------
    def add_recent(self, path: str) -> None:
        """最近使ったファイルへ追加（重複排除・件数制限）。"""
        p = str(path)
        if p in self.recent_files:
            self.recent_files.remove(p)
        self.recent_files.insert(0, p)
        del self.recent_files[self.max_recent :]

    # ------------------------------------------------------------------
    @classmethod
    def config_path(cls) -> Path:
        """設定 JSON のフルパス。"""
        return user_config_dir() / "settings.json"

    @classmethod
    def load(cls, path: "Path | None" = None) -> "AppSettings":
        """設定を読み込む。存在しなければ既定値を返す。

        Args:
            path: 読み込む JSON パス。``None`` なら OS 標準の設定パス
                （:meth:`config_path`）を用いる。テスト時に一時パスを渡せる。
        """
        path = Path(path) if path is not None else cls.config_path()
        if not path.exists():
            logger.info("設定ファイルが無いため既定値を使用: %s", path)
            return cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            known = {f for f in cls().__dataclass_fields__}  # type: ignore[attr-defined]
            filtered = {k: v for k, v in data.items() if k in known}
            return cls(**filtered)
        except Exception as exc:  # noqa: BLE001
            logger.warning("設定読込に失敗、既定値を使用: %s", exc)
            return cls()

    def save(self, path: "Path | None" = None) -> Path:
        """設定を JSON へ保存し、パスを返す。

        Args:
            path: 保存先。``None`` なら OS 標準の設定パスを用いる。
        """
        path = Path(path) if path is not None else self.config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8"
        )
        logger.debug("設定保存: %s", path)
        return path
