# PDF 번역기

PDF 파일을 Google 번역으로 자동 번역하는 데스크톱 앱입니다.  
**API 키 불필요 · 무료 · 설치 없이 exe 파일 하나로 실행**

---

## 주요 기능

| 기능 | 설명 |
|---|---|
| 포맷 보존 | 표·이미지·폰트 크기·굵기 유지 |
| 전자책 스타일 | 본문 바탕(세리프) / 제목 맑은 고딕 자동 구분 |
| 각주 위첨자 복원 | 번역 후에도 ⁷ ⁸ 등 각주 번호를 위첨자로 유지 |
| 가독성 최적화 | 줄 간격 1.4배 · 단락 여백 · bold 제거 · 크기 조정 |
| 빠른 번역 | 단락 묶음 병렬 처리 (6개 동시 요청, 기존 대비 30~50배 향상) |
| 드래그 앤 드롭 | PDF를 창에 끌어다 놓으면 바로 선택 |
| PDF 출력 | 번역 완료 시 PDF로 직접 저장 (Word 활용) |
| 진행률 표시 | 변환 → 번역 → 저장 단계별 % 실시간 표시 |
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
  ↓ [1/3] pdf2docx  →  임시 DOCX (텍스트·그림·표 구조 보존)
  ↓ [2/3] Google 번역  →  단락 묶음 병렬 번역 (6개 동시)
  ↓ [3/3] Microsoft Word  →  PDF 저장
번역된 PDF 출력
```

---

## 출력 문서 스타일

| 항목 | 값 |
|---|---|
| 본문 폰트 | **바탕** (세리프, 긴 글 가독성 최적) |
| 제목 폰트 | **맑은 고딕** (16pt 이상 텍스트에 자동 적용) |
| 본문 굵기 | bold 강제 해제 (원본 PDF bold 잔재 제거) |
| 본문 크기 | 원본 −2pt 축소 (최소 9pt) |
| 줄 간격 | 1.25배 |
| 본문 단락 여백 | 0pt (페이지 수 최적화) |
| 제목 단락 여백 | 전 3pt / 후 4pt |
| 각주 번호 | 위첨자(⁷ ⁸)로 복원 |

---

## 요구 사항

### 실행 환경
- Windows 10 / 11 (64비트)
- Microsoft Word 설치 필요 (PDF 저장 단계에서 사용)
  - Word가 없으면 자동으로 LibreOffice → DOCX 순서로 폴백

### 소스 실행 시 패키지

```
pip install -r requirements.txt
```

```
# requirements.txt
requests>=2.31.0
deep-translator>=1.11.0
pdf2docx>=0.5.6
python-docx>=1.1.0
tkinterdnd2>=0.4.0
pywin32>=306
docx2pdf>=0.1.8
numpy
opencv-python-headless
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
- **복잡한 다단 레이아웃**은 변환 시 근사치로 재현됩니다
- Google 번역 무료 사용으로 **일일 요청량이 많을 경우 일시적으로 제한**될 수 있습니다
- PDF → PDF 변환에 **Microsoft Word**가 필요합니다 (없으면 DOCX 출력)
- Word PDF 변환은 **문서 크기에 따라 수 초~수 분** 소요됩니다

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

| 단계 | 347페이지 기준 |
|---|---|
| PDF → DOCX 변환 | 2 ~ 5분 |
| 번역 (2000+ 단락, 병렬) | 1 ~ 3분 |
| DOCX → PDF 저장 (Word) | 1 ~ 3분 |
| **총계** | **약 5 ~ 10분** |

---

## 라이선스

개인·사내 사용 목적으로 자유롭게 사용 가능합니다.  
Google 번역 사용 시 [Google 서비스 약관](https://policies.google.com/terms)을 따릅니다.
