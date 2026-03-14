# Streamlit "잠시 멈췄다" 화면 안 뜨게 하기

Streamlit Community Cloud **무료** 플랜은 약 12시간 비활성 시 앱을 재우고, 다음 접속 시 "This app has gone to sleep" 화면을 띄웁니다.  
이 화면을 **안 뜨게** 하려면 아래 두 가지 중 하나를 선택하면 됩니다.

---

## 방법 1: 다른 호스팅으로 이전 (잠자기 없음, 권장)

앱을 **잠들지 않는** 서버에 배포하면 "깨우기" 화면 자체가 없습니다.

| 서비스 | 특징 | 비용 감 |
|--------|------|--------|
| **Railway** | Streamlit 공식 가이드 있음, 상시 실행 | 유료(월 약 $5~10 수준) |
| **Google Cloud Run** | 트래픽에 따라 과금, 최소 인스턴스 1로 상시 가능 | 사용량 따라 다름 |
| **Render** | 유료 플랜에서 상시 실행 | 무료는 15분 비활성 시 슬립 |
| **Fly.io** | 상시 실행 가능 | 유료 |

- **상용화**를 염두에 두고 있다면, 처음부터 Railway / Cloud Run 등으로 배포하는 것을 추천합니다.
- Streamlit Cloud 무료는 **테스트·데모용**으로 두고, 실제 서비스는 위 플랫폼 중 하나로 운영하는 구성을 권장합니다.

---

## 방법 2: Streamlit Cloud 유지 + 자동 "깨우기" (무료)

그대로 **Streamlit Community Cloud**를 쓰면서, **주기적으로 앱 URL을 방문**해 잠들지 않게 할 수 있습니다.

- 단순 `curl` 요청만으로는 **앱이 깨어나지 않습니다**.  
  Streamlit은 "깨우기" 페이지를 보여 주는 HTML만 주고, 실제 앱 프로세스는 사용자가 **브라우저에서 "Yes, get this app back up!" 버튼을 눌렀을 때**만 시작됩니다.
- 그래서 **브라우저 자동화**(Playwright 등)로 해당 버튼을 주기적으로 클릭하는 방식이 필요합니다.

이 레포에는 **GitHub Actions**로 위 동작을 하는 워크플로와 스크립트가 들어 있습니다.

- **위치**: `.github/workflows/streamlit-keepalive.yml`  
- **동작**: 앱 URL 접속 → "Yes, get this app back up!" 버튼이 보이면 클릭 → 앱이 깨어난 상태로 유지
- **Railway 사용 시**: 서버가 24시간 켜져 있으므로 **자동 실행(cron)은 비활성화**되어 있습니다. 수동 실행(workflow_dispatch)만 가능. Streamlit Cloud로 다시 전환하면 워크플로에서 `schedule` 주석을 해제해 두면 됩니다.
- **설정**:  
  - 기본 URL은 `https://nutrisort.streamlit.app` 입니다.  
  - 다른 URL을 쓰려면 GitHub 저장소 **Settings → Secrets and variables → Actions**에서 `STREAMLIT_APP_URL` 시크릿을 추가해 앱 URL을 넣으면 됩니다.

**주의**

- Streamlit 측에서 "프로그래밍 방식의 keep-alive"를 막을 수 있다고 안내한 바 있습니다.  
  장기적으로는 **방법 1(다른 호스팅)** 이 더 안정적입니다.
- 상용 서비스라면 가능한 한 **방법 1**로 이전하는 것을 권장합니다.

---

## 요약

| 목표 | 추천 |
|------|------|
| **잠자기 화면을 아예 안 보이게** | 방법 1: Railway / Cloud Run 등으로 이전 |
| **무료로 쓰되 화면 덜 뜨게** | 방법 2: GitHub Actions 자동 깨우기 사용 (이 레포 포함된 워크플로) |
