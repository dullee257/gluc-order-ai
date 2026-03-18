# Railway 배포 가이드 (NutriSort AI)

Streamlit 앱을 Railway에 배포하면 **잠자기 없이** 상시 실행됩니다.

---

## ⚠️ Google 로그인 사용 시 필수

**OAuth 승인된 리디렉션 URI**에 Railway 주소를 반드시 추가해야 합니다.

- 주소: `https://gluc-order-ai-production.up.railway.app` (및 `/` 붙인 버전)
- 위치: **Google Cloud Console** → **API 및 서비스** → **사용자 인증 정보** → 해당 OAuth 2.0 클라이언트 → **승인된 리디렉션 URI**에 추가

---

## 1. 사전 준비

- GitHub에 이 저장소가 푸시되어 있어야 합니다.
- [Railway](https://railway.app) 계정 (GitHub 로그인 가능).
- **GEMINI_API_KEY**, **Firebase** 설정값 (기존 Streamlit Cloud 시크릿과 동일).

---

## 2. Railway에서 새 프로젝트 만들기

1. [railway.app](https://railway.app) 로그인 후 **New Project** 클릭.
2. **Deploy from GitHub repo** 선택.
3. **dullee257/gluc-order-ai** (또는 사용 중인 저장소) 선택.
4. 브랜치 **main** 선택 후 배포 시작.

---

## 3. 환경 변수 설정

Railway 대시보드 → 해당 서비스 → **Variables** 탭에서 아래 변수를 추가합니다.

### 필수

| 변수명 | 설명 | 예시 |
|--------|------|------|
| `GEMINI_API_KEY` | Gemini API 키 | (기존과 동일) |
| `GEMINI_VISION_MODEL` | (선택) 멀티모달 모델 ID. 미설정 시 `gemini-2.5-flash` → `gemini-2.0-flash` 순으로 시도. **Gemini 1.5·`*-vision` 모델은 사용하지 마세요(폐기).** | `gemini-2.5-flash` |
| `BASE_URL` | **배포 후 부여되는 Railway URL** (아래 4단계에서 확인 후 입력) | `https://gluc-order-ai-production.up.railway.app` |
| `FIREBASE_API_KEY` | Firebase Web API Key | (Firebase 콘솔 → 프로젝트 설정) |
| `FIREBASE_GOOGLE_OAUTH_CLIENT_ID` | Google OAuth 클라이언트 ID | (Firebase/Google Cloud 콘솔) |
| `FIREBASE_GOOGLE_CLIENT_SECRET` | Google OAuth 클라이언트 시크릿 | (동일) |

### Firestore 저장 기능용 (서비스 계정)

**방법 A – JSON 한 번에 넣기 (권장)**

| 변수명 | 설명 |
|--------|------|
| `FIREBASE_CREDENTIALS_JSON` | Firebase 서비스 계정 키 JSON **전체를 한 줄 문자열**로 붙여넣기. (개행은 `\n` 그대로 두거나 실제 줄바꿈 가능) |

**방법 B – 항목별로 넣기**

| 변수명 |
|--------|
| `FIREBASE_TYPE`, `FIREBASE_PROJECT_ID`, `FIREBASE_PRIVATE_KEY_ID`, `FIREBASE_PRIVATE_KEY`, `FIREBASE_CLIENT_EMAIL`, `FIREBASE_CLIENT_ID`, `FIREBASE_AUTH_URI`, `FIREBASE_TOKEN_URI`, `FIREBASE_AUTH_PROVIDER_X509_CERT_URL`, `FIREBASE_CLIENT_X509_CERT_URL`, `FIREBASE_UNIVERSE_DOMAIN` |

- `FIREBASE_PRIVATE_KEY` 에는 `-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n` 형태로, 줄바꿈을 `\n`으로 넣어도 됩니다 (앱에서 `\\n` → `\n` 변환).

---

## 4. 공개 URL 부여 및 BASE_URL 반영

1. Railway 서비스 → **Settings** → **Networking** → **Generate Domain** 클릭.
2. 생성된 URL 예: `https://gluc-order-ai-production.up.railway.app`
3. **Variables** 에서 `BASE_URL` 값을 이 URL로 설정 (끝에 `/` 없이).
4. **재배포** 한 번 실행 (Variables 저장 후 자동으로 될 수도 있음).

---

## 5. Google OAuth 리디렉션 URI 추가 (Google 로그인 필수)

1. [Google Cloud Console](https://console.cloud.google.com/) → **API 및 서비스** → **사용자 인증 정보**.
2. 사용 중인 **OAuth 2.0 클라이언트 ID** 선택.
3. **승인된 리디렉션 URI**에 아래 두 개를 추가 (Railway 주소가 다르면 해당 주소로 변경).
   - `https://gluc-order-ai-production.up.railway.app`
   - `https://gluc-order-ai-production.up.railway.app/`
4. 저장 후 앱에서 구글 로그인 다시 시도.

---

## 6. 시작 명령 확인

- 이 저장소의 **nixpacks.toml** 에 Streamlit 시작 명령이 들어 있습니다. (Python 3.12 고정)
- **Procfile** 도 있으나, Railway는 Nixpacks를 쓰므로 **nixpacks.toml** 이 우선합니다.
- 그래도 크래시하면 Railway 서비스 → **Settings** → **Deploy** → **Start Command** 에 아래를 **직접 입력**하세요.  
  `streamlit run app.py --server.port $PORT --server.address 0.0.0.0`

---

## 6-1. 크래시 시 확인할 것

| 확인 항목 | 조치 |
|-----------|------|
| **로그** | Railway 서비스 → **Deployments** → 해당 배포 클릭 → **View Logs** 에서 에러 메시지 확인. |
| **Python 버전** | 3.13 사용 시 호환성 이슈 가능. 저장소의 **runtime.txt**(3.12) 또는 **nixpacks.toml** 반영 후 재배포. |
| **시작 명령** | 위 **Start Command** 가 설정돼 있는지 확인. 없으면 수동 입력. |
| **환경 변수** | `GEMINI_API_KEY`, `BASE_URL` 등 필수 변수가 빠지지 않았는지 확인. (없어도 기동은 되지만, 메뉴 진입 시 에러 가능.) |

---

## 7. GitHub Pages(또는 다른 도메인)에서 Railway 앱 연결

- **dullee257.github.io/gluc-order-ai** 등에서 iframe으로 쓰는 경우:
  - `docs/index.html` 의 iframe `src` 를 **Railway URL** 로 바꿉니다.  
    예: `https://gluc-order-ai-production.up.railway.app/?embed=true`
- 커스텀 도메인을 Railway에 연결한 경우에는 그 URL을 iframe `src` 와 `BASE_URL` 에 사용하면 됩니다.

---

## 8. 체크리스트

- [ ] Railway 프로젝트 생성 및 GitHub 저장소 연결
- [ ] Variables에 `GEMINI_API_KEY`, `BASE_URL`, Firebase 관련 변수 설정
- [ ] Generate Domain 후 `BASE_URL` 에 반영
- [ ] Google OAuth 리디렉션 URI에 Railway URL 추가
- [ ] 배포 성공 후 앱 접속·로그인·식단 저장 테스트
- [ ] (선택) GitHub Pages iframe `src` 를 Railway URL로 변경

---

*문서 버전: 1.0 | NutriSort AI Railway 배포*
