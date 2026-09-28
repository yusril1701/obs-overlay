# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for OBS Overlay (Windows, one-dir).

Build with:  pyinstaller packaging/ObsOverlay.spec --noconfirm
or:          powershell -ExecutionPolicy Bypass -File packaging/build.ps1

Deliberate choices
------------------
one-dir, not one-file
    One-file re-extracts ~150 MB of Qt to %TEMP% on every launch — seconds of
    cold-start lag, and the single biggest trigger for antivirus heuristics.
    Ship the folder (inside an installer if you want a single download).

upx=False
    PyInstaller skips UPX for CFG-enabled DLLs and Qt plugins, but not for
    Qt6Core/Qt6Gui/Qt6Widgets or VCRUNTIME. Compressed Qt core DLLs have a long
    history of silent crashes, and UPX packing is itself a strong AV signal.

no collect_all('PyQt6')
    The per-module hooks already collect the platform plugin (qwindows.dll),
    imageformats, iconengines and styles. collect_all would drag in
    QtWebEngineCore and add roughly a quarter of a gigabyte for nothing.

no DPI manifest
    Qt 6 sets DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 itself. An embedded
    manifest declaring dpiAware makes Qt's own call fail with ACCESS_DENIED and
    silently drops the app to system-aware, which renders the overlay blurry on
    a secondary monitor with different scaling.
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

SPEC_DIR = Path(SPECPATH).resolve()
PROJECT_ROOT = SPEC_DIR.parent

APP_NAME = "ObsOverlay"
ENTRY_POINT = str(PROJECT_ROOT / "src" / "obs_overlay" / "__main__.py")
ICON_PATH = PROJECT_ROOT / "packaging" / "obs-overlay.ico"
VERSION_FILE = PROJECT_ROOT / "packaging" / "version_info.txt"

hiddenimports = [
    # Submodules of the SpoutGL C extension, invisible to static analysis.
    "SpoutGL",
    "SpoutGL.enums",
    "SpoutGL.helpers",
    # No PyInstaller hook covers this one, and pywin32 reaches for it the first
    # time it converts a datetime — a runtime failure, not a build failure.
    "win32timezone",
]
hiddenimports += collect_submodules("obs_overlay")

# Everything that would only bloat the bundle. PyQt5/PySide are listed because
# PyInstaller >= 6.5 aborts the build outright if hooks for two Qt bindings run.
excludes = [
    "PyQt5",
    "PySide2",
    "PySide6",
    "shiboken2",
    "shiboken6",
    "tkinter",
    "matplotlib",
    "scipy",
    "pandas",
    "IPython",
    "jupyter",
    "notebook",
    "pytest",
    "setuptools",
    "pip",
    "PyQt6.QtWebEngineCore",
    "PyQt6.QtWebEngineWidgets",
    "PyQt6.QtQml",
    "PyQt6.QtQuick",
    "PyQt6.Qt3DCore",
    "PyQt6.QtBluetooth",
    "PyQt6.QtDesigner",
    "PyQt6.QtMultimedia",
    "PyQt6.QtCharts",
    "PyQt6.QtDataVisualization",
    "PyQt6.QtPositioning",
    "PyQt6.QtSerialPort",
    "PyQt6.QtSql",
    "PyQt6.QtTest",
]

a = Analysis(
    [ENTRY_POINT],
    pathex=[str(PROJECT_ROOT / "src")],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[str(PROJECT_ROOT / "packaging" / "hooks")],
    hooksconfig={},
    runtime_hooks=[str(PROJECT_ROOT / "packaging" / "hooks" / "rthook_spoutgl.py")],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # console=False is what makes this a windowed app: no console window
    # flashes up on launch. Diagnostics go to the rotating log file instead.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ICON_PATH) if ICON_PATH.is_file() else None,
    version=str(VERSION_FILE) if VERSION_FILE.is_file() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=APP_NAME,
)
