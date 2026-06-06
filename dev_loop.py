"""
dev_loop.py - QA 결과를 분석해 개발 피드백을 출력하는 스크립트
  사용: python dev_loop.py <qa_report_path>
  - QA 리포트를 읽어 이슈를 분석하고 다음 수정 방향을 출력
  - 점수 >= PASS_SCORE 이면 "PASS: 배포 준비 완료" 출력 후 exe 빌드 트리거
"""
import sys, re, subprocess
from pathlib import Path

PASS_SCORE   = 60   # 이 점수 이상이면 배포 준비 완료
PROJECT_ROOT = Path(__file__).parent


def parse_report(report_path: Path) -> dict:
    text = report_path.read_text(encoding="utf-8")

    def grab(pattern, default=None):
        m = re.search(pattern, text)
        return m.group(1) if m else default

    score        = int(grab(r"품질 점수\s*:\s*(\d+)/100", "0"))
    blank_pages  = int(grab(r"빈 페이지\s*:\s*(\d+)", "0"))
    overlap_pages= int(grab(r"겹침 페이지\s*:\s*(\d+)", "0"))
    tiny_pages   = int(grab(r"과소폰트 페이지\s*:\s*(\d+)", "0"))
    coverage_str = grab(r"블록 커버리지\s*:\s*[\d/]+\s*\(([\d.]+)%\)", "0")
    coverage     = float(coverage_str)

    issues = re.findall(r"  • (.+)", text)

    return {
        "score":         score,
        "blank_pages":   blank_pages,
        "overlap_pages": overlap_pages,
        "tiny_pages":    tiny_pages,
        "coverage":      coverage,
        "issues":        issues,
    }


def diagnose(m: dict) -> list[str]:
    """이슈 → 수정 방향 제안 목록 반환"""
    suggestions = []

    if m["blank_pages"] > 0:
        suggestions.append(
            f"[빈 페이지 {m['blank_pages']}p] "
            "insert_textbox가 bbox 외부에 텍스트를 삽입하지 못함. "
            "insert_bbox y1 확장 로직 확인"
        )

    if m["overlap_pages"] > 0:
        suggestions.append(
            f"[겹침 {m['overlap_pages']}p] "
            "인접 블록 bbox가 겹치거나 lineheight가 너무 작음. "
            "lineheight 값 증가 또는 블록 정렬 로직 재검토"
        )

    if m["tiny_pages"] > 0:
        suggestions.append(
            f"[과소폰트 {m['tiny_pages']}p] "
            "번역문이 확장 bbox에서도 넘침, 폰트 크기 또는 페이지 margin 재조정"
        )

    if m["coverage"] < 70:
        suggestions.append(
            f"[커버리지 {m['coverage']:.1f}%] "
            "번역 블록 수가 원문 대비 적음. "
            "텍스트 추출 조건(type==0 필터, empty span 필터) 재검토"
        )

    if not suggestions:
        suggestions.append("이슈 없음 - 배포 준비 완료")

    return suggestions


def build_exe():
    print("\n[BUILD] PyInstaller 빌드 시작...")
    result = subprocess.run(
        [".venv\\Scripts\\python.exe", "-m", "PyInstaller",
         "gui_translator.spec", "--clean"],
        cwd=str(PROJECT_ROOT),
        capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    if "Build complete" in result.stdout or "Build complete" in result.stderr:
        print("[BUILD] 빌드 완료 - dist/PDF-번역기.exe")
        return True
    print("[BUILD] 빌드 실패")
    print(result.stderr[-2000:])
    return False


def main():
    if len(sys.argv) < 2:
        # 최신 리포트 자동 탐색
        reports = sorted(
            (PROJECT_ROOT / "evaluation" / "qa_output").glob("report_*.txt"),
            key=lambda p: p.stat().st_mtime, reverse=True
        )
        if not reports:
            print("리포트 파일을 찾을 수 없습니다. qa_agent.py를 먼저 실행하세요.")
            sys.exit(1)
        report_path = reports[0]
    else:
        report_path = Path(sys.argv[1])

    print(f"리포트 분석: {report_path.name}")
    m = parse_report(report_path)

    print(f"\n점수: {m['score']}/100")
    print(f"빈 페이지: {m['blank_pages']}  겹침: {m['overlap_pages']}  "
          f"과소폰트: {m['tiny_pages']}  커버리지: {m['coverage']:.1f}%")

    suggestions = diagnose(m)
    print("\n── 개발 피드백 ──────────────────────────────")
    for s in suggestions:
        print(f"  - {s}")

    if m["score"] >= PASS_SCORE:
        print(f"\n[PASS] 점수 {m['score']} >= {PASS_SCORE} -- exe 빌드 시작")
        build_exe()
        sys.exit(0)
    else:
        print(f"\n[FAIL] 점수 {m['score']} < {PASS_SCORE} -- 수정 후 재실행 필요")
        sys.exit(1)


if __name__ == "__main__":
    main()
