# -*- coding: utf-8 -*-
"""NutriSort AI - 한글 기본, UTF-8 소스·출력 통일."""
import sys
import os
import json
import traceback
import urllib.parse
import re
from collections import defaultdict
import statistics

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
            parsed = json.loads(cred_json)
            # Railway 등에서 env로 넣을 때 private_key 내 \\n이 문자열로 들어올 수 있음
            if isinstance(parsed.get("private_key"), str):
                parsed["private_key"] = parsed["private_key"].replace("\\n", "\n")
            cfg.update(parsed)
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
from datetime import datetime, timezone
import io
import base64

# 언어별 타임존·로케일 (저장 시간 및 표시 형식 현지화)
LANG_TIMEZONE = {
    "KO": "Asia/Seoul",
    "JA": "Asia/Tokyo",
    "ZH": "Asia/Shanghai",
    "HI": "Asia/Kolkata",
    "EN": "UTC",
}
LANG_BABEL_LOCALE = {
    "KO": "ko_KR",
    "JA": "ja_JP",
    "ZH": "zh_CN",
    "HI": "hi_IN",
    "EN": "en_US",
}


def _format_record_date(date_str, saved_at_utc=None, lang="KO"):
    """선택 언어의 타임존과 로케일에 맞춰 기록 날짜/시간을 포맷. (pytz + babel)"""
    if not date_str and not saved_at_utc:
        return ""
    try:
        import pytz
        from babel.dates import format_datetime
        tz_name = LANG_TIMEZONE.get(lang) or "UTC"
        locale_name = LANG_BABEL_LOCALE.get(lang) or "en_US"
        tz = pytz.timezone(tz_name)
        dt = None
        if saved_at_utc:
            try:
                s = str(saved_at_utc).strip().replace("Z", "+00:00")
                dt_utc = datetime.fromisoformat(s)
                if dt_utc.tzinfo is None:
                    dt_utc = dt_utc.replace(tzinfo=timezone.utc)
                dt = dt_utc.astimezone(tz)
            except Exception:
                pass
        if dt is None and date_str:
            try:
                dt_naive = datetime.strptime(date_str.strip()[:16], "%Y-%m-%d %H:%M")
                dt = pytz.utc.localize(dt_naive).astimezone(tz)
            except Exception:
                return date_str
        return format_datetime(dt, format="medium", locale=locale_name) if dt else (date_str or str(saved_at_utc or ""))
    except Exception as e:
        sys.stderr.write(f"[날짜 포맷] {lang} {date_str!r}: {e}\n")
        return date_str or (str(saved_at_utc) if saved_at_utc else "")

def compress_image(img, max_size_kb=500, max_edge=1024):
    """이미지가 서버에 로드된 직후 500KB 이하로 브라우저 표시 및 전송 전에 최적화. 모바일 대용량 사진은 먼저 리사이즈해 인코딩 시간 단축."""
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    w, h = img.size
    # 1단계: 한 번에 최대 길이로 리사이즈 → 반복 인코딩 부담 감소 (모바일 지연 해소)
    if w > max_edge or h > max_edge:
        ratio = min(max_edge / w, max_edge / h)
        nw, nh = max(1, int(w * ratio)), max(1, int(h * ratio))
        img = img.resize((nw, nh), Image.Resampling.LANCZOS)
    quality = 88
    while True:
        output = io.BytesIO()
        img.save(output, format="JPEG", quality=quality)
        size_kb = len(output.getvalue()) / 1024
        if size_kb <= max_size_kb or quality <= 25:
            output.seek(0)
            return Image.open(output)
        quality -= 12
        img = img.resize((max(1, int(img.width * 0.85)), max(1, int(img.height * 0.85))), Image.Resampling.LANCZOS)


def compress_image_for_storage(img, max_width=1024, quality=80):
    """Firebase Storage 업로드 직전: 최대 너비 1024px, 화질 80, 비율 유지. (PIL Image, JPEG bytes) 반환."""
    if img is None:
        return None, None
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    w, h = img.size
    if w > max_width:
        ratio = max_width / w
        new_h = max(1, int(h * ratio))
        img = img.resize((max_width, new_h), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    buf.seek(0)
    img_bytes = buf.getvalue()
    # JPEG 매직 바이트 검증 (Firebase Storage 400 방지)
    if len(img_bytes) < 2 or img_bytes[0:2] != b"\xff\xd8":
        return None, None
    return img, img_bytes


# 2. 세션 상태 초기화
if 'history' not in st.session_state:
    st.session_state['history'] = []
if 'current_analysis' not in st.session_state:
    st.session_state['current_analysis'] = None
if 'logged_in' not in st.session_state:
    st.session_state['logged_in'] = False
if 'user_id' not in st.session_state:
    st.session_state['user_id'] = None
if 'user_email' not in st.session_state:
    st.session_state['user_email'] = None  # 환영 문구용 (이메일 로그인/구글 로그인 시 저장)
if 'login_type' not in st.session_state:
    st.session_state['login_type'] = None  # 'google' | 'guest'
# 로그인된 상태인데 login_type이 비어 있으면 user_id로 보정 (2페이지 뱃지 표시)
if st.session_state.get('logged_in') and not st.session_state.get('login_type'):
    st.session_state['login_type'] = 'guest' if st.session_state.get('user_id') == 'guest_user_demo' else 'google'
# Cal AI 스타일 하루 혈당 누적 추적
if 'daily_blood_sugar_score' not in st.session_state:
    st.session_state['daily_blood_sugar_score'] = 0
if 'daily_carbs' not in st.session_state:
    st.session_state['daily_carbs'] = 0
if 'daily_protein' not in st.session_state:
    st.session_state['daily_protein'] = 0
if 'daily_meals_count' not in st.session_state:
    st.session_state['daily_meals_count'] = 0
if "history_loaded_uid" not in st.session_state:
    st.session_state["history_loaded_uid"] = None
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


def render_login_badge():
    """현재 로그인 타입(google/guest)에 따라 상단에 뱃지 표시."""
    _lt = st.session_state.get("login_type")
    if _lt == "guest":
        st.markdown(
            f'<div style="background:#FF9800;color:white;padding:6px 12px;border-radius:8px;font-size:13px;font-weight:700;text-align:center;margin-bottom:8px;">⚠️ {t["login_badge_guest"]}</div>',
            unsafe_allow_html=True,
        )
    elif _lt == "google":
        # 이메일 로그인은 user_id가 Firebase UID이므로, 표시용은 user_email 사용
        email_for_display = st.session_state.get("user_email") or st.session_state.get("user_id") or ""
        if "@" in str(email_for_display):
            display_name = email_for_display.split("@")[0]
        else:
            display_name = t.get("welcome_fallback", "User")  # UID만 있을 때(구 세션) 일반 문구
        welcome_msg = get_text(st.session_state.get("lang", "KO"), "welcome_user", name=display_name)
        st.markdown(
            f'<div style="background:#4CAF50;color:white;padding:8px 12px;border-radius:8px;font-size:13px;font-weight:600;text-align:center;margin-bottom:8px;">✓ {welcome_msg}</div>',
            unsafe_allow_html=True,
        )


# 3. 사이드바 메뉴 (언어와 무관한 안정 키 사용 → 분석 후 rerun 시에도 스캐너/결과 화면 유지)
with st.sidebar:
    st.title(t.get("sidebar_title", "설정"))
    render_login_badge()
    # 2페이지 → 1페이지: 상단에 배치해 항상 보이도록
    _lt = st.session_state.get("login_type")
    if _lt == "guest":
        if st.button(f"🔐 {t['sidebar_go_login']}", key="sidebar_go_login", use_container_width=True):
            st.session_state["logged_in"] = False
            st.session_state["login_type"] = None
            st.session_state["user_id"] = None
            st.session_state["user_email"] = None
            st.session_state["history_loaded_uid"] = None
            st.session_state["history"] = []
            st.session_state["auth_mode"] = "login"
            st.rerun()
    elif _lt == "google":
        if st.button(f"🚪 {t['sidebar_logout']}", key="sidebar_logout", use_container_width=True):
            st.session_state["logged_in"] = False
            st.session_state["login_type"] = None
            st.session_state["user_id"] = None
            st.session_state["user_email"] = None
            st.session_state["history_loaded_uid"] = None
            st.session_state["history"] = []
            st.session_state["auth_mode"] = "login"
            st.rerun()
    st.divider()
    def _clear_nav_menu():
        st.session_state.pop("nav_menu", None)
    menu_key = st.radio(
        t.get("menu_label", "메뉴"),
        options=["scanner", "history"],
        format_func=lambda x: t["scanner_menu"] if x == "scanner" else t["history_menu"],
        key="sidebar_menu",
        on_change=_clear_nav_menu,
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
    """REST API를 활용한 Firebase 기본 이메일/패스워드 인증 로직.

    성공 시 (True, data), 실패 시 (False, {"code": "...", "raw": any}) 형태로 반환한다.
    """
    try:
        firebase_cfg = _get_firebase_config()
        api_key = firebase_cfg.get("api_key", "")
    except Exception as e:
        return False, {"code": "CONFIG_READ_ERROR", "raw": str(e)}

    if not api_key:
        return False, {"code": "MISSING_API_KEY", "raw": "Firebase Web API Key가 설정에 없습니다."}

    if mode == "signup":
        url = f"https://identitytoolkit.googleapis.com/v1/accounts:signUp?key={api_key}"
    else:
        url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={api_key}"

    payload = json.dumps({"email": email, "password": password, "returnSecureToken": True})
    headers = {"content-type": "application/json"}

    try:
        res = requests.post(url, data=payload, headers=headers)
        data = res.json()
        if "error" in data:
            err = data.get("error", {})
            code = str(err.get("message", "UNKNOWN"))
            return False, {"code": code, "raw": err}
        return True, data
    except Exception as e:
        return False, {"code": "EXCEPTION", "raw": str(e)}

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
                    _email = userinfo.get("email", "google_user")
                    st.session_state["user_id"] = _email
                    st.session_state["user_email"] = _email
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

    # 1페이지 반응형: 모바일에서 스크롤 없이 한 화면에 맞추기
    st.markdown("""
    <style>
    @media (max-height: 700px), (max-width: 480px) {
        .block-container { padding-top: 0.5rem !important; padding-bottom: 0.5rem !important; }
        .login-page-title { margin-top: 1vh !important; margin-bottom: 0.5vh !important; }
        .login-page-title .main { font-size: clamp(22px, 6vw, 36px) !important; }
        .login-page-title .sub { font-size: clamp(13px, 3.5vw, 18px) !important; }
    }
    .login-page-title { margin-top: 2vh; margin-bottom: 1.5vh; text-align: center; }
    .login-page-title .main { font-size: clamp(26px, 7vw, 40px); font-weight: 800; color: #333; margin-bottom: 0.5vh; }
    .login-page-title .sub { font-size: clamp(14px, 4vw, 20px); font-weight: 500; color: #86cc85; }
    </style>
    """, unsafe_allow_html=True)
    st.markdown(f"""
        <div class="login-page-title">
            <div class="main">{t['title']}</div>
            <div class="sub">{t['login_heading']}</div>
        </div>
    """, unsafe_allow_html=True)
    
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
    
    st.markdown("<div style='height:4px;'></div>", unsafe_allow_html=True)
    
    if st.session_state['auth_mode'] in ['login', 'signup']:
        mode_text = t["btn_login"] if st.session_state['auth_mode'] == 'login' else t["btn_signup"]
        submit_label = t["auth_submit_login"] if st.session_state['auth_mode'] == 'login' else t["auth_submit_signup"]
        with st.form("auth_form_modern"):
            st.markdown(f"#### 🔒 {mode_text}")
            email = st.text_input(t["auth_email_label"], placeholder=t["auth_email_placeholder"])
            # 이메일 도움말: 형식이 틀릴 때만 빨간 안내 문구
            email_valid = bool(email and ("@" in email))
            if email and not email_valid:
                st.caption("🔴 올바른 이메일 형식을 입력해 주세요.")

            pwd = st.text_input(t["auth_pwd_label"], type="password", placeholder=t["auth_pwd_placeholder"])

            # 검증 조건과 상관없이 버튼은 항상 활성화 (테스트/UX용)
            submitted = st.form_submit_button(
                submit_label,
                type="primary",
                use_container_width=True,
                disabled=False,
            )

            if submitted:
                # 1차 검증: 형식이 틀리면 경고 후 중단
                if not email_valid or not pwd:
                    st.error("형식이 틀렸습니다. 이메일과 비밀번호를 다시 확인해 주세요.")
                else:
                    with st.spinner("인증 중..."):
                        success, res = pyrebase_auth(
                            email,
                            pwd,
                            "login" if st.session_state['auth_mode'] == 'login' else "signup",
                        )

                    if success:
                        st.session_state['logged_in'] = True
                        st.session_state['user_id'] = res.get('localId', f"user_{email}")
                        st.session_state['user_email'] = email
                        st.session_state['login_type'] = "google"
                        st.rerun()
                    else:
                        # 에러 코드 가시화
                        code = str((res or {}).get("code", "UNKNOWN"))
                        upper_code = code.upper()

                        if "EMAIL_EXISTS" in upper_code:
                            st.error(t["err_email_exists"])
                        elif (
                            "INVALID_LOGIN_CREDENTIALS" in upper_code
                            or "INVALID_PASSWORD" in upper_code
                            or "EMAIL_NOT_FOUND" in upper_code
                        ):
                            st.error(t["err_invalid_credentials"])
                        else:
                            base_msg = get_text(
                                st.session_state.get("lang", "KO"),
                                "err_auth_failed",
                                msg=code,
                            )
                            st.error(f"{base_msg} (코드: {code})")

                        # Firebase 콘솔 설정 가이드 (OPERATION_NOT_ALLOWED)
                        if "OPERATION_NOT_ALLOWED" in upper_code:
                            st.error(
                                "Firebase 콘솔에서 이메일/비밀번호 로그인 방식이 비활성화되어 있습니다. "
                                "Firebase 프로젝트의 Authentication → Sign-in method에서 Email/Password를 활성화해 주세요."
                            )
                
        # 소셜 로그인: 버튼 클릭 시 펼침(expander 제거 → 글자 겹침 방지), 배경색·자동 스크롤
        _lang = st.session_state.get("lang", "KO")
        _show_kakao_naver = _lang == "KO"
        if "show_social_buttons" not in st.session_state:
            st.session_state["show_social_buttons"] = False
        _btn_label = t.get("btn_social_login", "소셜 계정으로 로그인하기")
        st.markdown("""
        <style>
        /* 소셜 로그인하기 버튼만 배경색 적용 (바로 다음 블록의 버튼) */
        #social-login-trigger-marker + div button { background-color: #e8f5e9 !important; color: #1b5e20 !important; border: 1px solid #a5d6a7 !important; border-radius: 8px !important; font-weight: 600 !important; }
        #social-login-trigger-marker + div button:hover { background-color: #c8e6c9 !important; }
        </style>
        """, unsafe_allow_html=True)
        st.markdown('<div id="social-login-trigger-marker"></div>', unsafe_allow_html=True)
        if st.button(_btn_label, key="social_login_toggle", type="secondary", use_container_width=True):
            st.session_state["show_social_buttons"] = True
            st.rerun()
        if st.session_state.get("show_social_buttons"):
            st.markdown('<div id="social-buttons-block" style="scroll-margin-top: 12px;"></div>', unsafe_allow_html=True)
            st.caption(t["or_social"])
            if _show_kakao_naver:
                col1, col2, col3 = st.columns(3)
            else:
                col1 = st.columns(1)[0]
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
            if _show_kakao_naver:
                with col2:
                    st.button(t["kakao_login_btn"], disabled=True, use_container_width=True)
                with col3:
                    st.button(t.get("naver_login_btn", "네이버 로그인"), disabled=True, use_container_width=True)
            # 펼친 직후 구글 등이 보이도록 자동 스크롤 (한글/비한글 공통, DOM 준비 후 실행)
            st.components.v1.html("""
            <script>
            (function(){
                function scrollToSocial() {
                    try {
                        var doc = window.parent.document;
                        var el = doc.getElementById("social-buttons-block");
                        if (el) el.scrollIntoView({ behavior: "smooth", block: "center" });
                    } catch (e) {}
                }
                setTimeout(scrollToSocial, 280);
            })();
            </script>
            """, height=1)
            
    elif st.session_state['auth_mode'] == 'guest':
        st.info(f"{t['guest_info_title']}\n\n{t['guest_info_body']}", icon="🚀")
        if st.button(t["guest_confirm_btn"], type="primary", use_container_width=True):
            st.session_state['logged_in'] = True
            st.session_state['user_id'] = "guest_user_demo"
            st.session_state['login_type'] = "guest"
            st.rerun()

    st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)

    st.stop()  # 로그인되지 않은 사용자는 식단 분석 로직을 볼 수 없음


def _normalize_image_url(url, bucket_name=None):
    """상대 경로 또는 Storage 경로를 완전한 공개 URL로 변환. 이미 http(s)로 시작하면 그대로 반환."""
    if not url or not isinstance(url, str) or not url.strip():
        return None
    url = url.strip()
    if url.startswith("http://") or url.startswith("https://"):
        return url
    if bucket_name:
        path_encoded = urllib.parse.quote(url, safe="/")
        return f"https://storage.googleapis.com/{bucket_name}/{path_encoded}"
    return url


def _delete_history_record(uid, doc_id):
    """Firestore(history + user_logs) 문서 및 Storage 이미지 삭제. 성공 시 (True, None), 실패 시 (False, '단계명')."""
    if not uid or not doc_id:
        sys.stderr.write("[기록 삭제] uid 또는 doc_id 없음\n")
        return False, None
    uid = str(uid)
    doc_id = str(doc_id)
    _FIREBASE_ADMIN_KEYS = [
        "type", "project_id", "private_key_id", "private_key",
        "client_email", "client_id", "auth_uri", "token_uri",
        "auth_provider_x509_cert_url", "client_x509_cert_url",
        "universe_domain"
    ]
    key_dict = {k: v for k, v in _get_firebase_config().items() if k in _FIREBASE_ADMIN_KEYS}
    if not key_dict.get("project_id"):
        sys.stderr.write("[기록 삭제] project_id 없음\n")
        return False, None
    try:
        from google.cloud import firestore as gcf
        from google.oauth2 import service_account
        creds = service_account.Credentials.from_service_account_info(key_dict)
        fs_client = gcf.Client(project=key_dict["project_id"], credentials=creds)
    except Exception as e:
        traceback.print_exc(file=sys.stderr)
        sys.stderr.write(f"[기록 삭제] Firestore 클라이언트 초기화 실패: {e}\n")
        return False, "Firestore(초기화)"

    # 1) Firestore users/{uid}/history/{doc_id} 문서 삭제 (doc_id는 해당 컬렉션의 문서 ID와 일치)
    try:
        ref = fs_client.collection("users").document(uid).collection("history").document(doc_id)
        ref.delete()
    except Exception as e:
        traceback.print_exc(file=sys.stderr)
        sys.stderr.write(f"[기록 삭제] Firestore(history) 단계 실패 doc_id={doc_id!r}: {e}\n")
        return False, "Firestore(history)"

    # 2) Storage 이미지 삭제
    _uid_safe = uid.replace("/", "_").replace("\\", "_")
    _storage_path = f"users/{_uid_safe}/meals/{doc_id}.jpg"
    try:
        import firebase_admin
        from firebase_admin import storage, credentials
        if not firebase_admin._apps:
            _opts = {}
            _bucket = os.environ.get("FIREBASE_STORAGE_BUCKET") or os.environ.get("STORAGE_BUCKET")
            if _bucket:
                _opts["storageBucket"] = _bucket
            else:
                _opts["storageBucket"] = f"{key_dict['project_id']}.appspot.com"
            firebase_admin.initialize_app(credentials.Certificate(key_dict), _opts)
        bucket = storage.bucket()
        blob = bucket.blob(_storage_path)
        blob.delete()
    except Exception as e:
        sys.stderr.write(f"[기록 삭제] Storage 단계 실패 path={_storage_path!r}: {type(e).__name__}: {e}\n")

    # 3) Firestore user_logs 컬렉션에서 history_doc_id가 doc_id인 문서 삭제
    try:
        q = fs_client.collection("user_logs").where("history_doc_id", "==", doc_id).where("user_id", "==", uid).stream()
        for doc in q:
            doc.reference.delete()
    except Exception as e:
        traceback.print_exc(file=sys.stderr)
        sys.stderr.write(f"[기록 삭제] Firestore(user_logs) 단계 실패 doc_id={doc_id!r}: {e}\n")
        return False, "Firestore(user_logs)"

    return True, None


def _get_firestore_db():
    """Firestore 클라이언트 반환 (필요 시 초기화)."""
    from firebase_admin import firestore, credentials
    import firebase_admin
    if not firebase_admin._apps:
        _FIREBASE_ADMIN_KEYS = [
            "type", "project_id", "private_key_id", "private_key",
            "client_email", "client_id", "auth_uri", "token_uri",
            "auth_provider_x509_cert_url", "client_x509_cert_url",
            "universe_domain"
        ]
        key_dict = {k: v for k, v in _get_firebase_config().items() if k in _FIREBASE_ADMIN_KEYS}
        cred = credentials.Certificate(key_dict)
        _opts = {}
        _bucket = os.environ.get("FIREBASE_STORAGE_BUCKET") or os.environ.get("STORAGE_BUCKET")
        if _bucket:
            _opts["storageBucket"] = _bucket
        elif key_dict.get("project_id"):
            _opts["storageBucket"] = f"{key_dict['project_id']}.appspot.com"
        firebase_admin.initialize_app(cred, _opts)
    return firestore.client()


def _save_glucose(uid, type_, value, note=None, timestamp=None):
    """users/{uid}/glucose 컬렉션에 공복/식후 혈당 저장. type_ in ('fasting','postprandial').
    timestamp는 반드시 timezone-aware Python datetime으로 전달하고, 문자열로 변환하지 않고 그대로 저장하여 Firestore Native Timestamp로 기록됨."""
    if not uid or type_ not in ("fasting", "postprandial"):
        return False
    try:
        print("저장 시도 중...")  # 임시 디버깅 로그
        db = _get_firestore_db()
        # 값 전처리: 공백/문자 제거 후 숫자로 변환
        v_str = str(value).strip()
        if not v_str:
            raise ValueError(f"빈 혈당 값입니다: {value!r}")
        v_clean = v_str.replace(",", "").replace(" ", "")
        v_num = float(v_clean)
        v_int = int(round(v_num))

        # timestamp: 문자열로 저장하지 않고, timezone-aware datetime 객체 그대로 저장 (Firestore Native Timestamp)
        if timestamp is not None:
            ts = timestamp
            if hasattr(ts, "astimezone"):
                if getattr(ts, "tzinfo", None) is None:
                    import pytz
                    ts = pytz.timezone("Asia/Seoul").localize(ts).astimezone(timezone.utc)
                else:
                    ts = ts.astimezone(timezone.utc)
            # 절대 .isoformat() 또는 str() 사용 금지 → 객체 그대로 전달
            ts_value = ts
        else:
            try:
                from firebase_admin import firestore
                ts_value = firestore.SERVER_TIMESTAMP
            except AttributeError:
                from google.cloud.firestore_v1 import SERVER_TIMESTAMP as ts_value

        db.collection("users").document(str(uid)).collection("glucose").add({
            "type": type_,
            "value": v_int,
            "timestamp": ts_value,
            "note": (str(note).strip() or None),
        })
        return True
    except Exception as e:
        traceback.print_exc(file=sys.stderr)
        sys.stderr.write(f"[glucose 저장] {e}\n")
        # 화면에도 에러 경고 표시 (임시 디버깅용)
        try:
            st.warning(f"혈당 저장 중 오류가 발생했습니다: {e}")
        except Exception:
            pass
        return False


@st.cache_data(ttl=120)
def get_today_summary(uid, date_key):
    """오늘(한국 날짜) 기준 평균 혈당, 탄수화물 합계, 식단 수. date_key 예: '2025-03-15'. 캐시로 Firestore 조회 최소화."""
    if not uid:
        return {"avg_glucose": None, "total_carbs": 0, "meal_count": 0}
    try:
        import pytz
        seoul = pytz.timezone("Asia/Seoul")
        from datetime import timedelta
        y, m, d = [int(x) for x in date_key.split("-")]
        start_seoul = seoul.localize(datetime(y, m, d, 0, 0, 0))
        end_seoul = start_seoul + timedelta(days=1)
        start_utc = start_seoul.astimezone(timezone.utc)
        end_utc = end_seoul.astimezone(timezone.utc)
        glucose_list, meals_list = _get_glucose_and_meals(uid, start_utc, end_utc)
        avg_g = sum(g.get("value", 0) for g in glucose_list) / len(glucose_list) if glucose_list else None
        total_c = sum(m.get("total_carbs", 0) for m in meals_list)
        return {"avg_glucose": round(avg_g) if avg_g is not None else None, "total_carbs": total_c, "meal_count": len(meals_list)}
    except Exception as e:
        sys.stderr.write(f"[get_today_summary] {e}\n")
        return {"avg_glucose": None, "total_carbs": 0, "meal_count": 0}


@st.cache_data(ttl=90)
def get_glucose_meals_cached(uid, start_iso, end_iso):
    """기간별 glucose+meals 캐시. start_iso/end_iso 예: '2025-03-15T00:00:00+00:00'."""
    try:
        start = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
        end = datetime.fromisoformat(end_iso.replace("Z", "+00:00"))
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        return _get_glucose_and_meals(uid, start, end)
    except Exception as e:
        sys.stderr.write(f"[get_glucose_meals_cached] {e}\n")
        return [], []


def _normalize_firestore_ts(ts):
    """Firestore에서 반환된 timestamp를 timezone-aware datetime으로 통일."""
    if ts is None:
        return None
    if hasattr(ts, "date") and hasattr(ts, "astimezone"):
        return ts.astimezone(timezone.utc) if getattr(ts, "tzinfo", None) is None else ts
    if hasattr(ts, "timestamp"):
        from datetime import datetime as dt
        return dt.fromtimestamp(ts.timestamp(), tz=timezone.utc)
    return ts


def _get_glucose_and_meals(uid, start, end):
    """기간 내 users/{uid}/glucose 및 user_logs 조회. 반환: (glucose_list, meals_list)."""
    try:
        db = _get_firestore_db()
        uid = str(uid)
        glucose_ref = db.collection("users").document(uid).collection("glucose").where("timestamp", ">=", start).where("timestamp", "<=", end)
        glucose_docs = list(glucose_ref.stream())
        glucose_list = []
        for d in glucose_docs:
            data = d.to_dict()
            ts = _normalize_firestore_ts(data.get("timestamp"))
            if ts is None:
                continue
            glucose_list.append({
                "timestamp": ts,
                "type": data.get("type", ""),
                "value": data.get("value", 0),
            })
        logs_ref = db.collection("user_logs").where("user_id", "==", uid).where("timestamp", ">=", start).where("timestamp", "<=", end)
        logs_docs = list(logs_ref.stream())
        meals_list = []
        for d in logs_docs:
            data = d.to_dict()
            ts = _normalize_firestore_ts(data.get("timestamp"))
            if ts is None:
                ts = start
            meals_list.append({
                "timestamp": ts,
                "date": data.get("date", ""),
                "total_carbs": data.get("total_carbs", 0),
                "blood_sugar_score": data.get("blood_sugar_score", 0),
                "total_protein": data.get("total_protein", 0),
            })
        return glucose_list, meals_list
    except Exception as e:
        sys.stderr.write(f"[glucose/meals 조회] {e}\n")
        return [], []


def _get_glucose_last_n(uid, n=5):
    """날짜 조건 없이 해당 UID의 glucose 문서를 최근 작성순 n개 조회. 반환: list of dict (id, type, value, timestamp, note)."""
    try:
        from firebase_admin import firestore
        db = _get_firestore_db()
        uid = str(uid)
        col = db.collection("users").document(uid).collection("glucose")
        docs = list(col.order_by("timestamp", direction=firestore.Query.DESCENDING).limit(n).stream())
        out = []
        for d in docs:
            data = d.to_dict()
            ts = data.get("timestamp")
            if hasattr(ts, "isoformat"):
                ts_str = ts.isoformat()
            elif hasattr(ts, "timestamp"):
                from datetime import datetime as _dt
                ts_str = _dt.fromtimestamp(ts.timestamp(), tz=timezone.utc).isoformat()
            else:
                ts_str = str(ts)
            out.append({
                "id": d.id,
                "type": data.get("type"),
                "value": data.get("value"),
                "timestamp": ts_str,
                "note": data.get("note"),
            })
        return out
    except Exception as e:
        sys.stderr.write(f"[_get_glucose_last_n] {e}\n")
        return []


def _warn_similar_food_glucose(uid, food_names, total_carbs):
    """과거 비슷한 음식(이름/탄수화물) 섭취 후 혈당이 높았던 기록이 있으면 경고 문구 반환, 없으면 None."""
    if not uid or not food_names and total_carbs is None:
        return None
    try:
        db = _get_firestore_db()
        uid = str(uid)
        from datetime import timedelta
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=90)
        logs_ref = db.collection("user_logs").where("user_id", "==", uid).where("timestamp", ">=", start).where("timestamp", "<=", end)
        logs = list(logs_ref.stream())
        food_set = {str(n).strip().lower() for n in (food_names or []) if n}
        carbs_low = (total_carbs or 0) * 0.7
        carbs_high = (total_carbs or 0) * 1.3 if total_carbs else 9999
        high_glucose_threshold = 140
        similar_meal_times = []
        for d in logs:
            data = d.to_dict()
            ts = data.get("timestamp")
            if not hasattr(ts, "isoformat"):
                continue
            log_carbs = data.get("total_carbs") or 0
            items = data.get("sorted_items") or []
            names = []
            for it in items:
                if isinstance(it, dict):
                    names.append(str(it.get("name", "")).strip())
                elif isinstance(it, (list, tuple)) and it:
                    names.append(str(it[0]).strip())
            log_names = {n.lower() for n in names if n}
            match = False
            if food_set and log_names and (food_set & log_names):
                match = True
            if total_carbs is not None and carbs_low <= log_carbs <= carbs_high:
                match = True
            if match:
                similar_meal_times.append(ts)
        if not similar_meal_times:
            return None
        glucose_ref = db.collection("users").document(uid).collection("glucose").where("timestamp", ">=", start).where("timestamp", "<=", end)
        glucose_docs = list(glucose_ref.stream())
        for g in glucose_docs:
            gdata = g.to_dict()
            gts = gdata.get("timestamp")
            gval = gdata.get("value") or 0
            if not hasattr(gts, "isoformat") or gval < high_glucose_threshold:
                continue
            for meal_ts in similar_meal_times:
                try:
                    delta_sec = (gts - meal_ts).total_seconds()
                except Exception:
                    continue
                if 30 * 60 <= delta_sec <= 3 * 3600:
                    return True
        return None
    except Exception as e:
        sys.stderr.write(f"[유사 음식 경고] {e}\n")
        return None


# 4-2. 로그인 성공 직후 Firestore에서 해당 uid 기록 불러오기 (새로고침 후 재로그인 시에도 표시)
def _load_my_history_from_firestore():
    uid = st.session_state.get("user_id")
    if not uid or st.session_state.get("login_type") != "google":
        return
    if st.session_state.get("history_loaded_uid") == uid:
        return
    try:
        from firebase_admin import firestore, storage
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
            _opts = {}
            _bucket = os.environ.get("FIREBASE_STORAGE_BUCKET") or os.environ.get("STORAGE_BUCKET")
            if _bucket:
                _opts["storageBucket"] = _bucket
            elif key_dict.get("project_id"):
                _opts["storageBucket"] = f"{key_dict['project_id']}.appspot.com"
            firebase_admin.initialize_app(cred, _opts)
        db = firestore.client()
        bucket_name = None
        try:
            bucket_name = storage.bucket().name
        except Exception:
            pass
        ref = db.collection("users").document(uid).collection("history").stream()
        def _sort_key(d):
            data = d.to_dict()
            return data.get("saved_at_utc") or data.get("date", "")
        docs = sorted(list(ref), key=_sort_key, reverse=True)
    except Exception as e:
        err_lower = str(e).lower()
        if "permission" in err_lower or "denied" in err_lower:
            sys.stderr.write(f"[Firestore 불러오기] Permission Denied 가능성: {e}\n")
            traceback.print_exc(file=sys.stderr)
        return
    loaded = []
    for d in docs:
        data = d.to_dict()
        raw_url = data.get("image_url")
        image_url = _normalize_image_url(raw_url, bucket_name) if raw_url else None
        items = data.get("sorted_items", [])
        if items and isinstance(items[0], dict):
            sorted_lists = [[item.get("name",""), item.get("gi",0), item.get("carbs",0), item.get("protein",0), item.get("color","")] for item in items]
        else:
            sorted_lists = items
        loaded.append({
            "doc_id": d.id,
            "date": data.get("date", ""),
            "saved_at_utc": data.get("saved_at_utc"),
            "image": None,
            "image_url": image_url,
            "sorted_items": sorted_lists,
            "advice": data.get("advice", ""),
            "blood_sugar_score": data.get("blood_sugar_score", 0),
            "total_carbs": data.get("total_carbs", 0),
            "total_protein": data.get("total_protein", 0),
            "avg_gi": data.get("avg_gi", 0),
        })
    st.session_state["history"] = loaded
    st.session_state["history_loaded_uid"] = uid


if st.session_state.get("logged_in") and st.session_state.get("login_type") == "google":
    _load_my_history_from_firestore()

# 5. 메인 화면 - 식단 스캔 / 나의 기록 전환 (사이드바 없이도 항상 노출)
# 위젯 키(sidebar_menu)는 직접 설정 불가 → nav_menu 사용 후 menu_key 반영
_nav1, _nav2 = st.columns(2)
with _nav1:
    if st.button(t.get("scanner_menu", "식단 스캐너"), key="nav_scanner", use_container_width=True, type="primary" if menu_key == "scanner" else "secondary"):
        st.session_state["nav_menu"] = "scanner"
        st.rerun()
with _nav2:
    if st.button(t.get("history_menu", "나의 식단 기록"), key="nav_history", use_container_width=True, type="primary" if menu_key == "history" else "secondary"):
        st.session_state["nav_menu"] = "history"
        st.rerun()
if st.session_state.get("nav_menu"):
    menu_key = st.session_state["nav_menu"]
st.markdown("<div style='height:6px;'></div>", unsafe_allow_html=True)

# 5-1. 식단 스캐너
if menu_key == "scanner":
    # 환영 문구를 로그아웃 버튼 위에 표시
    render_login_badge()
    # 메인 상단: 1페이지로 가기 버튼 (사이드바 접힌 상태에서도 보이도록)
    _lt = st.session_state.get("login_type")
    col_top1, col_top2 = st.columns([5, 1])
    with col_top2:
        if _lt == "guest":
            if st.button(f"🔐 {t['sidebar_go_login']}", key="main_go_login", use_container_width=True):
                st.session_state["logged_in"] = False
                st.session_state["login_type"] = None
                st.session_state["user_id"] = None
                st.session_state["user_email"] = None
                st.session_state["history_loaded_uid"] = None
                st.session_state["history"] = []
                st.session_state["auth_mode"] = "login"
                st.rerun()
        elif _lt == "google":
            if st.button(f"🚪 {t['sidebar_logout']}", key="main_logout", use_container_width=True):
                st.session_state["logged_in"] = False
                st.session_state["login_type"] = None
                st.session_state["user_id"] = None
                st.session_state["user_email"] = None
                st.session_state["history_loaded_uid"] = None
                st.session_state["history"] = []
                st.session_state["auth_mode"] = "login"
                st.rerun()
    if 'app_stage' not in st.session_state:
        st.session_state['app_stage'] = 'main'
    if 'current_page' not in st.session_state:
        st.session_state['current_page'] = 'main'

    API_KEY = _get_secret("GEMINI_API_KEY")
    if not API_KEY:
        st.error(t["gemini_key_error"])
        st.stop()
    client = genai.Client(api_key=API_KEY)

    if st.session_state['app_stage'] == 'main':
        is_guest = st.session_state.get('user_id') == 'guest_user_demo'
        if 'guest_usage_count' not in st.session_state:
            st.session_state['guest_usage_count'] = 0
        if 'guest_bonus_count' not in st.session_state:
            st.session_state['guest_bonus_count'] = 0
        total_remaining = (2 + st.session_state['guest_bonus_count']) - st.session_state['guest_usage_count']

        # ── 뒤로가기: 상세 페이지에서는 상단에 [← 뒤로] 표시 ──
        if st.session_state.get("current_page") != "main":
            if st.button(t.get("btn_back", "← 뒤로"), key="portal_back", use_container_width=True):
                st.session_state["current_page"] = "main"
                st.rerun()
            st.markdown("---")

        if st.session_state.get("current_page") == "main":
            # 1️⃣ 메인 포털: 타이틀 + 슬림 요약 바 + 4구 그리드
            title_parts = (t.get("description") or "📈|혈당 스파이크 방지|올바른 섭취 순서").split("|")
            st.markdown(f"""
                <div style="text-align: center; margin-top: 10px; margin-bottom: 2vh;">
                    <div style="font-size: clamp(35px, 10vw, 50px); margin-bottom: 1vh;">{title_parts[0]}</div>
                    <div style="font-size: clamp(20px, 6vw, 26px); font-weight: 800; color: #333333; line-height: 1.2;">{title_parts[1]}</div>
                    <div style="font-size: clamp(14px, 4vw, 18px); font-weight: 500; color: #86cc85; margin-top: 1vh;">{title_parts[2]}</div>
                </div>
            """, unsafe_allow_html=True)

            if is_guest and total_remaining <= 0:
                st.warning(t["guest_trial_exhausted"])
                st.info(t["guest_ad_bonus"])
                col_ad1, col_ad2 = st.columns([2, 1])
                with col_ad1:
                    st.markdown("""
                        <div style="border:1px solid #ddd; padding:15px; border-radius:10px; background-color:#fefefe; text-align:center;">
                            <span style="color:#888; font-size:12px;">Google 광고</span>
                            <div style="font-weight:700; color:#4285F4;">혈당 관리 전문앱, NutriSort 프리미엄!</div>
                        </div>
                    """, unsafe_allow_html=True)
                with col_ad2:
                    if st.button(t["btn_ad_charge"], use_container_width=True):
                        st.session_state['guest_bonus_count'] += 1
                        st.rerun()
                st.markdown("<br><hr>", unsafe_allow_html=True)
                st.markdown(f"**{t['guest_continue_question']}**")
                if st.button(t["btn_go_signup"], type="primary", use_container_width=True):
                    st.session_state['logged_in'] = False
                    st.session_state['login_type'] = None
                    st.session_state['user_id'] = None
                    st.session_state['user_email'] = None
                    st.session_state["history_loaded_uid"] = None
                    st.session_state["history"] = []
                    st.session_state['auth_mode'] = 'signup'
                    st.rerun()
            else:
                if is_guest:
                    st.info(get_text(st.session_state.get("lang", "KO"), "guest_remaining", n=total_remaining))

                # 슬림 요약 바: 오늘 평균 혈당 | 탄수화물 총량 (컴팩트)
                if st.session_state.get("login_type") == "google" and st.session_state.get("user_id"):
                    import pytz
                    _seoul = pytz.timezone("Asia/Seoul")
                    _date_key = datetime.now(_seoul).strftime("%Y-%m-%d")
                    _sum = get_today_summary(st.session_state["user_id"], _date_key)
                    _avg_g = _sum.get("avg_glucose")
                    _total_c = _sum.get("total_carbs", 0)
                    _g_str = f"{_avg_g}" if _avg_g is not None else "-"
                    st.markdown(f"""
                        <div style="font-size: 12px; color: #555; padding: 8px 12px; background: #f0f4f0; border-radius: 10px; margin-bottom: 12px; display: flex; justify-content: center; gap: 20px; flex-wrap: wrap;">
                            <span>{t.get("dashboard_avg_glucose", "오늘 평균 혈당")}: <strong>{_g_str} mg/dL</strong></span>
                            <span>{t.get("dashboard_total_carbs", "탄수화물 총량")}: <strong>{_total_c}g</strong></span>
                        </div>
                    """, unsafe_allow_html=True)

                # CSS: 포털 그리드가 모바일 높이 60~70% 내에 들어오도록
                st.markdown("""
                    <style>
                    .portal-grid-wrap { max-height: 70vh; padding: 0 0 1rem 0; }
                    .portal-grid-wrap .stButton > button { border-radius: 15px !important; box-shadow: 0 4px 14px rgba(0,0,0,0.12) !important; min-height: 14vh !important; font-size: 1.05rem !important; padding: 1rem !important; }
                    </style>
                """, unsafe_allow_html=True)

                # 4구 그리드: st.columns(2) 두 번
                st.markdown('<div class="portal-grid-wrap">', unsafe_allow_html=True)
                row1_c1, row1_c2 = st.columns(2)
                with row1_c1:
                    if st.button(t.get("btn_scan_diet", "📸 식단 분석 시작"), key="main_btn_scan", use_container_width=True, type="primary"):
                        st.session_state["current_page"] = "diet_scan"
                        st.rerun()
                with row1_c2:
                    if st.button(t.get("btn_input_glucose", "🩸 혈당 수치 입력"), key="main_btn_glucose", use_container_width=True):
                        st.session_state["current_page"] = "glucose_input"
                        st.rerun()
                row2_c1, row2_c2 = st.columns(2)
                with row2_c1:
                    if st.button(t.get("dashboard_view_report", "📊 리포트 보기"), key="main_btn_report", use_container_width=True):
                        st.session_state["current_page"] = "report"
                        st.rerun()
                with row2_c2:
                    if st.button(t.get("btn_settings", "⚙️ 설정"), key="main_btn_settings", use_container_width=True):
                        st.session_state["current_page"] = "settings"
                        st.rerun()
                st.markdown("</div>", unsafe_allow_html=True)

        elif st.session_state.get("current_page") == "diet_scan":
            # 식단 스캔 페이지: 업로더만
            if is_guest:
                st.info(get_text(st.session_state.get("lang", "KO"), "guest_remaining", n=total_remaining))
            if 'uploader_key' not in st.session_state:
                st.session_state['uploader_key'] = 0
            uploaded_file = st.file_uploader(
                "label_hidden",
                type=["jpg", "png", "jpeg"],
                label_visibility="collapsed",
                key=f"uploader_{st.session_state['uploader_key']}"
            )
            if uploaded_file:
                if is_guest:
                    st.session_state['guest_usage_count'] += 1
                img = Image.open(uploaded_file)
                img = compress_image(img, max_size_kb=500)
                st.session_state['current_img'] = img
                st.session_state['app_stage'] = 'analyze'
                st.rerun()

        elif st.session_state.get("current_page") == "glucose_input":
            # 혈당 입력 전용 페이지 (Google 로그인만)
            if st.session_state.get("login_type") == "google" and st.session_state.get("user_id"):
                uid_r = st.session_state["user_id"]
                with st.form(key="glucose_form_portal"):
                    import pytz
                    _seoul = pytz.timezone("Asia/Seoul")
                    _now_kr = datetime.now(_seoul)
                    _g_date = st.date_input("날짜", value=_now_kr.date(), key="g_date_portal")
                    _g_time = st.time_input("시간", value=_now_kr.time().replace(second=0, microsecond=0), key="g_time_portal")
                    _g_type = st.radio("유형", options=["fasting", "postprandial"], format_func=lambda x: t.get("glucose_fasting", "공복 혈당") if x == "fasting" else t.get("glucose_postprandial", "식후 혈당"), key="g_type_portal")
                    _g_val = st.number_input("mg/dL", min_value=40, max_value=400, value=100, step=1, key="g_val_portal")
                    if st.form_submit_button(t.get("glucose_save", "저장")):
                        _dt = _seoul.localize(datetime.combine(_g_date, _g_time))
                        try:
                            with st.spinner("데이터를 창고에 저장 중입니다..."):
                                ok = _save_glucose(uid_r, _g_type, _g_val, timestamp=_dt.astimezone(timezone.utc))
                        except Exception as e:
                            ok = False
                            st.error(f"저장 실패: {e}")
                        if ok:
                            get_today_summary.clear()
                            get_glucose_meals_cached.clear()
                            st.session_state["glucose_saved_portal"] = True
            # 저장 성공 후: 메인으로 이동 버튼 (폼 밖에서 독립적으로 작동)
            if st.session_state.get("glucose_saved_portal"):
                st.success("성공적으로 저장되었습니다!")
                st.caption("📊 메인에서 **리포트 보기**를 누르면 방금 저장한 혈당이 그래프에 반영됩니다.")
                if st.button("확인 후 메인으로 이동", key="btn_glucose_back_main", use_container_width=True):
                    st.session_state["open_glucose"] = False
                    st.session_state["current_page"] = "main"
                    st.session_state["glucose_saved_portal"] = False
                    st.rerun()
            else:
                st.info(t.get("login_heading", "로그인 후 혈당을 기록할 수 있습니다."))

        elif st.session_state.get("current_page") == "report":
            # 리포트 전용 페이지: 탭 + Plotly
            if st.session_state.get("login_type") == "google" and st.session_state.get("user_id"):
                uid_r = st.session_state["user_id"]
                st.markdown(f"### 📊 {t.get('report_section_title', '나의 혈당 관리 리포트')}")
                tab_d, tab_w, tab_m = st.tabs([
                    t.get("glucose_tab_daily", "Daily"),
                    t.get("glucose_tab_weekly", "Weekly"),
                    t.get("glucose_tab_monthly", "Monthly"),
                ])
                from datetime import timedelta
                import pytz
                _seoul_tz = pytz.timezone("Asia/Seoul")
                now_utc = datetime.now(timezone.utc)
                now_kr = now_utc.astimezone(_seoul_tz)

                def _report_start_end(tab_scope_key):
                    """한국 시간 기준으로 Daily/Weekly/Monthly 구간 (UTC datetime) 반환."""
                    if tab_scope_key == "daily":
                        start_kr = now_kr.replace(hour=0, minute=0, second=0, microsecond=0)
                        return start_kr.astimezone(timezone.utc), now_utc
                    if tab_scope_key == "weekly":
                        # 이번 주 월요일 00:00 (한국) ~ 지금
                        weekday = now_kr.weekday()
                        start_kr = (now_kr - timedelta(days=weekday)).replace(hour=0, minute=0, second=0, microsecond=0)
                        return start_kr.astimezone(timezone.utc), now_utc
                    # monthly
                    start_kr = now_kr.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                    return start_kr.astimezone(timezone.utc), now_utc

                def _render_glucose_tab(start, end, tab_scope_key):
                    glucose_list, meals_list = get_glucose_meals_cached(uid_r, start.isoformat(), end.isoformat())

                    # 기본 지표
                    c1, c2, c3 = st.columns(3)
                    with c1:
                        st.metric(t.get("report_meals_count", "식단 수"), len(meals_list))
                    with c2:
                        avg_c = sum(m.get("total_carbs", 0) for m in meals_list) / len(meals_list) if meals_list else 0
                        st.metric(t.get("report_avg_carbs", "평균 탄수화물"), f"{avg_c:.0f}g")
                    with c3:
                        avg_g = sum(g.get("value", 0) for g in glucose_list) / len(glucose_list) if glucose_list else 0
                        st.metric(t.get("glucose_value_mg", "혈당 (mg/dL)") + " avg", f"{avg_g:.0f}" if glucose_list else "-")

                    if glucose_list or meals_list:
                        import plotly.graph_objects as go
                        from plotly.subplots import make_subplots

                        # --- 그룹별 OHLC 및 탄수화물 "거래량" 집계 ---
                        ohlc = defaultdict(list)
                        volume = defaultdict(float)

                        def _group_key(ts):
                            if ts is None:
                                return None
                            if hasattr(ts, "astimezone"):
                                ts_kr = ts.astimezone(_seoul_tz)
                            else:
                                ts_kr = ts
                            d = ts_kr.date() if hasattr(ts_kr, "date") else ts_kr
                            if tab_scope_key == "daily":
                                return d
                            elif tab_scope_key == "weekly":
                                iso = d.isocalendar()
                                return (iso.year, iso.week)
                            else:
                                return (d.year, d.month)

                        # 혈당 OHLC
                        for g in glucose_list:
                            ts = g.get("timestamp")
                            val = g.get("value", 0)
                            key = _group_key(ts)
                            if key is not None:
                                ohlc[key].append((ts, val))

                        # 탄수화물 "거래량"
                        for m in meals_list:
                            ts = m.get("timestamp")
                            key = _group_key(ts)
                            if key is not None:
                                volume[key] += float(m.get("total_carbs", 0) or 0)

                        # 정렬된 x 축 및 OHLC 배열 구성
                        def _key_to_label(k):
                            if isinstance(k, tuple):
                                if tab_scope_key == "weekly":
                                    y, w = k
                                    return f"{y}-W{w:02d}"
                                else:
                                    y, mon = k
                                    return f"{y}-{mon:02d}"
                            if hasattr(k, "isoformat"):
                                return k.isoformat()
                            return str(k)

                        sorted_keys = sorted(ohlc.keys())
                        if not sorted_keys:
                            st.info(t.get("report_no_data", "해당 기간 기록이 없습니다."))
                        else:
                            x = []
                            open_v = []
                            high_v = []
                            low_v = []
                            close_v = []
                            vols = []

                            all_values_for_stats = []

                            for k in sorted_keys:
                                items = sorted(ohlc[k], key=lambda x: x[0])
                                vals = [v for _, v in items]
                                o = vals[0]
                                c = vals[-1]
                                h = max(vals)
                                l = min(vals)
                                x.append(_key_to_label(k))
                                open_v.append(o)
                                high_v.append(h)
                                low_v.append(l)
                                close_v.append(c)
                                vols.append(volume.get(k, 0.0))
                                all_values_for_stats.extend(vals)

                            fig = make_subplots(
                                rows=2,
                                cols=1,
                                shared_xaxes=True,
                                row_heights=[0.7, 0.3],
                                vertical_spacing=0.05,
                            )

                            fig.add_trace(
                                go.Candlestick(
                                    x=x,
                                    open=open_v,
                                    high=high_v,
                                    low=low_v,
                                    close=close_v,
                                    increasing_line_color="#e74c3c",
                                    decreasing_line_color="#2ecc71",
                                    name=t.get("glucose_value_mg", "혈당"),
                                ),
                                row=1,
                                col=1,
                            )

                            fig.add_trace(
                                go.Bar(
                                    x=x,
                                    y=vols,
                                    name=t.get("report_avg_carbs", "탄수화물") + " (g)",
                                    marker_color="#86cc85",
                                ),
                                row=2,
                                col=1,
                            )

                            fig.update_layout(
                                margin=dict(l=20, r=20, t=30, b=20),
                                height=360,
                                xaxis_tickangle=-45,
                                autosize=True,
                                showlegend=False,
                            )
                            fig.update_yaxes(title_text=t.get("glucose_value_mg", "혈당 (mg/dL)"), row=1, col=1)
                            fig.update_yaxes(title_text=t.get("report_avg_carbs", "탄수화물") + " (g)", row=2, col=1)
                            st.plotly_chart(fig, use_container_width=True, config=dict(responsive=True, displayModeBar=True))

                            # --- 간단 AI 스타일 분석 텍스트 ---
                            analysis_text = ""
                            if all_values_for_stats:
                                overall_avg = statistics.mean(all_values_for_stats)
                                if tab_scope_key == "daily":
                                    daily_range = max(all_values_for_stats) - min(all_values_for_stats)
                                    spike_flag = daily_range >= 40
                                    analysis_text = (
                                        f"오늘 평균 혈당은 약 **{overall_avg:.0f} mg/dL**이며, "
                                        f"일중 변동 폭은 약 **{daily_range:.0f} mg/dL** 입니다. "
                                    )
                                    if spike_flag and sum(vols) > 0:
                                        analysis_text += (
                                            "혈당 스파이크가 관찰되며, 같은 기간 탄수화물 섭취량이 높았던 구간과의 상관관계를 의심해볼 수 있습니다. "
                                            "탄수화물 섭취량이 많은 식사 전후의 혈당 패턴을 특히 유심히 관찰해 보세요."
                                        )
                                    else:
                                        analysis_text += (
                                            "전반적으로 혈당 변동성이 크지 않은 편이며, "
                                            "오늘의 식단과 혈당 관리가 비교적 안정적으로 유지된 것으로 보입니다."
                                        )
                                elif tab_scope_key == "weekly":
                                    try:
                                        vol = statistics.pstdev(all_values_for_stats)
                                    except statistics.StatisticsError:
                                        vol = 0.0
                                    analysis_text = (
                                        f"이번 주 평균 혈당은 약 **{overall_avg:.0f} mg/dL**, "
                                        f"표준편차(변동성)는 약 **{vol:.1f} mg/dL** 입니다. "
                                    )
                                    # 전주 대비 비교
                                    try:
                                        prev_start = (start - timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)
                                        prev_glucose, _ = get_glucose_meals_cached(uid_r, prev_start.isoformat(), start.isoformat())
                                        if prev_glucose:
                                            prev_vals = [g.get("value", 0) for g in prev_glucose]
                                            prev_avg = statistics.mean(prev_vals)
                                            diff = overall_avg - prev_avg
                                            if abs(diff) < 3:
                                                analysis_text += "전 주와 비교했을 때 평균 혈당은 큰 변화가 없습니다."
                                            elif diff > 0:
                                                analysis_text += f"전 주 대비 평균 혈당이 약 **{diff:.0f} mg/dL** 상승했습니다."
                                            else:
                                                analysis_text += f"전 주 대비 평균 혈당이 약 **{abs(diff):.0f} mg/dL** 감소했습니다."
                                    except Exception:
                                        pass
                                else:  # monthly
                                    # 당화혈색소 추정: HbA1c = (AvgGlucose + 46.7) / 28.7
                                    est_hba1c = (overall_avg + 46.7) / 28.7
                                    analysis_text = (
                                        f"이번 달 평균 혈당은 약 **{overall_avg:.0f} mg/dL** 입니다. "
                                        f"이를 기준으로 추정한 당화혈색소는 약 **{est_hba1c:.1f}%** 수준입니다. "
                                    )
                                    if est_hba1c < 6.5:
                                        analysis_text += "현재로서는 비교적 양호한 범위에 가까우나, 식사 패턴과 운동을 꾸준히 유지하는 것이 중요합니다."
                                    else:
                                        analysis_text += "당뇨 치료 목표 범위를 벗어날 가능성이 있으므로, 의료진과 상의하여 관리 계획을 조정하는 것을 권장드립니다."

                            if analysis_text:
                                st.markdown("#### 🔍 혈당 패턴 분석")
                                st.markdown(analysis_text)
                    else:
                        st.info(t.get("report_no_data", "해당 기간 기록이 없습니다."))
                        st.caption("혈당은 **🩸 혈당 수치 입력**에서 저장할 수 있습니다. 저장 후 이 페이지를 새로고침하거나 다시 **리포트 보기**를 눌러 주세요.")
                        st.caption("※ 이전에 문자열로 저장된 테스트 데이터는 쿼리에서 제외됩니다. **지금부터 새로 저장하는 데이터**부터 그래프에 반영됩니다.")
                        st.caption("아래 **🔧 데이터 조회 진단**을 펼쳐 조회 오류 여부와 기간·경로를 확인할 수 있습니다.")
                        # 진단: st.expander 화살표 글자 겹침 방지 → 버튼 토글로 대체
                        _diag_key = f"report_diag_open_{tab_scope_key}"
                        if _diag_key not in st.session_state:
                            st.session_state[_diag_key] = True
                        if st.button("🔧 데이터 조회 진단", key=_diag_key + "_btn", use_container_width=True, type="secondary"):
                            st.session_state[_diag_key] = not st.session_state[_diag_key]
                            st.rerun()
                        if st.session_state[_diag_key]:
                            _uid = str(uid_r)
                            _uid_mask = _uid[:3] + "***" + _uid[-2:] if len(_uid) > 5 else "***"
                            st.caption(f"조회 경로: users/{{uid}}/glucose (uid: {_uid_mask})")
                            st.caption(f"기간: {start.isoformat()} ~ {end.isoformat()}")
                            try:
                                _g2, _m2 = _get_glucose_and_meals(uid_r, start, end)
                                st.caption(f"직접 조회 결과: 혈당 {len(_g2)}건, 식단 {len(_m2)}건")
                                if not _g2 and not _m2:
                                    st.caption("Firestore에 해당 기간 문서가 없거나, 서비스 계정 권한/경로를 확인하세요.")
                            except Exception as _e:
                                st.error(f"조회 오류: {_e}")
                            _key_fetch5 = f"diagnostic_raw5_{tab_scope_key}"
                            if st.button("전체 데이터 5건 강제 확인", key=_key_fetch5, use_container_width=True):
                                _raw5 = _get_glucose_last_n(uid_r, 5)
                                st.session_state[_key_fetch5 + "_data"] = _raw5
                                st.rerun()
                            if st.session_state.get(_key_fetch5 + "_data") is not None:
                                _raw5 = st.session_state[_key_fetch5 + "_data"]
                                st.caption("최근 glucose 문서 5건 (원시 데이터):")
                                st.json(_raw5)

                    # 저장 성공 시 메시지 (폼 밖)
                    if st.session_state.get(f"glucose_saved_report_{tab_scope_key}"):
                        st.success("성공적으로 저장되었습니다!")
                        if st.button("확인 후 메인으로 이동", key=f"btn_glucose_back_main_{tab_scope_key}", use_container_width=True):
                            st.session_state["current_page"] = "main"
                            st.session_state[f"glucose_saved_report_{tab_scope_key}"] = False
                            st.rerun()

                    # 혈당 입력 폼: st.expander 화살표 글자 겹침 방지 → 버튼 토글로 대체
                    _form_key = f"report_glucose_form_open_{tab_scope_key}"
                    if _form_key not in st.session_state:
                        st.session_state[_form_key] = False
                    _label_form = t.get("btn_input_glucose", "🩸 혈당 수치 입력")
                    if st.button(_label_form, key=_form_key + "_btn", use_container_width=True, type="secondary"):
                        st.session_state[_form_key] = not st.session_state[_form_key]
                        st.rerun()
                    if st.session_state[_form_key]:
                        with st.form(key=f"glucose_form_{tab_scope_key}"):
                            import pytz
                            seoul = pytz.timezone("Asia/Seoul")
                            now_korea = datetime.now(seoul)
                            default_date = now_korea.date()
                            default_time = now_korea.time().replace(second=0, microsecond=0)
                            col_date, col_time, col_type = st.columns(3)
                            with col_date:
                                g_date = st.date_input("날짜", value=default_date, key=f"g_date_{tab_scope_key}")
                            with col_time:
                                g_time = st.time_input("시간", value=default_time, key=f"g_time_{tab_scope_key}")
                            with col_type:
                                g_type = st.radio("유형", options=["fasting", "postprandial"], format_func=lambda x: t.get("glucose_fasting", "공복 혈당") if x == "fasting" else t.get("glucose_postprandial", "식후 혈당"), key=f"g_type_{tab_scope_key}")
                            g_val = st.number_input("mg/dL", min_value=40, max_value=400, value=100, step=1, key=f"g_val_{tab_scope_key}")
                            if st.form_submit_button(t.get("glucose_save", "저장")):
                                dt_seoul = datetime.combine(g_date, g_time)
                                if dt_seoul.tzinfo is None:
                                    dt_seoul = seoul.localize(dt_seoul)
                                ts_utc = dt_seoul.astimezone(timezone.utc)
                                try:
                                    with st.spinner("데이터를 창고에 저장 중입니다..."):
                                        ok = _save_glucose(uid_r, g_type, g_val, timestamp=ts_utc)
                                except Exception as e:
                                    ok = False
                                    st.error(f"저장 실패: {e}")
                                if ok:
                                    get_today_summary.clear()
                                    get_glucose_meals_cached.clear()
                                    st.session_state[f"glucose_saved_report_{tab_scope_key}"] = True
                                    st.rerun()

                with tab_d:
                    start_d, end_d = _report_start_end("daily")
                    _render_glucose_tab(start_d, end_d, "daily")
                with tab_w:
                    start_w, end_w = _report_start_end("weekly")
                    _render_glucose_tab(start_w, end_w, "weekly")
                with tab_m:
                    start_m, end_m = _report_start_end("monthly")
                    _render_glucose_tab(start_m, end_m, "monthly")
            else:
                st.info(t.get("login_heading", "로그인 후 리포트를 볼 수 있습니다."))

        elif st.session_state.get("current_page") == "settings":
            # 설정 페이지: 언어, 목표, 로그아웃 (사이드바와 동일한 기능)
            st.subheader(t.get("btn_settings", "⚙️ 설정"))
            lang_col1, lang_col2 = st.columns([1, 2])
            with lang_col2:
                current_idx = SUPPORTED_LANGS.index(st.session_state["lang"]) if st.session_state["lang"] in SUPPORTED_LANGS else 0
                selected_lang = st.selectbox(
                    "Language",
                    options=SUPPORTED_LANGS,
                    format_func=lambda x: LANG_LABELS.get(x, x),
                    index=current_idx,
                    key="settings_lang",
                )
            if selected_lang != st.session_state["lang"]:
                st.session_state["lang"] = selected_lang
                t = LANG_DICT[st.session_state["lang"]]
                st.rerun()
            if st.session_state.get("login_type") == "google":
                if st.button(f"🚪 {t['sidebar_logout']}", key="settings_logout", use_container_width=True):
                    st.session_state["logged_in"] = False
                    st.session_state["login_type"] = None
                    st.session_state["user_id"] = None
                    st.session_state["user_email"] = None
                    st.session_state["history_loaded_uid"] = None
                    st.session_state["history"] = []
                    st.session_state["auth_mode"] = "login"
                    st.session_state["current_page"] = "main"
                    st.rerun()
            elif st.session_state.get("login_type") == "guest":
                if st.button(f"🔐 {t['sidebar_go_login']}", key="settings_go_login", use_container_width=True):
                    st.session_state["logged_in"] = False
                    st.session_state["login_type"] = None
                    st.session_state["user_id"] = None
                    st.session_state["user_email"] = None
                    st.session_state["history_loaded_uid"] = None
                    st.session_state["history"] = []
                    st.session_state["auth_mode"] = "login"
                    st.session_state["current_page"] = "main"
                    st.rerun()

    elif st.session_state['app_stage'] == 'analyze':
        # 2페이지: 업로드 완료 & 분석 대기 페이지
        if st.button(t["btn_back_main"], key="btn_back_main_1", use_container_width=True):
            st.session_state['app_stage'] = 'main'
            st.session_state['current_page'] = 'main'
            st.session_state['current_img'] = None
            st.session_state['uploader_key'] += 1 # 강제로 새 업로더 생성(초기화)
            st.rerun()
        
        # 미리보기: 최대 높이 350px, object-fit contain → 분석 버튼이 스크롤 없이 보이도록
        _img = st.session_state['current_img']
        if _img:
            _buf = io.BytesIO()
            if _img.mode in ("RGBA", "P"):
                _img = _img.convert("RGB")
            _img.save(_buf, format="JPEG", quality=85)
            _b64 = base64.b64encode(_buf.getvalue()).decode()
            st.markdown(f"""
            <div style="max-height:350px;display:flex;justify-content:center;align-items:center;margin-bottom:10px;background:#f8f9fa;border-radius:12px;overflow:hidden;">
                <img src="data:image/jpeg;base64,{_b64}" style="max-height:350px;width:100%;object-fit:contain;" />
            </div>
            """, unsafe_allow_html=True)
        
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
            st.session_state['current_page'] = 'main'
            st.session_state['current_img'] = None
            if 'uploader_key' in st.session_state:
                st.session_state['uploader_key'] += 1
            st.warning(t["session_reset_msg"])
            st.rerun()

        if st.button(t["btn_back_main_2"], key="btn_back_main_2", use_container_width=True):
            st.session_state['app_stage'] = 'main'
            st.session_state['current_page'] = 'main'
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
        if st.session_state.get("login_type") == "google" and st.session_state.get("user_id"):
            _food_names = [str(it[0]).strip() for it in (res.get("sorted_items") or []) if it and len(it) > 0]
            if _warn_similar_food_glucose(st.session_state.get("user_id"), _food_names, total_carbs):
                st.warning(t.get("similar_food_warning", "과거 비슷한 식사 후 혈당이 높았던 기록이 있습니다. 섭취량·순서를 조절해 보세요."))

        if score <= 40:
            risk_label, risk_color = f"{t['risk_safe']} 🟢", "#4CAF50"
        elif score <= 65:
            risk_label, risk_color = f"{t['risk_caution']} 🟡", "#FFB300"
        else:
            risk_label, risk_color = f"{t['risk_danger']} 🔴", "#F44336"

        # ── 1. 이미지 + 원형 혈당 스코어 (Cal AI 핵심 UI, 미리보기 높이 350px로 콤팩트) ──
        col_img, col_score = st.columns([1, 1])
        with col_img:
            _res_img = res.get("raw_img")
            if _res_img:
                _rb = io.BytesIO()
                if _res_img.mode in ("RGBA", "P"):
                    _res_img = _res_img.convert("RGB")
                _res_img.save(_rb, format="JPEG", quality=85)
                _res_b64 = base64.b64encode(_rb.getvalue()).decode()
                st.markdown(f"""
                <div style="max-height:350px;display:flex;justify-content:center;align-items:center;background:#f8f9fa;border-radius:12px;overflow:hidden;">
                    <img src="data:image/jpeg;base64,{_res_b64}" style="max-height:350px;width:100%;object-fit:contain;" />
                </div>
                """, unsafe_allow_html=True)
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
                st.session_state["user_id"] = None
                st.session_state["user_email"] = None
                st.session_state["history_loaded_uid"] = None
                st.session_state["history"] = []
                st.session_state["auth_mode"] = "login"
                st.rerun()
        else:
            if st.button(t["save_btn"], use_container_width=True):
                _lang = st.session_state.get("lang", "KO")
                try:
                    import pytz
                    tz = pytz.timezone(LANG_TIMEZONE.get(_lang) or "UTC")
                    now_utc = datetime.now(timezone.utc)
                    save_date_utc = now_utc.isoformat()
                    save_date = now_utc.astimezone(tz).strftime("%Y-%m-%d %H:%M")
                except Exception:
                    now_utc = datetime.now(timezone.utc)
                    save_date_utc = now_utc.isoformat()
                    save_date = now_utc.strftime("%Y-%m-%d %H:%M")
                uid = st.session_state.get("user_id")  # 현재 로그인한 사용자 uid (필수, user_logs 문서에 포함)
                if not uid:
                    st.toast("로그인된 사용자 정보가 없습니다.")
                else:
                    image_url = None
                    try:
                        from firebase_admin import firestore, storage
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
                            _opts = {}
                            _bucket = os.environ.get("FIREBASE_STORAGE_BUCKET") or os.environ.get("STORAGE_BUCKET")
                            if _bucket:
                                _opts["storageBucket"] = _bucket
                            elif key_dict.get("project_id"):
                                _opts["storageBucket"] = f"{key_dict['project_id']}.appspot.com"
                            firebase_admin.initialize_app(cred, _opts)
                        db = firestore.client()
                        doc_ref = db.collection("users").document(uid).collection("history").document()
                        doc_id = doc_ref.id
                        def _num(v):
                            if v is None:
                                return 0
                            try:
                                return int(v) if isinstance(v, (int, float)) or hasattr(v, "__int__") else int(float(v))
                            except (TypeError, ValueError):
                                return 0
                        raw_pil = res.get("raw_img")
                        if raw_pil is not None:
                            _, img_bytes = compress_image_for_storage(raw_pil, max_width=1024, quality=80)
                            if img_bytes and isinstance(img_bytes, bytes) and len(img_bytes) > 0:
                                try:
                                    bucket = storage.bucket()
                                    _uid_safe = str(uid).replace("/", "_").replace("\\", "_") if uid else "unknown"
                                    path = f"users/{_uid_safe}/meals/{doc_id}.jpg"
                                    blob = bucket.blob(path)
                                    blob.upload_from_string(img_bytes, content_type="image/jpeg")
                                    blob.make_public()  # Storage 규칙: 읽기 allow read 또는 공개 링크 허용 필요
                                    image_url = getattr(blob, "public_url", None) or ""
                                    if not (image_url and str(image_url).strip().startswith("http")):
                                        # public_url이 비어있거나 절대 URL이 아니면 bucket+path로 완전 URL 구성
                                        image_url = _normalize_image_url(path, bucket.name)
                                except Exception as storage_err:
                                    traceback.print_exc(file=sys.stderr)
                                    sys.stderr.write(f"[Storage] {type(storage_err).__name__}: {storage_err}\n")
                        sorted_items_safe = []
                        for item in res.get("sorted_items", []):
                            if not item:
                                continue
                            name = str(item[0]).strip() if len(item) > 0 else ""
                            gi = _num(item[1]) if len(item) > 1 else 0
                            carbs = _num(item[2]) if len(item) > 2 else 0
                            protein = _num(item[3]) if len(item) > 3 else 0
                            color = str(item[4]).strip() if len(item) > 4 else ""
                            sorted_items_safe.append({
                                "name": name,
                                "gi": gi,
                                "carbs": carbs,
                                "protein": protein,
                                "color": color,
                            })
                        new_db_record = {
                            "date": str(save_date),
                            "saved_at_utc": save_date_utc,
                            "sorted_items": sorted_items_safe,
                            "advice": str(res.get("advice", "")),
                            "blood_sugar_score": _num(res.get("blood_sugar_score")),
                            "total_carbs": _num(res.get("total_carbs")),
                            "total_protein": _num(res.get("total_protein")),
                            "avg_gi": _num(res.get("avg_gi")),
                            "image_url": image_url if image_url is not None else None,
                        }
                        doc_ref.set(new_db_record)
                        now_utc = datetime.now(timezone.utc)
                        db.collection("user_logs").add({
                            "user_id": str(uid),
                            "history_doc_id": doc_id,
                            "date": str(save_date),
                            "saved_at_utc": save_date_utc,
                            "timestamp": now_utc,
                            "sorted_items": sorted_items_safe,
                            "advice": new_db_record["advice"],
                            "blood_sugar_score": new_db_record["blood_sugar_score"],
                            "total_carbs": new_db_record["total_carbs"],
                            "total_protein": new_db_record["total_protein"],
                            "avg_gi": new_db_record["avg_gi"],
                            "image_url": new_db_record["image_url"],
                        })
                    except Exception as e:
                        traceback.print_exc(file=sys.stderr)
                        sys.stderr.write(f"[DB 저장] {type(e).__name__}: {e}\n")
                        err_lower = str(e).lower()
                        if "permission" in err_lower or "denied" in err_lower:
                            sys.stderr.write("[Firestore] Permission Denied 가능성. Rules 확인 필요.\n")
                        st.toast(f"DB 저장 에러: {str(e)}")
                    else:
                        st.session_state["history"].append({
                            "doc_id": doc_id,
                            "date": save_date,
                            "saved_at_utc": save_date_utc,
                            "image": res["raw_img"],
                            "image_url": image_url,
                            "sorted_items": res["sorted_items"],
                            "advice": res["advice"],
                            "blood_sugar_score": res.get("blood_sugar_score", 0),
                            "total_carbs": res.get("total_carbs", 0),
                            "total_protein": res.get("total_protein", 0),
                            "avg_gi": res.get("avg_gi", 0),
                        })
                        st.balloons()
                        st.success(t["save_msg"])
                        st.session_state["nav_menu"] = "history"
                        st.rerun()


# ── 나의 기록 탭 (Cal AI 스타일 히스토리) ──
elif menu_key == "history":
    # 환영 문구를 로그아웃 버튼 위에 표시
    render_login_badge()
    # 메인 상단: 1페이지로 가기 버튼
    _lt_h = st.session_state.get("login_type")
    c1, c2 = st.columns([5, 1])
    with c2:
        if _lt_h == "guest":
            if st.button(f"🔐 {t['sidebar_go_login']}", key="history_go_login", use_container_width=True):
                st.session_state["logged_in"] = False
                st.session_state["login_type"] = None
                st.session_state["user_id"] = None
                st.session_state["user_email"] = None
                st.session_state["history_loaded_uid"] = None
                st.session_state["history"] = []
                st.session_state["auth_mode"] = "login"
                st.rerun()
        elif _lt_h == "google":
            if st.button(f"🚪 {t['sidebar_logout']}", key="history_logout", use_container_width=True):
                st.session_state["logged_in"] = False
                st.session_state["login_type"] = None
                st.session_state["user_id"] = None
                st.session_state["user_email"] = None
                st.session_state["history_loaded_uid"] = None
                st.session_state["history"] = []
                st.session_state["auth_mode"] = "login"
                st.rerun()
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

    # st.expander 화살표(_arrow_right) 겹침 제거: 버튼 토글로 대체
    if st.session_state['history']:
        for i, rec in enumerate(reversed(st.session_state['history'])):
            rec_score = rec.get('blood_sugar_score', 0)
            rec_carbs = rec.get('total_carbs', 0)
            rec_gi = rec.get('avg_gi', 0)
            rc = "#4CAF50" if rec_score <= 40 else "#FFB300" if rec_score <= 65 else "#F44336"
            rl = t["risk_safe"] if rec_score <= 40 else t["risk_caution"] if rec_score <= 65 else t["risk_danger"]
            _key = f"hist_open_{i}"
            if _key not in st.session_state:
                st.session_state[_key] = False
            _lang = st.session_state.get("lang", "KO")
            _date = _format_record_date(rec.get("date", ""), rec.get("saved_at_utc"), _lang)
            _btn_label = f"🍴 {_date}  ·  혈당 {rec_score} ({rl})  ·  탄수화물 {rec_carbs}g"
            if st.button(_btn_label, key=_key + "_btn", use_container_width=True, type="secondary"):
                st.session_state[_key] = not st.session_state[_key]
                st.rerun()
            if st.session_state[_key]:
                st.markdown(f"**{_date}** · {t['blood_score_label']} **{rec_score}** ({rl}) · {t['carbs']} **{rec_carbs}g**")
                _img_url = rec.get("image_url")
                if _img_url and isinstance(_img_url, str) and _img_url.strip():
                    try:
                        st.image(_img_url, use_container_width=True)
                    except Exception as img_err:
                        sys.stderr.write(f"[이미지 로드] URL 표시 실패 (Storage 권한 또는 CORS 확인): {img_err}\n")
                        st.caption("(이미지를 불러올 수 없습니다. Storage 읽기 권한을 확인해 주세요.)")
                elif rec.get("image"):
                    st.image(rec["image"], use_container_width=True)
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
                    if isinstance(item, dict):
                        name = str(item.get("name", "")).replace("*", "").strip()
                        color_str = str(item.get("color", ""))
                        gi_val = item.get("gi", "-")
                    else:
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
                _doc_id = rec.get("doc_id")
                if _doc_id and st.button(t.get("delete_record", "🗑️ 기록 삭제"), key=f"hist_del_{i}", type="secondary"):
                    _uid = st.session_state.get("user_id")
                    if _uid:
                        ok, failed_step = _delete_history_record(_uid, _doc_id)
                        if ok:
                            st.session_state["history"] = [h for h in st.session_state["history"] if h.get("doc_id") != _doc_id]
                            st.success(t.get("delete_record_full", "기록이 완전히 삭제되었습니다."))
                            st.rerun()
                        else:
                            st.error(t.get("delete_record_failed", "삭제에 실패했습니다.") + (f" ({failed_step})" if failed_step else ""))
                    else:
                        st.toast(t.get("delete_record_failed", "삭제에 실패했습니다."))
    else:
        st.info(t["no_history_msg"])
