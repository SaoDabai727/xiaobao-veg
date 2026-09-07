# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 规格：生成单文件 dist/小宝蔬菜汇总.exe（依赖已内置）。"""

from PyInstaller.utils.hooks import collect_all, collect_data_files

datas = []
binaries = []
hiddenimports = [
    "customtkinter",
    "openpyxl",
    "PIL",
    "numpy",
    "rapidocr",
    "onnxruntime",
    "cv2",
    "pyclipper",
    "shapely",
    "omegaconf",
    "tksheet",
]

for pkg in ("rapidocr", "onnxruntime", "customtkinter", "opencv_python", "tksheet"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        pass

try:
    datas += collect_data_files("customtkinter")
except Exception:
    pass

a = Analysis(
    ["run.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="小宝蔬菜汇总",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
