"""macOS 向け py2app ビルドスクリプト.

使い方::

    pip install py2app
    python setup_py2app.py py2app

生成物は ``dist/VirtualMultiplexAnalyzer.app``。Apple Silicon / Intel いずれの
Python でも、その Python のアーキテクチャに合わせた .app が生成される
（ユニバーサル化する場合は universal2 ビルドの Python を使用すること）。

注意:
    OpenSlide のネイティブライブラリは Homebrew 等で別途導入が必要
    （``brew install openslide``）。SimpleITK・DeepLIIF などの重い依存は
    ``includes`` / ``packages`` に必要に応じて追記する。
"""
from pathlib import Path

from setuptools import setup

APP = ["app.py"]
DATA_FILES: list = []

icon = Path("icons/app.icns")
OPTIONS = {
    "argv_emulation": False,
    "packages": [
        "PySide6",
        "numpy",
        "scipy",
        "skimage",
        "pandas",
        "matplotlib",
        "SimpleITK",
        "openpyxl",
        "pptx",
        "imageio",
        "gui",
        "modules",
        "config",
    ],
    "includes": ["cv2"],
    "excludes": ["tkinter", "PyQt5", "PyQt6"],
    "plist": {
        "CFBundleName": "Virtual Multiplex Analyzer",
        "CFBundleDisplayName": "Virtual Multiplex Analyzer",
        "CFBundleIdentifier": "com.github.takamoto36.vmpa",
        "CFBundleVersion": "0.1.0",
        "CFBundleShortVersionString": "0.1.0",
        "NSHighResolutionCapable": True,
    },
}
if icon.exists():
    OPTIONS["iconfile"] = str(icon)

setup(
    app=APP,
    name="VirtualMultiplexAnalyzer",
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
