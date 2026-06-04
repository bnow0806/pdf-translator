# -*- mode: python ; coding: utf-8 -*-
import os
import tkinterdnd2
from PyInstaller.utils.hooks import collect_all, collect_submodules

dnd2_path = os.path.dirname(tkinterdnd2.__file__)

# numpy, cv2, pdf2docx 는 바이너리가 많아서 collect_all 로 통째로 수집
numpy_datas,   numpy_binaries,   numpy_hiddens   = collect_all('numpy')
cv2_datas,     cv2_binaries,     cv2_hiddens     = collect_all('cv2')
pdf2docx_datas,pdf2docx_binaries,pdf2docx_hiddens = collect_all('pdf2docx')
fitz_datas,    fitz_binaries,    fitz_hiddens    = collect_all('fitz')

a = Analysis(
    ['gui_translator.py'],
    pathex=[],
    binaries=[
        *numpy_binaries,
        *cv2_binaries,
        *pdf2docx_binaries,
        *fitz_binaries,
    ],
    datas=[
        (dnd2_path, 'tkinterdnd2'),
        *numpy_datas,
        *cv2_datas,
        *pdf2docx_datas,
        *fitz_datas,
    ],
    hiddenimports=[
        # tkinterdnd2
        'tkinterdnd2',
        'tkinterdnd2.TkinterDnD',
        # 번역
        'deep_translator',
        'deep_translator.google_trans',
        # PDF 처리
        'pdf2docx',
        *pdf2docx_hiddens,
        # Word 문서
        'docx',
        'docx.oxml',
        'docx.oxml.ns',
        'lxml',
        'lxml.etree',
        'lxml._elementpath',
        # MuPDF (PyMuPDF)
        'fitz',
        *fitz_hiddens,
        # numpy / cv2
        *numpy_hiddens,
        *cv2_hiddens,
        # 기타
        'PIL',
        'PIL.Image',
        'certifi',
        'charset_normalizer',
        'requests',
        'docx2pdf',
        'concurrent.futures',
        'win32com',
        'win32com.client',
        'win32com.server',
        'pythoncom',
        'pywintypes',
    ],
    excludes=[
        'IPython', 'jupyter', 'notebook',
        'matplotlib', 'scipy', 'pandas',
        'pdfplumber', 'pdfminer', 'fpdf',
        'deepl',
    ],
    noarchive=False,
    optimize=1,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='PDF-번역기',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=['numpy', 'cv2'],   # UPX가 numpy/cv2 압축 시 오류 유발 방지
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
