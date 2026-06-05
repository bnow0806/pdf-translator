# PDF 번역기

PDF 파일을 Google 번역으로 자동 번역하는 데스크톱 앱입니다.  
**API 키 불필요 · 무료 · 설치 없이 exe 파일 하나로 실행**

---

## 주요 기능

| 기능 | 설명 |
|---|---|
| **다이어그램 번역** | 순서도·플로우차트 내부 텍스트까지 번역 (pdf2docx 방식 대비 핵심 개선) |
| 포맷·이미지 보존 | 배경 도형·이미지 유지, 텍스트만 교체 |
| 빠른 번역 | 블록 묶음 병렬 처리 (6개 동시 요청) |
| 드래그 앤 드롭 | PDF를 창에 끌어다 놓으면 바로 선택 |
| PDF 직접 출력 | Word / LibreOffice 불필요, PyMuPDF로 직접 저장 |
| 진행률 표시 | 60fps easing 애니메이션, 타임스탬프 로그 |
| 설정 자동 저장 | 마지막 언어 설정 자동 기억 |

---

## 실행 방법

### 바로 실행 (권장)

```
dist/PDF-번역기.exe
```

별도 설치 없이 더블클릭으로 실행됩니다.

### 소스에서 실행

```bash
pip install -r requirements.txt
python gui_translator.py
```

---

## 사용법

1. **PDF 파일 선택** — 드래그 앤 드롭 또는 [클릭하여 선택]
2. **출력 경로 확인** — 자동 설정됨, 필요 시 변경
3. **언어 설정** — 소스 언어(자동 감지 가능), 타겟 언어 선택
4. **번역 시작** 클릭
5. 완료 후 PDF 파일이 지정 경로에 저장됨

---

## 번역 처리 흐름

```
PDF 입력
  ↓ [1/3] PyMuPDF  →  전체 텍스트 스팬 추출 (다이어그램 포함)
  ↓ [2/3] Google 번역  →  블록 묶음 병렬 번역 (6개 동시)
  ↓ [3/3] PyMuPDF  →  원위치 텍스트 교체, PDF 직접 저장
번역된 PDF 출력
```

---

## 출력 방식

- 원본 텍스트를 제거(`redact`)하고 같은 위치에 번역 텍스트 삽입
- 배경 도형·이미지는 `PDF_REDACT_IMAGE_NONE` 플래그로 보존
- 폰트: Windows 맑은 고딕 / 굴림 / 바탕 중 존재하는 폰트 자동 사용
- 블록 내 최소 폰트 크기 기준으로 삽입, bbox 초과 시 0.5pt씩 축소 (최소 6pt)

---

## 요구 사항

### 실행 환경
- Windows 10 / 11 (64비트)
- Microsoft Word **불필요** (PyMuPDF로 직접 저장)
- Windows 한글 폰트 (맑은 고딕 / 굴림 / 바탕 중 하나) 권장

### 소스 실행 시 패키지

```bash
pip install -r requirements.txt
```

```
# requirements.txt
requests>=2.31.0
deep-translator
tkinterdnd2>=0.4.0
customtkinter>=5.2.2
PyMuPDF
```

---

## exe 빌드 방법

```bash
python -m PyInstaller gui_translator.spec --clean
```

빌드된 파일: `dist/PDF-번역기.exe` (약 100 MB)

---

## 주의 사항

- **스캔 PDF (이미지 PDF)** 는 텍스트 추출이 되지 않아 번역되지 않습니다
- 번역 텍스트가 원본보다 길면 폰트 크기를 자동으로 줄여 원본 위치에 맞춥니다 (최소 6pt)
- Google 번역 무료 사용으로 **일일 요청량이 많을 경우 일시적으로 제한**될 수 있습니다

---

## 파일 구조

```
pdf-translator/
├── gui_translator.py     # 메인 애플리케이션
├── gui_translator.spec   # PyInstaller 빌드 설정
├── requirements.txt      # 패키지 목록
├── README.md
├── ref_design.png        # 출력 스타일 참고 디자인
├── docs/
│   └── 개발_히스토리.md  # 전체 개발 과정 기록
└── dist/
    └── PDF-번역기.exe    # 빌드된 실행 파일
```

---

## 번역 속도 (참고)

| 단계 | 282페이지 기준 |
|---|---|
| 텍스트 추출 | 수 초 |
| 번역 (병렬) | 1 ~ 3분 |
| PDF 저장 | 수 초 ~ 1분 |
| **총계** | **약 2 ~ 5분** |

---

## 라이선스

개인·사내 사용 목적으로 자유롭게 사용 가능합니다.  
Google 번역 사용 시 [Google 서비스 약관](https://policies.google.com/terms)을 따릅니다.
