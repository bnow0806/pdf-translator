#!/usr/bin/env python3
"""PDF 번역기 — 포맷 보존 · 진행률 표시 · PDF 출력"""

import sys, os, json, threading, time, tempfile
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

if sys.platform == "win32":
    import ctypes
    ctypes.windll.kernel32.SetConsoleOutputCP(65001)
    ctypes.windll.kernel32.SetConsoleCP(65001)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    HAS_DND = True
except ImportError:
    HAS_DND = False

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

# ── 설정 ──────────────────────────────────────────────────────────────────────
CONFIG_FILE = Path.home() / ".pdf_translator_config.json"

LANGUAGES = [
    ("ko","한국어"), ("en","영어"), ("ja","일본어"),
    ("zh-CN","중국어(간체)"), ("zh-TW","중국어(번체)"),
    ("de","독일어"), ("fr","프랑스어"), ("es","스페인어"),
    ("it","이탈리아어"), ("pt","포르투갈어"), ("ru","러시아어"),
    ("vi","베트남어"), ("th","태국어"), ("id","인도네시아어"),
]

# ── 라이트 테마 ───────────────────────────────────────────────────────────────
C = {
    "bg":       "#ffffff",
    "surface":  "#f5f5f5",
    "border":   "#d0d0d0",
    "entry":    "#f9f9f9",
    "fg":       "#1a1a1a",
    "subtle":   "#777777",
    "accent":   "#0078d4",
    "accent_h": "#005fa3",
    "green":    "#107c10",
    "red":      "#c50f1f",
    "yellow":   "#835c00",
    "drop":     "#eef4ff",
    "drop_hl":  "#d4e8ff",
    "drop_bd":  "#0078d4",
    "bar_bg":   "#e0e0e0",
    "bar_fg":   "#0078d4",
}

# ─────────────────────────────────────────────────────────────────────────────
def load_config():
    try:
        if CONFIG_FILE.exists():
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}

def save_config(data):
    CONFIG_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def normalize_drop(raw):
    p = raw.strip()
    if p.startswith("{") and p.endswith("}"):
        p = p[1:-1]
    return p.strip('"').strip("'")

# ── 번역 엔진 ─────────────────────────────────────────────────────────────────
SEP       = "\n◆◆◆\n"   # 번역 후에도 살아남는 구분자
MAX_CHARS = 4800          # Google Translate 단일 요청 한도
WORKERS   = 6             # 병렬 요청 수


def _gt(source: str, target: str):
    from deep_translator import GoogleTranslator
    return GoogleTranslator(source=source, target=target)


def _safe_translate(text: str, source: str, target: str) -> str:
    """단일 텍스트 번역. 실패·None 시 원문 반환."""
    if not text or not text.strip():
        return text
    try:
        r = _gt(source, target).translate(text)
        return r if isinstance(r, str) and r else text
    except Exception:
        return text


def _translate_joined(items: list, source: str, target: str) -> list:
    """
    items: [(global_idx, text), ...]
    여러 단락을 SEP으로 합쳐 1회 API 호출로 번역.
    구분자가 깨지면 절반씩 재귀 분할.
    어떤 상황에서도 len(items) 길이의 리스트 반환.
    """
    if not items:
        return []

    idxs  = [i for i, _ in items]
    texts = [t if isinstance(t, str) else "" for _, t in items]

    # 여러 단락 → SEP 구분 → 1회 요청
    if len(texts) > 1:
        try:
            joined = SEP.join(texts)
            raw    = _gt(source, target).translate(joined)
            if isinstance(raw, str) and raw:
                parts = raw.split(SEP)
                if len(parts) == len(texts):
                    return list(zip(idxs, parts))
        except Exception:
            pass

    # 단일 항목 처리
    if len(items) == 1:
        return [(idxs[0], _safe_translate(texts[0], source, target))]

    # 구분자 불일치 → 절반씩 재귀
    mid = len(items) // 2
    left  = _translate_joined(items[:mid], source, target)
    right = _translate_joined(items[mid:], source, target)
    return left + right


def _build_chunks(non_empty: list) -> list:
    """MAX_CHARS 이하가 되도록 단락 묶음 생성"""
    chunks, cur, cur_len = [], [], 0
    sep_len = len(SEP)
    for item in non_empty:
        text     = item[1] if isinstance(item[1], str) else ""
        text_len = len(text)
        extra    = sep_len if cur else 0
        if cur_len + extra + text_len > MAX_CHARS and cur:
            chunks.append(cur)
            cur, cur_len = [item], text_len
        else:
            cur.append(item)
            cur_len += extra + text_len
    if cur:
        chunks.append(cur)
    return chunks


def translate_paragraphs_parallel(all_texts, source, target, progress_cb, cancel):
    """all_texts: list[str] → list[str]  (순서 보존, 병렬 고속)"""
    # None·비문자열 방어
    safe_texts = [t if isinstance(t, str) else "" for t in all_texts]
    result     = list(safe_texts)
    non_empty  = [(i, t) for i, t in enumerate(safe_texts) if t.strip()]
    if not non_empty:
        return result

    chunks = _build_chunks(non_empty)
    total  = len(non_empty)
    done   = 0
    lock   = threading.Lock()

    def do_chunk(chunk):
        nonlocal done
        if cancel.is_set():
            return
        try:
            pairs = _translate_joined(chunk, source, target)
        except Exception:
            # 어떤 오류도 원문으로 폴백
            pairs = [(i, t) for i, t in chunk]
        if not pairs:
            pairs = [(i, t) for i, t in chunk]
        with lock:
            for idx, text in pairs:
                result[idx] = text if isinstance(text, str) else safe_texts[idx]
            done += len(chunk)
            progress_cb(done, total)

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futures = [ex.submit(do_chunk, c) for c in chunks]
        for f in as_completed(futures):
            if cancel.is_set():
                break
            try:
                f.result()
            except Exception:
                pass  # 개별 청크 실패는 무시 (원문 유지됨)

    return result


# 전자책 폰트 구성
# - 본문(작은 글씨): 바탕  — 세리프, 긴 텍스트 가독성 최적
# - 제목(큰 글씨/굵게): 맑은 고딕 — 깔끔한 산세리프, 시각적 구분
FONT_BODY    = "바탕"
FONT_HEADING = "맑은 고딕"
HEADING_PT   = 16   # 16pt 이상만 제목 폰트 (본문 최대 ~13pt, 실제 제목 16pt~)


def _set_run_font(run, font_name: str):
    """run의 ascii·hAnsi·eastAsia·cs 폰트를 모두 같은 값으로 설정."""
    from docx.oxml.ns import qn
    run.font.name = font_name
    rPr    = run._r.get_or_add_rPr()
    rFonts = rPr.get_or_add_rFonts()
    for attr in ("w:ascii", "w:hAnsi", "w:eastAsia", "w:cs"):
        rFonts.set(qn(attr), font_name)


def _pick_font(para) -> str:
    """
    단락의 폰트를 결정한다.
      - 최대 글씨 크기 >= HEADING_PT(16pt) → 제목 폰트 (맑은 고딕)
      - 나머지 → 본문 폰트 (바탕)
    bold 여부는 판단에서 제외: 본문 내 굵은 글씨도 바탕 유지.
    """
    runs = para.runs
    if not runs:
        return FONT_BODY

    # EMU → pt 변환 (1pt = 12700 EMU)
    sizes_pt = [r.font.size / 12700 for r in runs if r.font.size]
    max_pt   = max(sizes_pt) if sizes_pt else 12.0

    return FONT_HEADING if max_pt >= HEADING_PT else FONT_BODY


MIN_BODY_PT      = 9     # 본문 최소 폰트 크기 (pt)
LINE_SPACING     = 1.2   # 줄 간격 배율
BODY_SPACE_AFTER = 0     # 본문 단락 후 여백 pt
HEAD_SPACE_AFTER = 4     # 제목 단락 후 여백 pt
HEAD_SPACE_BEFORE= 3     # 제목 단락 전 여백 pt

import re as _re
# 각주 마커 패턴: 단어·구두점 바로 뒤에 공백 없이 붙은 1~3자리 숫자
# 예) "사망했습니다.7" → "7" 감지 / "10%" → 미감지
_FOOTNOTE_RE = _re.compile(r'(?<=[^\s\d])(\d{1,3})(?!\d)')


def _split_footnotes(run, font_name: str, font_size_emu: int | None):
    """
    run.text 안에서 각주 숫자를 찾아 위첨자 run으로 분리한다.
    원본 run의 텍스트는 비우고, 단락에 새 run들을 추가해 교체한다.
    """
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    para = run._r.getparent()   # <w:p> 요소
    text = run.text
    parts = _FOOTNOTE_RE.split(text)   # [normal, num, normal, num, ...]
    if len(parts) == 1:
        return   # 각주 없음 → 변경 불필요

    # 원본 run의 rPr(서식 정보) 복사 — 폰트·크기 기준으로 사용
    base_rpr = run._r.find(qn("w:rPr"))

    # 원본 run 비우기 (나중에 첫 normal 텍스트를 넣을 것)
    run.text = ""

    def _make_rpr(superscript=False):
        """새 run에 붙일 rPr 생성"""
        rpr = OxmlElement("w:rPr")
        # 폰트 설정
        rFonts = OxmlElement("w:rFonts")
        for attr in ("w:ascii", "w:hAnsi", "w:eastAsia", "w:cs"):
            rFonts.set(qn(attr), font_name)
        rpr.append(rFonts)
        # 크기 설정
        if font_size_emu:
            sz_val = str(int(font_size_emu / 12700 * 2))   # half-pt
            for tag in ("w:sz", "w:szCs"):
                el = OxmlElement(tag)
                el.set(qn("w:val"), sz_val)
                rpr.append(el)
        # 위첨자
        if superscript:
            va = OxmlElement("w:vertAlign")
            va.set(qn("w:val"), "superscript")
            rpr.append(va)
        return rpr

    # 원본 run 바로 뒤에 새 run들을 삽입
    insert_after = run._r

    def _insert_run(txt, is_sup):
        r_el = OxmlElement("w:r")
        r_el.append(_make_rpr(superscript=is_sup))
        t_el = OxmlElement("w:t")
        t_el.text = txt
        if txt.startswith(" ") or txt.endswith(" "):
            t_el.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        r_el.append(t_el)
        insert_after.addnext(r_el)
        return r_el

    # parts = [normal₀, num₁, normal₂, num₃, ...]  역순으로 삽입
    for part in reversed(parts):
        if not part:
            continue
        is_sup = bool(_FOOTNOTE_RE.fullmatch(part))
        insert_after = _insert_run(part, is_sup)


def apply_translations(doc, items, translated):
    """
    번역 텍스트를 단락 첫 번째 run에 적용.
    - 각주 숫자를 위첨자(superscript)로 분리
    - 본문: bold 제거 + 크기 1pt 축소
    - 줄 간격: LINE_SPACING 배율 적용
    """
    from docx.enum.text import WD_LINE_SPACING

    for (para, _), new_text in zip(items, translated):
        if not para.text.strip() or not para.runs:
            continue

        first      = para.runs[0]
        first.text = new_text or para.text
        font_name  = _pick_font(para)
        _set_run_font(first, font_name)

        if font_name == FONT_BODY:
            first.bold = False
            if first.font.size:
                size_pt     = first.font.size / 12700
                new_size_pt = max(MIN_BODY_PT, size_pt - 2)
                first.font.size = int(new_size_pt * 12700)

        # 나머지 run 비우기
        for run in para.runs[1:]:
            run.text = ""

        # 각주 숫자를 위첨자 run으로 분리
        _split_footnotes(first, font_name, first.font.size)

        # 줄 간격 · 단락 여백 설정 (ref_design 기준)
        from docx.shared import Pt as _Pt
        fmt = para.paragraph_format
        fmt.line_spacing      = LINE_SPACING
        fmt.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
        if font_name == FONT_BODY:
            fmt.space_after  = _Pt(BODY_SPACE_AFTER)
            fmt.space_before = None
        else:
            fmt.space_before = _Pt(HEAD_SPACE_BEFORE)
            fmt.space_after  = _Pt(HEAD_SPACE_AFTER)


def _word_to_pdf(docx_abs: str, pdf_abs: str) -> bool:
    """win32com으로 Word를 호출해 PDF 저장. 성공하면 True."""
    import pythoncom
    import win32com.client as wc

    pythoncom.CoInitialize()
    word = None
    doc  = None
    try:
        word = wc.Dispatch("Word.Application")
        word.Visible        = False
        word.DisplayAlerts  = 0   # 모든 팝업·대화상자 억제 (wdAlertsNone)
        word.AutomationSecurity = 3   # 매크로 비활성화

        doc = word.Documents.Open(
            docx_abs,
            False,   # ConfirmConversions
            True,    # ReadOnly
            False,   # AddToRecentFiles
        )
        # ExportAsFixedFormat : Word 2007+ PDF 전용 메서드 (SaveAs보다 안정적)
        doc.ExportAsFixedFormat(
            OutputFileName=pdf_abs,
            ExportFormat=17,          # wdExportFormatPDF
            OpenAfterExport=False,
            OptimizeFor=0,            # wdExportOptimizeForPrint
            Range=0,                  # wdExportAllDocument
            Item=0,                   # wdExportDocumentContent
            IncludeDocProps=True,
            KeepIRM=True,
            CreateBookmarks=0,        # wdExportCreateNoBookmarks
            DocStructureTags=True,
            BitmapMissingFonts=True,
            UseISO19005_1=False,
        )
        return True
    finally:
        if doc is not None:
            try: doc.Close(0)          # 0 = wdDoNotSaveChanges
            except Exception: pass
        if word is not None:
            try: word.Quit(0)
            except Exception: pass
        try: pythoncom.CoUninitialize()
        except Exception: pass


def _docx_to_pdf(docx_path: str, pdf_path: str, log):
    """DOCX → PDF. Word(타임아웃 5분) → LibreOffice → DOCX 폴백 순서로 시도."""
    docx_abs = os.path.abspath(docx_path)
    pdf_abs  = os.path.abspath(pdf_path)

    # ── 방법 1: Microsoft Word (별도 스레드 + 5분 타임아웃) ──────────────────
    log("  Word로 PDF 변환 중...  (문서 크기에 따라 수 초~수 분 소요될 수 있습니다)", "warn")
    success  = threading.Event()
    err_box  = [None]

    def _run_word():
        try:
            if _word_to_pdf(docx_abs, pdf_abs):
                success.set()
        except Exception as e:
            err_box[0] = e

    t = threading.Thread(target=_run_word, daemon=True)
    t.start()
    t.join(timeout=300)   # 5분 대기

    if success.is_set():
        log("  PDF 저장 완료", "ok")
        return

    if t.is_alive():
        log("  Word가 응답하지 않아 강제 종료합니다...", "warn")
        # Word 프로세스 강제 종료
        try:
            import subprocess
            subprocess.run(["taskkill", "/f", "/im", "WINWORD.EXE"],
                           capture_output=True)
        except Exception:
            pass
    else:
        log(f"  Word 실패: {err_box[0]}", "warn")

    # ── 방법 2: LibreOffice ──────────────────────────────────────────────────
    import subprocess as _sp, shutil as _sh
    lo_candidates = [
        _sh.which("soffice"), _sh.which("libreoffice"),
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    ]
    lo = next((p for p in lo_candidates if p and os.path.exists(p)), None)
    if lo:
        log("  LibreOffice로 PDF 변환 중...")
        try:
            out_dir = os.path.dirname(pdf_abs)
            _sp.run(
                [lo, "--headless", "--convert-to", "pdf",
                 "--outdir", out_dir, docx_abs],
                check=True, timeout=180,
                stdout=_sp.DEVNULL, stderr=_sp.DEVNULL,
            )
            lo_out = os.path.join(
                out_dir,
                os.path.splitext(os.path.basename(docx_abs))[0] + ".pdf"
            )
            if lo_out != pdf_abs and os.path.exists(lo_out):
                os.replace(lo_out, pdf_abs)
            log("  PDF 저장 완료 (LibreOffice)", "ok")
            return
        except Exception as e2:
            log(f"  LibreOffice 실패: {e2}", "warn")

    # ── 최종 폴백: DOCX 저장 ────────────────────────────────────────────────
    import shutil
    docx_out = str(Path(pdf_abs).with_suffix(".docx"))
    shutil.copy(docx_abs, docx_out)
    log("  Word·LibreOffice 모두 실패 → DOCX로 저장했습니다.", "warn")
    log(f"  파일: {docx_out}", "warn")


def collect_paragraphs(doc):
    items = []
    def add(paras, tag):
        for p in paras:
            items.append((p, tag))
    add(doc.paragraphs, "body")
    for i, tbl in enumerate(doc.tables):
        for r, row in enumerate(tbl.rows):
            for c, cell in enumerate(row.cells):
                add(cell.paragraphs, f"t{i}[{r},{c}]")
    for sec in doc.sections:
        for hdr in (sec.header, sec.footer):
            if hdr:
                add(hdr.paragraphs, "hf")
    return items

# ── 앱 ───────────────────────────────────────────────────────────────────────
class App:
    def __init__(self):
        self.root = TkinterDnD.Tk() if HAS_DND else tk.Tk()
        self.root.title("PDF 번역기")
        self.root.geometry("620x560")
        self.root.minsize(500, 480)
        self.root.configure(bg=C["bg"])

        self._style()
        self.cfg = load_config()
        self._cancel = threading.Event()
        self._build()
        self._load_cfg()

    # ── 스타일 ────────────────────────────────────────────────────────────────
    def _style(self):
        s = ttk.Style(self.root)
        s.theme_use("clam")
        s.configure(".",
            background=C["bg"], foreground=C["fg"],
            font=("맑은 고딕", 10))
        s.configure("TFrame",      background=C["bg"])
        s.configure("TLabel",      background=C["bg"], foreground=C["fg"])
        s.configure("TLabelframe",
            background=C["bg"], bordercolor=C["border"],
            relief="solid", borderwidth=1)
        s.configure("TLabelframe.Label",
            background=C["bg"], foreground=C["accent"],
            font=("맑은 고딕", 10, "bold"))
        s.configure("TEntry",
            fieldbackground=C["entry"], foreground=C["fg"],
            insertcolor=C["fg"], bordercolor=C["border"])
        s.configure("TCombobox",
            fieldbackground=C["entry"], foreground=C["fg"],
            background=C["bg"], arrowcolor=C["accent"],
            bordercolor=C["border"])
        s.map("TCombobox",
            fieldbackground=[("readonly", C["entry"])],
            selectbackground=[("readonly", C["entry"])],
            selectforeground=[("readonly", C["fg"])])
        s.configure("TProgressbar",
            troughcolor=C["bar_bg"], background=C["bar_fg"],
            borderwidth=0, thickness=14)
        s.configure("TButton",
            background=C["surface"], foreground=C["fg"],
            bordercolor=C["border"], relief="solid",
            borderwidth=1, padding=(8, 5))
        s.map("TButton",
            background=[("active", C["border"]), ("disabled", C["surface"])],
            foreground=[("disabled", C["subtle"])])
        s.configure("Accent.TButton",
            background=C["accent"], foreground="#ffffff",
            font=("맑은 고딕", 11, "bold"),
            padding=(24, 11), borderwidth=0)
        s.map("Accent.TButton",
            background=[("active", C["accent_h"]), ("disabled", C["bar_bg"])],
            foreground=[("disabled", C["subtle"])])

    # ── UI ────────────────────────────────────────────────────────────────────
    def _build(self):
        pad = dict(padx=20, pady=16)
        main = ttk.Frame(self.root)
        main.pack(fill=tk.BOTH, expand=True, **pad)

        # ── PDF 파일 ──
        ff = ttk.LabelFrame(main, text=" PDF 파일 ", padding=(12, 8))
        ff.pack(fill=tk.X, pady=(0, 12))

        # 드롭 존
        self.df = tk.Frame(ff, bg=C["drop"], cursor="hand2",
                           highlightthickness=1,
                           highlightbackground=C["drop_bd"], height=76)
        self.df.pack(fill=tk.X, pady=(0, 10))
        self.df.pack_propagate(False)
        self.di = tk.Label(self.df, text="📄", bg=C["drop"], font=("맑은 고딕", 22))
        self.di.pack(pady=(7, 1))
        self.dl = tk.Label(self.df, bg=C["drop"], fg=C["subtle"], font=("맑은 고딕", 10),
                           text="PDF를 여기에 끌어다 놓거나  [클릭하여 선택]")
        self.dl.pack()
        for w in (self.df, self.di, self.dl):
            w.bind("<Button-1>", lambda _: self._pick_in())
            w.bind("<Enter>",    lambda _: self._hover(True))
            w.bind("<Leave>",    lambda _: self._hover(False))
        if HAS_DND:
            for w in (self.df, self.di, self.dl):
                w.drop_target_register(DND_FILES)
                w.dnd_bind("<<Drop>>",      self._drop)
                w.dnd_bind("<<DragEnter>>", lambda _: self._hover(True))
                w.dnd_bind("<<DragLeave>>", lambda _: self._hover(False))

        self.iv = tk.StringVar()
        self.ov = tk.StringVar()
        self._frow(ff, "입력:", self.iv, self._pick_in)
        self._frow(ff, "출력:", self.ov, self._pick_out)

        # ── 언어 ──
        lf = ttk.LabelFrame(main, text=" 번역 언어 ", padding=(12, 10))
        lf.pack(fill=tk.X, pady=(0, 12))
        lr = ttk.Frame(lf)
        lr.pack()
        vals = [f"{c}  {n}" for c, n in LANGUAGES]
        src  = ["auto  자동 감지"] + vals

        ttk.Label(lr, text="소스 언어:").pack(side=tk.LEFT)
        self.sc = ttk.Combobox(lr, values=src, state="readonly", width=16)
        self.sc.current(0)
        self.sc.pack(side=tk.LEFT, padx=(6, 4))

        ttk.Label(lr, text="→", foreground=C["accent"],
                  font=("맑은 고딕", 13, "bold")).pack(side=tk.LEFT, padx=6)

        ttk.Label(lr, text="타겟 언어:").pack(side=tk.LEFT)
        self.tc = ttk.Combobox(lr, values=vals, state="readonly", width=16)
        self.tc.current(0)
        self.tc.pack(side=tk.LEFT, padx=(6, 0))
        self.tc.bind("<<ComboboxSelected>>", self._tgt_changed)

        # ── 버튼 ──
        br = ttk.Frame(main)
        br.pack(fill=tk.X, pady=(0, 12))
        self.btn = ttk.Button(br, text="번역 시작", style="Accent.TButton",
                              command=self._start)
        self.btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        self.cbtn = ttk.Button(br, text="취소", command=self._do_cancel,
                               state=tk.DISABLED, width=7)
        self.cbtn.pack(side=tk.LEFT)

        # ── 진행률 ──
        pf = ttk.LabelFrame(main, text=" 진행 상황 ", padding=(12, 8))
        pf.pack(fill=tk.BOTH, expand=True)

        # 퍼센트 레이블 + 프로그레스바
        top = ttk.Frame(pf)
        top.pack(fill=tk.X, pady=(0, 6))
        self.pct_lbl = tk.Label(top, text="0%", bg=C["bg"], fg=C["accent"],
                                font=("맑은 고딕", 10, "bold"), width=5, anchor=tk.E)
        self.pct_lbl.pack(side=tk.RIGHT)
        self.pbar = ttk.Progressbar(top, mode="determinate", maximum=100)
        self.pbar.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))

        self.status = tk.Label(pf, text="대기 중", bg=C["bg"], fg=C["subtle"],
                               font=("맑은 고딕", 9), anchor=tk.W)
        self.status.pack(fill=tk.X, pady=(0, 6))

        self.log = scrolledtext.ScrolledText(
            pf, height=6, wrap=tk.WORD, relief="solid",
            borderwidth=1,
            bg=C["surface"], fg=C["fg"], font=("Consolas", 9),
            insertbackground=C["fg"],
        )
        self.log.pack(fill=tk.BOTH, expand=True)
        for tag, col in [("ok", C["green"]), ("err", C["red"]),
                         ("info", C["accent"]), ("warn", C["yellow"])]:
            self.log.tag_configure(tag, foreground=col)
        self.log.config(state=tk.DISABLED)

    def _frow(self, parent, label, var, cmd):
        r = ttk.Frame(parent)
        r.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(r, text=label, width=7, anchor=tk.W).pack(side=tk.LEFT)
        ttk.Entry(r, textvariable=var, font=("맑은 고딕", 9)
                  ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
        ttk.Button(r, text="찾기", width=5, command=cmd).pack(side=tk.LEFT)

    # ── 헬퍼 ─────────────────────────────────────────────────────────────────
    def _load_cfg(self):
        if "target_lang" in self.cfg:
            for i, (c, _) in enumerate(LANGUAGES):
                if c == self.cfg["target_lang"]: self.tc.current(i); break
        if "source_lang" in self.cfg:
            v = self.cfg["source_lang"]
            if v == "auto":
                self.sc.current(0)
            else:
                for i, (c, _) in enumerate(LANGUAGES):
                    if c == v: self.sc.current(i + 1); break

    def _src(self):
        v = self.sc.get()
        return "auto" if v.startswith("auto") else v.split()[0]

    def _tgt(self):
        return self.tc.get().split()[0]

    def _hover(self, on):
        bg = C["drop_hl"] if on else C["drop"]
        for w in (self.df, self.di, self.dl): w.config(bg=bg)

    def _set_in(self, path):
        self.iv.set(path)
        p = Path(path)
        self.ov.set(str(p.parent / f"{p.stem}_{self._tgt()}.pdf"))
        self.dl.config(text=p.name, fg=C["fg"])
        self.di.config(text="✅")

    def _drop(self, e):
        p = normalize_drop(e.data)
        if not p.lower().endswith(".pdf"):
            self._log("PDF 파일만 지원합니다.", "warn"); return
        self._set_in(p)

    def _tgt_changed(self, _=None):
        if self.iv.get():
            p = Path(self.iv.get())
            self.ov.set(str(p.parent / f"{p.stem}_{self._tgt()}.pdf"))

    def _pick_in(self):
        p = filedialog.askopenfilename(title="번역할 PDF 선택",
                                       filetypes=[("PDF","*.pdf"),("모두","*.*")])
        if p: self._set_in(p)

    def _pick_out(self):
        p = filedialog.asksaveasfilename(title="출력 파일", defaultextension=".pdf",
                                         filetypes=[("PDF","*.pdf")])
        if p: self.ov.set(p)

    def _log(self, msg, tag=""):
        def _w():
            self.log.config(state=tk.NORMAL)
            self.log.insert(tk.END, msg + "\n", tag)
            self.log.see(tk.END)
            self.log.config(state=tk.DISABLED)
        self.root.after(0, _w)

    def _set_pct(self, pct, status=""):
        def _w():
            self.pbar["value"] = pct
            self.pct_lbl.config(text=f"{int(pct)}%")
            if status:
                self.status.config(text=status)
        self.root.after(0, _w)

    def _set_running(self, on):
        self.btn.config(state=tk.DISABLED if on else tk.NORMAL)
        self.cbtn.config(state=tk.NORMAL if on else tk.DISABLED)
        # 완료 후 progress는 100% 유지 — 다음 번역 시작 시 _start()에서 리셋

    def _do_cancel(self):
        self._cancel.set()
        self._log("취소 요청...", "warn")

    # ── 번역 실행 ─────────────────────────────────────────────────────────────
    def _start(self):
        inp = self.iv.get().strip()
        out = self.ov.get().strip()
        if not inp:
            messagebox.showerror("오류", "PDF 파일을 선택하세요."); return
        if not Path(inp).exists():
            messagebox.showerror("오류", f"파일 없음:\n{inp}"); return
        if not out:
            p = Path(inp)
            out = str(p.parent / f"{p.stem}_{self._tgt()}.pdf")
            self.ov.set(out)

        save_config({"target_lang": self._tgt(), "source_lang": self._src()})
        self._cancel.clear()
        self._set_pct(0, "시작 중...")   # 새 번역 시작 시 리셋
        self.root.after(0, lambda: self._set_running(True))
        self.log.config(state=tk.NORMAL)
        self.log.delete("1.0", tk.END)
        self.log.config(state=tk.DISABLED)
        self._set_pct(0, "시작 중...")

        threading.Thread(target=self._worker,
                         args=(inp, out, self._src(), self._tgt()),
                         daemon=True).start()

    def _worker(self, inp, out, src, tgt):
        try:
            from pdf2docx import Converter
            from docx import Document
            from deep_translator import GoogleTranslator  # noqa
        except ImportError as e:
            self._log(f"패키지 오류: {e}", "err")
            self.root.after(0, lambda: self._set_running(False)); return

        tmp = tempfile.mktemp(suffix=".docx")
        tmp_translated = tempfile.mktemp(suffix=".docx")

        try:
            # ── 1단계: PDF → DOCX ─────────────────────────────────────────
            self._set_pct(2, "1/3  PDF 변환 중...")
            self._log(f"[1/3] PDF → DOCX 변환 중: {Path(inp).name}", "info")

            # fitz로 페이지 수 파악
            import fitz as _fitz
            with _fitz.open(inp) as _pdf:
                total_pages = len(_pdf)
            self._log(f"  총 {total_pages}페이지")

            # 변환 중 진행률 애니메이션 (2 → 24%)
            # pdf2docx는 변환 콜백을 지원하지 않으므로 시간 기반으로 추정
            conv_done = threading.Event()
            estimated_sec = max(total_pages * 0.25, 5)

            def _anim():
                t0 = time.time()
                while not conv_done.is_set():
                    elapsed = time.time() - t0
                    pct = min(24, 2 + elapsed / estimated_sec * 22)
                    self._set_pct(pct, f"1/3  PDF 변환 중... ({int(elapsed)}초 경과 / {total_pages}페이지)")
                    time.sleep(0.4)

            threading.Thread(target=_anim, daemon=True).start()

            cv = Converter(inp)
            cv.convert(tmp, start=0, end=None)
            cv.close()
            conv_done.set()
            self._log("  변환 완료", "ok")
            self._set_pct(25, "2/3  번역 중...")

            if self._cancel.is_set(): raise InterruptedError()

            # ── 2단계: 번역 ────────────────────────────────────────────────
            self._log(f"[2/3] 번역 중  ({src} → {tgt})...", "info")

            doc   = Document(tmp)
            items = collect_paragraphs(doc)
            texts = [p.text for p, _ in items]
            non_empty_count = sum(1 for t in texts if t.strip())
            self._log(f"  단락 수: {non_empty_count}개")

            done_ref = [0]

            def prog_cb(done, total):
                done_ref[0] = done
                pct = 25 + done / max(total, 1) * 65
                self._set_pct(pct, f"2/3  번역 중... {done}/{total} 단락")

            translated = translate_paragraphs_parallel(
                texts, src, tgt, prog_cb, self._cancel
            )

            if self._cancel.is_set(): raise InterruptedError()

            apply_translations(doc, items, translated)
            doc.save(tmp_translated)
            self._log("  번역 완료", "ok")
            self._set_pct(90, "3/3  PDF 저장 중...")

            # ── 3단계: DOCX → PDF ──────────────────────────────────────────
            self._log("[3/3] PDF 저장 중...", "info")
            _docx_to_pdf(tmp_translated, out, self._log)

            self._set_pct(100, "완료!")
            self._log(f"\n번역 완료!", "ok")
            self._log(f"저장: {out}", "ok")
            self.root.after(0, lambda: messagebox.showinfo(
                "완료", f"번역 완료!\n\n{out}"))

        except InterruptedError:
            self._log("취소됨.", "warn")
            self._set_pct(0, "취소됨")
        except Exception as e:
            msg = str(e)
            self._log(f"오류: {msg}", "err")
            self.root.after(0, lambda m=msg: messagebox.showerror("오류", m))
        finally:
            for f in (tmp, tmp_translated):
                try: os.remove(f)
                except Exception: pass
            self.root.after(0, lambda: self._set_running(False))

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    App().run()
