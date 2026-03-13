# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller 打包設定

打包指令：
    pyinstaller app.spec --clean

產物位置：
    dist/契約稽核系統/
"""

import os
from PyInstaller.utils.hooks import collect_all

block_cipher = None
ROOT = os.path.abspath('.')

# ── 預先收集所有套件資料（必須在 Analysis 之前）───────────────────
# 取得 certifi 的 CA 憑證路徑（解決 Neo4j Aura SSL 連線問題）
import certifi

all_datas = [
    ('prompts/', 'prompts/'),
    ('settings.yaml', '.'),
    (certifi.where(), 'certifi/'),  # SSL CA 憑證
]
all_binaries = []
all_hiddenimports = [
    # LangChain
    'langchain_openai',
    'langchain_neo4j',
    'langchain_core.output_parsers',
    'langchain_core.runnables',
    'langchain_core.messages',
    'langchain_core.prompts',
    # OpenAI SDK
    'openai',
    'openai.resources',
    # ReportLab CJK
    'reportlab.pdfbase.cidfonts',
    'reportlab.pdfbase._fontdata',
    'reportlab.pdfbase.pdfmetrics',
    # python-docx
    'docx',
    'docx.oxml',
    # PyMuPDF (fitz)
    'fitz',
    'pymupdf',
    # tkinter
    'tkinter',
    'tkinter.ttk',
    'tkinter.filedialog',
    'tkinter.messagebox',
    'tkinter.scrolledtext',
]

# 完整收集有 C 擴展的套件
for pkg in ['graphrag', 'lancedb', 'pyarrow', 'neo4j', 'tiktoken', 'pymupdf', 'fitz', 'litellm', 'graspologic']:
    pkg_datas, pkg_binaries, pkg_hiddenimports = collect_all(pkg)
    all_datas += pkg_datas
    all_binaries += pkg_binaries
    all_hiddenimports += pkg_hiddenimports

# ── Analysis ──────────────────────────────────────────────────────
a = Analysis(
    ['app/main.py'],
    pathex=[ROOT],
    binaries=all_binaries,
    datas=all_datas,
    hiddenimports=all_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
    name='契約稽核系統',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='契約稽核系統',
)
