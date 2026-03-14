# 한글 표시 분석 및 조치 (NutriSort AI)

> 한글을 기본으로 하고, 영어·불어 등은 추후 확대하는 전제로 분석·수정한 내용입니다.

---

## 1. 원인 분석 요약

한글이 제대로 안 보일 수 있는 지점을 다음처럼 정리했습니다.

| 구분 | 가능 원인 | 확인 내용 |
|------|-----------|-----------|
| **1. 폰트** | Streamlit/브라우저 기본 폰트에 한글 글리프가 없음 | 서버 기본 폰트가 한글을 지원하지 않으면 □ 또는 깨진 글자로 표시됨. |
| **2. 인코딩** | 서버·stdout이 UTF-8이 아님 (Railway 등 Linux) | Python 3는 기본 UTF-8이지만, 환경에 따라 stdout/stderr 인코딩이 달라질 수 있음. |
| **3. HTML/CSS** | 페이지 전체에 한글 지원 폰트가 적용되지 않음 | `st.markdown`(HTML), Streamlit 위젯, CSS `content` 등이 같은 폰트 정책을 쓰지 않을 수 있음. |
| **4. 기본 언어** | 언어 선택 기본값이 한글이 아님 | 사용자가 선택하지 않았을 때 한글(KO)이 선택되도록 명시 필요. |
| **5. 소스 인코딩** | app.py가 UTF-8이 아님 | Windows 등에서 다른 인코딩으로 저장되면 소스 내 한글 리터럴이 깨질 수 있음. |

---

## 2. 적용한 조치

### 2.1 소스·실행 환경 UTF-8 고정

- **app.py 최상단**
  - `# -*- coding: utf-8 -*-` 추가 → 소스 파일을 UTF-8로 해석하도록 명시.
- **표준 출력/에러**
  - `sys.stdout.reconfigure(encoding="utf-8")`, `sys.stderr.reconfigure(encoding="utf-8")` 호출 (가능한 경우만)  
  → Railway 등 Linux에서 한글 로그·출력 깨짐 방지.

### 2.2 전역 한글 폰트 적용

- **Google Fonts**
  - `Noto Sans KR` (400, 500, 700) 로드:
    - `@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;700&display=swap');`
- **전역 폰트 지정**
  - Streamlit 앱 영역과 자주 쓰는 요소에 동일 폰트 적용:
    - `.stApp`, `.stMarkdown`, `p`, `span`, `label`, `[data-testid]`, 파일 업로더 `::after` 등
  - 폰트 스택: `"Noto Sans KR", "Malgun Gothic", "Apple SD Gothic Neo", "Nanum Gothic", sans-serif`
  - 한글 UI 텍스트와 CSS `content`(예: "식단 스캔시작")가 같은 한글 지원 폰트를 쓰도록 맞춤.

### 2.3 기본 언어 한글(KO)로 고정

- 사이드바 언어 선택
  - `st.radio("언어 / Language", ["KO", "EN"], index=0)` 로 **항상 첫 선택값 = KO(한국어)**.
  - 제목을 "설정"으로 두어, 처음 보는 사용자에게 한글이 기본임을 드러냄.

---

## 3. 그대로 둔 부분 (추가 변경 없음)

- **Gemini API**
  - `lang == "KO"` 일 때 이미 한글 프롬프트 사용 → 응답도 한글로 받는 구조. 별도 인코딩 처리 없음.
- **Firestore**
  - Python 3 기준으로 문자열은 유니코드로 저장·조회되므로, 한글 필드 별도 인코딩 조치 없음.
- **docs/index.html**
  - 이미 `<meta charset="UTF-8">`, `<html lang="ko">` 사용 중 → iframe 부모 페이지는 UTF-8·한국어 설정 유지.

---

## 4. 추후 다국어(영어·불어 등) 확대 시

- `texts` 사전에 `"EN"`, `"FR"` 등을 추가하고, 언어별로 동일 키를 쓰면 됨.
- 폰트는 현재 전역에 Noto Sans KR을 썼기 때문에, 영어/불어도 같은 폰트로 표시되며, 필요 시 언어별로 `font-family`만 추가하면 됨.

---

*문서 버전: 1.0 | 한글 표시 분석·조치*
