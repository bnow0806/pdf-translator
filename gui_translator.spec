# -*- mode: python ; coding: utf-8 -*-
import os
import tkinterdnd2
import customtkinter
from PyInstaller.utils.hooks import collect_all

dnd2_path = os.path.dirname(tkinterdnd2.__file__)
ctk_path  = os.path.dirname(customtkinter.__file__)

numpy_datas,    numpy_binaries,    numpy_hiddens    = collect_all('numpy')
cv2_datas,      cv2_binaries,      cv2_hiddens      = collect_all('cv2')
pdf2docx_datas, pdf2docx_binaries, pdf2docx_hiddens = collect_all('pdf2docx')
fitz_datas,     fitz_binaries,     fitz_hiddens     = collect_all('fitz')

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
        (ctk_path,  'customtkinter'),
        *numpy_datas,
        *cv2_datas,
        *pdf2docx_datas,
        *fitz_datas,
    ],
    hiddenimports=[
        'tkinterdnd2',
        'tkinterdnd2.TkinterDnD',
        'customtkinter',
        'darkdetect',
        'deep_translator',
        'pdf2docx',
        *pdf2docx_hiddens,
        'docx',
        'docx.oxml',
        'docx.oxml.ns',
        'lxml',
        'lxml.etree',
        'lxml._elementpath',
        'fitz',
        *fitz_hiddens,
        *numpy_hiddens,
        *cv2_hiddens,
        'win32com',
        'win32com.client',
        'pythoncom',
        'pywintypes',
        'PIL',
        'PIL.Image',
        'certifi',
        'charset_normalizer',
        'requests',
        'concurrent.futures',
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
    upx_exclude=['numpy', 'cv2', 'fitz', '_fitz'],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
