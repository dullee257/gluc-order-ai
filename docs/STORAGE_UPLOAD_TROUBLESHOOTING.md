# Firebase Storage 사진 업로드 안 됨 — 정밀 점검 및 해결

Railway / Firebase / GitHub 환경에서 **식단 저장 시 사진이 Firebase Storage에 올라가지 않고 `image_url`이 null**인 경우, 아래 항목을 순서대로 확인하세요.

---

## 1. 원인 요약 (코드/환경)

| 구분 | 원인 | 해결 |
|------|------|------|
| **Firebase Admin SDK** | `initialize_app(cred)` 시 **`storageBucket` 미지정** → `storage.bucket()` 호출 시 기본 버킷이 없어 **ValueError** 발생. 예외는 catch되어 Firestore만 저장되고 `image_url`은 null. | `initialize_app(cred, {'storageBucket': '프로젝트ID.appspot.com'})` 지정 (코드 반영됨) |
| **Railway 환경 변수** | `FIREBASE_CREDENTIALS_JSON`에 서비스 계정 JSON을 넣을 때 **`private_key` 안의 줄바꿈**이 `\n` 문자열로 들어가면 인증 실패. | JSON 파싱 후 `private_key.replace("\\n", "\n")` 처리 (코드 반영됨). 또는 JSON 한 줄로 넣을 때 실제 줄바꿈 유지. |
| **세션/워커** | Streamlit이 **다중 워커**이거나 **재시작**되면, 저장 버튼을 누를 때 **다른 프로세스**에서 실행되어 `current_analysis` / `raw_img`가 비어 있을 수 있음. | 단일 워커·세션 유지. 또는 분석 직후 곧바로 저장 유도. |
| **Firebase Storage 규칙** | 서비스 계정으로 업로드하는 경우 보통 규칙과 무관. 다만 **버킷 자체가 비활성**이면 실패. | Firebase 콘솔 → Storage 활성화·규칙 확인. |
| **404 The specified bucket does not exist** | Firebase 프로젝트에 따라 기본 버킷 이름이 **project_id.appspot.com**이 아니라 **project_id.firebasestorage.app**인 경우가 있음. 코드 기본값은 appspot.com. | Railway(및 로컬)에 **FIREBASE_STORAGE_BUCKET** 환경 변수 설정. Firebase 콘솔 Storage 상단에 표시된 버킷 이름 그대로 넣기. 예: `gluc-order-ai.firebasestorage.app` |

---

## 2. 404 "The specified bucket does not exist" 해결

Firebase 콘솔 Storage에 표시되는 버킷이 **project_id.firebasestorage.app** 형태일 수 있습니다. 이 경우 코드 기본값(project_id.appspot.com)으로는 404가 납니다.

**해결:** Railway(및 필요 시 로컬)에 환경 변수 추가:

- **이름:** `FIREBASE_STORAGE_BUCKET`
- **값:** Firebase 콘솔 → Storage → 상단에 보이는 버킷 이름 그대로 (예: `gluc-order-ai.firebasestorage.app`)

저장 후 재배포하고 식단 저장을 다시 시도하세요.

---

## 3. Railway 점검

- **환경 변수**
  - `FIREBASE_CREDENTIALS_JSON`: Firebase 콘솔에서 받은 **서비스 계정 JSON 전체**가 들어가 있는지 확인.
  - JSON을 **한 줄**로 넣을 때: `private_key` 값 안의 `\n`이 **실제 줄바꿈**인지, **문자 그대로 백슬래시+n**인지 확인. (코드에서 `\\n` → `\n` 치환 처리했음.)
- **로그**
  - Railway 대시보드 → 해당 서비스 → **Deployments** → **View Logs**.
  - 저장 시점에 `[Storage]` 로그가 있는지 확인.  
    - `ValueError: ... bucket` → 이전에는 `storageBucket` 미지정 때문이었음 (수정 반영됨).  
    - `PermissionDenied` / `403` → 서비스 계정 권한 또는 Storage 규칙 확인.  
    - `AttributeError` / `public_url` 관련 → SDK/버전 확인.

---

## 4. Firebase 점검

- **Storage 활성화**  
  Firebase 콘솔 → **Storage** → “시작하기” 후 버킷 생성 여부.
- **버킷 이름**  
  기본값: `프로젝트ID.appspot.com`. 코드에서는 `project_id`를 서비스 계정 JSON에서 읽어 `storageBucket`으로 사용.
- **규칙**  
  Admin SDK(서비스 계정)는 **Firebase Storage 규칙과 무관**하게 동작. 그래도 테스트용으로 아래처럼 두었다면:
  ```
  allow read, write: if request.auth != null;
  ```
  업로드는 **서버(서비스 계정)** 이 하므로 규칙보다는 **서비스 계정 IAM 권한**이 중요함.
- **서비스 계정 권한**  
  Google Cloud 콘솔 → IAM → 해당 서비스 계정 이메일에  
  **Storage 객체 관리자** 또는 **Storage 관리자** 역할이 있는지 확인.

---

## 5. GitHub(코드) 점검

- **`initialize_app(cred)`**  
  반드시 **옵션으로 `storageBucket`** 이 들어가 있어야 함.  
  예: `firebase_admin.initialize_app(cred, {'storageBucket': f'{project_id}.appspot.com'})`.
- **저장 흐름**  
  1. `res = st.session_state['current_analysis']`  
  2. `raw_pil = res.get("raw_img")`  
  3. `raw_pil`이 있으면 압축 후 `bucket.blob(path).upload_from_string(...)`  
  4. `image_url = blob.public_url` 또는 `_normalize_image_url(path, bucket.name)`  
  - `raw_img`가 없으면 업로드 자체를 하지 않음 → **분석 결과에 이미지가 포함되는지**, **세션 유지되는지** 확인.
- **`_get_firebase_config()`**  
  - `st.secrets["firebase"]` 또는 `FIREBASE_CREDENTIALS_JSON`(및 개별 `FIREBASE_*` env)에서 **project_id, private_key, client_email** 등이 빠지지 않았는지 확인.

---

## 6. 적용된 코드 수정 요약

1. **`storageBucket` 지정**  
   `firebase_admin.initialize_app(cred)` 호출부 세 곳 모두에  
   `initialize_app(cred, {'storageBucket': f'{key_dict["project_id"]}.appspot.com'})` 적용.  
   → `storage.bucket()` 호출 시 기본 버킷이 있어 업로드가 진행됨.
2. **`private_key` 줄바꿈**  
   `FIREBASE_CREDENTIALS_JSON` 파싱 후 `private_key.replace("\\n", "\n")` 적용.  
   → Railway 등에서 env로 JSON 넣을 때 인증 오류 감소.

---

## 7. 여전히 null일 때 확인 순서

1. **Railway 로그**에서 저장 시 `[Storage]` 예외 메시지 확인.  
2. **Firebase 콘솔** → Storage → **파일** 탭에서 `users/{uid}/meals/` 아래에 파일이 생기는지 확인.  
3. **Firestore** `users/{uid}/history` 문서에 `image_url` 필드가 아예 없거나 null인지 확인.  
4. **분석 직후** 같은 탭에서 곧바로 저장해 보기 (세션/워커 이슈 배제).  
5. **로컬**에서 동일 서비스 계정 JSON으로 실행해 보기 (Railway env만의 이슈인지 구분).

이렇게 점검하면 “사진이 Firebase Storage에 업로드 안 됨” 원인을 좁히고, 위 수정으로 대부분 해결할 수 있습니다.
