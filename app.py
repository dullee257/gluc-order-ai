# -*- coding: utf-8 -*-
"""NutriSort AI - 한글 기본, UTF-8 소스·출력 통일."""
import sys
import os
import json

# Railway 등 Linux 환경에서 한글 출력 깨짐 방지
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

import streamlit as st

# --- Railway 등에서 환경 변수로 시크릿 읽기 (Streamlit Cloud는 st.secrets 유지) ---
def _get_secret(key, default=None):
    v = os.environ.get(key)
    if v:
        return v
    try:
        return getattr(st.secrets, "get", lambda k, d=None: d)(key, default)
    except Exception:
        return default

def _get_firebase_config():
    try:
        if getattr(st.secrets, "get", None) and st.secrets.get("firebase"):
            return st.secrets["firebase"]
    except Exception:
        pass
    cfg = {
        "api_key": os.environ.get("FIREBASE_API_KEY", ""),
        "google_oauth_client_id": os.environ.get("FIREBASE_GOOGLE_OAUTH_CLIENT_ID", ""),
        "google_client_secret": os.environ.get("FIREBASE_GOOGLE_CLIENT_SECRET", ""),
    }
    cred_json = os.environ.get("FIREBASE_CREDENTIALS_JSON")
    if cred_json:
        try:
            cfg.update(json.loads(cred_json))
        except Exception:
            pass
    else:
        for key in ["type", "project_id", "private_key_id", "private_key", "client_email", "client_id", "auth_uri", "token_uri", "auth_provider_x509_cert_url", "client_x509_cert_url", "universe_domain"]:
            val = os.environ.get("FIREBASE_" + key.upper())
            if val and key == "private_key":
                val = val.replace("\\n", "\n")
            if val:
                cfg[key] = val
    return cfg

# 호스팅 이전 시 이 URL만 바꾸면 됨 (환경 변수 BASE_URL 또는 Streamlit 시크릿)
try:
    _base = os.environ.get("BASE_URL") or getattr(st.secrets, "get", lambda k, d=None: d)("BASE_URL", "https://nutrisort.streamlit.app")
except Exception:
    _base = os.environ.get("BASE_URL", "https://nutrisort.streamlit.app")
BASE_URL = (_base or "https://nutrisort.streamlit.app").rstrip("/")

# 1. 카톡 및 네이버 인앱 브라우저 탈출 스크립트 (화면 깨짐 및 양식 중복 제출 방지)
_base_host = BASE_URL.replace("https://", "").replace("http://", "").split("/")[0]
_embed_script = """
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
    var targetUrl = '__BASE_URL__';
    
    // 카카오톡 및 네이버 앱 탈출 스크립트 (안드로이드에서는 반드시 풀버전 크롬 브라우저로 열리게 강제)
    if (agent.indexOf('kakao') > -1) {
        if (agent.indexOf('android') > -1) {
            win.top.location.href = 'intent://__BASE_HOST__#Intent;scheme=https;package=com.android.chrome;end';
        } else {
            win.top.location.href = 'kakaotalk://web/openExternal?url=' + encodeURIComponent(targetUrl);
        }
    } else if (agent.indexOf('naver') > -1) {
        if (agent.indexOf('android') > -1) {
            win.top.location.href = 'intent://__BASE_HOST__#Intent;scheme=https;package=com.android.chrome;end';
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
    """
st.components.v1.html(
    _embed_script.replace("__BASE_URL__", BASE_URL).replace("__BASE_HOST__", _base_host),
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
# Cal AI 스타일 하루 혈당 누적 추적
if 'daily_blood_sugar_score' not in st.session_state:
    st.session_state['daily_blood_sugar_score'] = 0
if 'daily_carbs' not in st.session_state:
    st.session_state['daily_carbs'] = 0
if 'daily_protein' not in st.session_state:
    st.session_state['daily_protein'] = 0
if 'daily_meals_count' not in st.session_state:
    st.session_state['daily_meals_count'] = 0
if 'user_goal' not in st.session_state:
    st.session_state['user_goal'] = '일반 관리'

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

# 3. 사이드바 메뉴 (기본 언어: 한글 KO)
with st.sidebar:
    st.title("설정")
    lang = st.radio("언어 / Language", ["KO", "EN"], index=0, help="KO=한국어(기본), EN=English")
    t = texts[lang]
    st.divider()
    st.title(t["sidebar_title"])
    menu = st.radio("Menu", [t["scanner_menu"], t["history_menu"]])
    # Streamlit Cloud 잠자기 화면 안내 (최초 1회)
    if "sleep_notice_seen" not in st.session_state:
        st.session_state["sleep_notice_seen"] = True
        st.info(
            "💤 **처음 접속 시** '잠시 멈췄다' 화면이 나오면 "
            "**'Yes, get this app back up!'** 버튼을 눌러 주세요. "
            "서버가 깨어나면 앱이 정상적으로 열립니다."
        )
    
    # === 혈당 관리 목표 설정 ===
    st.divider()
    st.markdown("### 🎯 나의 건강 목표")
    goal_options = ["일반 관리", "당뇨 관리", "다이어트", "근력 강화"]
    goal = st.selectbox("목표 선택", goal_options,
        index=goal_options.index(st.session_state['user_goal'])
    )
    if goal != st.session_state['user_goal']:
        st.session_state['user_goal'] = goal
    goal_carbs_map = {"일반 관리": 250, "당뇨 관리": 130, "다이어트": 150, "근력 강화": 300}
    target_carbs = goal_carbs_map[st.session_state['user_goal']]
    if st.session_state['daily_meals_count'] > 0:
        carb_pct = min(100, int(st.session_state['daily_carbs'] / max(target_carbs,1) * 100))
        bar_color = '#4CAF50' if carb_pct < 80 else '#FFB300' if carb_pct < 100 else '#F44336'
        st.markdown(f"""
        <div style="background:#f8f9fa;border-radius:10px;padding:12px;margin-top:6px;">
            <div style="font-size:12px;color:#888;margin-bottom:3px;">오늘 탄수화물</div>
            <div style="font-size:20px;font-weight:800;color:#333;">{st.session_state['daily_carbs']}g <span style="font-size:12px;color:#888;">/ {target_carbs}g</span></div>
            <div style="background:#e0e0e0;border-radius:4px;height:6px;margin-top:5px;">
                <div style="background:{bar_color};width:{carb_pct}%;height:6px;border-radius:4px;"></div>
            </div>
            <div style="font-size:11px;color:#888;margin-top:4px;">식사 {st.session_state['daily_meals_count']}회 분석</div>
        </div>
        """, unsafe_allow_html=True)
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
    # === 상용화: 건강 정보 면책 고지 (법적 권장) ===
    with st.expander("⚠️ 건강 정보 이용 안내", expanded=False):
        st.caption(
            "본 서비스는 의료 행위가 아니며, 진단·치료를 대체하지 않습니다. "
            "당뇨 등 질환 관리 시 반드시 의료진과 상담하세요. "
            "식단·영양 정보는 참고용이며, 개인 결과에 따라 차이가 있을 수 있습니다."
        )

# 4. 피그마 디자인 + 한글 표시 보장 (UTF-8·폰트)
st.markdown(f"""
<style>
    /* 한글 표시: Noto Sans KR 로드 후 전역 적용 (한글 깨짐 방지) */
    @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;700&display=swap');
    .stApp, .stApp .stMarkdown, .stApp p, .stApp span, .stApp label, .stApp div[data-testid], 
    [data-testid="stFileUploader"] section::after {{
        font-family: "Noto Sans KR", "Malgun Gothic", "Apple SD Gothic Neo", "Nanum Gothic", sans-serif !important;
    }}

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
        firebase_cfg = _get_firebase_config()
        api_key = firebase_cfg.get("api_key", "")
    except Exception:
        return False, "Firebase 설정을 읽는 중 오류가 발생했습니다."
        
    if not api_key:
        return False, "Firebase Web API Key가 설정에 없습니다."
        
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
        
    firebase_cfg = _get_firebase_config()
    google_client_id = firebase_cfg.get("google_oauth_client_id", "")
    google_client_secret = firebase_cfg.get("google_client_secret", "")
        
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
            "redirect_uri": BASE_URL,
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
                    "redirect_uri": BASE_URL + "/",
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
                oauth_state = st.session_state.get("oauth_state", "oauth")
                auth_html = f'''
                    <form action="https://accounts.google.com/o/oauth2/v2/auth" method="GET" target="_top" style="margin: 0; padding: 0;">
                        <input type="hidden" name="client_id" value="{google_client_id}">
                        <input type="hidden" name="redirect_uri" value="{BASE_URL}">
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
            "🚀 **비회원 체험 모드 안내**\n\n"
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
        
    API_KEY = _get_secret("GEMINI_API_KEY")
    if not API_KEY:
        st.error("GEMINI_API_KEY가 설정되지 않았습니다. 환경 변수 또는 시크릿을 확인해 주세요.")
        st.stop()
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
                    # Cal AI 스타일 혈당 분석 프롬프트 (GI + 탄수화물 + 단백질)
                    if lang == "KO":
                        prompt = """사진 속 음식들을 혈당 관리 관점에서 분석해줘.
각 음식을 아래 형식으로 정확히 반환해 (헤더 없이 데이터만, 한 줄에 하나):
음식이름|GI수치|탄수화물g|단백질g|혈당신호|섭취순서

규칙:
- GI수치: 0~100 정수 (혈당지수)
- 탄수화물g: 해당 음식 예상 섭취량 기준 정수
- 단백질g: 해당 음식 예상 섭취량 기준 정수
- 혈당신호: 초록/노랑/빨강 중 하나
- 섭취순서: 1부터 시작

예시:
나물반찬|22|8|3|초록|1
잡곡밥|55|45|5|노랑|2
삼겹살|28|0|22|초록|3"""
                    else:
                        prompt = """Analyze foods in the photo for blood sugar management.
Return each food in this exact format (data only, one line each):
FoodName|GI|Carbs_g|Protein_g|Signal|EatingOrder
- GI: integer 0-100
- Carbs_g and Protein_g: estimated grams (integer)
- Signal: Green/Yellow/Red
- EatingOrder: integer from 1"""

                    response = client.models.generate_content(
                        model="gemini-flash-latest",
                        contents=[prompt, st.session_state['current_img']]
                    )

                    # 결과 파싱 (새 형식: name|GI|carbs|protein|color|order)
                    raw_lines = response.text.strip().split('\n')
                    items = []
                    for line in raw_lines:
                        line = line.strip()
                        if '|' not in line:
                            continue
                        skip_words = ['---', 'GI', 'Food', '음식이름', '형식', '규칙', '예시']
                        if any(x in line for x in skip_words):
                            continue
                        parts = [p.strip() for p in line.split('|')]
                        try:
                            if len(parts) >= 6:
                                gi = int(''.join(filter(str.isdigit, parts[1])) or '50')
                                carbs = int(''.join(filter(str.isdigit, parts[2])) or '0')
                                protein = int(''.join(filter(str.isdigit, parts[3])) or '0')
                                order = int(''.join(filter(str.isdigit, parts[5])) or '99')
                                items.append([parts[0], gi, carbs, protein, parts[4], order])
                            elif len(parts) >= 3:
                                # 구 형식 fallback
                                order = int(''.join(filter(str.isdigit, parts[2])) or '99')
                                items.append([parts[0], 50, 30, 10, parts[1] if len(parts) > 1 else '노랑', order])
                        except Exception:
                            pass

                    if items:
                        sorted_items = sorted(items, key=lambda x: x[5])
                        # 혈당 스코어 계산
                        avg_gi = int(sum(i[1] for i in items) / len(items))
                        blood_sugar_score = min(100, avg_gi)
                        total_carbs = sum(i[2] for i in items)
                        total_protein = sum(i[3] for i in items)

                        # 소견 분석
                        advice_res = client.models.generate_content(
                            model="gemini-flash-latest",
                            contents=[t["advice_prompt"], st.session_state['current_img']]
                        )

                        # 하루 누적 업데이트
                        prev_count = st.session_state['daily_meals_count']
                        st.session_state['daily_blood_sugar_score'] = int(
                            (st.session_state['daily_blood_sugar_score'] * prev_count + blood_sugar_score) / (prev_count + 1)
                        )
                        st.session_state['daily_carbs'] += total_carbs
                        st.session_state['daily_protein'] += total_protein
                        st.session_state['daily_meals_count'] += 1

                        st.session_state['current_analysis'] = {
                            "sorted_items": sorted_items,
                            "advice": advice_res.text,
                            "raw_img": st.session_state['current_img'],
                            "blood_sugar_score": blood_sugar_score,
                            "total_carbs": total_carbs,
                            "total_protein": total_protein,
                            "avg_gi": avg_gi,
                        }
                        loading_placeholder.empty()
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
        if st.button("⬅️ 메인으로 돌아가기 (다시하기)", key="btn_back_main_2", use_container_width=True):
            st.session_state['app_stage'] = 'main'
            st.session_state['current_img'] = None
            st.session_state['current_analysis'] = None
            if 'uploader_key' in st.session_state:
                st.session_state['uploader_key'] += 1
            st.rerun()

        res = st.session_state['current_analysis']
        score = res.get('blood_sugar_score', 50)
        total_carbs = res.get('total_carbs', 0)
        total_protein = res.get('total_protein', 0)
        avg_gi = res.get('avg_gi', score)

        if score <= 40:
            risk_label, risk_color = "혈당 안전 🟢", "#4CAF50"
        elif score <= 65:
            risk_label, risk_color = "주의 필요 🟡", "#FFB300"
        else:
            risk_label, risk_color = "혈당 위험 🔴", "#F44336"

        # ── 1. 이미지 + 원형 혈당 스코어 (Cal AI 핵심 UI) ──
        col_img, col_score = st.columns([1, 1])
        with col_img:
            st.image(res['raw_img'], use_container_width=True)
        with col_score:
            st.markdown(f"""
            <div style="display:flex;flex-direction:column;justify-content:center;align-items:center;height:100%;padding:8px;">
                <div style="font-size:12px;color:#888;font-weight:600;letter-spacing:1px;margin-bottom:6px;">혈당 스코어</div>
                <div style="width:110px;height:110px;border-radius:50%;
                    background:conic-gradient({risk_color} {score}%, #f0f0f0 {score}%);
                    display:flex;justify-content:center;align-items:center;
                    box-shadow:0 4px 18px {risk_color}44;">
                    <div style="width:82px;height:82px;border-radius:50%;background:white;
                        display:flex;flex-direction:column;justify-content:center;align-items:center;">
                        <div style="font-size:26px;font-weight:900;color:{risk_color};line-height:1;">{score}</div>
                        <div style="font-size:9px;color:#aaa;">/ 100</div>
                    </div>
                </div>
                <div style="margin-top:10px;background:{risk_color}22;color:{risk_color};
                    font-weight:700;font-size:13px;padding:5px 12px;border-radius:20px;">{risk_label}</div>
            </div>
            """, unsafe_allow_html=True)

        # ── 2. 매크로 요약 3칸 ──
        st.markdown(f"""
        <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;margin:14px 0;">
            <div style="background:white;border-radius:14px;padding:13px;text-align:center;box-shadow:0 2px 8px rgba(0,0,0,0.06);border:1px solid #f0f0f0;">
                <div style="font-size:18px;">🍚</div>
                <div style="font-size:21px;font-weight:900;color:#333;margin:3px 0;">{total_carbs}g</div>
                <div style="font-size:10px;color:#888;">탄수화물</div>
            </div>
            <div style="background:white;border-radius:14px;padding:13px;text-align:center;box-shadow:0 2px 8px rgba(0,0,0,0.06);border:1px solid #f0f0f0;">
                <div style="font-size:18px;">🩸</div>
                <div style="font-size:21px;font-weight:900;color:{risk_color};margin:3px 0;">{avg_gi}</div>
                <div style="font-size:10px;color:#888;">평균 GI</div>
            </div>
            <div style="background:white;border-radius:14px;padding:13px;text-align:center;box-shadow:0 2px 8px rgba(0,0,0,0.06);border:1px solid #f0f0f0;">
                <div style="font-size:18px;">💪</div>
                <div style="font-size:21px;font-weight:900;color:#333;margin:3px 0;">{total_protein}g</div>
                <div style="font-size:10px;color:#888;">단백질</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        # ── 3. 혈당 스파이크 예측 바 ──
        spike_label = "낮음 🙂" if score <= 40 else "보통 😐" if score <= 65 else "높음 😰"
        st.markdown(f"""
        <div style="background:white;border-radius:14px;padding:14px;margin-bottom:14px;box-shadow:0 2px 8px rgba(0,0,0,0.06);border:1px solid #f0f0f0;">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:7px;">
                <div style="font-weight:700;font-size:14px;color:#333;">⚡ 혈당 스파이크 예측</div>
                <div style="font-weight:700;font-size:14px;color:{risk_color};">{spike_label}</div>
            </div>
            <div style="background:#f0f0f0;border-radius:8px;height:10px;overflow:hidden;">
                <div style="background:linear-gradient(90deg,#4CAF50,#FFB300,#F44336);width:{score}%;height:10px;border-radius:8px;"></div>
            </div>
            <div style="display:flex;justify-content:space-between;margin-top:4px;">
                <div style="font-size:10px;color:#aaa;">안전(0)</div>
                <div style="font-size:10px;color:#aaa;">위험(100)</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        # ── 4. 음식별 혈당 분석 카드 (GI 바 포함) ──
        st.markdown("""<div style="display:flex;align-items:center;margin:12px 0 8px;"><div style="width:5px;height:20px;background:linear-gradient(to bottom,#86cc85,#359f33);border-radius:4px;margin-right:9px;"></div><div style="font-size:16px;font-weight:800;color:#1e293b;">음식별 혈당 분석</div></div>""", unsafe_allow_html=True)

        cards_html = ""
        for idx, item in enumerate(res['sorted_items'], 1):
            name = str(item[0]).replace('*', '').strip()
            gi = item[1] if len(item) > 1 and isinstance(item[1], int) else 50
            carbs = item[2] if len(item) > 2 and isinstance(item[2], int) else 0
            protein = item[3] if len(item) > 3 and isinstance(item[3], int) else 0
            color_str = str(item[4]) if len(item) > 4 else '노랑'
            if any(x in color_str for x in ["초록", "Green"]):
                tc, bg, bc, gl = "#4CAF50", "#F1F8E9", "#C5E1A5", "낮음"
            elif any(x in color_str for x in ["노랑", "주황", "Yellow", "Orange"]):
                tc, bg, bc, gl = "#FFB300", "#FFFDE7", "#FFF59D", "보통"
            else:
                tc, bg, bc, gl = "#F44336", "#FFEBEE", "#EF9A9A", "높음"
            gi_w = min(100, gi)
            cards_html += f"""
            <div style="background:{bg};border:1px solid {bc};border-radius:14px;padding:13px;margin-bottom:9px;">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:7px;">
                    <div style="display:flex;align-items:center;gap:9px;">
                        <div style="width:26px;height:26px;border-radius:50%;background:{tc};color:white;display:flex;justify-content:center;align-items:center;font-weight:800;font-size:13px;flex-shrink:0;">{idx}</div>
                        <div style="font-size:15px;font-weight:700;color:#1e293b;">{name}</div>
                    </div>
                    <div style="text-align:right;">
                        <div style="font-size:17px;font-weight:900;color:{tc};">GI {gi}</div>
                        <div style="font-size:10px;color:#888;">{gl}</div>
                    </div>
                </div>
                <div style="background:rgba(255,255,255,0.5);border-radius:5px;height:5px;margin-bottom:7px;">
                    <div style="background:{tc};width:{gi_w}%;height:5px;border-radius:5px;"></div>
                </div>
                <div style="display:flex;gap:14px;">
                    <div style="font-size:12px;color:#555;">🍚 탄수화물 <b>{carbs}g</b></div>
                    <div style="font-size:12px;color:#555;">💪 단백질 <b>{protein}g</b></div>
                </div>
            </div>"""
        st.markdown(cards_html, unsafe_allow_html=True)

        # ── 5. 권장 섭취 순서 태그 ──
        st.markdown("""<div style="display:flex;align-items:center;margin:12px 0 8px;"><div style="width:5px;height:20px;background:linear-gradient(to bottom,#86cc85,#359f33);border-radius:4px;margin-right:9px;"></div><div style="font-size:16px;font-weight:800;color:#1e293b;">🥗 권장 섭취 순서</div></div>""", unsafe_allow_html=True)
        tags_html = '<div style="display:flex;flex-wrap:wrap;gap:7px;margin-bottom:14px;">'
        for idx, item in enumerate(res['sorted_items'], 1):
            name = str(item[0]).replace('*', '').strip()
            color_str = str(item[4]) if len(item) > 4 else '노랑'
            tc = "#4CAF50" if any(x in color_str for x in ["초록","Green"]) else "#FFB300" if any(x in color_str for x in ["노랑","Yellow","Orange"]) else "#F44336"
            tags_html += f'<div style="background:{tc}22;border:1px solid {tc}55;border-radius:20px;padding:5px 12px;font-size:13px;font-weight:600;color:{tc};">{idx}. {name}</div>'
        tags_html += '</div>'
        st.markdown(tags_html, unsafe_allow_html=True)

        # ── 6. AI 소견 ──
        st.markdown("""<div style="display:flex;align-items:center;margin:12px 0 8px;"><div style="width:5px;height:20px;background:linear-gradient(to bottom,#86cc85,#359f33);border-radius:4px;margin-right:9px;"></div><div style="font-size:16px;font-weight:800;color:#1e293b;">🤖 혈당 관리 AI 소견</div></div>""", unsafe_allow_html=True)
        st.info(res['advice'])

        # ── 7. 저장 버튼 ──
        if st.button(t["save_btn"], use_container_width=True):
            save_date = datetime.now().strftime("%Y-%m-%d %H:%M")
            uid = st.session_state['user_id']
            try:
                from firebase_admin import firestore
                import firebase_admin
                from firebase_admin import credentials
                if not firebase_admin._apps:
                    # firebase_admin SDK가 인식하는 서비스 계정 키만 추출
                    # (google_oauth_client_id, google_client_secret, api_key 등 비SDK 키 제외)
                    _FIREBASE_ADMIN_KEYS = [
                        "type", "project_id", "private_key_id", "private_key",
                        "client_email", "client_id", "auth_uri", "token_uri",
                        "auth_provider_x509_cert_url", "client_x509_cert_url",
                        "universe_domain"
                    ]
                    key_dict = {k: v for k, v in _get_firebase_config().items() if k in _FIREBASE_ADMIN_KEYS}
                    cred = credentials.Certificate(key_dict)
                    firebase_admin.initialize_app(cred)
                db = firestore.client()
                new_db_record = {
                    "date": save_date,
                    "sorted_items": [[str(x) for x in item] for item in res['sorted_items']],
                    "advice": res['advice'],
                    "blood_sugar_score": res.get('blood_sugar_score', 0),
                    "total_carbs": res.get('total_carbs', 0),
                    "total_protein": res.get('total_protein', 0),
                    "avg_gi": res.get('avg_gi', 0),
                }
                doc_ref = db.collection("users").document(uid).collection("history").document()
                doc_ref.set(new_db_record)
            except Exception as e:
                st.toast(f"DB 저장 에러: {str(e)}")

            st.session_state['history'].append({
                "date": save_date,
                "image": res['raw_img'],
                "sorted_items": res['sorted_items'],
                "advice": res['advice'],
                "blood_sugar_score": res.get('blood_sugar_score', 0),
                "total_carbs": res.get('total_carbs', 0),
                "total_protein": res.get('total_protein', 0),
                "avg_gi": res.get('avg_gi', 0),
            })
            st.balloons()
            st.success(t["save_msg"])


# ── 나의 기록 탭 (Cal AI 스타일 히스토리) ──
elif menu == t["history_menu"]:
    st.title(f"📅 {t['history_menu']}")

    # 오늘 하루 요약 대시보드
    if st.session_state['daily_meals_count'] > 0:
        goal_carbs_map2 = {"일반 관리": 250, "당뇨 관리": 130, "다이어트": 150, "근력 강화": 300}
        target_c = goal_carbs_map2.get(st.session_state['user_goal'], 250)
        ds = st.session_state['daily_blood_sugar_score']
        ds_color = "#4CAF50" if ds <= 40 else "#FFB300" if ds <= 65 else "#F44336"
        ds_label = "안전" if ds <= 40 else "주의" if ds <= 65 else "위험"
        carb_pct2 = min(100, int(st.session_state['daily_carbs'] / max(target_c, 1) * 100))
        st.markdown(f"""
        <div style="background:linear-gradient(135deg,#1e293b,#334155);border-radius:20px;padding:20px;margin-bottom:18px;color:white;">
            <div style="font-size:13px;color:#94a3b8;margin-bottom:10px;">📊 오늘의 혈당 관리 현황</div>
            <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;margin-bottom:12px;">
                <div style="text-align:center;">
                    <div style="font-size:26px;font-weight:900;color:{ds_color};">{ds}</div>
                    <div style="font-size:10px;color:#94a3b8;">평균 혈당스코어</div>
                    <div style="font-size:12px;font-weight:700;color:{ds_color};">{ds_label}</div>
                </div>
                <div style="text-align:center;">
                    <div style="font-size:26px;font-weight:900;color:white;">{st.session_state['daily_carbs']}g</div>
                    <div style="font-size:10px;color:#94a3b8;">탄수화물</div>
                    <div style="font-size:11px;color:#94a3b8;">목표 {target_c}g</div>
                </div>
                <div style="text-align:center;">
                    <div style="font-size:26px;font-weight:900;color:white;">{st.session_state['daily_meals_count']}</div>
                    <div style="font-size:10px;color:#94a3b8;">분석 식사</div>
                    <div style="font-size:11px;color:#94a3b8;">{st.session_state['user_goal']}</div>
                </div>
            </div>
            <div style="background:rgba(255,255,255,0.15);border-radius:6px;height:7px;">
                <div style="background:{ds_color};width:{carb_pct2}%;height:7px;border-radius:6px;"></div>
            </div>
        </div>
        """, unsafe_allow_html=True)
        if st.button("🔄 오늘 기록 초기화", use_container_width=True):
            st.session_state['daily_blood_sugar_score'] = 0
            st.session_state['daily_carbs'] = 0
            st.session_state['daily_protein'] = 0
            st.session_state['daily_meals_count'] = 0
            st.rerun()
        st.markdown("---")

    if st.session_state['history']:
        for rec in reversed(st.session_state['history']):
            rec_score = rec.get('blood_sugar_score', 0)
            rec_carbs = rec.get('total_carbs', 0)
            rec_gi = rec.get('avg_gi', 0)
            rc = "#4CAF50" if rec_score <= 40 else "#FFB300" if rec_score <= 65 else "#F44336"
            rl = "안전" if rec_score <= 40 else "주의" if rec_score <= 65 else "위험"
            with st.expander(f"🍴 {rec['date']}  |  혈당 {rec_score}점({rl})  |  탄수화물 {rec_carbs}g"):
                if rec.get('image'):
                    st.image(rec['image'], use_container_width=True)
                st.markdown(f"""
                <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin:10px 0;">
                    <div style="background:{rc}11;border:1px solid {rc}33;border-radius:10px;padding:10px;text-align:center;">
                        <div style="font-size:18px;font-weight:900;color:{rc};">{rec_score}</div>
                        <div style="font-size:10px;color:#888;">혈당스코어</div>
                    </div>
                    <div style="background:#f8f9fa;border-radius:10px;padding:10px;text-align:center;">
                        <div style="font-size:18px;font-weight:900;color:#333;">{rec_carbs}g</div>
                        <div style="font-size:10px;color:#888;">탄수화물</div>
                    </div>
                    <div style="background:#f8f9fa;border-radius:10px;padding:10px;text-align:center;">
                        <div style="font-size:18px;font-weight:900;color:#333;">{rec_gi}</div>
                        <div style="font-size:10px;color:#888;">평균 GI</div>
                    </div>
                </div>
                """, unsafe_allow_html=True)
                for item in rec['sorted_items']:
                    name = str(item[0]).replace('*', '').strip() if item else ''
                    color_str = str(item[4]) if len(item) > 4 else (str(item[1]) if len(item) > 1 else '노랑')
                    gi_val = item[1] if len(item) > 1 and isinstance(item[1], int) else '-'
                    ic = "#4CAF50" if any(x in color_str for x in ["초록","Green"]) else "#FFB300" if any(x in color_str for x in ["노랑","Yellow"]) else "#F44336"
                    st.markdown(f"""
                    <div style="display:flex;align-items:center;padding:7px 0;border-bottom:1px solid #f0f0f0;">
                        <div style="width:12px;height:12px;background:{ic};border-radius:50%;margin-right:9px;flex-shrink:0;"></div>
                        <span style="font-size:14px;font-weight:500;">{name}</span>
                        <span style="margin-left:auto;font-size:12px;color:#888;">GI {gi_val}</span>
                    </div>""", unsafe_allow_html=True)
                st.divider()
                st.info(rec['advice'])
    else:
        st.info("저장된 식단 기록이 없습니다. 분석 후 '저장하기' 버튼을 눌러보세요!")
