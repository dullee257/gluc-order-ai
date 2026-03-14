# 호스팅 이전 가이드 (Streamlit Cloud → Railway 등)

상용화 전에 다른 호스팅(Railway, Cloud Run 등)으로 옮길 때 **코드는 수정하지 않고**, 설정만 바꾸면 됩니다.

---

## 1. 이전이 쉬운 이유

- **앱 코드는 그대로** 사용합니다. `app.py`, `requirements.txt` 수정 없이 동일한 GitHub 저장소를 새 플랫폼에 연결하면 됩니다.
- **앱 URL**만 환경 변수 `BASE_URL`로 통일해 두었기 때문에, 이전 시 **환경 변수(또는 시크릿) 한 가지만** 새 주소로 바꾸면 됩니다.

---

## 2. 이전 시 할 일 체크리스트

### 2.1 새 호스팅에서 할 일

| 단계 | 내용 |
|------|------|
| 1 | 새 플랫폼(Railway, Render, Cloud Run 등)에서 **같은 GitHub 저장소** 연결 |
| 2 | **환경 변수(또는 시크릿)** 설정: `BASE_URL` = 새 앱 주소 (예: `https://nutrisort.up.railway.app`) |
| 3 | 기존과 동일하게 설정: `GEMINI_API_KEY`, Firebase 관련 키들 (Streamlit에서는 `secrets.toml`에 있던 항목들) |
| 4 | 배포 후 앱이 정상 동작하는지 확인 |

### 2.2 Google OAuth (구글 로그인) 쪽

- **Google Cloud Console** → 사용자 인증 정보 → 해당 OAuth 2.0 클라이언트 ID → **승인된 리디렉션 URI**에 **새 앱 URL** 추가  
  예: `https://nutrisort.up.railway.app`, `https://nutrisort.up.railway.app/`
- 기존 `https://nutrisort.streamlit.app` 은 테스트용으로 남겨 두거나, 완전 이전 후 제거해도 됩니다.

### 2.3 PWA / docs/index.html (선택)

- `docs/index.html` 에서 iframe `src`가 **Streamlit 주소**로 하드코딩되어 있으면, 새 앱 주소로 바꿔야 합니다.  
  (앱을 별도 도메인/페이지에서 iframe으로만 띄우는 경우에만 해당)

---

## 3. 환경 변수 정리

이전한 뒤 새 호스팅에서 넣어 줄 값 예시입니다.

| 변수명 | 설명 | 예시 |
|--------|------|------|
| `BASE_URL` | 앱이 실제로 서비스되는 주소 (끝에 `/` 제외) | `https://nutrisort.up.railway.app` |
| `GEMINI_API_KEY` | Gemini API 키 | (기존과 동일) |
| Firebase 관련 | 기존 `secrets.toml` / Firebase 설정과 동일 | (기존과 동일) |

- **Streamlit Cloud**에서만 쓰던 값은 **새 플랫폼의 환경 변수(또는 시크릿)** 에 그대로 옮기면 됩니다.

---

## 4. 요약

- **코드 변경**: 없음 (이미 `BASE_URL` 반영됨).
- **할 일**: 새 호스팅 연결 → `BASE_URL` + 기존 API/시크릿 설정 → Google OAuth 리디렉션 URI 추가.
- 이렇게 하면 **상용화 전 호스팅 이전이 비교적 쉽게** 가능합니다.
