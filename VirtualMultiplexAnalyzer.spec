# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller ビルド定義（主に Windows 11 向け）.

使い方::

    pip install pyinstaller
    pyinstaller VirtualMultiplexAnalyzer.spec

生成物は ``dist/VirtualMultiplexAnalyzer/`` 以下に出力される。単一 EXE 化したい
場合は下部の ``EXE(...)`` の ``exclude_binaries`` を False にし、COLLECT を外す
（one-file 化。ただし起動は遅くなる）。

注意:
    OpenSlide のネイティブ DLL は Python パッケージに含まれない。Windows では
    OpenSlide 配布の ``bin`` フォルダを PATH に通すか、``binaries`` に追加して
    同梱する必要がある（README「配布」節を参照）。
"""
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

block_cipher = None

# 動的インポートされがちなパッケージを明示収集
hiddenimports = []
for pkg in ("skimage", "scipy", "SimpleITK", "pptx", "openpyxl", "imageio"):
    hiddenimports += collect_submodules(pkg)

datas = []
for pkg in ("skimage", "matplotlib"):
    datas += collect_data_files(pkg)

# OpenSlide DLL を同梱する場合は下記を編集（例）:
# binaries = [(r"C:\\openslide\\bin\\*.dll", ".")]
binaries = []

a = Analysis(
    ["app.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "PyQt5", "PyQt6"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="VirtualMultiplexAnalyzer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # GUI アプリなのでコンソール非表示
    icon="icons/app.ico" if __import__("pathlib").Path("icons/app.ico").exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="VirtualMultiplexAnalyzer",
)
