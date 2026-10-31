# -*- mode: python ; coding: utf-8 -*-
import os
from PyInstaller.utils.hooks import collect_all

block_cipher = None

# Base repository directory
ROOT_DIR = os.path.abspath(os.path.join(SPECPATH, '..'))

datas = [
    (os.path.join(ROOT_DIR, 'src', 'gui', 'app_icon.ico'), 'gui'),
    (os.path.join(ROOT_DIR, 'src', 'gui', 'assets', 'icons'), 'gui/assets/icons'),
    (os.path.join(ROOT_DIR, 'config.example.json'), '.'),
]

# Collect package data and submodules for dynamic Tkinter and tray dependencies
sv_ttk_datas, sv_ttk_binaries, sv_ttk_hiddenimports = collect_all('sv_ttk')
ttkwidgets_datas, ttkwidgets_binaries, ttkwidgets_hiddenimports = collect_all('ttkwidgets')
pystray_datas, pystray_binaries, pystray_hiddenimports = collect_all('pystray')

datas += sv_ttk_datas + ttkwidgets_datas + pystray_datas
binaries = sv_ttk_binaries + ttkwidgets_binaries + pystray_binaries

hiddenimports = [
    'PIL',
    'PIL._tkinter_finder',
    'pystray',
    'pystray._win32',
    'openpyxl',
    'xlsxwriter',
    'pathspec',
    'sqlite3',
] + sv_ttk_hiddenimports + ttkwidgets_hiddenimports + pystray_hiddenimports

a = Analysis(
    [os.path.join(ROOT_DIR, 'launch.pyw')],
    pathex=[os.path.join(ROOT_DIR, 'src')],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['IPython', 'ipykernel', 'pytest'],
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
    name='FastMirror',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(ROOT_DIR, 'src', 'gui', 'app_icon.ico'),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='FastMirror',
)

