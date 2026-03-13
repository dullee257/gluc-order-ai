import streamlit as st
# 1. 카톡 및 네이버 인앱 브라우저 탈출 스크립트 (화면 깨짐 및 양식 중복 제출 방지)
st.components.v1.html(
    """
    <script>
    // 1. 문서 객체 참조 (Streamlit Cloud의 CORS 에러 우회하기 위해 try-catch 적용)
    let doc = window.document;
    let win = window;
    try {
        if (window.parent.document) {
            doc = window.parent.document;
            win = window.parent;
        }
    } catch (e) {
        console.log("CORS blocked accessing parent window. Using current window.");
    }

    var agent = navigator.userAgent.toLowerCase();
    var targetUrl = 'https://nutrisort.streamlit.app';
    
    // 카카오톡 및 네이버 앱 탈출 스크립트 (안드로이드에서는 반드시 풀버전 크롬 브라우저로 열리게 강제)
    if (agent.indexOf('kakao') > -1) {
        if (agent.indexOf('android') > -1) {
            win.top.location.href = 'intent://nutrisort.streamlit.app#Intent;scheme=https;package=com.android.chrome;end';
        } else {
            win.top.location.href = 'kakaotalk://web/openExternal?url=' + encodeURIComponent(targetUrl);
        }
    } else if (agent.indexOf('naver') > -1) {
        if (agent.indexOf('android') > -1) {
            win.top.location.href = 'intent://nutrisort.streamlit.app#Intent;scheme=https;package=com.android.chrome;end';
        } else {
            if (win.location.href.indexOf('?') === -1) {
                win.top.location.replace(targetUrl + '?reload=' + new Date().getTime());
            }
        }
    }
    
    // 2. [PWA 지원] Streamlit 기본 매니페스트를 강력하게 실시간으로 덮어쓰기 (Data URI 방식)
    const myManifest = {
        "name": "혈당스캐너 - NutriSort",
        "short_name": "혈당스캐너",
        "description": "혈당 관리 섭취 순서 스캐너",
        "start_url": "/",
        "display": "standalone",
        "orientation": "portrait",
        "background_color": "#ffffff",
        "theme_color": "#86cc85",
        "icons": [
            { "src": "/app/static/icon-192.png", "sizes": "192x192", "type": "image/png" },
            { "src": "/app/static/icon-512.png", "sizes": "512x512", "type": "image/png" }
        ]
    };
    // Blob 대신 브라우저가 직접 파싱할 수 있는 Base64 Data URI 방식으로 변경
    const manifestStr = JSON.stringify(myManifest);
    const encodedManifest = btoa(unescape(encodeURIComponent(manifestStr)));
    const manifestURL = 'data:application/manifest+json;base64,' + encodedManifest;
    
    function forceManifestAndIcon() {
        let manifest = doc.querySelector('link[rel="manifest"]');
        if (manifest) {
            if (manifest.getAttribute('href') !== manifestURL) {
                manifest.setAttribute('href', manifestURL);
            }
        } else {
            manifest = doc.createElement('link');
            manifest.rel = 'manifest';
            manifest.href = manifestURL;
            doc.head.appendChild(manifest);
        }

        doc.querySelectorAll('link[rel="shortcut icon"], link[rel="apple-touch-icon"], link[rel="icon"]').forEach(el => {
            if (el.getAttribute('href') !== '/app/static/icon-192.png') {
                el.href = '/app/static/icon-192.png';
            }
        });
        if (doc.title !== '혈당스캐너 - NutriSort') doc.title = '혈당스캐너 - NutriSort';
    }

    // 🚀 [핵심] embed=true 상황에서 DOM을 뒤져서 강제로 추가된 'Built with Streamlit' 배너 및 배포 아이콘 제거!
    function killWatermarks() {
        // [1] 상위 프레임(Streamlit Cloud) 전체에 강력한 감춤 속성을 가진 CSS를 영구적으로 박아 넣기
        if (!doc.getElementById('custom-streamlit-killer')) {
            const killerStyle = doc.createElement('style');
            killerStyle.id = 'custom-streamlit-killer';
            killerStyle.innerHTML = `
                [data-testid="stAppDeployButton"], 
                [data-testid="stStatusWidget"], 
                .viewerBadge_container, 
                .viewerBadge_link, 
                .stDeployButton,
                iframe[title*="Deploy"],
                iframe[src*="share.streamlit.io"] {
                    display: none !important;
                    visibility: hidden !important;
                    opacity: 0 !important;
                    pointer-events: none !important;
                    width: 0 !important;
                    height: 0 !important;
                    position: absolute !important;
                    z-index: -9999 !important;
                }
            `;
            doc.head.appendChild(killerStyle);
        }

        // [2] 직접 DOM을 훑어서 인라인 스타일로도 조져버리기
        doc.querySelectorAll('[data-testid="stAppDeployButton"], [data-testid="stStatusWidget"], .viewerBadge_container, .viewerBadge_link').forEach(el => {
            el.style.setProperty('display', 'none', 'important');
            // 만약 감싸는 부모 컨테이너가 있다면 같이 날려버림
            let parent = el.parentElement;
            if (parent && parent.tagName !== 'BODY' && parent.clientHeight < 100) {
                parent.style.setProperty('display', 'none', 'important');
            }
        });
        
        doc.querySelectorAll('iframe').forEach(el => {
            if (el.title && el.title.includes('Deploy')) {
                el.style.setProperty('display', 'none', 'important');
            }
        });

        doc.querySelectorAll('div, footer, span, a').forEach(el => {
            if (el.textContent && el.textContent.includes('Built with Streamlit')) {
                let parent = el;
                while (parent && parent.tagName !== 'BODY' && parent.tagName !== 'HTML') {
                    if (parent.clientHeight > 0 && parent.clientHeight < 100) {
                        parent.style.setProperty('display', 'none', 'important');
                    }
                    parent = parent.parentElement;
                }
                el.style.display = 'none';
            }
        });
    }

    forceManifestAndIcon();
    setTimeout(forceManifestAndIcon, 500);
    setTimeout(killWatermarks, 500);
    setTimeout(killWatermarks, 1500);
    setTimeout(killWatermarks, 3000);

    // Streamlit 페이지가 늦게 켜지면서 오리지널 매니페스트를 다시 심는 것을 0.1초 단위로 감시하고 폭파시키는 감시자 설정
    const headObserver = new MutationObserver(() => forceManifestAndIcon());
    headObserver.observe(doc.head, { childList: true, attributes: true, subtree: true });

    // 바디 감시자로 워터마크가 튀어나오면 즉시 제거
    const bodyObserver = new MutationObserver(() => killWatermarks());
    if (doc.body) {
        bodyObserver.observe(doc.body, { childList: true, subtree: true });
    }
    
    // 3. [PWA 지원] 서비스 워커 등록
    if ('serviceWorker' in win.navigator) {
        win.addEventListener('load', function() {
            win.navigator.serviceWorker.register('/app/static/sw.js')
            .then(function(registration) {
                console.log('ServiceWorker registered with scope: ', registration.scope);
            }, function(err) {
                console.log('ServiceWorker registration failed: ', err);
            });
        });
    }

    // 4. [성능 최적화] 브라우저 단 이미지 압축 로직은 모바일 카메라 촬영 시 
    // 메모리/캔버스 오작동을 유발하므로 제거됨. (Python 서버단 compress_image 함수가 대신 처리)

    // iframe 내부의 PWA 배너 로직 생성 코드는 docs/index.html의 최상위 프레임 전용으로 이관되어 삭제됨.


    </script>
    """,
    height=0,
)
from google import genai
from PIL import Image
from datetime import datetime
import io

def compress_image(img, max_size_kb=500):
    """이미지가 서버에 로드된 직후 500KB 이하로 브라우저 표시 및 전송 전에 최적화(압축)하는 함수"""
    quality = 90
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    while True:
        output = io.BytesIO()
        img.save(output, format="JPEG", quality=quality)
        size_kb = len(output.getvalue()) / 1024
        if size_kb <= max_size_kb or quality <= 20:
            output.seek(0)
            return Image.open(output)
        quality -= 10
        img = img.resize((int(img.width * 0.8), int(img.height * 0.8)), Image.Resampling.LANCZOS)

# 1. 페이지 설정 (모바일 최적화를 위해 centered 레이아웃 권장)
# 1. 페이지 설정 및 보안 옵션 적용
st.set_page_config(
    page_title="혈당스캐너 - NutriSort",
    page_icon="🩸",
    layout="centered",
    initial_sidebar_state="collapsed",
    menu_items={
        'Get Help': None,
        'Report a bug': None,
        'About': None  # 'About'을 None으로 설정하거나 소스 링크를 제거합니다.
    }
)

# 2. 세션 상태 초기화
if 'history' not in st.session_state:
    st.session_state['history'] = []
if 'current_analysis' not in st.session_state:
    st.session_state['current_analysis'] = None
if 'logged_in' not in st.session_state:
    st.session_state['logged_in'] = False
if 'user_id' not in st.session_state:
    st.session_state['user_id'] = None

# 다국어 텍스트 사전 정의
texts = {
    "KO": {
        "title": "🥗 NutriSort AI",
        "sidebar_title": "💡 NutriSort 관리 시스템",
        "description": "📈|혈당 스파이크 방지|섭취 순서의 마법", # | 기호로 행 구분점을 만듭니다. 
        "uploader_label": "음식 스캔하기",
        "analyze_btn": "혈당관리 솔루션 및 섭취순서 분석",
        "save_btn": "💾 이 식단 기록 저장하기",
        "scanner_menu": "식단 스캐너",
        "history_menu": "나의 식단 기록",
        "analysis_title": "섭취순서",
        "advice_title": "식단분석",
        "advice_prompt": "사진 속 음식을 분석하여 혈당 관리를 위한 조언을 다음 4단계 카테고리로 나누어 '반드시' 순서대로 작성해줘. 각 카테고리 앞에 번호와 제목을 적어줘.\n\n1. 사진 속 메뉴 확인\n- '사진 속 메뉴를 보니...'로 시작하여 사진의 음식에 대한 간략한 기본 분석을 진행해.\n- 실제로 사진에 잡곡밥, 채소 등 칭찬할 요소가 있을 때만 칭찬하고 없으면 지어내지 마.\n\n2. 장소 유추 및 실전 메뉴 꿀팁\n- 음식(배경/로고 등)을 기반으로 식사 장소를 유추해.\n- [가장 중요한 규칙]: 유추한 장소가 카페나 디저트 전문점처럼 채소/단백질 메뉴가 메인이 아닌 곳이라면, **굳이 채소 샐러드나 샌드위치를 억지로 추가 주문하라고 제안하지 마!** 해당 장소에 적합한 가벼운 팁(예: 시럽 빼기, 우유 대신 오트밀크 변경 등)만 주고 넘어가.\n- 밥집/고깃집 등 추가 반찬 주문이 자연스러운 곳에서만 보완 음식을 적극 제안해.\n\n3. 권장 식사 순서\n- '2번 단계에서 실제로 추가를 제안한 음식이 있을 경우에만' 원래 상차림과 합쳐서 섭취 순서를 안내해.\n- 억지로 채소나 단백질을 먹으라는 템플릿 문구를 쓰지 말고, **오직 지금 사진에 찍힌 음식(+자연스러운 추가 메뉴) 에 한해서만** 어떻게 순서대로 먹는 것이 혈당 방어에 최선인지 설명해 줘. (커피만 있으면 커피 마시는 법만 설명해).\n\n4. 그 외 부가 설명\n- 음식의 나트륨, 조리법 주의사항, 식후 10분 걷기 등 추가적인 혈당 조언을 자연스럽게 덧붙여줘.",
        "save_msg": "대표님, '나의 기록' 탭에 저장되었습니다!",
        "browse_text": "파일 찾기"
    },
    "EN": {
        "title": "🥗 NutriSort AI",
        "sidebar_title": "💡 NutriSort Admin",
        "description": "Daily Glucose Status",
        "uploader_label": "Scan Food",
        "analyze_btn": "Sort Eating Order",
        "save_btn": "💾 Save this record",
        "scanner_menu": "Meal Scanner",
        "history_menu": "My History",
        "analysis_title": "Eating Order",
        "advice_title": "Nutritional Analysis",
        "advice_prompt": "Analyze the food in the photo and set the eating order for blood sugar management.",
        "save_msg": "Successfully saved to 'My History'!",
        "browse_text": "Browse files"
    }
}

# 3. 사이드바 메뉴
with st.sidebar:
    st.title("Settings")
    lang = st.radio("Language / 언어 선택", ["KO", "EN"])
    t = texts[lang]
    st.divider()
    st.title(t["sidebar_title"])
    menu = st.radio("Menu", [t["scanner_menu"], t["history_menu"]])
    
    # === PWA 설치 (앱처럼 쓰기) 가이드 ===
    st.divider()
    st.markdown("### 📱 앱처럼 사용하기")
    st.info(
        "**[안드로이드]**\n\n"
        "우측 상단 메뉴(⋮) ➔ **'홈 화면에 추가'**\n\n"
        "---\n"
        "**[아이폰(iOS)]**\n\n"
        "하단 공유 버튼(⍐) ➔ **'홈 화면에 추가'**"
    )

# 4. 피그마 디자인 완벽 이식 및 광채 효과 CSS
st.markdown(f"""
<style>
    .stApp {{ background-color: #f8f9fa; }}

    [data-testid="stFileUploader"] {{
        display: flex;
        justify-content: center;
        margin: 0 auto;
        width: 100% !important;
    }}

    /* 굵은 민트 테두리와 입체적 광채 */
    [data-testid="stFileUploader"] section {{
        background-color: #ffffff !important;
        border: 18px solid #86cc85 !important;
        box-shadow: 
            0 0 15px rgba(134, 204, 133, 0.5), 
            0 0 35px rgba(134, 204, 133, 0.3),
            0 0 55px rgba(134, 204, 133, 0.1) !important;
        border-radius: 50% !important;
        width: 65vw !important;  /* 화면 가로 너비의 65% */
        height: 65vw !important; /* 높이도 가로와 똑같이 맞춰서 항상 원형 유지 */
        max-width: 280px !important; /* 너무 커지는 것 방지 */
        max-height: 280px !important;
        margin: 0 auto !important;
        display: flex;
        flex-direction: column;
        justify-content: center;
        align-items: center;
        position: relative;
        transition: all 0.2s cubic-bezier(0.175, 0.885, 0.32, 1.275) !important;
    }}

    /* 클릭 시 쫀득하게 눌리는 반응 */
    [data-testid="stFileUploader"] section:active {{
        transform: scale(0.92);
        box-shadow: 0 0 65px rgba(134, 204, 133, 0.7) !important;
    }}

    [data-testid="stFileUploader"] section > div {{ display: none !important; }}
    [data-testid="stFileUploader"] section small {{ display: none !important; }}
    [data-testid="stFileUploader"] section span {{ display: none !important; }}

    /* 내부 아이콘: 화면이 작아지면 같이 작아짐 (최소 40px ~ 최대 70px) */
    [data-testid="stFileUploader"] section::before {{
        content: "📷"; 
        font-size: clamp(40px, 12vw, 70px); 
        margin-bottom: 2vw; /* 간격도 비율로 띄움 */
        z-index: 2;
    }}

    /* 내부 텍스트: 화면이 작아지면 같이 작아짐 (최소 14px ~ 최대 20px) */
    [data-testid="stFileUploader"] section::after {{
        content: "식단 스캔시작"; 
        font-size: clamp(14px, 4vw, 20px); 
        font-weight: 700;
        color: #333333;
        z-index: 2;
    }}

    [data-testid="stFileUploader"] section button {{
        opacity: 0 !important;
        position: absolute !important;
        width: 100% !important;
        height: 100% !important;
        z-index: 10;
        cursor: pointer;
    }}
    /* Streamlit 클라우드 기본 제공 하단 관리자 메뉴 및 여백 강제 숨김 */
    .viewerBadge_container {{ display: none !important; }}
    .viewerBadge_link {{ display: none !important; }}
    [data-testid="viewerBadge"] {{ display: none !important; }}
    [data-testid="stDecoration"] {{ display: none !important; }}
    [data-testid="stStatusWidget"] {{ display: none !important; }}
    [data-testid="stAppDeployButton"] {{ display: none !important; }}
    .stDeployButton {{ display: none !important; }}
    [data-testid="stToolbar"] {{ display: none !important; }}
    iframe[title="Streamlit App Deploy Button"] {{ display: none !important; }}
    iframe[src*="share.streamlit.io"] {{ display: none !important; visibility: hidden !important; }}

    /* 우측 상단 메뉴 버튼 및 스트림릿 워터마크 숨기기 */
    #MainMenu {{visibility: hidden;}}
    footer {{display: none !important; visibility: hidden !important; opacity: 0 !important; height: 0 !important; overflow: hidden !important;}}
    header {{display: none !important; visibility: hidden !important; height: 0 !important; overflow: hidden !important;}}
    
    /* embed 모드 해제로 인한 기본 상하 여백 최소화 */
    .block-container {{
        padding-top: 1rem !important;
        padding-bottom: 1rem !important;
        padding-left: 1rem !important;
        padding-right: 1rem !important;
        padding-bottom: 0px !important;
    }}

    /* 🚀 추가: 파일 업로드 후 생기는 파일명 박스 강제 숨기기 & 찌그러짐 방지 */
    [data-testid="stFileUploader"] > div {{ 
        display: none !important; 
    }}
    [data-testid="stUploadedFile"] {{
        display: none !important;
    }}
    /* 가로모드(Landscape) 방지 오버레이: 억지로 회전시 화면 덮어버림 */
    @media screen and (orientation: landscape) and (max-height: 600px) {{
        #root, .stApp {{ display: none !important; }}
        body::before {{
            content: "📱 측면(가로) 모드는 지원하지 않습니다.\\A스마트폰을 다시 세로로 돌려주세요.";
            white-space: pre-wrap;
            display: flex;
            justify-content: center;
            align-items: center;
            text-align: center;
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background-color: #333333;
            color: #ffffff;
            font-size: 20px;
            font-weight: 800;
            z-index: 999999;
            line-height: 1.5;
        }}
    }}
</style>
""", unsafe_allow_html=True)

# --- 🛑 사용자 로그인 및 접근 권한 체크 ---
import requests
import json

def pyrebase_auth(email, password, mode="login"):
    """REST API를 활용한 Firebase 기본 이메일/패스워드 인증 로직"""
    try:
        if "firebase" not in st.secrets:
            return False, "Firebase secrets 설정이 존재하지 않습니다."
        api_key = st.secrets["firebase"].get("api_key", "")
    except Exception:
        return False, "secrets.toml 파일을 읽는 중 오류가 발생했습니다."
        
    if not api_key:
        return False, "Firebase Web API Key가 secrets.toml에 없습니다."
        
    if mode == "signup":
        url = f"https://identitytoolkit.googleapis.com/v1/accounts:signUp?key={api_key}"
    else:
        url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={api_key}"
        
    payload = json.dumps({"email": email, "password": password, "returnSecureToken": True})
    headers = {'content-type': 'application/json'}
    
    try:
        res = requests.post(url, data=payload, headers=headers)
        data = res.json()
        if "error" in data:
            return False, data["error"]["message"]
        return True, data
    except Exception as e:
        return False, str(e)

if not st.session_state['logged_in']:
    import urllib.parse
    import uuid

    if "oauth_state" not in st.session_state:
        st.session_state["oauth_state"] = str(uuid.uuid4())
        
    google_client_id = ""
    google_client_secret = ""
    try:
        if "firebase" in st.secrets:
            google_client_id = st.secrets["firebase"].get("google_oauth_client_id", "")
            google_client_secret = st.secrets["firebase"].get("google_client_secret", "")
    except Exception:
        pass
        
    # --- [구글 소셜 로그인 리다이렉트 처리 콜백 로직] ---
    if "code" in st.query_params:
        code = st.query_params["code"]
        
        # 새 창 콜백 시 세션이 분리되어 oauth_state가 달라지는 Streamlit 특성 상, 
        # State 엄격 검증을 생략하고 바로 Token을 요청하여 인증을 진행합니다.
        token_url = "https://oauth2.googleapis.com/token"
        data = {
            "code": code,
            "client_id": google_client_id,
            "client_secret": google_client_secret,
            "redirect_uri": "https://nutrisort.streamlit.app",
            "grant_type": "authorization_code"
        }
        try:
            res = requests.post(token_url, data=data)
            if res.status_code == 200:
                access_token = res.json().get("access_token")
                userinfo_res = requests.get("https://www.googleapis.com/oauth2/v2/userinfo", headers={"Authorization": f"Bearer {access_token}"})
                if userinfo_res.status_code == 200:
                    userinfo = userinfo_res.json()
                    st.session_state["logged_in"] = True
                    st.session_state["user_id"] = userinfo.get("email", "google_user")  # 이메일을 고유 ID로 활용
                    st.query_params.clear()
                    st.rerun()
                else:
                    st.error(f"🚨 구글 사용자 정보를 불러오지 못했습니다! 에러코드: {userinfo_res.status_code}")
                    st.query_params.clear()
                    st.stop()
            else:
                st.error(f"🚨 구글 로그인 인증 토큰 교환에 실패했습니다!\n에러 응답: {res.text}")
                st.query_params.clear()
                st.stop()
        except Exception as e:
            st.error(f"🚨 구글 로그인 서버와의 통신 중 오류가 발생했습니다!\n{str(e)}")
            st.query_params.clear()
            st.stop()

    st.markdown("""
        <div style="text-align: center; margin-top: 5vh; margin-bottom: 3vh;">
            <div style="font-size: clamp(30px, 8vw, 40px); font-weight: 800; color: #333333; margin-bottom: 1vh;">🥗 NutriSort AI</div>
            <div style="font-size: clamp(16px, 4vw, 20px); font-weight: 500; color: #86cc85;">로그인하고 나만의 식단 기록을 시작하세요</div>
        </div>
    """, unsafe_allow_html=True)
    
    # 더 세련된 커스텀 상태 관리를 통한 모드 변경
    if 'auth_mode' not in st.session_state:
        st.session_state['auth_mode'] = 'login'
        
    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("로그인", type="primary" if st.session_state['auth_mode'] == 'login' else "secondary", use_container_width=True):
            st.session_state['auth_mode'] = 'login'
            st.rerun()
    with c2:
        if st.button("회원가입", type="primary" if st.session_state['auth_mode'] == 'signup' else "secondary", use_container_width=True):
            st.session_state['auth_mode'] = 'signup'
            st.rerun()
    with c3:
        if st.button("체험하기", type="primary" if st.session_state['auth_mode'] == 'guest' else "secondary", use_container_width=True):
            st.session_state['auth_mode'] = 'guest'
            st.rerun()
            
    st.markdown("<br>", unsafe_allow_html=True)
    
    if st.session_state['auth_mode'] in ['login', 'signup']:
        mode_text = "로그인" if st.session_state['auth_mode'] == 'login' else "회원가입"
        with st.form("auth_form_modern"):
            st.markdown(f"#### 🔒 {mode_text}")
            email = st.text_input("이메일 (Email)", placeholder="example@email.com")
            pwd = st.text_input("비밀번호 (Password)", type="password", placeholder="6자리 이상 입력")
            submitted = st.form_submit_button(f"{mode_text}하기", type="primary", use_container_width=True)
            
            if submitted:
                if not email or not pwd:
                    st.error("이메일과 비밀번호를 모두 입력해주세요.")
                else:
                    success, res = pyrebase_auth(email, pwd, "login" if st.session_state['auth_mode'] == 'login' else "signup")
                    
                    if success:
                        st.session_state['logged_in'] = True
                        st.session_state['user_id'] = res.get('localId', f"user_{email}")
                        st.rerun()
                    else:
                        if "EMAIL_EXISTS" in res:
                            st.error("이미 식단 앱에 가입된 이메일입니다. 로그인해주세요.")
                        elif "INVALID_LOGIN_CREDENTIALS" in res or "INVALID_PASSWORD" in res or "EMAIL_NOT_FOUND" in res:
                            st.error("이메일 또는 비밀번호가 잘못되었습니다.")
                        else:
                            st.error(f"{mode_text} 실패: {res}")
                
        st.markdown("<br> <div style='text-align:center; color:#888; font-size:14px;'>또는 소셜 계정으로 계속하기</div> <br>", unsafe_allow_html=True)
        col1, col2 = st.columns(2)
        with col1:
            if google_client_id:
                auth_url = "https://accounts.google.com/o/oauth2/v2/auth"
                params = {
                    "client_id": google_client_id,
                    "redirect_uri": "https://nutrisort.streamlit.app/",
                    "response_type": "code",
                    "scope": "openid email profile",
                    "state": st.session_state.get("oauth_state", "oauth"),
                    "access_type": "offline",
                    "prompt": "consent"
                }
                full_auth_url = f"{auth_url}?{urllib.parse.urlencode(params)}"
                
                # [Google Login 403 Forbidden 우회 끝판왕]
                # 자바스크립트나 일반 a 태그까지도 Streamlit의 내부 React Router 돔 이벤트 리스너가 
                # e.preventDefault()로 가로채기 때문에 403이 발생합니다.
                # 완벽한 해결책: 버튼 클릭 시 순수 브라우저의 기본 Form 제출 엔진을 사용하여 완전히 React를 무시하고 튕겨나갑니다.
                auth_html = f'''
                    <form action="https://accounts.google.com/o/oauth2/v2/auth" method="GET" target="_top" style="margin: 0; padding: 0;">
                        <input type="hidden" name="client_id" value="{google_client_id}">
                        <input type="hidden" name="redirect_uri" value="https://nutrisort.streamlit.app">
                        <input type="hidden" name="response_type" value="code">
                        <input type="hidden" name="scope" value="openid email profile">
                        <input type="hidden" name="state" value="{oauth_state}">
                        <input type="hidden" name="access_type" value="offline">
                        <input type="hidden" name="prompt" value="consent">
                        <button type="submit" style="display: flex; align-items: center; justify-content: center; height: 43px; width: 100%; border: 1px solid #dcdcdc; border-radius: 8px; font-weight: 600; font-size: 15.5px; background-color: white; color: #333333; cursor: pointer; text-decoration: none; transition: background-color 0.2s;">
                            🟢 구글로 로그인
                        </button>
                    </form>
                    <div style="text-align:center; font-size:11px; color:#999; margin-top:5px; line-height:1.2;">
                        * 만약 에러 시, 화면 우측 상단 ⋮ 메뉴에서<br>'기본 브라우저에서 열기'를 눌러주세요.
                    </div>
                '''
                st.components.v1.html(auth_html, height=80)
            else:
                st.button("🟢 구글 로그인", disabled=True, use_container_width=True, help="secrets에 설정이 필요합니다.")
                
        with col2:
            st.button("🟡 카카오 로그인", disabled=True, use_container_width=True)
            
    elif st.session_state['auth_mode'] == 'guest':
        st.info(
            "🚀 **비회원 체험 모드 안내**\\n\\n"
            "체험 모드에서는 본인의 현재 모바일 기기에만 임시 데이터가 기록되며, "
            "추후 브라우저 캐시가 삭제되면 기록이 지워질 수 있습니다."
        )
        
        if st.button("🚀 위 내용을 확인했으며, 게스트로 입장합니다", type="primary", use_container_width=True):
            st.session_state['logged_in'] = True
            st.session_state['user_id'] = "guest_user_demo"
            st.rerun()

    st.markdown("<br><br>", unsafe_allow_html=True)
    with st.expander("📲 스마트폰 배경화면에 앱으로 설치하기", expanded=False):
        st.markdown("""
            **NutriSort AI**는 설치형 웹앱(PWA)입니다. 아래 방법에 따라 스마트폰 홈 화면에 아이콘을 추가하시면, 매번 브라우저를 켤 필요 없이 진짜 앱처럼 **전체 화면(가로모드 고정 등)**으로 쾌적하게 이용하실 수 있습니다!
            
            🍎 **아이폰 (Safari)**
            1. 화면 화면 하단의 **[공유하기(네모와 위쪽 화살표)]** 아이콘 터치
            2. 메뉴를 조금 올려서 **[홈 화면에 추가]** 터치
            
            🤖 **안드로이드 (Chrome / 삼성 인터넷)**
            1. 화면 우측 상단(또는 하단)의 **[⋮] (메뉴)** 아이콘 터치
            2. **[홈 화면에 추가]** 또는 **[앱 설치]** 터치
        """)

    st.stop()  # 로그인되지 않은 사용자는 식단 분석 로직을 볼 수 없음


# 5. 메인 화면 - 식단 스캐너
if menu == t["scanner_menu"]:
    if 'app_stage' not in st.session_state:
        st.session_state['app_stage'] = 'main'
        
    API_KEY = st.secrets["GEMINI_API_KEY"]
    client = genai.Client(api_key=API_KEY)

    if st.session_state['app_stage'] == 'main':
        # 1️⃣ 전문적인 3행 타이틀 디자인 (반응형 폰트 및 여백 적용)
        title_parts = t["description"].split("|")
        st.markdown(f"""
            <div style="text-align: center; margin-top: 10px; margin-bottom: 3vh;">
                <div style="font-size: clamp(35px, 10vw, 50px); margin-bottom: 1vh;">{title_parts[0]}</div>
                <div style="font-size: clamp(20px, 6vw, 26px); font-weight: 800; color: #333333; line-height: 1.2;">{title_parts[1]}</div>
                <div style="font-size: clamp(14px, 4vw, 18px); font-weight: 500; color: #86cc85; margin-top: 1vh;">{title_parts[2]}</div>
            </div>
        """, unsafe_allow_html=True)
        
        # [무료 체험 일일 횟수 및 광고 리워드 로직]
        is_guest = st.session_state['user_id'] == 'guest_user_demo'
        if 'guest_usage_count' not in st.session_state:
            st.session_state['guest_usage_count'] = 0
            
        # 광고 시청 후 획득한 보너스 횟수
        if 'guest_bonus_count' not in st.session_state:
            st.session_state['guest_bonus_count'] = 0
            
        total_remaining = (2 + st.session_state['guest_bonus_count']) - st.session_state['guest_usage_count']
        
        if is_guest and total_remaining <= 0:
            st.warning("⚠️ **무료 체험 횟수(2회)를 모두 소진하셨습니다.**")
            st.info("💡 **광고를 보면 1회 무료 분석을 추가로 드립니다!**")
            
            # --- [Google AdSense 보상형 광고 시뮬레이션 버튼] ---
            # 실제 배포 시에는 구글 애드몹/애드센스 리워드형 태그로 교체 가능합니다.
            col_ad1, col_ad2 = st.columns([2, 1])
            with col_ad1:
                st.markdown("""
                    <div style="border:1px solid #ddd; padding:15px; border-radius:10px; background-color:#fefefe; text-align:center;">
                        <span style="color:#888; font-size:12px; display:block; margin-bottom:5px;">Google 광고</span>
                        <div style="font-weight:700; color:#4285F4; margin-bottom:5px;">혈당 관리 전문앱, NutriSort 프리미엄!</div>
                        <div style="font-size:14px; color:#555;">지금 구독하시면 첫 달 무료 혜택과 무제한 스캔을 제공합니다.</div>
                    </div>
                """, unsafe_allow_html=True)
            with col_ad2:
                st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True) # 줄맞춤
                if st.button("🎁 광고 보고 1회 충전", use_container_width=True):
                    # 광고를 보면 보너스 횟수를 1 부여하고 화면 리로드
                    st.session_state['guest_bonus_count'] += 1
                    st.rerun()
            
            st.markdown("<br><hr>", unsafe_allow_html=True)
            st.markdown("**기다리지 않고 바로 계속 분석하시겠어요?**")
            if st.button("🔐 회원가입 / 로그인 탭으로 이동", type="primary", use_container_width=True):
                st.session_state['logged_in'] = False
                st.session_state['auth_mode'] = 'signup'
                st.rerun()
        else:
            if is_guest:
                st.info(f"💡 현재 **무료 체험 모드**입니다. (남은 횟수: {total_remaining}회)")
                
            if 'uploader_key' not in st.session_state:
                st.session_state['uploader_key'] = 0
                
            # 2️⃣ 업로드 위젯 (외부 라벨을 완전히 숨김) - key를 동적으로 주어 이전 파일 잔여물 제거
            uploaded_file = st.file_uploader(
                "label_hidden", 
                type=["jpg", "png", "jpeg"],
                label_visibility="collapsed",
                key=f"uploader_{st.session_state['uploader_key']}"
            )
            
            if uploaded_file:
                if is_guest:
                    st.session_state['guest_usage_count'] += 1
                    
                img = Image.open(uploaded_file) # PIL을 떼고 Image로 바로 호출합니다.
                
                # [최적화] 이미지가 서버 메모리에 로드된 직후 브라우저 표시 및 전송 전에 500KB 이하로 압축
                img = compress_image(img, max_size_kb=500)
                
                st.session_state['current_img'] = img
                st.session_state['app_stage'] = 'analyze'
                st.rerun()

    elif st.session_state['app_stage'] == 'analyze':
        # 2페이지: 업로드 완료 & 분석 대기 페이지
        if st.button("⬅️ 메인으로 가기", key="btn_back_main_1", use_container_width=True):
            st.session_state['app_stage'] = 'main'
            st.session_state['current_img'] = None
            st.session_state['uploader_key'] += 1 # 강제로 새 업로더 생성(초기화)
            st.rerun()
            
        st.image(st.session_state['current_img'], use_container_width=True)
        
        # 분석 버튼 (피그마 스타일 & 무지개 애니메이션) - primary 타입으로 지정하여 다른 버튼(뒤로가기)과 CSS 분리
        if st.button(t["analyze_btn"], use_container_width=True, type="primary"):
            loading_placeholder = st.empty()
            loading_placeholder.markdown("""
                <style>
                /* 분석 버튼(primary) 자체를 무지개색 반응형 패널로 강제 변조 */
                button[data-testid="baseButton-primary"], 
                button[kind="primary"] {
                    background: linear-gradient(124deg, #ff2400, #e81d1d, #e8b71d, #e3e81d, #1de840, #1ddde8, #2b1de8, #dd00f3, #dd00f3) !important;
                    background-size: 1800% 1800% !important;
                    animation: rainbowBtn 2s ease infinite !important;
                    border: none !important;
                    box-shadow: 0 4px 15px rgba(0,0,0,0.2) !important;
                    position: relative !important;
                    pointer-events: none !important; /* 중복 클릭 방지 */
                }
                button[data-testid="baseButton-primary"] p, 
                button[kind="primary"] p {
                    color: transparent !important; /* 기존 글자 투명화 (공간 유지용) */
                }
                button[data-testid="baseButton-primary"]::after, 
                button[kind="primary"]::after {
                    content: '🤖 분석중. . .' !important;
                    position: absolute !important;
                    top: 50% !important;
                    left: 50% !important;
                    transform: translate(-50%, -50%) !important;
                    color: white !important;
                    font-weight: 800 !important;
                    font-size: 18px !important;
                    visibility: visible !important;
                    width: 100% !important;
                    text-align: center !important;
                    animation: blinkText 1.2s infinite !important;
                }
                @keyframes rainbowBtn { 
                    0% { background-position: 0% 50% }
                    50% { background-position: 100% 50% }
                    100% { background-position: 0% 50% }
                }
                @keyframes blinkText {
                    0% { opacity: 0.4; }
                    50% { opacity: 1; }
                    100% { opacity: 0.4; }
                }
                </style>
            """, unsafe_allow_html=True)
            import time
            import random
            
            max_retries = 3
            success = False
            last_err_msg = ""
            is_503 = False
            
            for attempt in range(max_retries):
                try:
                    # 에러 방지: 모델명을 'gemini-flash-latest'로 고정
                    prompt = f"Analyze food for glucose management. Format: FoodName|TrafficColor|Order. Lang: {lang}"
                    response = client.models.generate_content(
                        model="gemini-flash-latest", 
                        contents=[prompt, st.session_state['current_img']]
                    )
                    
                    # 결과 파싱
                    raw_lines = response.text.strip().split('\n')
                    items = []
                    for line in raw_lines:
                        if '|' in line and not any(x in line for x in ['---', 'Food', '음식']):
                            parts = line.split('|')
                            if len(parts) >= 3:
                                items.append([p.strip() for p in parts])
                    
                    if items:
                        sorted_items = sorted(items, key=lambda x: x[2])
                        # 소견 분석
                        advice_res = client.models.generate_content(
                            model="gemini-flash-latest", 
                            contents=[t["advice_prompt"], st.session_state['current_img']]
                        )
                        
                        st.session_state['current_analysis'] = {
                            "sorted_items": sorted_items,
                            "advice": advice_res.text,
                            "raw_img": st.session_state['current_img'] 
                        }
                        loading_placeholder.empty()
                        
                        # 분석이 끝나면 3페이지(결과 페이지)로 이동
                        st.session_state['app_stage'] = 'result'
                        success = True
                        st.rerun()
                    else:
                        loading_placeholder.empty()
                        st.warning("분석에 실패했습니다. 올바른 음식 사진인지 확인해 주세요.")
                        success = True
                        break
                        
                except Exception as e:
                    err_str = str(e)
                    last_err_msg = err_str
                    if '503' in err_str:
                        is_503 = True
                        if attempt < max_retries - 1:
                            # 503 발생 시 점진적으로 대기 시간을 늘립니다.
                            time.sleep(random.uniform(2.0, 4.0))
                            continue
                    
                    is_503 = '503' in err_str
                    break
                    
            if not success:
                loading_placeholder.empty()
                # 에러로 인해 스캔이 실패했으므로, 게스트 유저인 경우 차감된 횟수를 1회 복구해줍니다.
                if is_guest and st.session_state['guest_usage_count'] > 0:
                    st.session_state['guest_usage_count'] -= 1
                    
                if is_503:
                    st.error("🚀 접속자가 많아 AI 서버가 잠시 지연되고 있습니다. 2~3초 뒤에 다시 스캔 버튼을 눌러주세요!")
                else:
                    st.error(f"분석 엔진 오류가 발생했습니다. 잠시 후 다시 시도해 주세요. ({last_err_msg})")

    elif st.session_state['app_stage'] == 'result':
        # 3페이지: 분석 완료 및 결과 확인 페이지
        if st.button("⬅️ 메인으로 돌아가기 (다시하기)", key="btn_back_main_2", use_container_width=True):
            st.session_state['app_stage'] = 'main'
            st.session_state['current_img'] = None
            st.session_state['current_analysis'] = None
            if 'uploader_key' in st.session_state:
                st.session_state['uploader_key'] += 1
            st.rerun()
            
        st.image(st.session_state['current_img'], use_container_width=True)
        
        res = st.session_state['current_analysis']
        
        # 결과 페이지 렌더링 시 사진 아래(분석 내용 시작점)로 확실하게 자동 스크롤 (모바일 프레임 완벽 대응)
        st.components.v1.html(
            """
            <script>
                // Streamlit의 DOM 로딩 타이밍 이슈를 해결하기 위해 최대 1.5초간 반복 시도
                let scrollAttempts = 0;
                const scrollInterval = setInterval(() => {
                    scrollAttempts++;
                    // 모바일 PWA 또는 Iframe 내부일 수 있으므로 parent 및 최상위 window 객체까지 시도
                    let targetWindow = window;
                    try { if (window.parent) targetWindow = window.parent; } catch(e){}
                    
                    // 스크롤 시도 (문서 전체 창을 y축 400px 가량 아래로 밀어버림)
                    if (targetWindow.document && targetWindow.document.documentElement) {
                        targetWindow.scrollTo({ top: 400, left: 0, behavior: 'smooth' });
                        // 특정 엘리먼트를 찾아서 스크롤
                        const appNode = targetWindow.document.querySelector('.stApp');
                        if (appNode) {
                            appNode.scrollTo({ top: 400, left: 0, behavior: 'smooth' });
                        }
                    }
                    
                    if (scrollAttempts >= 10) { // 10회 (1초) 시도 후 종료
                        clearInterval(scrollInterval);
                    }
                }, 100);
            </script>
            """,
            height=0
        )
        
        html_cards = ""
        # 🚀 프리미엄 섭취 순서 카드 UI
        for idx, (name, color, score) in enumerate(res['sorted_items'], 1):
            clean_name = name.replace('*', '').strip()
            
            if any(x in color for x in ["초록", "녹색", "Green"]):
                theme_color = "#4CAF50" 
                bg_color = "#F1F8E9"    
                border_color = "#C5E1A5"
            elif any(x in color for x in ["노랑", "주황", "Yellow", "Orange"]):
                theme_color = "#FFB300" 
                bg_color = "#FFFDE7"    
                border_color = "#FFF59D"
            else:
                theme_color = "#F44336" 
                bg_color = "#FFEBEE"    
                border_color = "#EF9A9A"
                
            html_cards += f"""<div style="display: flex; align-items: center; padding: 16px; margin-bottom: 12px; border-radius: 12px; background-color: {bg_color}; border: 1px solid {border_color}; box-shadow: 0 2px 4px rgba(0,0,0,0.03);"><div style="width: 32px; height: 32px; border-radius: 50%; background-color: {theme_color}; color: white; display: flex; justify-content: center; align-items: center; font-weight: 800; font-size: 16px; margin-right: 15px; flex-shrink: 0;">{idx}</div><div style="flex-grow: 1; font-size: 18px; font-weight: 700; color: #333333;">{clean_name}</div><div style="width: 16px; height: 16px; border-radius: 50%; background-color: {theme_color}; box-shadow: 0 0 8px {theme_color}; flex-shrink: 0;"></div></div>"""
            
        # 하나로 묶인 그룹 UI 출력 & 대안 타이틀 출력
        st.markdown(f"""<div style="margin-top: 15px; margin-bottom: 35px; border-radius: 20px; box-shadow: 0 8px 25px rgba(0,0,0,0.06); overflow: hidden; border: 1px solid #f0f0f0; background: white;"><div style="background: linear-gradient(135deg, #1e293b, #334155); color: white; padding: 18px 22px; font-size: 18px; font-weight: 800; letter-spacing: -0.5px;">🥗 현재 음식 종류와 혈당신호등</div><div style="padding: 20px; background-color: #fafbfc;">{html_cards}</div></div><div style="display: flex; align-items: center; margin-bottom: 15px; margin-top: 10px;"><div style="width: 6px; height: 24px; background: linear-gradient(to bottom, #86cc85, #359f33); border-radius: 4px; margin-right: 10px;"></div><h3 style="margin: 0; font-size: 20px; font-weight: 800; color: #1e293b; letter-spacing: -0.5px;">혈당 스파이크 예방 최적의 대안</h3></div>""", unsafe_allow_html=True)
        
        st.info(res['advice'])
        
        if st.button(t["save_btn"], use_container_width=True):
            save_date = datetime.now().strftime("%Y-%m-%d %H:%M")
            
            # --- [Firebase Firestore 연결 및 저장 로직 예시] ---
            uid = st.session_state['user_id']
            try:
                from firebase_admin import firestore
                import firebase_admin
                from firebase_admin import credentials
                
                # 중복 초기화 방지
                if not firebase_admin._apps:
                    # secrets.toml에서 정보를 가져와 credentials 구성
                    key_dict = dict(st.secrets["firebase"])
                    cred = credentials.Certificate(key_dict)
                    firebase_admin.initialize_app(cred)
                
                db = firestore.client()
                
                # Firestore 저장을 위한 데이터 (Image는 URL로 올리거나 용량 문제로 일단 텍스트 결과만 저장)
                new_db_record = {
                    "date": save_date,
                    "sorted_items": res['sorted_items'],
                    "advice": res['advice'],
                    # "image_url": "업로드된 버킷 주소..." 
                }
                
                # users/{uid}/history 컬렉션에 새 난수 문서로 추가
                doc_ref = db.collection("users").document(uid).collection("history").document()
                doc_ref.set(new_db_record)
            except Exception as e:
                st.toast(f"데이터베이스 저장 에러: {str(e)}")
            # ------------------------------------------------
            
            st.session_state['history'].append({
                "date": save_date,
                "image": res['raw_img'],
                "sorted_items": res['sorted_items'],
                "advice": res['advice']
            })
            st.balloons()
            st.success(t["save_msg"])
            


# (나의 기록 탭은 기존 로직 유지하되 디자인 가이드 및 DB 불러오기 적용 가능)
elif menu == t["history_menu"]:
    st.title(f"📅 {t['history_menu']}")
    if st.session_state['history']:
        for rec in reversed(st.session_state['history']):
            with st.expander(f"🍴 {rec['date']} 식단 기록"):
                if rec['image']:
                    st.image(rec['image'], use_container_width=True)
                
                st.markdown(f"**[{t['analysis_title']}]**")
                for name, color, score in rec['sorted_items']:
                    icon_color = "#00FF00" if any(x in color for x in ["초록", "Green"]) else "#FFFF00" if any(x in color for x in ["노랑", "Yellow"]) else "#FF0000"
                    st.markdown(f"""
                        <div class="result-card">
                            <span style="font-size: 16px; font-weight: 500;">{name}</span>
                            <div style="width: 18px; height: 18px; background-color: {icon_color}; border-radius: 50%;"></div>
                        </div>
                    """, unsafe_allow_html=True)
                
                st.divider()
                st.markdown(f"**[{t['advice_title']}]**")
                st.success(rec['advice'])
    else:
        st.info("No records found.")
