# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Video Discusser desktop app.

Build from the repository root:
    pyinstaller --clean packaging/video-discusser.spec

Produces dist/VideoDiscusser/ (onedir — predictable startup, no temp
extraction). Ollama, model weights, and FFmpeg are deliberately NOT bundled:
they remain separate installations (roadmap Sprint 22 constraint).
"""

import os

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))

a = Analysis(
    [os.path.join(ROOT, "scripts", "desktop.py")],
    pathex=[ROOT],
    binaries=[],
    datas=[(os.path.join(ROOT, "app", "static"), "app/static")],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,
    name="VideoDiscusser",
    debug=False,
    strip=False,
    upx=False,
    console=False,  # windowed desktop app; logs go to data/logs/backend.log
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="VideoDiscusser",
)
