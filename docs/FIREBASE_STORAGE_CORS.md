# Firebase Storage CORS 설정 (Streamlit에서 이미지 불러오기)

Streamlit 웹 앱에서 Firebase Storage에 저장된 이미지 URL을 `st.image(url)` 등으로 표시할 때, 브라우저가 **다른 도메인(Storage)** 에서 리소스를 가져오므로 **CORS** 설정이 필요합니다.  
CORS를 설정하지 않으면 이미지 요청이 차단되어 빈 칸 또는 에러가 날 수 있습니다.

---

## 1. 버킷 이름 확인

- Firebase 콘솔 → **Storage** → 상단에 표시되는 버킷 이름을 확인합니다.  
  예: `your-project-id.appspot.com`
- 또는 터미널에서:
  ```bash
  gcloud storage buckets list
  ```
  목록에서 사용 중인 Storage 버킷 이름을 확인합니다.

---

## 2. CORS 설정 JSON 파일 만들기

프로젝트 루트에 `storage-cors.json` 파일을 만들고, **Streamlit 앱이 접속하는 출처(origin)** 를 넣습니다.

**중요:** `gcloud storage buckets update --cors-file` 에 넣을 파일은 **최상위 `"cors":` 래퍼 없이**, CORS 규칙 **배열만** 넣은 JSON이어야 합니다. (Google 공식 문서: [CORS configuration structure for gcloud CLI](https://cloud.google.com/storage/docs/cors-configurations).)

### 로컬 개발용 예시

```json
[
  {
    "origin": ["http://localhost:8501", "http://127.0.0.1:8501"],
    "method": ["GET", "HEAD"],
    "responseHeader": ["Content-Type", "Content-Length", "Accept"],
    "maxAgeSeconds": 3600
  }
]
```

### 배포 URL까지 포함하는 예시

Streamlit Cloud, Railway, yourdomain.com 등에 배포했다면 해당 URL을 `origin`에 추가합니다.

```json
[
  {
    "origin": [
      "http://localhost:8501",
      "http://127.0.0.1:8501",
      "https://your-app-name.streamlit.app",
      "https://your-app.onrender.com",
      "https://your-domain.com"
    ],
    "method": ["GET", "HEAD"],
    "responseHeader": ["Content-Type", "Content-Length", "Accept"],
    "maxAgeSeconds": 3600
  }
]
```

- `origin`: Streamlit 앱이 열리는 주소(프로토콜 포함). 로컬은 `http://localhost:8501` 등.
- `method`: 이미지 로드는 **GET** (그리고 **HEAD**)만 있으면 됩니다.
- `responseHeader`: 브라우저가 노출해도 되는 응답 헤더. 이미지 표시에는 `Content-Type` 등이 필요합니다.
- `maxAgeSeconds`: preflight 캐시 시간(초).

**주의:** `origin`에 `*`를 쓰면 모든 도메인 허용이지만, 보안상 배포 URL을 명시하는 편이 좋습니다.

---

## 3. gcloud CLI로 CORS 적용

### 3-1. gcloud 설치 및 로그인

- [Google Cloud SDK 설치](https://cloud.google.com/sdk/docs/install)
- 로그인 및 프로젝트 지정:
  ```bash
  gcloud auth login
  gcloud config set project YOUR_PROJECT_ID
  ```

### 3-2. CORS 설정 적용

아래에서 `BUCKET_NAME`을 실제 버킷 이름으로, `storage-cors.json`을 만든 파일 경로로 바꿉니다.

```bash
gcloud storage buckets update gs://BUCKET_NAME --cors-file=storage-cors.json
```

예시:

```bash
gcloud storage buckets update gs://my-project.appspot.com --cors-file=storage-cors.json
```

- 파일이 다른 경로에 있으면 절대 경로 또는 상대 경로로 지정:
  ```bash
  gcloud storage buckets update gs://BUCKET_NAME --cors-file=./storage-cors.json
  ```

### 3-3. (선택) gsutil 사용

gsutil이 설치되어 있다면:

```bash
gsutil cors set storage-cors.json gs://BUCKET_NAME
```

---

## 4. 로컬에서 Python 스크립트로 CORS 설정 (serviceAccountKey.json 사용)

인증 에러 없이 로컬에서 CORS를 적용하려면, Firebase 서비스 계정 키로 `serviceAccountKey.json`을 만든 뒤 해당 파일을 사용해 스크립트를 실행합니다.

### 4-1. serviceAccountKey.json 생성

**방법 A – Firebase에서 받은 JSON 파일로 생성**

1. Firebase 콘솔 → 프로젝트 설정 → 서비스 계정 → **키 추가** → JSON 다운로드.
2. `FIREBASE_CREDENTIALS_JSON`에 **다운로드한 JSON 파일 경로**를 넣고 스크립트를 실행하면, 해당 파일을 읽어 `serviceAccountKey.json`을 만듭니다.

   **PowerShell:**
   ```powershell
   cd e:\suger
   $env:FIREBASE_CREDENTIALS_JSON = "C:\경로\다운로드한키.json"
   python scripts/write_service_account_key.py
   ```
   (경로가 실제 파일을 가리키면 스크립트가 그 파일을 읽어서 프로젝트 루트에 `serviceAccountKey.json`을 생성합니다.)

   **CMD:**
   ```cmd
   cd e:\suger
   set FIREBASE_CREDENTIALS_JSON=C:\경로\다운로드한키.json
   python scripts/write_service_account_key.py
   ```

   JSON 전체를 한 줄 문자열로 환경 변수에 넣어도 됩니다.

**방법 B – .streamlit/secrets.toml 에 [firebase] 가 있을 때**

```bash
pip install tomli
python scripts/write_service_account_key.py --from-secrets
```

생성된 파일은 프로젝트 루트의 **`serviceAccountKey.json`** 이며, **절대 Git에 커밋하지 마세요.** (`.gitignore`에 이미 포함됨)

### 4-2. CORS 스크립트 실행

**PowerShell:**
```powershell
cd e:\suger
$env:GOOGLE_APPLICATION_CREDENTIALS = (Resolve-Path "serviceAccountKey.json").Path
$env:BUCKET_NAME = "gluc-order-ai.appspot.com"
python scripts/set_storage_cors.py
```

**CMD:**
```cmd
cd e:\suger
set GOOGLE_APPLICATION_CREDENTIALS=e:\suger\serviceAccountKey.json
set BUCKET_NAME=gluc-order-ai.appspot.com
python scripts/set_storage_cors.py
```

버킷 이름은 Firebase 콘솔의 Storage에서 확인한 값으로 바꾸면 됩니다 (일반적으로 `프로젝트ID.appspot.com`).

---

## 5. 적용 확인

- CORS 설정은 적용 후 곧바로 반영됩니다.
- Streamlit 앱에서 **새로고침** 후 식단 기록의 이미지가 로드되는지 확인합니다.
- 브라우저 개발자 도구(F12) → **Network** 탭에서 이미지 요청이 **Status 200**으로 오는지, **Console**에 CORS 관련 에러가 없는지 확인합니다.

---

## 6. 요약

| 단계 | 내용 |
|------|------|
| 1 | Firebase/Cloud Console에서 Storage **버킷 이름** 확인 |
| 2 | `storage-cors.json`에 Streamlit 앱 **origin**(로컬/배포 URL) 작성 |
| 3 | `gcloud storage buckets update gs://BUCKET_NAME --cors-file=storage-cors.json` 실행 또는 **Python 스크립트** (`scripts/set_storage_cors.py`) + `serviceAccountKey.json` 사용 |
| 4 | 앱에서 이미지 로드 및 Network/Console로 확인 |

이렇게 설정하면 Streamlit 웹 앱에서 Firebase Storage 이미지를 CORS 문제 없이 불러올 수 있습니다.
