# NutriSort / 혈당스캐너 — 마스터 아키텍처 & UI/UX 블루프린트

> 신규 CTO·개발자용 요약. 코드 전체가 아닌 **구조·흐름·레이아웃** 중심.

---

## 1. 기술 스택 및 환경 (Tech Stack)

### 프레임워크·런타임
| 구분 | 내용 |
|------|------|
| UI / 서버 | **Streamlit** (`streamlit>=1.28,<2`) — 단일 `app.py` 기반 풀스택 UI |
| Python | `runtime.txt` 기준 (배포 환경과 동일하게 맞출 것) |

### 주요 라이브러리 (`requirements.txt` 기준)
| 패키지 | 역할 |
|--------|------|
| **google-genai** (≥1.0.0) | Gemini Developer API — `genai.Client`, `models.generate_content` |
| **firebase-admin** | Firestore · Firebase Storage |
| **google-cloud-firestore / storage** | 서버측 DB·스토리지 클라이언트 |
| **Pillow** | 이미지 압축·리사이즈 |
| **plotly** | 리포트 차트 |
| **requests** | Firebase Auth REST, OAuth 토큰 교환 등 |
| **pytz**, **Babel** | 타임존·로케일 표시 |
| **pandas** | 데이터 처리(보조) |

### 외부 연동·시크릿
- **Firebase**: 이메일/비밀번호·구글 OAuth, Firestore, Storage (`st.secrets` / 환경변수)
- **Gemini API**: `GEMINI_API_KEY` 필수
- **선택 환경변수**: `GEMINI_VISION_MODEL` — 미설정 시 아래 모델 순으로 폴백

### AI 모델명 (멀티모달·식단 이미지 분석)
- **1순위**: `gemini-2.5-flash`
- **2순위**: `gemini-2.0-flash`
- `GEMINI_VISION_MODEL`이 설정되면 해당 ID를 후보 리스트 맨 앞에 삽입(중복 제거)
- **Gemini 1.5·`*-vision` 접미사 모델은 코드에서 사용하지 않음(폐기 반영)**

---

## 2. 디렉토리 및 파일 구조 (Directory Tree)

```
suger/
├── app.py                 # 앱 전부: 인증, 포털, 스캐너, 혈당입력, 리포트, 설정, CSS 인라인, Plotly, FAB
├── translation.py         # LANG_DICT, SUPPORTED_LANGS, get_text() — UI 문자열
├── prompts.py             # Gemini용 음식 매크로 포맷 + 조언(4단계) 프롬프트
├── requirements.txt
├── runtime.txt
├── .streamlit/config.toml
├── nixpacks.toml          # 일부 호스팅용
├── scripts/               # CORS, 서비스계정 키 등 운영 스크립트
└── docs/                  # 배포·스토리지·본 문서 등
```

| 파일 | 역할 요약 |
|------|-----------|
| **app.py** | 단일 진입점. 세션 상태(`current_page`, `app_stage`, `login_type` …), Firestore CRUD, Gemini 호출, 리포트 탭·차트, 모바일 CSS·FAB HTML |
| **translation.py** | 언어별 키-값 딕셔너리; 로그인 전 언어 선택·설정 화면에서 `st.session_state["lang"]` 갱신 |
| **prompts.py** | `get_analysis_prompt(lang)` → (음식 줄 단위 파싱용 프롬프트, 조언 프롬프트) |
| **style.css** | 없음 — 스타일은 `app.py` 내 `st.markdown(..., unsafe_allow_html=True)` 로 주입 |

---

## 3. 데이터베이스 스키마 (Firebase Firestore)

### 컬렉션 경로 요약

| 경로 | 용도 |
|------|------|
| `users/{uid}/glucose` | 혈당 기록 (공복/식후) |
| `users/{uid}/history` | 식단 분석 결과 스냅샷(정렬 항목, 조언, 점수 등) |
| `user_logs` | 식단 저장 시 리포트·통계용 로그(탄수화물 등). `user_id` + `timestamp`로 쿼리 |

### 주요 필드 (개념)

**`users/{uid}/glucose` (문서 자동 ID)**  
- `type`: `"fasting"` \| `"postprandial"`  
- `value`: int (mg/dL)  
- **`timestamp`**: **Native Timestamp** 권장 — Python timezone-aware `datetime`(UTC) 또는 `SERVER_TIMESTAMP`. 문자열 timestamp는 범위 쿼리에서 제외될 수 있음.  
- `note`: optional string  

**`users/{uid}/history/{docId}`**  
- `date`, `saved_at_utc`, `sorted_items`[], `advice`, `blood_sugar_score`, `total_carbs`, `total_protein`, `total_fat`, `total_kcal`, `avg_gi`, `image_url` 등  

**`user_logs` (자동 ID)**  
- `user_id`, `history_doc_id`, `timestamp` (**서버 기준 UTC** 등), `total_carbs`, `blood_sugar_score`, `sorted_items`, `advice`, `image_url` …  
- 리포트 하단 **탄수화물 막대**는 이 컬렉션의 `total_carbs`를 기간별로 집계.

---

## 4. 모바일 UI/UX 및 화면 레이아웃 (Screen Flow)

### 전역 레이아웃
- **헤더/푸터**: `#MainMenu`, `footer`, `[data-testid="stHeader"]`, 배포 배지 등 **숨김** → 네이티브 앱 느낌.
- **모바일(≤768px)**: `.block-container` **상·좌·우 패딩 축소**, 하단 **FAB 여백**(`padding-bottom` 확보).

### 지표 2×2 (리포트 등)
- **Metric이 들어 있는 가로 블록**에 한해, 모바일에서 `flex`로 **약 50% 폭 2열**을 유지하도록 CSS `:has([data-testid="stMetric"])` 사용.
- 리포트 상단: 식단 수 / 평균 탄수화물 / 혈당 평균 / 기간 탄수화물 합 — **2행×2열** 배치.

### FAB (플로팅 액션)
- **구현**: 고정 위치 CSS(`.nutri-fab-wrap`) + **일반 `<a href="?fab=scan">` / `?fab=glucose`**.  
- **라우팅**: 페이지 로드 시 `st.query_params`에 `fab`이 있으면  
  - `scan` → `current_page=diet_scan`, `nav_menu=scanner`  
  - `glucose` → `current_page=glucose_input`  
  이후 `query_params.clear()` + `st.rerun()`.  
- 모바일: 하단 **중앙 가로 2버튼**; 데스크톱: **우측 세로** 스택.

### 리포트 화면 — 4탭

| 탭 | 기간·입력 UI | 혈당 데이터 | 차트 |
|----|----------------|-------------|------|
| **일간** | `date_input` (한국일 기준 하루) | 전체 유형 | `make_subplots` 2행, 상단 `Scatter`(lines+markers+text), 하단 `Bar`(탄수화물). **shared_xaxes=True**. X 상단: 시간 `%H:%M`. |
| **주간** | 시작일 → +7일 고정 | **공복(`fasting`)만** | X `%m/%d` |
| **월간** | 연·월 select | **공복만** | X `%Y-%m` |
| **월별 평균 공복** | 기간 pills(3M/6M/1Y/2Y/직접 연월) | 공복만 월별 평균 | 단일 `Figure` Scatter, X `%y.%m` |

**공통 Plotly 설정(요약)**  
- `use_container_width=True`, `margin` 소형(l/r/t/b), **Safe Zone**: 혈당 Y축 **90~140** `add_hrect` 연한 초록.  
- 점 색: **140 초과 빨강, 이하 파랑**.  
- 범례: 가로 배치·하단 근처(서브플롯은 `showlegend` + legend 옵션).  
- 데이터 없을 때 **최근 glucose 5건** 폴백 표시(일부 탭).

---

## 5. 핵심 비즈니스 로직 (Core Logic)

### 5.1 데이터 저장 흐름 (혈당)
1. UI에서 **한국 시간** 기준 날짜·시간 선택 → `datetime` 결합 → **UTC**로 변환.  
2. `_save_glucose(uid, type, value, timestamp=utc_dt)`  
   - 명시 timestamp → Firestore에 **datetime 그대로** → Native Timestamp.  
   - 없으면 **`SERVER_TIMESTAMP`**.  
3. 저장 성공 시 `get_today_summary` / `get_glucose_meals_cached` 등 **캐시 무효화**.

### 5.2 비전 AI 분석 흐름 (식단)
1. **업로드** → PIL 압축 → `st.session_state['current_img']`, `app_stage='analyze'`.  
2. 분석 버튼 → **Gemini** `generate_content(model, [food_prompt, image])`.  
3. 응답 텍스트를 **파이프 구분 줄**로 파싱: 이름, GI, 탄·단·지, kcal, 신호, 순서 등 → 항목 리스트.  
4. **조언**: 두 번째 호출 `[advice_prompt, image]`.  
5. **혈당 순서 가이드**: 규칙 기반으로 식이섬유 후보 / 단백질 / 탄수화물 버킷에 나눈 뒤 문장을 **조언 하단에 덧붙임**.  
6. **저장**: 로그인 사용자 → `users/{uid}/history` + **`user_logs`**(탄수화물 등) + Storage 이미지 URL.  
→ 리포트 막대그래프는 **`user_logs.total_carbs`** + **`timestamp`**(한국일 그룹핑)로 반영.

### 5.3 다국어 처리
- **`translation.py`**: `LANG_DICT["KO"|"EN"|...][key]`.  
- **`st.session_state["lang"]`** — 로그인 전 상단 select, 설정 화면에서 변경 시 `t = LANG_DICT[lang]` 갱신 후 `rerun`.  
- **`get_text(lang, key, **kwargs)`**: 플레이스홀더 치환용.  
- **내부 저장**: 건강 목표 등 일부 키는 **항상 한글**(`GOAL_INTERNAL_KEYS`).

---

## 6. 한눈에 보는 요청 흐름

```
[브라우저] → Streamlit app.py
  ├─ 미로그인 → Firebase Auth UI
  └─ 로그인 → 포털 / 스캐너 / 혈당 / 리포트 / 설정
       ├─ 스캐너: Gemini(2.5→2.0 flash) → history + user_logs
       ├─ 혈당: Firestore users/.../glucose
       └─ 리포트: Firestore 쿼리 + Plotly + @st.cache_data
```

---

*문서 버전: 코드베이스 기준 스냅샷. 배포 시 `requirements.txt`·모델명·환경변수는 저장소 최신본을 우선하세요.*
