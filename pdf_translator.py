#!/usr/bin/env python3
"""
DeepL 기반 PDF 번역기
- DeepL Document Translation API로 레이아웃 보존 번역 (기본)
- 텍스트 추출 후 번역 모드 (--text-mode)
"""

import argparse
import os
import sys

# Windows 콘솔 UTF-8 설정
if sys.platform == "win32":
    import ctypes
    ctypes.windll.kernel32.SetConsoleOutputCP(65001)
    ctypes.windll.kernel32.SetConsoleCP(65001)
    # Python stdout/stderr 인코딩도 UTF-8로 재설정
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
import time
from pathlib import Path


def check_dependencies(text_mode: bool = False) -> None:
    missing = []
    try:
        import deepl  # noqa: F401
    except ImportError:
        missing.append("deepl")

    if text_mode:
        try:
            import pdfplumber  # noqa: F401
        except ImportError:
            missing.append("pdfplumber")
        try:
            from fpdf import FPDF  # noqa: F401
        except ImportError:
            missing.append("fpdf2")

    if missing:
        print("필수 패키지 누락:", ", ".join(missing))
        print("설치 명령어:")
        print(f"  pip install {' '.join(missing)}")
        sys.exit(1)


def get_translator(api_key: str):
    import deepl
    try:
        translator = deepl.Translator(api_key)
        usage = translator.get_usage()
        if usage.character.limit_exceeded:
            print("경고: DeepL API 문자 한도를 초과했습니다.")
        else:
            remaining = usage.character.limit - usage.character.count
            print(f"API 잔여 문자: {remaining:,} / {usage.character.limit:,}")
        return translator
    except deepl.AuthorizationException:
        print("오류: API 키가 유효하지 않습니다.")
        print("  https://www.deepl.com/ko/account/summary 에서 확인하세요.")
        sys.exit(1)
    except Exception as e:
        print(f"DeepL 연결 오류: {e}")
        sys.exit(1)


def translate_document_mode(
    input_path: Path,
    output_path: Path,
    translator,
    source_lang: str | None,
    target_lang: str,
) -> None:
    """DeepL 문서 번역 API — 레이아웃·이미지·표 보존"""
    import deepl

    print(f"\n번역 중 (문서 모드): {input_path.name}")
    print(f"  언어: {source_lang or '자동감지'} → {target_lang}")

    try:
        translator.translate_document_from_filepath(
            str(input_path),
            str(output_path),
            source_lang=source_lang if source_lang else None,
            target_lang=target_lang,
        )
        print(f"완료: {output_path}")
    except deepl.DocumentTranslationException as e:
        print(f"문서 번역 오류: {e}")
        print("텍스트 모드로 재시도하려면 --text-mode 옵션을 사용하세요.")
        sys.exit(1)
    except deepl.QuotaExceededException:
        print("오류: API 한도를 초과했습니다. 다음 달까지 기다리거나 Pro 플랜으로 업그레이드하세요.")
        sys.exit(1)
    except Exception as e:
        print(f"오류: {e}")
        sys.exit(1)


def translate_text_mode(
    input_path: Path,
    output_path: Path,
    translator,
    source_lang: str | None,
    target_lang: str,
    chunk_size: int = 4500,
) -> None:
    """텍스트 추출 → 번역 → PDF 재생성 (레이아웃 단순화)"""
    import pdfplumber
    from fpdf import FPDF

    print(f"\n번역 중 (텍스트 모드): {input_path.name}")
    print(f"  언어: {source_lang or '자동감지'} → {target_lang}")
    print("  ※ 레이아웃이 단순화됩니다. 이미지·표는 포함되지 않습니다.")

    # 1. PDF에서 텍스트 추출
    print("\n[1/3] 텍스트 추출 중...")
    pages_text: list[str] = []
    with pdfplumber.open(str(input_path)) as pdf:
        total = len(pdf.pages)
        for i, page in enumerate(pdf.pages, 1):
            text = page.extract_text() or ""
            pages_text.append(text)
            print(f"  페이지 {i}/{total} 추출", end="\r")
    print(f"  {total}페이지 추출 완료        ")

    # 2. DeepL로 번역 (청크 단위)
    print("\n[2/3] 번역 중...")
    pages_translated: list[str] = []

    for page_num, text in enumerate(pages_text, 1):
        if not text.strip():
            pages_translated.append("")
            continue

        translated_chunks: list[str] = []
        # 긴 텍스트를 청크로 분할
        paragraphs = text.split("\n\n")
        current_chunk = ""

        for para in paragraphs:
            if len(current_chunk) + len(para) < chunk_size:
                current_chunk += para + "\n\n"
            else:
                if current_chunk.strip():
                    result = translator.translate_text(
                        current_chunk,
                        source_lang=source_lang if source_lang else None,
                        target_lang=target_lang,
                    )
                    translated_chunks.append(result.text)
                    time.sleep(0.1)  # API 속도 제한 방지
                current_chunk = para + "\n\n"

        if current_chunk.strip():
            result = translator.translate_text(
                current_chunk,
                source_lang=source_lang if source_lang else None,
                target_lang=target_lang,
            )
            translated_chunks.append(result.text)

        pages_translated.append("\n\n".join(translated_chunks))
        print(f"  페이지 {page_num}/{total} 번역 완료", end="\r")

    print(f"  {total}페이지 번역 완료        ")

    # 3. PDF 생성
    print("\n[3/3] PDF 생성 중...")
    _create_pdf(pages_translated, output_path, target_lang)
    print(f"완료: {output_path}")


def _find_korean_font() -> str | None:
    """시스템에서 한글 폰트 경로를 찾아 반환"""
    candidates = [
        # Windows
        "C:/Windows/Fonts/malgun.ttf",
        "C:/Windows/Fonts/malgunbd.ttf",
        "C:/Windows/Fonts/gulim.ttc",
        # Ubuntu/Debian (fonts-nanum)
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
        "/usr/share/fonts/truetype/nanum/NanumBarunGothic.ttf",
        # Noto CJK
        "/usr/share/fonts/opentype/noto/NotoSansCJKkr-Regular.otf",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        # macOS
        "/Library/Fonts/Arial Unicode MS.ttf",
        "/System/Library/Fonts/AppleSDGothicNeo.ttc",
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


def _create_pdf(pages: list[str], output_path: Path, target_lang: str) -> None:
    from fpdf import FPDF

    needs_cjk = target_lang.upper() in ("KO", "ZH", "JA")

    font_path = None
    if needs_cjk:
        font_path = _find_korean_font()
        if not font_path:
            print(
                "\n  경고: 한글 폰트를 찾을 수 없습니다. 한글이 깨질 수 있습니다."
                "\n  해결: pip install 후 나눔폰트 설치 (Ubuntu: sudo apt install fonts-nanum)"
                "\n        또는 malgun.ttf 등 TTF 폰트 경로를 --font-path 옵션으로 지정하세요."
            )

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)

    if font_path:
        pdf.add_font("KoreanFont", "", font_path, uni=True)
        body_font = "KoreanFont"
    else:
        body_font = "Arial"

    for page_text in pages:
        pdf.add_page()
        pdf.set_font(body_font, size=10)
        # 줄 단위로 추가
        for line in page_text.split("\n"):
            if line.strip():
                pdf.multi_cell(0, 6, line)
            else:
                pdf.ln(3)

    pdf.output(str(output_path))


def list_languages(translator) -> None:
    """지원 언어 목록 출력"""
    print("\n[소스 언어]")
    for lang in translator.get_source_languages():
        print(f"  {lang.code:10} {lang.name}")
    print("\n[타겟 언어]")
    for lang in translator.get_target_languages():
        print(f"  {lang.code:10} {lang.name}")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="pdf-translator",
        description="DeepL API를 사용한 PDF 번역기",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  # 기본 사용 (영어 → 한국어, 레이아웃 보존)
  python pdf_translator.py report.pdf

  # 출력 파일 지정
  python pdf_translator.py report.pdf -o report_ko.pdf

  # 언어 직접 지정
  python pdf_translator.py doc.pdf -s EN -t KO

  # 텍스트 추출 모드 (레이아웃 단순)
  python pdf_translator.py report.pdf --text-mode

  # 지원 언어 목록 확인
  python pdf_translator.py --list-languages

  # API 키를 환경변수로 설정
  export DEEPL_API_KEY="your-api-key"
  python pdf_translator.py report.pdf

DeepL API 키 발급:
  1. https://www.deepl.com/ko/account/summary 접속
  2. 회원가입 후 'API' 탭 → API 키 복사
  3. 무료 플랜: 월 500,000자 무료
""",
    )

    parser.add_argument("input", nargs="?", help="입력 PDF 파일 경로")
    parser.add_argument("-o", "--output", help="출력 파일 경로 (기본: 입력파일명_번역.pdf)")
    parser.add_argument(
        "-k", "--api-key",
        help="DeepL API 키 (또는 환경변수 DEEPL_API_KEY 사용)",
    )
    parser.add_argument(
        "-s", "--source",
        default=None,
        metavar="LANG",
        help="소스 언어 코드 (기본: 자동감지). 예: EN, JA, DE",
    )
    parser.add_argument(
        "-t", "--target",
        default="KO",
        metavar="LANG",
        help="타겟 언어 코드 (기본: KO)",
    )
    parser.add_argument(
        "--text-mode",
        action="store_true",
        help="텍스트 추출 모드 - 레이아웃 단순화, pdfplumber+fpdf2 필요",
    )
    parser.add_argument(
        "--list-languages",
        action="store_true",
        help="지원 언어 목록 출력 후 종료",
    )

    args = parser.parse_args()

    # API 키 확인
    api_key = args.api_key or os.environ.get("DEEPL_API_KEY")
    if not api_key:
        print("오류: DeepL API 키가 필요합니다.")
        print("\n방법 1: --api-key 옵션 사용")
        print("  python pdf_translator.py report.pdf --api-key YOUR_KEY")
        print("\n방법 2: 환경변수 설정")
        print("  Windows PowerShell: $env:DEEPL_API_KEY='YOUR_KEY'")
        print("  Linux/macOS:        export DEEPL_API_KEY='YOUR_KEY'")
        print("\nDeepL API 키 발급: https://www.deepl.com/ko/account/summary")
        sys.exit(1)

    check_dependencies(text_mode=args.text_mode)
    translator = get_translator(api_key)

    if args.list_languages:
        list_languages(translator)
        return

    if not args.input:
        parser.print_help()
        sys.exit(1)

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"오류: 파일을 찾을 수 없습니다 — {input_path}")
        sys.exit(1)
    if input_path.suffix.lower() != ".pdf":
        print(f"경고: PDF 파일이 아닐 수 있습니다 — {input_path.suffix}")

    # 출력 경로
    if args.output:
        output_path = Path(args.output)
    else:
        stem = input_path.stem
        suffix = input_path.suffix
        target = args.target.lower()
        output_path = input_path.parent / f"{stem}_{target}{suffix}"

    target_lang = args.target.upper()
    source_lang = args.source.upper() if args.source else None

    if args.text_mode:
        translate_text_mode(input_path, output_path, translator, source_lang, target_lang)
    else:
        translate_document_mode(input_path, output_path, translator, source_lang, target_lang)


if __name__ == "__main__":
    main()
