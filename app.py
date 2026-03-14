# -*- coding: utf-8 -*-
"""NutriSort AI - 한글 기본, UTF-8 소스·출력 통일."""
import sys
import os
import json

from translation import LANG_DICT, get_text, SUPPORTED_LANGS, LANG_LABELS, LANG_HTML_ATTR, GOAL_INTERNAL_KEYS
from prompts import get_analysis_prompt

# Railway 등 Linux 환경에서 한글 출력 깨짐 방지
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

import streamlit as st

# ※ 반드시 첫 번째 Streamlit 호출이어야 함 (그렇지 않으면 오류 발생)
st.set_page_config(
    page_title="혈당스캐너 - NutriSort",
    page_icon="🩸",
    layout="centered",
    initial_sidebar_state="collapsed",
    menu_items={"Get Help": None, "Report a bug": None, "About": None},
)

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

# 2. 세션 상태 초기화
if 'history' not in st.session_state:
    st.session_state['history'] = []
if 'current_analysis' not in st.session_state:
    st.session_state['current_analysis'] = None
if 'logged_in' not in st.session_state:
    st.session_state['logged_in'] = False
if 'user_id' not in st.session_state:
    st.session_state['user_id'] = None
if 'login_type' not in st.session_state:
    st.session_state['login_type'] = None  # 'google' | 'guest'
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
if 'lang' not in st.session_state:
    st.session_state['lang'] = 'KO'

# 다국어: translation.py의 LANG_DICT 사용 (언어 추가 시 SUPPORTED_LANGS만 확장)
_current_lang = st.session_state.get("lang", "KO")
if _current_lang not in LANG_DICT:
    _current_lang = "KO"
    st.session_state["lang"] = _current_lang
t = LANG_DICT[_current_lang]

# 3. 사이드바 메뉴 (언어와 무관한 안정 키 사용 → 분석 후 rerun 시에도 스캐너/결과 화면 유지)
with st.sidebar:
    st.title(t.get("sidebar_title", "설정"))
    # 로그인 타입 뱃지: 게스트는 주황색 경고, 계정 로그인은 초록 표시
    _lt = st.session_state.get("login_type")
    if _lt == "guest":
        st.markdown(
            f'<div style="background:#FF9800;color:white;padding:6px 12px;border-radius:8px;font-size:13px;font-weight:700;text-align:center;margin-bottom:8px;">⚠️ {t["login_badge_guest"]}</div>',
            unsafe_allow_html=True,
        )
    elif _lt == "google":
        st.markdown(
            f'<div style="background:#4CAF50;color:white;padding:6px 12px;border-radius:8px;font-size:13px;font-weight:600;text-align:center;margin-bottom:8px;">✓ {t["login_badge_account"]}</div>',
            unsafe_allow_html=True,
        )
    st.divider()
    menu_key = st.radio(
        t.get("menu_label", "메뉴"),
        options=["scanner", "history"],
        format_func=lambda x: t["scanner_menu"] if x == "scanner" else t["history_menu"],
        key="sidebar_menu",
    )
    if "sleep_notice_seen" not in st.session_state:
        st.session_state["sleep_notice_seen"] = True
        st.info(t.get("sleep_notice", ""))
    
    # === 혈당 관리 목표 설정 (저장은 항상 GOAL_INTERNAL_KEYS 한글 키) ===
    st.divider()
    st.markdown(f"### 🎯 {t['my_health_goal']}")
    goal_display = t.get("goal_display", {})
    goal_options = [goal_display.get(k, k) for k in GOAL_INTERNAL_KEYS]
    current_internal = st.session_state.get("user_goal", "일반 관리")
    current_display = goal_display.get(current_internal, current_internal)
    goal_index = goal_options.index(current_display) if current_display in goal_options else 0
    goal = st.selectbox(t["goal_select"], goal_options, index=goal_index)
    goal_display_rev = {v: k for k, v in goal_display.items()}
    goal_to_save = goal_display_rev.get(goal, current_internal)
    if goal_to_save != st.session_state['user_goal']:
        st.session_state['user_goal'] = goal_to_save
    goal_carbs_map = {"일반 관리": 250, "당뇨 관리": 130, "다이어트": 150, "근력 강화": 300}
    target_carbs = goal_carbs_map[st.session_state['user_goal']]
    if st.session_state['daily_meals_count'] > 0:
        carb_pct = min(100, int(st.session_state['daily_carbs'] / max(target_carbs,1) * 100))
        bar_color = '#4CAF50' if carb_pct < 80 else '#FFB300' if carb_pct < 100 else '#F44336'
        meals_text = t["meals_analyzed"].replace("{n}", str(st.session_state['daily_meals_count']))
        st.markdown(f"""
        <div style="background:#f8f9fa;border-radius:10px;padding:12px;margin-top:6px;">
            <div style="font-size:12px;color:#888;margin-bottom:3px;">{t['today_carbs']}</div>
            <div style="font-size:20px;font-weight:800;color:#333;">{st.session_state['daily_carbs']}g <span style="font-size:12px;color:#888;">/ {target_carbs}g</span></div>
            <div style="background:#e0e0e0;border-radius:4px;height:6px;margin-top:5px;">
                <div style="background:{bar_color};width:{carb_pct}%;height:6px;border-radius:4px;"></div>
            </div>
            <div style="font-size:11px;color:#888;margin-top:4px;">{meals_text}</div>
        </div>
        """, unsafe_allow_html=True)
    # === 상용화: 건강 정보 면책 고지 (법적 권장) ===
    with st.expander(f"⚠️ {t['health_disclaimer_title']}", expanded=False):
        st.caption(t.get("health_disclaimer_body", ""))

# 3-2. 언어 선택 드롭다운: 로그인/체험 전(1페이지)에만 표시, 2페이지부터는 숨김
if not st.session_state.get("logged_in", False):
    st.markdown("<div style='height:6px;'></div>", unsafe_allow_html=True)
    lang_col1, lang_col2, lang_col3 = st.columns([1, 2, 1])
    with lang_col2:
        current_idx = SUPPORTED_LANGS.index(st.session_state["lang"]) if st.session_state["lang"] in SUPPORTED_LANGS else 0
        selected_lang = st.selectbox(
            "Language",
            options=SUPPORTED_LANGS,
            format_func=lambda x: LANG_LABELS.get(x, x),
            index=current_idx,
            key="lang_select_top",
            label_visibility="collapsed",
        )
    if selected_lang != st.session_state["lang"]:
        st.session_state["lang"] = selected_lang
        t = LANG_DICT[st.session_state["lang"]]
        st.rerun()
    st.markdown("<div style='height:4px;'></div>", unsafe_allow_html=True)

# 3-3. 브라우저 자동번역 방지: 선택된 언어로 HTML lang 속성 설정
_lang_attr = LANG_HTML_ATTR.get(st.session_state.get("lang", "KO"), "ko")
st.markdown(f'<script>try{{document.documentElement.lang="{_lang_attr}";}}catch(e){{}}</script>', unsafe_allow_html=True)

# 4. 피그마 디자인 + 한글 표시 보장 (UTF-8·폰트)
# 업로더 placeholder: CSS content 내 따옴표·백슬래시 이스케이프 (글자 오류 방지)
_uploader_ph = (t.get("uploader_placeholder") or "식단 스캔 시작").replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
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
        content: "{_uploader_ph}"; 
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
                    st.session_state["user_id"] = userinfo.get("email", "google_user")
                    st.session_state["login_type"] = "google"
                    st.query_params.clear()
                    st.rerun()
                else:
                    st.error(get_text(st.session_state.get("lang", "KO"), "google_oauth_err_userinfo", code=userinfo_res.status_code))
                    st.query_params.clear()
                    st.stop()
            else:
                st.error(get_text(st.session_state.get("lang", "KO"), "google_oauth_err_token", msg=res.text))
                st.query_params.clear()
                st.stop()
        except Exception as e:
            st.error(get_text(st.session_state.get("lang", "KO"), "google_oauth_err_network", err=str(e)))
            st.query_params.clear()
            st.stop()

    st.markdown(f"""
        <div style="text-align: center; margin-top: 5vh; margin-bottom: 3vh;">
            <div style="font-size: clamp(30px, 8vw, 40px); font-weight: 800; color: #333333; margin-bottom: 1vh;">{t['title']}</div>
            <div style="font-size: clamp(16px, 4vw, 20px); font-weight: 500; color: #86cc85;">{t['login_heading']}</div>
        </div>
    """, unsafe_allow_html=True)
    
    # 더 세련된 커스텀 상태 관리를 통한 모드 변경
    if 'auth_mode' not in st.session_state:
        st.session_state['auth_mode'] = 'login'
        
    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button(t["btn_login"], type="primary" if st.session_state['auth_mode'] == 'login' else "secondary", use_container_width=True):
            st.session_state['auth_mode'] = 'login'
            st.rerun()
    with c2:
        if st.button(t["btn_signup"], type="primary" if st.session_state['auth_mode'] == 'signup' else "secondary", use_container_width=True):
            st.session_state['auth_mode'] = 'signup'
            st.rerun()
    with c3:
        if st.button(t["btn_guest"], type="primary" if st.session_state['auth_mode'] == 'guest' else "secondary", use_container_width=True):
            st.session_state['auth_mode'] = 'guest'
            st.rerun()
            
    st.markdown("<br>", unsafe_allow_html=True)
    
    if st.session_state['auth_mode'] in ['login', 'signup']:
        mode_text = t["btn_login"] if st.session_state['auth_mode'] == 'login' else t["btn_signup"]
        submit_label = t["auth_submit_login"] if st.session_state['auth_mode'] == 'login' else t["auth_submit_signup"]
        with st.form("auth_form_modern"):
            st.markdown(f"#### 🔒 {mode_text}")
            email = st.text_input(t["auth_email_label"], placeholder=t["auth_email_placeholder"])
            pwd = st.text_input(t["auth_pwd_label"], type="password", placeholder=t["auth_pwd_placeholder"])
            submitted = st.form_submit_button(submit_label, type="primary", use_container_width=True)
            
            if submitted:
                if not email or not pwd:
                    st.error(t["err_email_pwd_empty"])
                else:
                    success, res = pyrebase_auth(email, pwd, "login" if st.session_state['auth_mode'] == 'login' else "signup")
                    
                    if success:
                        st.session_state['logged_in'] = True
                        st.session_state['user_id'] = res.get('localId', f"user_{email}")
                        st.session_state['login_type'] = "google"
                        st.rerun()
                    else:
                        if "EMAIL_EXISTS" in res:
                            st.error(t["err_email_exists"])
                        elif "INVALID_LOGIN_CREDENTIALS" in res or "INVALID_PASSWORD" in res or "EMAIL_NOT_FOUND" in res:
                            st.error(t["err_invalid_credentials"])
                        else:
                            st.error(get_text(st.session_state.get("lang", "KO"), "err_auth_failed", msg=str(res)))
                
        st.markdown(f"<br> <div style='text-align:center; color:#888; font-size:14px;'>{t['or_social']}</div> <br>", unsafe_allow_html=True)
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
                            {t['google_login_btn']}
                        </button>
                    </form>
                    <div style="text-align:center; font-size:11px; color:#999; margin-top:5px; line-height:1.2;">
                        {t['oauth_open_in_browser']}
                    </div>
                '''
                st.components.v1.html(auth_html, height=80)
            else:
                st.button(t["google_login_btn"], disabled=True, use_container_width=True, help=t["google_login_disabled_help"])
                
        with col2:
            st.button(t["kakao_login_btn"], disabled=True, use_container_width=True)
            
    elif st.session_state['auth_mode'] == 'guest':
        st.info(f"{t['guest_info_title']}\n\n{t['guest_info_body']}")
        
        if st.button(t["guest_confirm_btn"], type="primary", use_container_width=True):
            st.session_state['logged_in'] = True
            st.session_state['user_id'] = "guest_user_demo"
            st.session_state['login_type'] = "guest"
            st.rerun()

    st.markdown("<br><br>", unsafe_allow_html=True)

    st.stop()  # 로그인되지 않은 사용자는 식단 분석 로직을 볼 수 없음


# 5. 메인 화면 - 식단 스캐너
if menu_key == "scanner":
    if 'app_stage' not in st.session_state:
        st.session_state['app_stage'] = 'main'
        
    API_KEY = _get_secret("GEMINI_API_KEY")
    if not API_KEY:
        st.error(t["gemini_key_error"])
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
            st.warning(t["guest_trial_exhausted"])
            st.info(t["guest_ad_bonus"])
            
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
                if st.button(t["btn_ad_charge"], use_container_width=True):
                    # 광고를 보면 보너스 횟수를 1 부여하고 화면 리로드
                    st.session_state['guest_bonus_count'] += 1
                    st.rerun()
            
            st.markdown("<br><hr>", unsafe_allow_html=True)
            st.markdown(f"**{t['guest_continue_question']}**")
            if st.button(t["btn_go_signup"], type="primary", use_container_width=True):
                st.session_state['logged_in'] = False
                st.session_state['login_type'] = None
                st.session_state['auth_mode'] = 'signup'
                st.rerun()
        else:
            if is_guest:
                st.info(get_text(st.session_state.get("lang", "KO"), "guest_remaining", n=total_remaining))
                
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
        if st.button(t["btn_back_main"], key="btn_back_main_1", use_container_width=True):
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
                    content: '🤖 분석 중...' !important;
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
            _lang = st.session_state.get("lang", "KO")
            food_prompt, advice_prompt = get_analysis_prompt(_lang)

            for attempt in range(max_retries):
                try:
                    response = client.models.generate_content(
                        model="gemini-flash-latest",
                        contents=[food_prompt, st.session_state['current_img']]
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

                        # 소견 분석 (선택 언어로 응답하도록 prompts.get_advice_prompt 사용)
                        advice_res = client.models.generate_content(
                            model="gemini-flash-latest",
                            contents=[advice_prompt, st.session_state['current_img']]
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
                        st.warning(t["analysis_failed"])
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
                    st.error(t["server_busy"])
                else:
                    st.error(get_text(st.session_state.get("lang", "KO"), "analysis_error_generic", msg=last_err_msg))

    elif st.session_state['app_stage'] == 'result':
        # 세션 손실(다중 워커/타임아웃 등) 시 분석 결과가 없으면 메인으로 복귀
        if st.session_state.get('current_analysis') is None:
            st.session_state['app_stage'] = 'main'
            st.session_state['current_img'] = None
            if 'uploader_key' in st.session_state:
                st.session_state['uploader_key'] += 1
            st.warning(t["session_reset_msg"])
            st.rerun()

        if st.button(t["btn_back_main_2"], key="btn_back_main_2", use_container_width=True):
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
            risk_label, risk_color = f"{t['risk_safe']} 🟢", "#4CAF50"
        elif score <= 65:
            risk_label, risk_color = f"{t['risk_caution']} 🟡", "#FFB300"
        else:
            risk_label, risk_color = f"{t['risk_danger']} 🔴", "#F44336"

        # ── 1. 이미지 + 원형 혈당 스코어 (Cal AI 핵심 UI) ──
        col_img, col_score = st.columns([1, 1])
        with col_img:
            st.image(res['raw_img'], use_container_width=True)
        with col_score:
            st.markdown(f"""
            <div style="display:flex;flex-direction:column;justify-content:center;align-items:center;height:100%;padding:8px;">
                <div style="font-size:12px;color:#888;font-weight:600;letter-spacing:1px;margin-bottom:6px;">{t['blood_score_circle']}</div>
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
                <div style="font-size:10px;color:#888;">{t['carbs']}</div>
            </div>
            <div style="background:white;border-radius:14px;padding:13px;text-align:center;box-shadow:0 2px 8px rgba(0,0,0,0.06);border:1px solid #f0f0f0;">
                <div style="font-size:18px;">🩸</div>
                <div style="font-size:21px;font-weight:900;color:{risk_color};margin:3px 0;">{avg_gi}</div>
                <div style="font-size:10px;color:#888;">{t['avg_gi_label']}</div>
            </div>
            <div style="background:white;border-radius:14px;padding:13px;text-align:center;box-shadow:0 2px 8px rgba(0,0,0,0.06);border:1px solid #f0f0f0;">
                <div style="font-size:18px;">💪</div>
                <div style="font-size:21px;font-weight:900;color:#333;margin:3px 0;">{total_protein}g</div>
                <div style="font-size:10px;color:#888;">{t['protein']}</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        # ── 3. 혈당 스파이크 예측 바 ──
        spike_label = t["spike_low"] if score <= 40 else t["spike_mid"] if score <= 65 else t["spike_high"]
        st.markdown(f"""
        <div style="background:white;border-radius:14px;padding:14px;margin-bottom:14px;box-shadow:0 2px 8px rgba(0,0,0,0.06);border:1px solid #f0f0f0;">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:7px;">
                <div style="font-weight:700;font-size:14px;color:#333;">{t['spike_prediction']}</div>
                <div style="font-weight:700;font-size:14px;color:{risk_color};">{spike_label}</div>
            </div>
            <div style="background:#f0f0f0;border-radius:8px;height:10px;overflow:hidden;">
                <div style="background:linear-gradient(90deg,#4CAF50,#FFB300,#F44336);width:{score}%;height:10px;border-radius:8px;"></div>
            </div>
            <div style="display:flex;justify-content:space-between;margin-top:4px;">
                <div style="font-size:10px;color:#aaa;">{t['safe_end']}</div>
                <div style="font-size:10px;color:#aaa;">{t['danger_end']}</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        # ── 4. 음식별 혈당 분석 카드 (GI 바 포함) ──
        st.markdown(f"""<div style="display:flex;align-items:center;margin:12px 0 8px;"><div style="width:5px;height:20px;background:linear-gradient(to bottom,#86cc85,#359f33);border-radius:4px;margin-right:9px;"></div><div style="font-size:16px;font-weight:800;color:#1e293b;">{t['food_analysis_section']}</div></div>""", unsafe_allow_html=True)

        cards_html = ""
        for idx, item in enumerate(res['sorted_items'], 1):
            name = str(item[0]).replace('*', '').strip()
            gi = item[1] if len(item) > 1 and isinstance(item[1], int) else 50
            carbs = item[2] if len(item) > 2 and isinstance(item[2], int) else 0
            protein = item[3] if len(item) > 3 and isinstance(item[3], int) else 0
            color_str = str(item[4]) if len(item) > 4 else '노랑'
            if any(x in color_str for x in ["초록", "Green"]):
                tc, bg, bc, gl = "#4CAF50", "#F1F8E9", "#C5E1A5", t["gi_level_low"]
            elif any(x in color_str for x in ["노랑", "주황", "Yellow", "Orange"]):
                tc, bg, bc, gl = "#FFB300", "#FFFDE7", "#FFF59D", t["gi_level_mid"]
            else:
                tc, bg, bc, gl = "#F44336", "#FFEBEE", "#EF9A9A", t["gi_level_high"]
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
                    <div style="font-size:12px;color:#555;">🍚 {t['carbs_short']} <b>{carbs}g</b></div>
                    <div style="font-size:12px;color:#555;">💪 {t['protein_short']} <b>{protein}g</b></div>
                </div>
            </div>"""
        st.markdown(cards_html, unsafe_allow_html=True)

        # ── 5. 권장 섭취 순서 태그 ──
        st.markdown(f"""<div style="display:flex;align-items:center;margin:12px 0 8px;"><div style="width:5px;height:20px;background:linear-gradient(to bottom,#86cc85,#359f33);border-radius:4px;margin-right:9px;"></div><div style="font-size:16px;font-weight:800;color:#1e293b;">{t['recommended_order_section']}</div></div>""", unsafe_allow_html=True)
        tags_html = '<div style="display:flex;flex-wrap:wrap;gap:7px;margin-bottom:14px;">'
        for idx, item in enumerate(res['sorted_items'], 1):
            name = str(item[0]).replace('*', '').strip()
            color_str = str(item[4]) if len(item) > 4 else '노랑'
            tc = "#4CAF50" if any(x in color_str for x in ["초록","Green"]) else "#FFB300" if any(x in color_str for x in ["노랑","Yellow","Orange"]) else "#F44336"
            tags_html += f'<div style="background:{tc}22;border:1px solid {tc}55;border-radius:20px;padding:5px 12px;font-size:13px;font-weight:600;color:{tc};">{idx}. {name}</div>'
        tags_html += '</div>'
        st.markdown(tags_html, unsafe_allow_html=True)

        # ── 6. AI 소견 ──
        st.markdown(f"""<div style="display:flex;align-items:center;margin:12px 0 8px;"><div style="width:5px;height:20px;background:linear-gradient(to bottom,#86cc85,#359f33);border-radius:4px;margin-right:9px;"></div><div style="font-size:16px;font-weight:800;color:#1e293b;">{t['ai_advice_section']}</div></div>""", unsafe_allow_html=True)
        st.info(res['advice'])

        # ── 7. 저장 버튼 (게스트는 비활성화 + 로그인 유도) ──
        if st.session_state.get("login_type") == "guest":
            st.button(t["save_btn"], use_container_width=True, disabled=True, help=t["guest_save_disabled_msg"])
            st.info(t["guest_save_disabled_msg"])
            if st.button(t["guest_save_go_login"], use_container_width=True, type="primary"):
                st.session_state["logged_in"] = False
                st.session_state["login_type"] = None
                st.session_state["auth_mode"] = "login"
                st.rerun()
        else:
            if st.button(t["save_btn"], use_container_width=True):
                save_date = datetime.now().strftime("%Y-%m-%d %H:%M")
                uid = st.session_state['user_id']
                try:
                    from firebase_admin import firestore
                    import firebase_admin
                    from firebase_admin import credentials
                    if not firebase_admin._apps:
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
elif menu_key == "history":
    st.title(f"📅 {t['history_menu']}")

    # 오늘 하루 요약 대시보드
    if st.session_state['daily_meals_count'] > 0:
        goal_carbs_map2 = {"일반 관리": 250, "당뇨 관리": 130, "다이어트": 150, "근력 강화": 300}
        target_c = goal_carbs_map2.get(st.session_state['user_goal'], 250)
        ds = st.session_state['daily_blood_sugar_score']
        ds_color = "#4CAF50" if ds <= 40 else "#FFB300" if ds <= 65 else "#F44336"
        ds_label = t["risk_safe"] if ds <= 40 else t["risk_caution"] if ds <= 65 else t["risk_danger"]
        carb_pct2 = min(100, int(st.session_state['daily_carbs'] / max(target_c, 1) * 100))
        st.markdown(f"""
        <div style="background:linear-gradient(135deg,#1e293b,#334155);border-radius:20px;padding:20px;margin-bottom:18px;color:white;">
            <div style="font-size:13px;color:#94a3b8;margin-bottom:10px;">📊 {t['today_glucose_status']}</div>
            <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;margin-bottom:12px;">
                <div style="text-align:center;">
                    <div style="font-size:26px;font-weight:900;color:{ds_color};">{ds}</div>
                    <div style="font-size:10px;color:#94a3b8;">{t['avg_blood_score']}</div>
                    <div style="font-size:12px;font-weight:700;color:{ds_color};">{ds_label}</div>
                </div>
                <div style="text-align:center;">
                    <div style="font-size:26px;font-weight:900;color:white;">{st.session_state['daily_carbs']}g</div>
                    <div style="font-size:10px;color:#94a3b8;">{t['carbs']}</div>
                    <div style="font-size:11px;color:#94a3b8;">{t['goal_target']} {target_c}g</div>
                </div>
                <div style="text-align:center;">
                    <div style="font-size:26px;font-weight:900;color:white;">{st.session_state['daily_meals_count']}</div>
                    <div style="font-size:10px;color:#94a3b8;">{t['analyzed_meals']}</div>
                    <div style="font-size:11px;color:#94a3b8;">{t.get('goal_display', {}).get(st.session_state['user_goal'], st.session_state['user_goal'])}</div>
                </div>
            </div>
            <div style="background:rgba(255,255,255,0.15);border-radius:6px;height:7px;">
                <div style="background:{ds_color};width:{carb_pct2}%;height:7px;border-radius:6px;"></div>
            </div>
        </div>
        """, unsafe_allow_html=True)
        if st.button(f"🔄 {t['reset_today']}", use_container_width=True):
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
            rl = t["risk_safe"] if rec_score <= 40 else t["risk_caution"] if rec_score <= 65 else t["risk_danger"]
            with st.expander(f"🍴 {rec['date']}  |  {t['blood_score_label']} {rec_score} ({rl})  |  {t['carbs']} {rec_carbs}g"):
                if rec.get('image'):
                    st.image(rec['image'], use_container_width=True)
                st.markdown(f"""
                <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin:10px 0;">
                    <div style="background:{rc}11;border:1px solid {rc}33;border-radius:10px;padding:10px;text-align:center;">
                        <div style="font-size:18px;font-weight:900;color:{rc};">{rec_score}</div>
                        <div style="font-size:10px;color:#888;">{t['blood_score']}</div>
                    </div>
                    <div style="background:#f8f9fa;border-radius:10px;padding:10px;text-align:center;">
                        <div style="font-size:18px;font-weight:900;color:#333;">{rec_carbs}g</div>
                        <div style="font-size:10px;color:#888;">{t['carbs']}</div>
                    </div>
                    <div style="background:#f8f9fa;border-radius:10px;padding:10px;text-align:center;">
                        <div style="font-size:18px;font-weight:900;color:#333;">{rec_gi}</div>
                        <div style="font-size:10px;color:#888;">{t['avg_gi_label']}</div>
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
        st.info(t["no_history_msg"])
