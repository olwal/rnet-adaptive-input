# PyInstaller spec for the rnet command-line tool.
#
#   python -m PyInstaller packaging/rnet.spec
#
# Produces a single self-contained executable so the build, flash, scope and
# HID tools can be used without installing Python. Run from the project root.
#
# What is and is not in here:
#   in   rnet, scope, hid, rnetport   (pyserial only, ~12 MB)
#   out  the marble game              (raylib + numpy + scipy, ~150 MB)
#
# The demo is excluded deliberately. Bundling a scientific stack to ship a
# game most people will not run makes the download an order of magnitude
# bigger for everyone. `rnet demo` in a packaged build reports that it needs a
# Python install rather than failing obscurely.

from pathlib import Path

# SPECPATH is set by PyInstaller to the directory holding this file.
ROOT = Path(SPECPATH).parent
TOOLS = ROOT / "tools"

a = Analysis(
    [str(TOOLS / "rnet.py")],
    pathex=[str(TOOLS)],
    binaries=[],
    datas=[],
    # rnet reaches these through importlib, so static analysis cannot see
    # them and they have to be named explicitly.
    hiddenimports=["scope", "hid", "rnetport", "serial", "serial.tools.list_ports"],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # Never used by the packaged commands, and each is large.
        "numpy", "scipy", "pygame", "raylib", "pyray", "_cffi_backend",
        "PIL", "tkinter", "matplotlib", "pytest", "setuptools", "pip",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="rnet",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX is off: it buys a few MB and is a reliable way to get flagged by
    # antivirus, which is already a problem for unsigned one-file builds.
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
