# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['pdf_translator.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        # deepl
        'deepl',
        'deepl.translator',
        'deepl.exceptions',
        # pdfplumber
        'pdfplumber',
        'pdfminer',
        'pdfminer.high_level',
        'pdfminer.layout',
        'pdfminer.pdfpage',
        'pdfminer.pdfinterp',
        'pdfminer.converter',
        'pdfminer.pdfdocument',
        'pdfminer.pdfparser',
        'pypdfium2',
        # fpdf2
        'fpdf',
        'fpdf.fpdf',
        'fpdf.fonts',
        'fpdf.image_parsing',
        'fonttools',
        'fonttools.ttLib',
        # misc
        'PIL',
        'PIL.Image',
        'cryptography',
        'certifi',
        'charset_normalizer',
    ],
    excludes=[
        'tkinter',
        'matplotlib',
        'numpy',
        'scipy',
        'pandas',
        'IPython',
        'jupyter',
        'notebook',
    ],
    noarchive=False,
    optimize=2,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='pdf-translator',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,          # CLI 도구이므로 콘솔 창 사용
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
