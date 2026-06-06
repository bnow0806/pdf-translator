"""
QA Agent — 빌드 후 번역 품질 자동 평가
  - evaluation/ 폴더의 테스트 PDF를 번역 (첫 5페이지)
  - 빈 페이지 / 텍스트 겹침 / 최소 폰트 비율 측정
  - evaluation/qa_output/ 에 PNG + 리포트 저장
"""
import os, sys, threading, datetime
from pathlib import Path

import fitz  # PyMuPDF

# gui_translator의 독립 함수 임포트
sys.path.insert(0, str(Path(__file__).parent))
from gui_translator import (translate_paragraphs_parallel,
                            _wrap_lines, LINE_HEIGHT_RATIO, PARA_GAP_RATIO)

# ── 설정 ────────────────────────────────────────────────────────────────────
TEST_PDF   = Path(__file__).parent / "evaluation" / "_OceanofPDF.com_The_Geek_Way_-_Andrew_McAfee.pdf"
OUTPUT_DIR = Path(__file__).parent / "evaluation" / "qa_output"
QA_PAGES   = 346        # 번역할 페이지 수 (전체)
SRC_LANG   = "en"
TGT_LANG   = "ko"
MIN_FONT          = 6.0   # 폰트 크기 최소 임계치
OVERLAP_THRESHOLD = 5.0   # 겹침 최소 면적 (pt²)
MARGIN_MIN_PT     = 20.0  # 좌우 여백 최소값 (pt) — 이보다 좁으면 경고

KO_FONT_CANDIDATES = [
    "C:/Windows/Fonts/KoPubBatangMedium.ttf",
    "C:/Windows/Fonts/NanumMyeongjo.ttf",
    "C:/Windows/Fonts/HANBatang.ttf",
    "C:/Windows/Fonts/batang.ttc",
    "C:/Windows/Fonts/malgun.ttf",
]


# ── 번역 (gui_translator._worker 와 동일 로직) ───────────────────────────────
def translate_pdf(inp: Path, out: Path, max_pages: int):
    ko_font_path = next((f for f in KO_FONT_CANDIDATES if os.path.exists(f)), None)
    ko_font = fitz.Font(fontfile=ko_font_path) if ko_font_path else fitz.Font("cjk")
    cancel  = threading.Event()

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

    print(f"[2/3] 번역 중 ({SRC_LANG} → {TGT_LANG})...")
    translated = translate_paragraphs_parallel(
        all_texts, SRC_LANG, TGT_LANG,
        lambda d, t: print(f"  {d}/{t}", end="\r", flush=True),
        cancel,
    )
    print()

    print("[3/3] 텍스트 삽입 중...")

    SPECIAL_CHARS = 400
    page_img_rects = []
    special_pages  = set()
    for pidx in range(total):
        raw_blks = doc[pidx].get_text(
            "dict", flags=fitz.TEXT_PRESERVE_WHITESPACE | fitz.TEXT_PRESERVE_IMAGES
        )["blocks"]
        imgs = [fitz.Rect(b["bbox"]) for b in raw_blks if b.get("type") == 1]
        page_img_rects.append(imgs)
        if sum(len(blk["text"]) for blk in page_blocks[pidx]) < SPECIAL_CHARS:
            special_pages.add(pidx)

    # 원본 텍스트 일괄 제거
    for pidx in range(total):
        pblks = page_blocks[pidx]
        if not pblks: continue
        for blk in pblks:
            for sp in blk["spans"]:
                doc[pidx].add_redact_annot(fitz.Rect(sp["bbox"]), fill=None)
        doc[pidx].apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)

    def _content_area(pblks):
        if not pblks: return None
        bboxes = [blk["bbox"] for blk in pblks]
        return (min(b.x0 for b in bboxes), max(b.x1 for b in bboxes),
                min(b.y0 for b in bboxes), max(b.y1 for b in bboxes))

    page_areas = [_content_area(page_blocks[p]) for p in range(total)]
    valid = [a for a in page_areas if a]
    def _med(lst): s = sorted(lst); return s[len(s) // 2]
    std_area = (_med([a[0] for a in valid]), _med([a[1] for a in valid]),
                _med([a[2] for a in valid]), _med([a[3] for a in valid])) if valid \
               else (50, 550, 50, 750)

    regular_q   = []
    special_map = {}
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
            else:
                regular_q.append(item)

    page_w = doc[0].rect.width; page_h = doc[0].rect.height

    def _get_area(pidx):
        a = page_areas[pidx] if pidx < len(page_areas) and page_areas[pidx] else std_area
        ax0, ax1, ay0, ay1 = a
        if pidx < len(page_img_rects):
            col = fitz.Rect(ax0, 0, ax1, page_h)
            for img_r in page_img_rects[pidx]:
                if img_r.intersects(col) and img_r.y0 < ay1:
                    ay0 = max(ay0, img_r.y1 + 8)
        return ax0, ax1, ay0, ay1

    def _place(page, ax0, ax1, ay0, ay1, queue):
        y = ay0
        while queue:
            item = queue[0]
            size = item["size"]; lh = size * LINE_HEIGHT_RATIO; gap = size * PARA_GAP_RATIO
            bw   = max(ax1 - ax0, 1.0)
            if y + size > ay1: break
            lines = _wrap_lines(item["text"], bw, ko_font, size)
            tw    = fitz.TextWriter(page.rect, color=item["color"])
            rendered = 0
            for line in lines:
                if y + size > ay1: break
                tw.append((ax0, y + size), line, font=ko_font, fontsize=size)
                y += lh; rendered += 1
            tw.write_text(page)
            if rendered < len(lines):
                queue[0] = {**item, "text": " ".join(lines[rendered:])}; break
            else:
                queue.pop(0); y += gap

    pidx = 0
    while True:
        if not regular_q and not special_map: break
        if pidx >= len(doc):
            if not regular_q: break
            doc.new_page(width=page_w, height=page_h)
        page = doc[pidx]
        ax0, ax1, ay0, ay1 = _get_area(pidx)
        if pidx in special_pages and pidx < total:
            _place(page, ax0, ax1, ay0, ay1, special_map.pop(pidx, []))
        else:
            _place(page, ax0, ax1, ay0, ay1, regular_q)
        pidx += 1

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
        "total_orig_blocks":  0,
        "total_trans_blocks": 0,
        "issues": [],
    }

    for pidx in range(n):
        op = orig[pidx]
        tp = trans[pidx]

        orig_text  = op.get_text().strip()
        trans_text = tp.get_text().strip()

        # 빈 페이지 검사
        if orig_text and not trans_text:
            metrics["blank_pages"] += 1
            metrics["issues"].append(f"p{pidx+1}: 빈 페이지 (원문 {len(orig_text)}자)")

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
            metrics["issues"].append(f"p{pidx+1}: 텍스트 겹침 {overlaps}건")

        # 최소 폰트 비율 검사 (6pt 이하 스팬)
        all_spans = [sp for blk in trans_blks for line in blk["lines"] for sp in line["spans"] if sp["text"].strip()]
        tiny = [sp for sp in all_spans if sp["size"] <= MIN_FONT]
        if all_spans and len(tiny) / len(all_spans) > 0.3:
            metrics["tiny_font_pages"] += 1
            metrics["issues"].append(f"p{pidx+1}: 과소 폰트 스팬 {len(tiny)}/{len(all_spans)} ({len(tiny)*100//len(all_spans)}%)")

        # 이미지-텍스트 겹침 검사
        img_blks_t = [b for b in tp.get_text("dict")["blocks"] if b.get("type") == 1]
        if img_blks_t and all_spans:
            img_overlaps = 0
            for ib in img_blks_t:
                ir = fitz.Rect(ib["bbox"])
                for sp in all_spans:
                    sr = fitz.Rect(sp["bbox"])
                    if ir.intersects(sr) and (ir & sr).get_area() > 50:
                        img_overlaps += 1
            if img_overlaps:
                metrics["img_overlap_pages"] += 1
                metrics["issues"].append(f"p{pidx+1}: 이미지 위 텍스트 겹침 {img_overlaps}건")

        # 좌우 여백 검사 — 리플로우 후엔 절대 페이지 여백 기준으로 검사
        # (원본 span 비교는 리플로우로 인해 무의미해짐)
        page_w = tp.rect.width
        if all_spans:
            trans_left  = min(fitz.Rect(sp["bbox"]).x0 for sp in all_spans)
            trans_right = max(fitz.Rect(sp["bbox"]).x1 for sp in all_spans)
            if trans_left < MARGIN_MIN_PT or (page_w - trans_right) < MARGIN_MIN_PT:
                metrics["margin_pages"] += 1
                metrics["issues"].append(
                    f"p{pidx+1}: 여백 부족 "
                    f"(좌 {trans_left:.0f}pt / 우 {page_w - trans_right:.0f}pt)"
                )

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


# ── 메인 ─────────────────────────────────────────────────────────────────────
def main():
    timestamp   = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_pdf     = OUTPUT_DIR / f"translated_{timestamp}.pdf"
    png_dir     = OUTPUT_DIR / f"pages_{timestamp}"

    print("=" * 60)
    print(f"QA Agent  —  {timestamp}")
    print(f"입력: {TEST_PDF.name}")
    print(f"페이지: {QA_PAGES}p  |  언어: {SRC_LANG} → {TGT_LANG}")
    print("=" * 60)

    # 1. 번역
    translate_pdf(TEST_PDF, out_pdf, QA_PAGES)

    # 2. 평가
    print("\n[4/4] 품질 평가 중...")
    m = evaluate(TEST_PDF, out_pdf, QA_PAGES)

    # 3. PNG 렌더링
    pngs = render_pages(out_pdf, png_dir, QA_PAGES)

    # 4. 리포트
    block_coverage = (m["total_trans_blocks"] / max(m["total_orig_blocks"], 1)) * 100
    score = 100
    score -= m["blank_pages"]       * 20
    score -= m["overlap_pages"]     * 15
    score -= m["tiny_font_pages"]   * 10
    score -= m["margin_pages"]      *  5
    score -= m["img_overlap_pages"] * 10
    score = max(0, score)

    report_lines = [
        "=" * 60,
        f"QA 결과 - {timestamp}",
        "=" * 60,
        f"평가 페이지     : {m['pages']}p",
        f"블록 커버리지   : {m['total_trans_blocks']}/{m['total_orig_blocks']} ({block_coverage:.1f}%)",
        f"빈 페이지       : {m['blank_pages']}p",
        f"겹침 페이지     : {m['overlap_pages']}p",
        f"과소폰트 페이지 : {m['tiny_font_pages']}p",
        f"여백 초과 페이지: {m['margin_pages']}p",
        f"이미지겹침 페이지: {m['img_overlap_pages']}p",
        f"품질 점수       : {score}/100",
        "",
    ]
    if m["issues"]:
        report_lines.append("이슈:")
        report_lines.extend(f"  * {iss}" for iss in m["issues"])
    else:
        report_lines.append("이슈 없음")
    report_lines += [
        "",
        f"번역 PDF : {out_pdf}",
        f"PNG 출력 : {png_dir}",
        "=" * 60,
    ]
    report = "\n".join(report_lines)
    print("\n" + report)

    # 리포트 파일 저장
    report_path = OUTPUT_DIR / f"report_{timestamp}.txt"
    report_path.write_text(report, encoding="utf-8")

    return score


if __name__ == "__main__":
    sys.exit(0 if main() >= 60 else 1)
