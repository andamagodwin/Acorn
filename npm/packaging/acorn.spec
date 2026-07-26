# PyInstaller spec for the standalone Acorn binary.
#
# Built per platform in CI and shipped inside the per-platform npm packages, so
# `npm install -g acorn-agent` works on machines with no Python at all.
#
# Run from the repo root:  pyinstaller npm/build/acorn.spec --clean --noconfirm

from PyInstaller.utils.hooks import collect_submodules, collect_data_files

# google-genai resolves a lot of its surface lazily, and PyInstaller's static
# analysis can't see through that — without these the binary builds fine and
# then dies at runtime on the first API call.
hidden = [
    *collect_submodules("google.genai"),
    *collect_submodules("google.auth"),
    *collect_submodules("pydantic"),
    # pydantic v2 compiles its core to a binary module whose imports are opaque.
    "pydantic.deprecated.decorator",
    # Requested lazily by google-auth depending on which credential type is used.
    "google.auth.transport.requests",
    "google.auth.transport.urllib3",
    # websockets is used for the live/streaming transport.
    *collect_submodules("websockets"),
    # certifi's bundle is what our TLS fix depends on.
    "certifi",
]

# Data files: certifi ships a .pem that must travel with the binary, and
# google-genai carries version metadata it reads at import time.
datas = [
    *collect_data_files("certifi"),
    *collect_data_files("google.genai"),
]

a = Analysis(
    ["../../acorn/main.py"],
    pathex=["../.."],
    binaries=[],
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Trimming the stdlib GUI and test frameworks keeps the binary meaningfully
    # smaller; Acorn is a terminal program and never touches these.
    excludes=[
        "tkinter",
        "matplotlib",
        "PIL",
        "numpy",
        "pytest",
        "IPython",
        "test",
        "unittest",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    name="acorn",
    debug=False,
    bootloader_ignore_signals=False,
    # strip=False on macOS: stripping breaks code signatures on arm64, and an
    # unsigned/invalidly-signed binary is killed by Gatekeeper on launch.
    strip=False,
    upx=False,
    # One file, so the npm package ships a single artifact and there's no
    # extraction directory to manage.
    onefile=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
