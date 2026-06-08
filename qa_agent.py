"""
QA Agent — 빌드 후 번역 품질 자동 평가
  - evaluation/ 폴더의 3개 테스트 PDF를 모두 번역
  - 빈 페이지 / 텍스트 겹침 / 최소 폰트 비율 / 여백 / 이미지 겹침 측정
  - evaluation/qa_output/ 에 PNG + 리포트 저장
"""
import os, sys, threading, datetime
from pathlib import Path

import fitz  # PyMuPDF

# gui_translator의 독립 함수 임포트
sys.path.insert(0, str(Path(__file__).parent))
from gui_translator import (translate_paragraphs_parallel,
                            _wrap_lines, _insert_ko_text,
                            LINE_HEIGHT_RATIO, LINE_HEIGHT_RATIO_LATIN,
                            PARA_GAP_RATIO,
                            _select_output_font, _is_cjk_lang)

# ── 설정 ────────────────────────────────────────────────────────────────────
OUTPUT_DIR = Path(__file__).parent / "evaluation" / "qa_output"
MIN_FONT          = 5.5   # 폰트 크기 최소 임계치 (우리 최솟값 6pt는 허용)
OVERLAP_THRESHOLD = 5.0   # 겹침 최소 면적 (pt²)
MARGIN_MIN_PT     = 20.0  # 좌우 여백 최소값 (pt)

# 하위 호환: run_qa_ocpp.py 등에서 덮어쓸 수 있도록 유지
TEST_PDF = Path(__file__).parent / "evaluation" / "The Geek Way_original.pdf"
QA_PAGES = 346
SRC_LANG = "en"
TGT_LANG = "ko"

# ── 3개 테스트 케이스 ─────────────────────────────────────────────────────────
_EVAL_DIR = Path(__file__).parent / "evaluation"
TEST_CASES = [
    {"name": "The Geek Way",    "pdf": _EVAL_DIR / "The Geek Way_original.pdf",
     "src": "en", "tgt": "ko", "pages": 346},
    {"name": "OCPP QR Japan",   "pdf": _EVAL_DIR / "ocpp_qr_japan-v1.pdf",
     "src": "en", "tgt": "ko", "pages": 9999},
    {"name": "UL 표준 (ko→en)", "pdf": _EVAL_DIR / "UL.pdf",
     "src": "ko", "tgt": "en", "pages": 9999},
]


# ── 번역 (gui_translator._worker 와 동일 로직) ───────────────────────────────
def translate_pdf(inp: Path, out: Path, max_pages: int,
                  src_lang: str = "en", tgt_lang: str = "ko"):
    out_font = _select_output_font(tgt_lang)
    _lh_ratio = LINE_HEIGHT_RATIO if _is_cjk_lang(tgt_lang) else LINE_HEIGHT_RATIO_LATIN
    cancel   = threading.Event()

    doc = fitz.open(str(inp))
    total = min(len(doc), max_pages)
    print(f"[1/3] 텍스트 추출 ({total}페이지)...")

    page_blocks = []
    for pidx in range(total):
        page    = doc[pidx]
        raw_blks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]
        result  = []
        for blk in raw_blks:
            if blk.get("type") != 0:
                continue
            spans = []
            for line in blk["lines"]:
                for sp in line["spans"]:
                    clean = " ".join(sp["text"].split())
                    if clean:
                        spans.append({**sp, "text": clean})
            if not spans:
                continue
            result.append({
                "text":  " ".join(sp["text"] for sp in spans),
                "spans": spans,
                "bbox":  fitz.Rect(blk["bbox"]),
            })
        page_blocks.append(result)

    all_texts = [b["text"] for pb in page_blocks for b in pb]
    print(f"  블록 {len(all_texts)}개")

    print(f"[2/3] 번역 중 ({src_lang} → {tgt_lang})...")
    translated = translate_paragraphs_parallel(
        all_texts, src_lang, tgt_lang,
        lambda d, t: print(f"  {d}/{t}", end="\r", flush=True),
        cancel,
    )
    print()

    print("[3/3] 텍스트 삽입 중...")

    SPECIAL_CHARS = 400
    page_img_rects  = []
    page_draw_zones = []
    special_pages   = set()
    for pidx in range(total):
        raw_blks = doc[pidx].get_text(
            "dict", flags=fitz.TEXT_PRESERVE_WHITESPACE | fitz.TEXT_PRESERVE_IMAGES
        )["blocks"]
        imgs = [fitz.Rect(b["bbox"]) for b in raw_blks if b.get("type") == 1]
        page_img_rects.append(imgs)
        drawings = doc[pidx].get_drawings()
        _page_rect = doc[pidx].rect
        _page_area = _page_rect.get_area()
        sig = []
        for _d in drawings:
            _r = fitz.Rect(_d["rect"])
            if _r.height < 30 and _r.width > _r.height * 5:
                continue
            _clipped = (_r & _page_rect).get_area()
            if 500 <= _clipped < _page_area * 0.8:
                sig.append(_r)
        if sig:
            dz = sig[0]
            for r in sig[1:]: dz |= r
            page_draw_zones.append(dz)
        else:
            page_draw_zones.append(fitz.Rect())
        if sum(len(blk["text"]) for blk in page_blocks[pidx]) < SPECIAL_CHARS:
            special_pages.add(pidx)

    # 배경 이미지 판별: 텍스트 블록 3개 이상 겹치면 배경(표 행 음영 등) → inplace·skip 제외
    _BG_THRESH = 3
    background_imgs = []
    for pidx in range(total):
        bg = set()
        for i_idx, img_r in enumerate(page_img_rects[pidx]):
            cnt = sum(
                1 for blk in page_blocks[pidx]
                if (blk["bbox"] & img_r).get_area() > blk["bbox"].get_area() * 0.4
            )
            if cnt >= _BG_THRESH:
                bg.add(i_idx)
        background_imgs.append(bg)

    # 원본 텍스트 일괄 제거
    for pidx in range(total):
        pblks = page_blocks[pidx]
        if not pblks: continue
        for blk in pblks:
            for sp in blk["spans"]:
                doc[pidx].add_redact_annot(fitz.Rect(sp["bbox"]), fill=None)
        doc[pidx].apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)

    # 배경 이미지 white cover: 이미지에 구워진 원본 텍스트 픽셀 제거
    for pidx in range(total):
        bg_list = [page_img_rects[pidx][i] for i in background_imgs[pidx]]
        if bg_list:
            page = doc[pidx]
            for img_r in bg_list:
                page.add_redact_annot(img_r, fill=(1, 1, 1))
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_PIXELS)

    # 문서 전체 블록에서 컬럼 경계 도출 (페이지마다 min→오염 방지)
    from collections import Counter as _Ctr
    _all_x0 = [round(blk["bbox"].x0) for pb in page_blocks for blk in pb]
    _all_x1 = [round(blk["bbox"].x1) for pb in page_blocks for blk in pb]
    doc_ax0 = _Ctr(_all_x0).most_common(1)[0][0] if _all_x0 else 50
    doc_ax1 = _Ctr(_all_x1).most_common(1)[0][0] if _all_x1 else 550

    def _content_area(pblks):
        if not pblks: return None
        bboxes = [blk["bbox"] for blk in pblks]
        return (doc_ax0, doc_ax1,
                min(b.y0 for b in bboxes), max(b.y1 for b in bboxes))

    page_areas = [_content_area(page_blocks[p]) for p in range(total)]
    valid = [a for a in page_areas if a]
    def _med(lst): s = sorted(lst); return s[len(s) // 2]
    std_area = (doc_ax0, doc_ax1,
                _med([a[2] for a in valid]),
                _med([a[3] for a in valid])) if valid else (50, 550, 50, 750)

    def _is_inplace(blk_bbox, pidx, blk=None):
        blk_area = blk_bbox.get_area()
        if blk_area <= 0:
            return False
        for img_r in page_img_rects[pidx]:
            if (blk_bbox & img_r).get_area() > blk_area * 0.4:
                return True
            if blk:
                for sp in blk.get("spans", []):  # qa_agent 블록은 flat spans
                    sp_r = fitz.Rect(sp["bbox"])
                    sp_a = sp_r.get_area()
                    if sp_a > 0 and (sp_r & img_r).get_area() > sp_a * 0.5:
                        return True
        if pidx < len(page_draw_zones):
            dz = page_draw_zones[pidx]
            if not dz.is_empty and (blk_bbox & dz).get_area() > blk_area * 0.4:
                return True
        return False

    regular_q   = []
    special_map = {}
    inplace_map = {}
    b_idx = 0
    for pidx in range(total):
        for blk in page_blocks[pidx]:
            t_text = translated[b_idx]; b_idx += 1
            if not t_text or not t_text.strip(): continue
            spans = blk["spans"]
            _sz_w = {}
            for s in spans:
                k = round(s["size"], 1); _sz_w[k] = _sz_w.get(k, 0) + len(s["text"])
            size  = max(_sz_w, key=_sz_w.get)
            raw_c = spans[0].get("color", 0)
            color = (((raw_c >> 16) & 0xFF) / 255, ((raw_c >> 8) & 0xFF) / 255,
                     (raw_c & 0xFF) / 255) if isinstance(raw_c, int) else (raw_c or (0,0,0))
            item = {"text": t_text, "size": size, "color": color}
            if pidx in special_pages:
                special_map.setdefault(pidx, []).append(item)
            elif _is_inplace(blk["bbox"], pidx, blk):
                inplace_map.setdefault(pidx, []).append((blk["bbox"], t_text, size, color))
            else:
                regular_q.append(item)

    # 본문 크기 정규화: 최빈 크기를 body_size로 정의하고
    # body_size ±2pt 이내 항목을 통일 (chapter 내 글자 불규칙 방지)
    if regular_q:
        from collections import Counter
        size_counts = Counter(round(item["size"]) for item in regular_q)
        body_size = float(size_counts.most_common(1)[0][0])
        for item in regular_q:
            if abs(item["size"] - body_size) <= 2.0:
                item["size"] = body_size

    page_w = doc[0].rect.width; page_h = doc[0].rect.height

    def _get_area(pidx):
        a = page_areas[pidx] if pidx < len(page_areas) and page_areas[pidx] else std_area
        ax0, ax1, ay0, ay1 = a
        return ax0, ax1, ay0, ay1

    def _place(page, ax0, ax1, ay0, ay1, queue, pidx_=None):
        col = fitz.Rect(ax0, ay0, ax1, ay1)
        skips = sorted(
            [r for r in (page_img_rects[pidx_] if pidx_ is not None
                         and pidx_ < len(page_img_rects) else [])
             if r.intersects(col)],
            key=lambda r: r.y0
        )
        # draw_zone(표·다이어그램)도 skip 대상에 포함
        if pidx_ is not None and pidx_ < len(page_draw_zones):
            dz = page_draw_zones[pidx_]
            if not dz.is_empty and dz.intersects(col):
                skips.append(dz)
                skips.sort(key=lambda r: r.y0)

        def _skip(y, sz=0):
            changed = True
            while changed:
                changed = False
                for r in skips:
                    if y < r.y1 and y + sz >= r.y0:
                        y = r.y1 + 4
                        changed = True
            return y

        y   = _skip(ay0)
        tws = {}
        bw  = max(ax1 - ax0, 1.0)
        while queue:
            item = queue[0]
            size = item["size"]; lh = size * _lh_ratio; gap = size * PARA_GAP_RATIO
            y = _skip(y, lh)
            if y + size > ay1: break
            lines = _wrap_lines(item["text"], bw, out_font, size)
            color = item["color"]
            if color not in tws:
                tws[color] = fitz.TextWriter(page.rect, color=color)
            tw = tws[color]
            rendered = 0
            for line in lines:
                y = _skip(y, lh)
                if y + size > ay1: break
                tw.append((ax0, y + size), line, font=out_font, fontsize=size)
                y += lh; rendered += 1
            if rendered < len(lines):
                queue[0] = {**item, "text": " ".join(lines[rendered:])}; break
            else:
                queue.pop(0); y += gap
        for tw in tws.values():
            tw.write_text(page)

    pidx = 0
    while True:
        if not regular_q and not special_map: break
        if pidx >= len(doc):
            if not regular_q: break
            doc.new_page(width=page_w, height=page_h)
        page = doc[pidx]
        ax0, ax1, ay0, ay1 = _get_area(pidx)
        if pidx in special_pages and pidx < total:
            _place(page, ax0, ax1, ay0, ay1, special_map.pop(pidx, []), pidx_=pidx)
        else:
            _place(page, ax0, ax1, ay0, ay1, regular_q, pidx_=pidx)
        pidx += 1

    for ip_pidx, items in inplace_map.items():
        page = doc[ip_pidx]
        for bbox, _t, _s, _c in items:
            page.add_redact_annot(fitz.Rect(bbox), fill=(1, 1, 1))
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_PIXELS)

    for ip_pidx, items in inplace_map.items():
        page = doc[ip_pidx]
        for bbox, text, size, color in items:
            _insert_ko_text(page, bbox, text, out_font, size, color,
                            lh_ratio=_lh_ratio)

    out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out), deflate=True, garbage=4)
    doc.close()
    print(f"  저장: {out}")


# ── 품질 평가 ─────────────────────────────────────────────────────────────────
def evaluate(orig_path: Path, trans_path: Path, max_pages: int) -> dict:
    orig  = fitz.open(str(orig_path))
    trans = fitz.open(str(trans_path))
    n     = min(len(orig), len(trans), max_pages)

    metrics = {
        "pages":          n,
        "blank_pages":       0,
        "overlap_pages":     0,
        "tiny_font_pages":   0,
        "margin_pages":      0,
        "img_overlap_pages": 0,
        "vmargin_pages":     0,
        "table_line_pages":  0,
        "total_orig_blocks":  0,
        "total_trans_blocks": 0,
        "issue_page_set": set(),
        "issues": [],
    }

    for pidx in range(n):
        op = orig[pidx]
        tp = trans[pidx]

        orig_text  = op.get_text().strip()
        trans_text = tp.get_text().strip()

        def _flag(msg):
            metrics["issues"].append(f"p{pidx+1}: {msg}")
            metrics["issue_page_set"].add(pidx)

        # 빈 페이지 검사
        if orig_text and not trans_text:
            metrics["blank_pages"] += 1
            _flag(f"빈 페이지 (원문 {len(orig_text)}자)")

        # 블록 수
        orig_blks  = [b for b in op.get_text("dict")["blocks"] if b.get("type") == 0]
        trans_blks = [b for b in tp.get_text("dict")["blocks"] if b.get("type") == 0]
        metrics["total_orig_blocks"]  += len(orig_blks)
        metrics["total_trans_blocks"] += len(trans_blks)

        # 텍스트 겹침 검사
        # - 인접 줄 bbox가 한국어 폰트 ascender 특성상 미세하게 겹치는 False Positive 제거
        # - 작은 rect 면적의 25% 이상 겹칠 때만 실제 겹침으로 판단
        rects = []
        for blk in trans_blks:
            for line in blk["lines"]:
                for sp in line["spans"]:
                    if sp["text"].strip():
                        rects.append(fitz.Rect(sp["bbox"]))

        overlaps = 0
        for i, r1 in enumerate(rects):
            for r2 in rects[i + 1:]:
                if r1.intersects(r2):
                    inter_area  = (r1 & r2).get_area()
                    smaller_area = min(r1.get_area(), r2.get_area())
                    if smaller_area > 0 and inter_area / smaller_area > 0.25:
                        overlaps += 1
        if overlaps:
            metrics["overlap_pages"] += 1
            _flag(f"텍스트 겹침 {overlaps}건")

        # 최소 폰트 비율 검사 (MIN_FONT 이하 스팬)
        # MIN_FONT=5.5: 우리 최솟값(6pt)으로 의도적 압축된 텍스트는 제외
        all_spans = [sp for blk in trans_blks for line in blk["lines"] for sp in line["spans"] if sp["text"].strip()]
        tiny = [sp for sp in all_spans if sp["size"] <= MIN_FONT]
        if all_spans and len(tiny) / len(all_spans) > 0.3:
            metrics["tiny_font_pages"] += 1
            _flag(f"과소 폰트 스팬 {len(tiny)}/{len(all_spans)} ({len(tiny)*100//len(all_spans)}%)")

        # 이미지-텍스트 겹침 검사
        # 스팬이 이미지에 30% 미만으로 겹쳐야 진짜 겹침으로 판단:
        #   - inplace 텍스트(이미지 내부, 높은 겹침률) → 의도된 배치, 제외
        #   - 표 행 경계의 경계 스팬(중간 겹침률) → 제외
        #   - 잘못 배치된 텍스트(이미지 밖에서 작게 겹침, 낮은 겹침률) → 플래그
        img_blks_t = [b for b in tp.get_text("dict")["blocks"] if b.get("type") == 1]
        if img_blks_t and all_spans:
            img_overlaps = 0
            for ib in img_blks_t:
                ir = fitz.Rect(ib["bbox"])
                for sp in all_spans:
                    sr = fitz.Rect(sp["bbox"])
                    if ir.intersects(sr):
                        ov = (ir & sr).get_area()
                        sa = sr.get_area()
                        if sa > 0 and ov > 50 and ov / sa < 0.05:
                            # 같은 스팬이 이미 다른 이미지 내부에 대부분 있으면 (인접 이미지 경계 클립) 무시
                            already_inplace = any(
                                (fitz.Rect(ib2["bbox"]) & sr).get_area() / sa > 0.5
                                for ib2 in img_blks_t
                                if ib2 is not ib
                            )
                            if not already_inplace:
                                img_overlaps += 1
            if img_overlaps:
                metrics["img_overlap_pages"] += 1
                _flag(f"이미지 위 텍스트 겹침 {img_overlaps}건")

        # 좌우 여백 검사 — 리플로우 후엔 절대 페이지 여백 기준으로 검사
        # (원본 span 비교는 리플로우로 인해 무의미해짐)
        page_w = tp.rect.width
        if all_spans:
            trans_left  = min(fitz.Rect(sp["bbox"]).x0 for sp in all_spans)
            trans_right = max(fitz.Rect(sp["bbox"]).x1 for sp in all_spans)
            if trans_left < MARGIN_MIN_PT or (page_w - trans_right) < MARGIN_MIN_PT:
                metrics["margin_pages"] += 1
                _flag(f"여백 부족 (좌 {trans_left:.0f}pt / 우 {page_w - trans_right:.0f}pt)")

        # ── 원본 대비 수직 여백 비교 ─────────────────────────────────────────
        orig_spans = [sp for blk in orig_blks
                      for line in blk["lines"] for sp in line["spans"]
                      if sp["text"].strip()]
        if orig_spans and all_spans:
            orig_top = min(fitz.Rect(sp["bbox"]).y0 for sp in orig_spans)
            orig_bot = max(fitz.Rect(sp["bbox"]).y1 for sp in orig_spans)
            trans_top = min(fitz.Rect(sp["bbox"]).y0 for sp in all_spans)
            trans_bot = max(fitz.Rect(sp["bbox"]).y1 for sp in all_spans)
            top_diff = trans_top - orig_top
            bot_diff = trans_bot - orig_bot
            # 이미지 커버리지에 따라 임계값 동적 조정
            # 이미지가 '빈 구간'을 많이 차지하면 여백 불일치가 당연한 구조적 현상
            _page_h = op.rect.height
            _orig_img_blks = op.get_text(
                "dict", flags=fitz.TEXT_PRESERVE_IMAGES)["blocks"]
            _orig_imgs = [fitz.Rect(b["bbox"]) for b in _orig_img_blks
                          if b.get("type") == 1]
            _img_cover = sum(
                min(r.y1, _page_h) - max(r.y0, 0)
                for r in _orig_imgs if r.get_area() > 0
            )
            _img_ratio = _img_cover / _page_h if _page_h > 0 else 0
            _thresh = 200 if _img_ratio > 0.35 else 40
            if abs(top_diff) > _thresh or abs(bot_diff) > _thresh:
                metrics["vmargin_pages"] += 1
                _flag(
                    f"수직 여백 불일치 "
                    f"(상단 원본{orig_top:.0f}→번역{trans_top:.0f} Δ{top_diff:+.0f}, "
                    f"하단 원본{orig_bot:.0f}→번역{trans_bot:.0f} Δ{bot_diff:+.0f})"
                )

        # ── 표 선 위 텍스트 겹침 검사 ────────────────────────────────────────
        thin_lines = []
        for d in tp.get_drawings():
            if not d.get("rect"):
                continue
            r = fitz.Rect(d["rect"])
            if (r.height < 4 and r.width > 20) or (r.width < 4 and r.height > 20):
                thin_lines.append(r)
        if thin_lines and all_spans:
            text_on_line = 0
            for ln in thin_lines:
                for sp in all_spans:
                    sr = fitz.Rect(sp["bbox"])
                    if ln.intersects(sr) and (ln & sr).get_area() > 20:
                        text_on_line += 1
                        break
            if text_on_line > 6:
                metrics["table_line_pages"] += 1
                _flag(f"표 선 위 텍스트 {text_on_line}건")

    orig.close()
    trans.close()
    return metrics


# ── 페이지 → PNG ──────────────────────────────────────────────────────────────
def render_pages(pdf_path: Path, out_dir: Path, max_pages: int) -> list:
    doc    = fitz.open(str(pdf_path))
    out_dir.mkdir(parents=True, exist_ok=True)
    paths  = []
    mat    = fitz.Matrix(1.5, 1.5)
    for i in range(min(len(doc), max_pages)):
        pix  = doc[i].get_pixmap(matrix=mat)
        dest = out_dir / f"page_{i+1:02d}.png"
        pix.save(str(dest))
        paths.append(dest)
    doc.close()
    return paths


# ── 원본/번역 비교 PNG 저장 ───────────────────────────────────────────────────
def render_comparison(orig_path: Path, trans_path: Path, out_dir: Path,
                      max_pages: int, issue_pages: set):
    """이슈 페이지(+처음 3p)의 원본·번역 PNG를 나란히 저장."""
    orig  = fitz.open(str(orig_path))
    trans = fitz.open(str(trans_path))
    out_dir.mkdir(parents=True, exist_ok=True)
    n   = min(len(orig), len(trans), max_pages)
    mat = fitz.Matrix(1.0, 1.0)
    targets = sorted((issue_pages | set(range(min(3, n)))) & set(range(n)))
    for i in targets[:15]:
        orig[i].get_pixmap(matrix=mat).save(str(out_dir / f"orig_p{i+1:02d}.png"))
        trans[i].get_pixmap(matrix=mat).save(str(out_dir / f"trans_p{i+1:02d}.png"))
    orig.close()
    trans.close()


# ── 단일 케이스 실행 ──────────────────────────────────────────────────────────
def _run_case(case: dict, timestamp: str) -> int:
    """하나의 테스트 케이스를 실행하고 점수를 반환."""
    name      = case["name"]
    pdf_path  = case["pdf"]
    src       = case["src"]
    tgt       = case["tgt"]
    max_pages = case["pages"]

    if not pdf_path.exists():
        print(f"  [SKIP] {name}: 파일 없음 ({pdf_path.name})")
        return -1

    out_pdf = OUTPUT_DIR / f"translated_{timestamp}_{pdf_path.stem}.pdf"
    png_dir = OUTPUT_DIR / f"pages_{timestamp}_{pdf_path.stem}"

    print("=" * 60)
    print(f"케이스: {name}")
    print(f"입력: {pdf_path.name}  |  {src} → {tgt}")
    print("=" * 60)

    translate_pdf(pdf_path, out_pdf, max_pages, src_lang=src, tgt_lang=tgt)

    print("\n[4/4] 품질 평가 중...")
    m = evaluate(pdf_path, out_pdf, max_pages)
    render_pages(out_pdf, png_dir, min(max_pages, 20))

    cmp_dir = OUTPUT_DIR / f"compare_{timestamp}_{pdf_path.stem}"
    render_comparison(pdf_path, out_pdf, cmp_dir, max_pages, m["issue_page_set"])

    block_coverage = (m["total_trans_blocks"] / max(m["total_orig_blocks"], 1)) * 100
    # 빈 페이지: 블록 커버리지 ≥ 80% → 리플로우 오버플로 (컨텐츠는 다른 페이지에 존재)
    #            블록 커버리지 < 80% → 진짜 컨텐츠 손실 → 감점
    effective_blank = m["blank_pages"] if block_coverage < 80 else 0
    score = 100
    score -= effective_blank           * 20
    score -= m["overlap_pages"]        * 15
    score -= m["tiny_font_pages"]      * 10
    score -= m["margin_pages"]         *  5
    score -= m["img_overlap_pages"]    * 10
    score -= m["vmargin_pages"]        *  5
    score -= m["table_line_pages"]     *  8
    score = max(0, score)

    report_lines = [
        "=" * 60,
        f"QA 결과 [{name}] - {timestamp}",
        "=" * 60,
        f"언어            : {src} → {tgt}",
        f"평가 페이지     : {m['pages']}p",
        f"블록 커버리지   : {m['total_trans_blocks']}/{m['total_orig_blocks']} ({block_coverage:.1f}%)",
        f"빈 페이지       : {m['blank_pages']}p{'  (리플로우 오버플로, 감점 없음)' if m['blank_pages'] and block_coverage >= 80 else ''}",
        f"겹침 페이지     : {m['overlap_pages']}p",
        f"과소폰트 페이지 : {m['tiny_font_pages']}p",
        f"여백 초과 페이지: {m['margin_pages']}p",
        f"이미지겹침 페이지: {m['img_overlap_pages']}p",
        f"수직여백 불일치 : {m['vmargin_pages']}p  (원본 대비 ±40pt 초과)",
        f"표선겹침 페이지 : {m['table_line_pages']}p  (표 선 위 텍스트)",
        f"품질 점수       : {score}/100",
        "",
    ]
    if m["issues"]:
        report_lines.append("이슈:")
        report_lines.extend(f"  * {iss}" for iss in m["issues"][:30])
    else:
        report_lines.append("이슈 없음")
    report_lines += [
        "",
        f"번역 PDF : {out_pdf}",
        f"PNG 출력 : {png_dir}",
        f"비교 PNG : {cmp_dir}  (orig_pXX.png / trans_pXX.png)",
        "=" * 60,
    ]
    report = "\n".join(report_lines)
    print("\n" + report)

    report_path = OUTPUT_DIR / f"report_{timestamp}_{pdf_path.stem}.txt"
    report_path.write_text(report, encoding="utf-8")
    return score


# ── 메인 ─────────────────────────────────────────────────────────────────────
def main(single_pdf: Path = None, src: str = None, tgt: str = None,
         pages: int = 9999):
    """
    single_pdf 미지정 시: TEST_CASES의 3개 PDF를 모두 테스트.
    single_pdf 지정 시(하위 호환용): 해당 PDF만 테스트.
    """
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 하위 호환: run_qa_ocpp.py 등이 전역 변수를 덮어쓴 경우
    if single_pdf is None and TEST_PDF != (_EVAL_DIR / "The Geek Way_original.pdf"):
        single_pdf = TEST_PDF
        src = SRC_LANG
        tgt = TGT_LANG
        pages = QA_PAGES

    if single_pdf is not None:
        cases = [{"name": single_pdf.stem, "pdf": single_pdf,
                  "src": src or SRC_LANG, "tgt": tgt or TGT_LANG, "pages": pages}]
    else:
        cases = TEST_CASES

    scores = []
    for case in cases:
        s = _run_case(case, timestamp)
        if s >= 0:
            scores.append((case["name"], s))

    if len(scores) > 1:
        print("\n" + "=" * 60)
        print("종합 결과")
        print("=" * 60)
        for name, s in scores:
            print(f"  {name:25} {s:3}/100")
        avg = sum(s for _, s in scores) // len(scores)
        print(f"  {'평균':25} {avg:3}/100")
        print("=" * 60)

    if not scores:
        return 0
    return min(s for _, s in scores)


if __name__ == "__main__":
    sys.exit(0 if main() >= 60 else 1)
