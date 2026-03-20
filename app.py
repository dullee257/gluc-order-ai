# -*- coding: utf-8 -*-
"""NutriSort AI - 한글 기본, UTF-8 소스·출력 통일."""
import sys
import os
import json
import traceback
import urllib.parse
import html as html_module
import re
from collections import defaultdict
import statistics
import io
from PIL import Image
from datetime import datetime, timezone

from translation import LANG_DICT, get_text, GOAL_INTERNAL_KEYS
from prompts import get_analysis_prompt
from firebase_db import (
    upload_image_to_storage,
    save_meal_and_summary,
    get_daily_summary,
)

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
from google import genai  # 패키지: google-genai (구 google-generativeai 아님)
from google.genai import types as gtypes
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


def _extract_json_blob_from_text(raw):
    """Gemini 텍스트 응답에서 JSON 객체 문자열만 추출 (마크다운 펜스·잡담 대응)."""
    if raw is None:
        return None
    if not isinstance(raw, str):
        raw = str(raw)
    s = raw.strip()
    if not s:
        return None
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", s, re.IGNORECASE)
    if fence:
        inner = fence.group(1).strip()
        if inner.startswith("{"):
            s = inner
    dec = json.JSONDecoder()
    i = s.find("{")
    while i != -1:
        try:
            _obj, end = dec.raw_decode(s, i)
            return s[i:end]
        except json.JSONDecodeError:
            i = s.find("{", i + 1)
    return None


def _coerce_int_nutrient(v, default=0):
    """JSON 숫자 필드를 정수로 안전 변환."""
    if v is None:
        return default
    if isinstance(v, bool):
        return default
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return int(round(v))
    s = str(v).strip()
    if not s:
        return default
    try:
        return int(float(s))
    except (TypeError, ValueError):
        digits = "".join(c for c in s if c.isdigit() or c in ".-")
        try:
            return int(float(digits)) if digits else default
        except (TypeError, ValueError):
            return default


def _parse_food_analysis_json_response(text):
    """
    비전 JSON 응답 → (sorted_items, total_carbs) 또는 None.
    sorted_items 항목: [name, gi, carbs, protein, color, order, fat, kcal]
    """
    blob = _extract_json_blob_from_text(text)
    if not blob:
        return None
    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    items = data.get("items")
    if not isinstance(items, list) or len(items) == 0:
        return None
    parsed = []
    for it in items:
        if not isinstance(it, dict):
            continue
        name = str(it.get("name", "")).strip()
        if not name:
            continue
        gi = max(0, min(100, _coerce_int_nutrient(it.get("gi"), 50)))
        carbs = max(0, _coerce_int_nutrient(it.get("carbs"), 0))
        protein = max(0, _coerce_int_nutrient(it.get("protein"), 0))
        fat = max(0, _coerce_int_nutrient(it.get("fat"), 0))
        kcal = max(0, _coerce_int_nutrient(it.get("kcal"), 0))
        signal = it.get("signal") or it.get("color") or "노랑"
        signal = str(signal).strip() or "노랑"
        order = max(1, _coerce_int_nutrient(it.get("order"), 99))
        parsed.append([name, gi, carbs, protein, signal, order, fat, kcal])
    if not parsed:
        return None
    sorted_items = sorted(parsed, key=lambda x: x[5])
    sum_carbs = sum(x[2] for x in parsed)
    tc_raw = data.get("total_carbs")
    try:
        tc = int(float(tc_raw))
    except (TypeError, ValueError):
        tc = sum_carbs
    if sum_carbs > 0 and abs(tc - sum_carbs) > max(8, int(sum_carbs * 0.35)):
        tc = sum_carbs
    total_carbs = max(0, tc)
    return sorted_items, total_carbs


def _reset_vision_analysis_parse_error(is_guest, loading_placeholder):
    """JSON 파싱 실패 시 게스트 횟수 복구·분석 상태 초기화·사용자 알림."""
    if loading_placeholder is not None:
        try:
            loading_placeholder.empty()
        except Exception:
            pass
    st.session_state["vision_analysis_status"] = "idle"
    st.session_state.pop("current_analysis", None)
    if is_guest and st.session_state.get("guest_usage_count", 0) > 0:
        st.session_state["guest_usage_count"] -= 1
    st.error("이미지 분석 중 오류가 발생했습니다. 다시 시도해 주세요.")


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
# KR 단일 타겟팅: 언어는 KO로 고정
t = LANG_DICT["KO"]


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
        welcome_msg = get_text("KO", "welcome_user", name=display_name)
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

# 3-2. 브라우저 자동번역 방지: KR 단일 타겟팅 (항상 ko)
st.markdown('<script>try{document.documentElement.lang="ko";}catch(e){}</script>', unsafe_allow_html=True)

# 3-2b. 모바일: viewport 고정 + CSS/JS로 핀치·더블탭 줌 억제 (iframe·부모 문서)
st.markdown(
    r"""
<script>
(function () {
  var VIEWPORT = "width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, shrink-to-fit=no";
  function fixViewport(doc) {
    if (!doc || !doc.head) return;
    var m = doc.querySelector('meta[name="viewport"]');
    if (!m) {
      m = doc.createElement("meta");
      m.setAttribute("name", "viewport");
      doc.head.insertBefore(m, doc.head.firstChild);
    }
    m.setAttribute("content", VIEWPORT);
  }
  try { fixViewport(document); } catch (e) {}
  try {
    if (window.parent && window.parent !== window && window.parent.document) {
      fixViewport(window.parent.document);
    }
  } catch (e) {}
})();

function blockZoom(doc) {
  if (!doc || !doc.addEventListener) return;
  doc.addEventListener(
    "touchmove",
    function (event) {
      var multi = event.touches && event.touches.length > 1;
      var scaled = typeof event.scale === "number" && event.scale !== 1;
      if (multi || scaled) {
        event.preventDefault();
      }
    },
    { passive: false }
  );

  var lastTouchEnd = 0;
  doc.addEventListener(
    "touchend",
    function (event) {
      var now = new Date().getTime();
      if (now - lastTouchEnd <= 300) {
        event.preventDefault();
      }
      lastTouchEnd = now;
    },
    { passive: false }
  );

  doc.addEventListener("gesturestart", function (event) {
    event.preventDefault();
  });
}

try { blockZoom(document); } catch (e) {}
try {
  if (window.parent && window.parent.document) {
    blockZoom(window.parent.document);
  }
} catch (e) {}

/* st.expander: Streamlit 1.47+ stIconMaterial 폰트 미로드 시 노출되는 glyph 이름 텍스트 제거 (summary 밖 포함) */
(function () {
  var GHOST_PARTS = [
    "_arrow_right",
    "_arrow_down",
    "_arrow_drop_down",
    "_arrow_drop_up",
    "arrow_right",
    "arrow_down",
    "keyboard_arrow_right",
    "keyboard_arrow_down",
    "keyboard_arrow_up",
  ];
  function stripGhostTextInSubtree(root) {
    if (!root || !root.ownerDocument) return;
    var doc = root.ownerDocument;
    try {
      var walker = doc.createTreeWalker(root, NodeFilter.SHOW_TEXT, null, false);
      var node;
      while ((node = walker.nextNode())) {
        if (!node.nodeValue) continue;
        var v = node.nodeValue;
        var next = v;
        for (var p = 0; p < GHOST_PARTS.length; p++) {
          var part = GHOST_PARTS[p];
          if (next.indexOf(part) !== -1) next = next.split(part).join("");
        }
        if (next !== v) node.nodeValue = next;
      }
    } catch (err) {}
  }

  function stripAllExpanderGhostText(doc) {
    if (!doc || !doc.querySelectorAll) return;
    var list = doc.querySelectorAll('[data-testid="stExpander"]');
    for (var i = 0; i < list.length; i++) {
      stripGhostTextInSubtree(list[i]);
    }
  }

  function installExpanderGhostCleaner(doc) {
    if (!doc || !doc.documentElement) return;
    stripAllExpanderGhostText(doc);
    if (doc.__nutriExpanderGhostObserverInstalled) return;
    doc.__nutriExpanderGhostObserverInstalled = true;
    var t = null;
    function schedule() {
      if (t) clearTimeout(t);
      t = setTimeout(function () {
        stripAllExpanderGhostText(doc);
        try {
          if (typeof requestAnimationFrame === "function") {
            requestAnimationFrame(function () {
              stripAllExpanderGhostText(doc);
            });
          }
        } catch (e1) {}
        t = null;
      }, 0);
    }
    try {
      var obs = new MutationObserver(function () {
        schedule();
      });
      obs.observe(doc.documentElement, {
        childList: true,
        subtree: true,
        characterData: true,
      });
    } catch (err) {}
  }

  try {
    installExpanderGhostCleaner(document);
  } catch (e) {}
  try {
    if (window.parent && window.parent.document) {
      installExpanderGhostCleaner(window.parent.document);
    }
  } catch (e) {}
})();
</script>
""",
    unsafe_allow_html=True,
)

# 4. 피그마 디자인 + 한글 표시 보장 (UTF-8·폰트)
# 업로더 placeholder: CSS content 내 따옴표·백슬래시 이스케이프 (글자 오류 방지)
_uploader_ph = (t.get("uploader_placeholder") or "식단 스캔 시작").replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
st.markdown(f"""
<style>
    /* 한글 표시: Noto Sans KR 로드 후 전역 적용 (한글 깨짐 방지) */
    @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;700&display=swap');
    /* 모바일: 스크롤(pan)만 허용, 핀치·더블탭 확대 제스처 억제 (pan-x pan-y) */
    html, body, .stApp, .block-container, button, input, select, textarea {{
        touch-action: pan-x pan-y !important;
        -webkit-text-size-adjust: 100% !important;
    }}
    /*
     * st.expander: 기본 아이콘·SVG·래퍼 물리적 제거, 라벨은 이모지 문구로 안내(우측 가상 화살표 없음)
     */
    [data-testid="stExpander"] details summary {{
        list-style: none !important;
        display: block !important;
        width: 100% !important;
        box-sizing: border-box !important;
        padding: 0.4rem 0.5rem !important;
        text-align: left !important;
    }}
    [data-testid="stExpander"] details summary::-webkit-details-marker {{
        display: none !important;
    }}
    /* Expander 우측 기본 아이콘 및 잔여 영역 완전 제거 */
    [data-testid="stExpander"] details summary svg,
    [data-testid="stExpander"] details summary .material-icons,
    [data-testid="stExpander"] details summary i,
    [data-testid="stExpander"] details summary [data-testid="stExpanderIconWrapper"],
    [data-testid="stExpander"] details summary [data-testid="stIconMaterial"],
    [data-testid="stExpander"] [data-testid="stIconMaterial"],
    [data-testid="stExpander"] details summary .st-icon,
    [data-testid="stExpanderIcon"] {{
        display: none !important;
        opacity: 0 !important;
        visibility: hidden !important;
        width: 0 !important;
        height: 0 !important;
        overflow: hidden !important;
        pointer-events: none !important;
        margin: 0 !important;
        padding: 0 !important;
        border: none !important;
    }}
    [data-testid="stExpander"] details summary::after {{
        content: none !important;
        display: none !important;
    }}
    [data-testid="stExpander"] details > summary > div:first-child,
    [data-testid="stExpander"] details > summary .stMarkdown {{
        text-align: left !important;
    }}
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

    /* 우측 상단 메뉴·헤더·푸터 숨김 (독립 앱 느낌) */
    #MainMenu {{visibility: hidden !important; height: 0 !important;}}
    footer {{visibility: hidden !important; display: none !important; height: 0 !important;}}
    header {{visibility: hidden !important; display: none !important; height: 0 !important;}}
    [data-testid="stHeader"] {{display: none !important; visibility: hidden !important; height: 0 !important;}}
    [data-testid="stToolbar"] {{display: none !important;}}
    
    .block-container {{
        padding-top: 1rem !important;
        padding-left: 1rem !important;
        padding-right: 1rem !important;
        padding-bottom: 1rem !important;
    }}
    /* 모바일: 여백 대폭 축소 + FAB 영역 확보 */
    @media screen and (max-width: 768px) {{
        .block-container {{
            padding-top: 0.35rem !important;
            padding-left: 0.45rem !important;
            padding-right: 0.45rem !important;
            padding-bottom: calc(100px + env(safe-area-inset-bottom, 20px)) !important;
            max-width: 100% !important;
        }}
    }}
    /* 1. 먼저 .bottom-bar-anchor를 가진 모든 세로 블록을 하단에 고정 */
    div[data-testid="stVerticalBlock"]:has(.bottom-bar-anchor) {{
        position: fixed !important;
        bottom: 0;
        left: 0;
        right: 0;
        background-color: white;
        z-index: 999;
        height: 80px;
        padding-bottom: env(safe-area-inset-bottom, 20px);
        padding-top: 10px;
        box-sizing: border-box;
        box-shadow: 0 -2px 10px rgba(0,0,0,0.05);
    }}
    /* 2. [핵심] 부모 블록은 고정 해제! (자식 중에 anchor가 있는 부모 블록은 원상복구) */
    div[data-testid="stVerticalBlock"]:has(> div > div > div[data-testid="stVerticalBlock"] .bottom-bar-anchor),
    div[data-testid="stVerticalBlock"]:has(div[data-testid="stVerticalBlock"] .bottom-bar-anchor) {{
        position: static !important;
        background-color: transparent !important;
        box-shadow: none !important;
        padding-bottom: 0 !important;
        padding-top: 0 !important;
    }}
    /* 3. 스크롤 시 하단 바에 내용이 가리지 않도록 메인 앱 영역 여백 확보 */
    div[data-testid="stAppViewBlockContainer"] {{
        padding-bottom: calc(100px + env(safe-area-inset-bottom, 20px)) !important;
    }}

    /* Native Bottom Bar 오버레이: 보기용 HTML 위에 투명 st.button을 덮어쓰기 */
    div[data-testid="stVerticalBlock"]:has(.bottom-bar-anchor) div[data-testid="column"] {{
        position: relative;
        height: 100%;
        display: flex;
        justify-content: center;
        align-items: center;
    }}
    div[data-testid="stVerticalBlock"]:has(.bottom-bar-anchor) div[data-testid="column"] .stButton > button {{
        opacity: 0 !important;
        position: absolute !important;
        top: 0 !important;
        left: 0 !important;
        right: 0 !important;
        bottom: 0 !important;
        margin: 0 !important;
        padding: 0 !important;
        min-width: 0 !important;
        background: transparent !important;
        box-shadow: none !important;
    }}
    div[data-testid="stVerticalBlock"]:has(.bottom-bar-anchor) .bottom-tab-decor {{
        pointer-events: none;
        z-index: 0;
        display: flex;
        flex-direction: column;
        justify-content: center;
        align-items: center;
        gap: 2px;
        width: 100%;
    }}
    /* Metric이 있는 가로 행: 모바일에서 2열(2x2) 강제 */
    @media screen and (max-width: 768px) {{
        div[data-testid="stHorizontalBlock"]:has([data-testid="stMetric"]) {{
            flex-wrap: nowrap !important;
            gap: 0.25rem !important;
        }}
        div[data-testid="stHorizontalBlock"]:has([data-testid="stMetric"]) > div[data-testid="column"] {{
            flex: 1 1 calc(50% - 4px) !important;
            min-width: calc(50% - 4px) !important;
            max-width: 50% !important;
        }}
        div[data-testid="stHorizontalBlock"]:has([data-testid="stMetric"]) [data-testid="stMetricValue"] {{
            font-size: clamp(1.1rem, 4vw, 1.35rem) !important;
        }}
    }}
    /* 모바일: Full-width Bottom Bar */
    .nutri-fab-wrap {{
        position: fixed;
        z-index: 999;
        left: 0;
        right: 0;
        bottom: 0;
        height: 80px;
        padding-left: 14px;
        padding-right: 14px;
        padding-top: 0;
        padding-bottom: env(safe-area-inset-bottom, 0px);
        background: white;
        box-shadow: 0 -2px 10px rgba(0,0,0,0.05);
        display: flex;
        flex-direction: row;
        gap: 12px;
        justify-content: center;
        align-items: center;
        width: 100%;
        max-width: none;
        transform: none;
        pointer-events: auto;
    }}
    .nutri-fab-wrap a {{
        pointer-events: auto;
        flex: 1;
        text-align: center;
        text-decoration: none !important;
        font-weight: 900;
        font-size: clamp(13px, 3.8vw, 16px);
        padding: 12px 10px;
        border-radius: 16px;
        box-shadow: 0 6px 18px rgba(0,0,0,0.08);
        border: none;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }}
    .nutri-fab-green {{
        background: linear-gradient(135deg, #2e7d32, #43a047);
        color: #fff !important;
    }}
    .nutri-fab-mint {{
        background: linear-gradient(135deg, #5a9e59, #86cc85);
        color: #1b2e1b !important;
    }}
    @media screen and (min-width: 769px) {{
        .nutri-fab-wrap {{
            display: none !important;
        }}
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

    /* --- EXPANDER: 아이콘 래퍼 최종 Nuke(하단 규칙이 상단을 덮어씀) + 요약 줄 우측 여백 --- */
    [data-testid="stExpander"] details summary,
    [data-testid="stExpander"] summary {{
        padding: 0.45rem 2.35rem 0.45rem 0.5rem !important;
        box-sizing: border-box !important;
    }}
    [data-testid="stExpander"] details summary i.material-icons,
    [data-testid="stExpander"] details summary .material-icons,
    [data-testid="stExpander"] summary i.material-icons,
    [data-testid="stExpander"] summary .material-icons,
    [data-testid="stExpander"] details summary [data-testid="stIconMaterial"],
    [data-testid="stExpander"] [data-testid="stIconMaterial"],
    [data-testid="stExpander"] [data-testid="stExpanderIconWrapper"],
    [data-testid="stExpander"] [data-testid="stExpanderIcon"] {{
        display: none !important;
        opacity: 0 !important;
        visibility: hidden !important;
        width: 0px !important;
        height: 0px !important;
        max-width: 0 !important;
        max-height: 0 !important;
        overflow: hidden !important;
        pointer-events: none !important;
        margin: 0 !important;
        padding: 0 !important;
        border: none !important;
        font-size: 0 !important;
        line-height: 0 !important;
        flex: 0 0 0 !important;
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


_ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")


def _load_legal_markdown(kind: str, lang: str) -> str:
    """KR 단일 타겟팅: assets/terms_ko.md, assets/privacy_ko.md만 사용"""
    path = os.path.join(_ASSETS_DIR, f"{kind}_ko.md")
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except Exception:
        return f"*(Could not load legal file: {kind}_ko.md)*"


def handle_social_login(provider: str) -> dict:
    """
    글로벌 소셜 로그인 통합 진입점 (Firebase Authentication UID 단일 체계 전제).

    Google Play 인앱 결제(Billing) 영수증 검증 후 서버에서 **동일 사용자**를 식별하려면
    어떤 소셜(OAuth)로 가입했든 최종 식별자는 **Firebase Auth localId(UID)** 로 맞추는 것이 일반적이다.

    향후 흐름(뼈대):
    - google: Google OAuth code/id_token → Firebase `signInWithCredential` 또는 Custom Token 발급
    - naver / kakao / facebook: 각 SDK/OAuth → Firebase Custom Token (백엔드) → 동일 UID 네임스페이스
    - 모든 경로에서 `st.session_state['user_id']` = Firebase UID 로 저장 (현재는 이메일/게스트 병행)

    Returns:
        dict with keys: action in ('oauth_google', 'stub', 'error'), optional 'provider'
    """
    p = (provider or "").strip().lower()
    if p == "google":
        return {"action": "oauth_google"}
    if p in ("naver", "kakao", "facebook"):
        return {"action": "stub", "provider": p}
    return {"action": "error", "provider": p}


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
                    st.error(get_text("KO", "google_oauth_err_userinfo", code=userinfo_res.status_code))
                    st.query_params.clear()
                    st.stop()
            else:
                st.error(get_text("KO", "google_oauth_err_token", msg=res.text))
                st.query_params.clear()
                st.stop()
        except Exception as e:
            st.error(get_text("KO", "google_oauth_err_network", err=str(e)))
            st.query_params.clear()
            st.stop()

    _lg = "KO"
    _t = LANG_DICT["KO"]

    for _k, _v in [
        ("auth_splash_done", False),
        ("auth_sheet_open", False),
        ("auth_phase", "splash"),
        ("pending_social_provider", None),
        ("auth_guest_step", False),
    ]:
        if _k not in st.session_state:
            st.session_state[_k] = _v
    if "auth_mode" not in st.session_state:
        st.session_state["auth_mode"] = "login"

    # --- 약관 통과 후 Google OAuth 1회 자동 제출 (Firebase UID 통합 전 단계: Google 계정 식별) ---
    if st.session_state.pop("proceed_google_oauth", False):
        if google_client_id:
            _oauth_state = html_module.escape(st.session_state.get("oauth_state", "oauth"))
            _cid = html_module.escape(google_client_id)
            _uri = html_module.escape(BASE_URL)
            _oauth_html = f"""
            <form id="gOAuthForm" action="https://accounts.google.com/o/oauth2/v2/auth" method="GET" target="_top">
                <input type="hidden" name="client_id" value="{_cid}">
                <input type="hidden" name="redirect_uri" value="{_uri}">
                <input type="hidden" name="response_type" value="code">
                <input type="hidden" name="scope" value="openid email profile">
                <input type="hidden" name="state" value="{_oauth_state}">
                <input type="hidden" name="access_type" value="offline">
                <input type="hidden" name="prompt" value="consent">
            </form>
            <script>document.getElementById("gOAuthForm").submit();</script>
            <p style="font-size:14px;color:#666;">Redirecting to Google…</p>
            """
            st.components.v1.html(_oauth_html, height=120)
            st.caption(_t.get("oauth_open_in_browser", ""))
        else:
            st.error(_t.get("google_login_disabled_help", "Configure OAuth client ID."))
        st.stop()

    st.markdown(
        """
    <style>
    body.auth-login-splash header[data-testid="stHeader"],
    body.auth-login-splash [data-testid="stToolbar"],
    body.auth-login-splash footer { visibility: hidden !important; height: 0 !important; min-height: 0 !important;
      overflow: hidden !important; margin: 0 !important; padding: 0 !important; border: none !important; }
    body.auth-login-splash [data-testid="stDecoration"] { display: none !important; }
    body.auth-login-splash .block-container { padding-top: 0.75rem !important; max-width: 100% !important; }
    body.auth-login-splash .stApp { background: linear-gradient(180deg, #e8f5e9 0%, #fafafa 45%, #ffffff 100%) !important; min-height: 100vh !important; }
    .splash-container {
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      min-height: 55vh;
      text-align: center;
      padding: 0 1rem;
    }
    .splash-title {
      font-size: clamp(2.3rem, 10vw, 3rem);
      font-weight: 800;
      color: #1a1a1a;
      line-height: 1.2;
      margin: 0;
      animation: tracking-in 0.8s ease-out both;
    }
    .splash-subtitle-line1 {
      animation: fade-in-up 0.8s ease-out 0.6s both;
      font-size: clamp(1rem, 4.1vw, 1.1rem);
      font-weight: 700;
      color: #333;
      line-height: 1.45;
      margin-top: 0.95rem;
    }
    .splash-subtitle-line2 {
      animation: fade-in-up 0.8s ease-out 1.2s both;
      font-weight: 800;
      color: #2ecc71;
      font-size: clamp(1.1rem, 4.6vw, 1.3rem);
      line-height: 1.45;
      margin-top: 5px;
    }
    .spike-crash-animation {
      margin-top: 20px;
      display: flex;
      justify-content: center;
      width: 100%;
      max-width: 300px;
    }
    .real-spike-svg { overflow: visible; }
    .bg-grid { opacity: 0; animation: fade-in 0.5s ease-out 1.5s forwards; }
    .path-base {
      stroke-dasharray: 100;
      stroke-dashoffset: 100;
      animation: draw-line 0.7s linear 1.5s forwards;
    }
    .path-rise {
      stroke-dasharray: 50;
      stroke-dashoffset: 50;
      animation: draw-line 0.3s ease-in 2.2s forwards;
    }
    .path-cut {
      opacity: 0;
      transform-origin: 110px 40px;
      will-change: transform, opacity;
      animation: break-and-fall 0.6s cubic-bezier(0.550, 0.085, 0.680, 0.530) 2.5s forwards;
    }
    .slash-effect {
      opacity: 0;
      will-change: transform, opacity;
      animation: flash-slash 0.3s ease-out 2.45s forwards;
    }
    @keyframes tracking-in {
      0% { letter-spacing: 0.5em; opacity: 0; }
      40% { opacity: 0.6; }
      100% { letter-spacing: normal; opacity: 1; }
    }
    @keyframes fade-in-up {
      0% { transform: translateY(20px); opacity: 0; }
      100% { transform: translateY(0); opacity: 1; }
    }
    @keyframes fade-in { to { opacity: 1; } }
    @keyframes draw-line { to { stroke-dashoffset: 0; } }
    @keyframes flash-slash {
      0% { opacity: 0; transform: scale(0.5) translate(-10px, 10px); }
      50% { opacity: 1; transform: scale(1.3) translate(0, 0); }
      100% { opacity: 0; transform: scale(1.5) translate(10px, -10px); }
    }
    @keyframes break-and-fall {
      0% { opacity: 1; transform: rotate(0) translate(0, 0); }
      100% { opacity: 0; transform: rotate(45deg) translate(20px, 60px); }
    }
    .auth-sheet-enter main .block-container { animation: authSlideUp 0.42s ease-out; }
    @keyframes authSlideUp { from { transform: translateY(72%); opacity: 0.65; } to { transform: translateY(0); opacity: 1; } }
    .auth-soc-row button { height: 48px !important; font-weight: 700 !important; border-radius: 12px !important; }
    .auth-mark-google + div button {
      background: #ffffff !important; color: #3c4043 !important; border: 1px solid #dadce0 !important; }
    .auth-mark-naver + div button {
      background: #03C75A !important; color: #fff !important; border: none !important; }
    .auth-mark-kakao + div button {
      background: #FEE500 !important; color: #191919 !important; border: none !important; }
    /* KR 단일: Facebook 버튼 제거 */
    .auth-terms-panel { border: 1px solid #e0e0e0; border-radius: 12px; padding: 0.75rem; background: #fafafa; max-height: 220px; overflow-y: auto; margin-top: 0.35rem; }
    </style>
    """,
        unsafe_allow_html=True,
    )

    # 스플래시 시 헤더/푸터 숨김
    if not st.session_state.get("auth_splash_done"):
        st.components.v1.html(
            """
        <script>
        try { window.parent.document.body.classList.add("auth-login-splash"); } catch(e) {}
        </script>
        """,
            height=0,
        )
    else:
        st.components.v1.html(
            """
        <script>
        try { window.parent.document.body.classList.remove("auth-login-splash"); } catch(e) {}
        </script>
        """,
            height=0,
        )

    # ---------- 약관 동의 화면 (소셜 클릭 후) ----------
    if st.session_state.get("auth_phase") == "terms" and st.session_state.get("pending_social_provider"):
        prov = st.session_state["pending_social_provider"]
        st.markdown(f"### {_t['terms_modal_title']}")
        if st.button(_t["auth_back"], key="terms_back"):
            st.session_state["auth_phase"] = "sheet"
            st.session_state["pending_social_provider"] = None
            for x in ("terms_cb_all", "terms_cb_tos", "terms_cb_privacy"):
                st.session_state.pop(x, None)
            st.rerun()

        agree_all = st.checkbox(_t["terms_agree_all"], key="terms_cb_all")
        with st.expander(_t.get("terms_expander_tos", _t["terms_required_tos"]), expanded=False):
            st.markdown(_load_legal_markdown("terms", _lg))
        with st.expander(_t.get("terms_expander_privacy", _t["terms_required_privacy"]), expanded=False):
            st.markdown(_load_legal_markdown("privacy", _lg))

        if agree_all:
            cb_tos = True
            cb_priv = True
            st.caption("✓ " + _t["terms_required_tos"] + " / " + _t["terms_required_privacy"])
        else:
            cb_tos = st.checkbox(_t["terms_required_tos"] + " — " + _t.get("terms_continue_btn", ""), key="terms_cb_tos")
            cb_priv = st.checkbox(_t["terms_required_privacy"], key="terms_cb_privacy")

        if st.button(_t["terms_continue_btn"], type="primary", use_container_width=True, key="terms_submit"):
            if not (cb_tos and cb_priv):
                st.error(_t["terms_must_check"])
            else:
                st.session_state["terms_accepted_provider"] = prov
                decision = handle_social_login(prov)
                st.session_state["auth_phase"] = "sheet"
                st.session_state["pending_social_provider"] = None
                if decision.get("action") == "oauth_google":
                    st.session_state["proceed_google_oauth"] = True
                    st.rerun()
                elif decision.get("action") == "stub":
                    pname = str(decision.get("provider", prov) or "").title()
                    st.session_state["auth_flash_msg"] = get_text(_lg, "social_provider_stub", provider=pname)
                st.rerun()

        st.stop()

    # ---------- 게스트 확정 ----------
    if st.session_state.get("auth_guest_step"):
        st.info(f"{_t['guest_info_title']}\n\n{_t['guest_info_body']}", icon="🚀")
        if st.button(_t["guest_confirm_btn"], type="primary", use_container_width=True):
            st.session_state["logged_in"] = True
            st.session_state["user_id"] = "guest_user_demo"
            st.session_state["login_type"] = "guest"
            st.session_state["auth_guest_step"] = False
            st.rerun()
        if st.button(_t["auth_back"], key="guest_back"):
            st.session_state["auth_guest_step"] = False
            st.rerun()
        st.stop()

    # ---------- 스플래시 (첫 진입) ----------
    if not st.session_state.get("auth_splash_done"):
        st.markdown(
            """
            <div class="splash-container">
              <div class="splash-title">혈당스캐너 AI</div>
              <div class="splash-subtitle-line1">같은 음식인데 결과는 다르다</div>
              <div class="splash-subtitle-line2">먹는 순서가 바꾸는 혈당 변화</div>
              <div class="spike-crash-animation">
                <svg viewBox="0 0 200 100" width="100%" height="120" class="real-spike-svg" aria-hidden="true">
                  <g class="bg-grid" stroke="#e0e0e0" stroke-width="1" stroke-dasharray="4 4">
                    <line x1="0" y1="20" x2="200" y2="20" />
                    <line x1="0" y1="50" x2="200" y2="50" />
                    <line x1="0" y1="80" x2="200" y2="80" />
                  </g>
                  <path class="path-base" d="M 10,80 L 90,80" stroke="#2ecc71" stroke-width="6" stroke-linecap="round" fill="none" />
                  <path class="path-rise" d="M 90,80 L 110,40" stroke="#e74c3c" stroke-width="6" stroke-linecap="round" fill="none" />
                  <path class="path-cut" d="M 110,40 L 130,0 L 150,80" stroke="#e74c3c" stroke-width="6" stroke-linecap="round" stroke-linejoin="round" fill="none" />
                  <line class="slash-effect" x1="80" y1="60" x2="150" y2="10" stroke="#ffffff" stroke-width="8" stroke-linecap="round" />
                </svg>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown("<div style='height:18vh;'></div>", unsafe_allow_html=True)
        if st.button(_t.get("splash_start_btn", "시작하기"), type="primary", use_container_width=True, key="splash_start"):
            st.session_state["auth_splash_done"] = True
            st.session_state["auth_sheet_open"] = True
            st.session_state["auth_phase"] = "sheet"
            st.rerun()
        st.stop()

    # ---------- 슬라이드업 느낌의 로그인 시트 ----------
    if st.session_state.get("auth_sheet_open") and not st.session_state.get("auth_guest_step"):
        st.components.v1.html(
            """
        <script>
        try {
          var m = window.parent.document.querySelector("main");
          if (m && !m.classList.contains("auth-sheet-enter")) {
            m.classList.add("auth-sheet-enter");
            setTimeout(function(){ try { m.classList.remove("auth-sheet-enter"); } catch(e) {} }, 600);
          }
        } catch(e) {}
        </script>
        """,
            height=0,
        )

    _flash = st.session_state.pop("auth_flash_msg", None)
    if _flash:
        st.warning(_flash)

    # 로그인 화면(미니멀): 상단 SVG 로고 + 중앙 정렬
    st.markdown(
        """
        <div style="text-align:center;margin:0 auto 10px auto;max-width:520px;">
          <div style="width:120px;height:120px;margin:0 auto 10px auto;">
            <svg viewBox="0 0 120 120" width="120" height="120" aria-hidden="true">
              <defs>
                <linearGradient id="g0" x1="0" y1="0" x2="1" y2="1">
                  <stop offset="0" stop-color="#2ecc71"/>
                  <stop offset="1" stop-color="#e74c3c"/>
                </linearGradient>
              </defs>
              <circle cx="60" cy="60" r="48" fill="none" stroke="rgba(134,204,133,0.18)" stroke-width="6"/>
              <path d="M 18 66 L 34 58 L 48 62 L 62 44 L 76 52 L 92 40" fill="none" stroke="url(#g0)" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/>
              <path d="M 18 66 L 34 58 L 48 62 L 62 44 L 76 52 L 92 40"
                    fill="none" stroke="url(#g0)" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"
                    stroke-dasharray="220" stroke-dashoffset="220"
                    style="animation: authDraw 1.2s ease-out forwards;"/>
              <style>
                @keyframes authDraw { to { stroke-dashoffset: 0; } }
              </style>
            </svg>
          </div>
          <div style="font-weight:900;font-size:1.25rem;letter-spacing:-0.02em;">{LOGIN_TITLE}</div>
          <div style="font-size:0.95rem;color:#86cc85;font-weight:700;margin-top:6px;">혈당 관리 시작</div>
        </div>
        """.replace("{LOGIN_TITLE}", html_module.escape(_t.get("login_sheet_title", ""))),
        unsafe_allow_html=True,
    )

    st.markdown('<div class="auth-soc-row">', unsafe_allow_html=True)
    _is_ko = _lg == "KO"
    if _is_ko:
        st.markdown('<div class="auth-mark-google"></div>', unsafe_allow_html=True)
        if st.button(_t["social_google_ko"], key="soc_ko_g", use_container_width=True):
            st.session_state["pending_social_provider"] = "google"
            st.session_state["auth_phase"] = "terms"
            st.rerun()
        st.markdown('<div class="auth-mark-naver"></div>', unsafe_allow_html=True)
        if st.button(_t["social_naver_ko"], key="soc_ko_n", use_container_width=True):
            st.session_state["pending_social_provider"] = "naver"
            st.session_state["auth_phase"] = "terms"
            st.rerun()
        st.markdown('<div class="auth-mark-kakao"></div>', unsafe_allow_html=True)
        if st.button(_t["social_kakao_ko"], key="soc_ko_k", use_container_width=True):
            st.session_state["pending_social_provider"] = "kakao"
            st.session_state["auth_phase"] = "terms"
            st.rerun()
    # KR 단일: 해외 소셜(예: Facebook) 제거
    st.markdown("</div>", unsafe_allow_html=True)

    st.caption(_t.get("or_social", ""))
    if st.button(_t.get("guest_entry_link", "Guest"), key="guest_entry"):
        st.session_state["auth_guest_step"] = True
        st.rerun()

    with st.expander(_t.get("auth_email_expand", "Email")):
        c1, c2, c3 = st.columns(3)
        with c1:
            if st.button(t["btn_login"], type="primary" if st.session_state["auth_mode"] == "login" else "secondary", use_container_width=True):
                st.session_state["auth_mode"] = "login"
                st.rerun()
        with c2:
            if st.button(t["btn_signup"], type="primary" if st.session_state["auth_mode"] == "signup" else "secondary", use_container_width=True):
                st.session_state["auth_mode"] = "signup"
                st.rerun()
        with c3:
            pass
        if st.session_state["auth_mode"] in ("login", "signup"):
            mode_text = t["btn_login"] if st.session_state["auth_mode"] == "login" else t["btn_signup"]
            submit_label = t["auth_submit_login"] if st.session_state["auth_mode"] == "login" else t["auth_submit_signup"]
            with st.form("auth_form_modern"):
                st.markdown(f"### {mode_text}")
                email = st.text_input("", placeholder=t["auth_email_placeholder"])
                email_valid = bool(email and ("@" in email))
                if email and not email_valid:
                    st.caption("🔴 올바른 이메일 형식을 입력해 주세요.")
                pwd = st.text_input("", type="password", placeholder=t["auth_pwd_placeholder"])
                submitted = st.form_submit_button(submit_label, type="primary", use_container_width=True)
                if submitted:
                    if not email_valid or not pwd:
                        st.error("형식이 틀렸습니다. 이메일과 비밀번호를 다시 확인해 주세요.")
                    else:
                        with st.spinner("인증 중..."):
                            success, res = pyrebase_auth(
                                email,
                                pwd,
                                "login" if st.session_state["auth_mode"] == "login" else "signup",
                            )
                        if success:
                            st.session_state["logged_in"] = True
                            st.session_state["user_id"] = res.get("localId", f"user_{email}")
                            st.session_state["user_email"] = email
                            st.session_state["login_type"] = "email"
                            st.rerun()
                        else:
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
                                st.error(f"{get_text(_lg, 'err_auth_failed', msg=code)} (코드: {code})")
                            if "OPERATION_NOT_ALLOWED" in upper_code:
                                st.error(
                                    "Firebase 콘솔 → Authentication → Email/Password 활성화가 필요합니다."
                                )

    st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)
    st.stop()


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
    """오늘 요약: daily_summaries/{date_key} 단일 문서 기반 (대시보드 경량 조회)."""
    if not uid:
        return {"avg_glucose": None, "latest_glucose": None, "total_carbs": 0, "meal_count": 0, "avg_spike": 0}
    try:
        s = get_daily_summary(uid, date_key)
        avg_spike = int(s.get("avg_spike") or 0)
        return {
            "avg_glucose": avg_spike if avg_spike > 0 else None,
            "latest_glucose": avg_spike if avg_spike > 0 else None,
            "total_carbs": int(s.get("total_carbs") or 0),
            "meal_count": int(s.get("meal_count") or 0),
            "avg_spike": avg_spike,
        }
    except Exception as e:
        sys.stderr.write(f"[get_today_summary] {e}\n")
        return {"avg_glucose": None, "latest_glucose": None, "total_carbs": 0, "meal_count": 0, "avg_spike": 0}


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
        import pytz
        db = _get_firestore_db()
        uid = str(uid)
        col = db.collection("users").document(uid).collection("glucose")
        docs = list(col.order_by("timestamp", direction=firestore.Query.DESCENDING).limit(n).stream())
        out = []
        for d in docs:
            data = d.to_dict()
            ts = data.get("timestamp")
            if hasattr(ts, "isoformat"):
                # 진단 표시용: UTC → 한국 시간으로 변환해 사람이 보는 값과 맞춥니다.
                seoul = pytz.timezone("Asia/Seoul")
                try:
                    ts_k = ts.astimezone(seoul)
                except Exception:
                    ts_k = ts
                ts_str = ts_k.isoformat()
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

# Native Bottom Bar (HTML 데코 + 투명 st.button 오버레이)
if menu_key == "scanner":
    with st.container():
        st.markdown('<div class="bottom-bar-anchor"></div>', unsafe_allow_html=True)
        _stage = st.session_state.get("app_stage", "main")
        _login_type = st.session_state.get("login_type")
        _is_guest = _login_type == "guest"

        if _stage == "main":
            c_home, c_record, c_capture, c_glucose, c_settings = st.columns(5)

            with c_home:
                st.markdown(
                    '<div class="bottom-tab-decor">🏠<div style="font-size:12px;font-weight:700;">홈</div></div>',
                    unsafe_allow_html=True,
                )
                st.button("", use_container_width=True, key="bb_tab_home", disabled=True)

            with c_record:
                st.markdown(
                    '<div class="bottom-tab-decor">📊<div style="font-size:12px;font-weight:700;">기록</div></div>',
                    unsafe_allow_html=True,
                )
                if st.button("", use_container_width=True, key="bb_tab_record"):
                    st.session_state["nav_menu"] = "history"
                    st.rerun()

            with c_capture:
                st.markdown(
                    '<div class="bottom-tab-decor">📸<div style="font-size:12px;font-weight:700;">촬영</div></div>',
                    unsafe_allow_html=True,
                )
                if st.button("", use_container_width=True, key="bb_tab_capture"):
                    st.session_state["current_page"] = "diet_scan"
                    st.session_state["app_stage"] = "main"
                    st.rerun()

            with c_glucose:
                st.markdown(
                    '<div class="bottom-tab-decor">🩹<div style="font-size:12px;font-weight:700;">혈당</div></div>',
                    unsafe_allow_html=True,
                )
                if st.button("", use_container_width=True, key="bb_tab_glucose"):
                    st.session_state["current_page"] = "glucose_input"
                    st.session_state["app_stage"] = "main"
                    st.rerun()

            with c_settings:
                st.markdown(
                    '<div class="bottom-tab-decor">⚙️<div style="font-size:12px;font-weight:700;">설정</div></div>',
                    unsafe_allow_html=True,
                )
                if st.button("", use_container_width=True, key="bb_tab_settings"):
                    st.session_state["current_page"] = "settings"
                    st.session_state["app_stage"] = "main"
                    st.rerun()

        elif _stage == "result":
            c_save, c_retake = st.columns(2)

            with c_save:
                st.markdown(
                    '<div class="bottom-tab-decor">💾<div style="font-size:12px;font-weight:700;">기록하기</div></div>',
                    unsafe_allow_html=True,
                )
                if st.button("", use_container_width=True, key="bb_tab_save", type="primary", disabled=_is_guest):
                    st.session_state["meal_save_trigger"] = True
                    st.session_state["retake_dialog_open"] = False
                    st.rerun()

            with c_retake:
                st.markdown(
                    '<div class="bottom-tab-decor">📸<div style="font-size:12px;font-weight:700;">다시 촬영</div></div>',
                    unsafe_allow_html=True,
                )
                if st.button("", use_container_width=True, key="bb_tab_retake"):
                    st.session_state["retake_dialog_open"] = True
                    st.session_state["meal_save_trigger"] = False
                    st.rerun()

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
    if "vision_analysis_status" not in st.session_state:
        st.session_state["vision_analysis_status"] = "idle"

    API_KEY = _get_secret("GEMINI_API_KEY")
    if not API_KEY:
        st.error(t["gemini_key_error"])
        st.stop()
    client = genai.Client(api_key=API_KEY)

    # ── 이탈 방지 모달: 분석 결과에서 "새 식단 촬영" 시 경고 ──
    @st.dialog("⚠️ 저장하지 않고 이동하시겠습니까?")
    def confirm_retake_dialog():
        st.write("아직 식단을 기록하지 않았습니다. 이대로 새 사진을 촬영하면 현재 분석된 혈당 스파이크 데이터가 모두 사라집니다.")
        c_left, c_right = st.columns(2)
        with c_left:
            if st.button("아니요, 돌아가서 저장할게요", key="retake_cancel"):
                st.session_state["retake_dialog_open"] = False
        with c_right:
            if st.button("네, 삭제하고 새로 촬영합니다", key="retake_confirm", type="primary"):
                # 분석 상태/이미지/결과 정리
                st.session_state["current_analysis"] = None
                st.session_state["current_img"] = None
                st.session_state["vision_analysis_status"] = "idle"
                st.session_state["meal_save_trigger"] = False
                st.session_state["meal_save_in_progress"] = False
                st.session_state["retake_dialog_open"] = False
                st.session_state["app_stage"] = "main"
                st.session_state["current_page"] = "diet_scan"
                if "uploader_key" in st.session_state:
                    st.session_state["uploader_key"] += 1
                else:
                    st.session_state["uploader_key"] = 0
                st.rerun()

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
            # 1️⃣ 메인 포털: 환영 인사 + (계정) 오늘의 요약 대시보드 + 액션 그리드
            if not is_guest:
                st.markdown(t.get("main_welcome_motivation", "### 🌞 오늘 하루도 완벽한 방어를 응원합니다!"))

            title_parts = (t.get("description") or "📈|혈당 스파이크 방지|올바른 섭취 순서").split("|")
            st.markdown(f"""
                <div style="text-align: center; margin-top: 10px; margin-bottom: 1.2vh;">
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
                    st.info(get_text("KO", "guest_remaining", n=total_remaining))

                # 오늘의 요약: Firestore(한국 당일) 실시간 조회 → 2x2 메트릭 + 혈당 게이지
                _uid_main = st.session_state.get("user_id")
                if (not is_guest) and _uid_main:
                    import pytz
                    import plotly.graph_objects as go

                    _seoul = pytz.timezone("Asia/Seoul")
                    _date_key = datetime.now(_seoul).strftime("%Y-%m-%d")
                    _cached_dash = st.session_state.get("daily_summary_today")
                    _cached_key = st.session_state.get("daily_summary_today_key")
                    if isinstance(_cached_dash, dict) and _cached_key == _date_key:
                        _dash = dict(_cached_dash)
                    else:
                        _dash = get_today_summary(_uid_main, _date_key)
                        st.session_state["daily_summary_today"] = dict(_dash)
                        st.session_state["daily_summary_today_key"] = _date_key
                    _avg_g = _dash.get("avg_glucose")
                    _latest_g = _dash.get("latest_glucose")
                    _total_c = int(_dash.get("total_carbs") or 0)
                    _meal_n = int(_dash.get("meal_count") or 0)

                    st.markdown(f"#### {t.get('dash_today_title', '오늘의 요약')}")
                    m1, m2 = st.columns(2)
                    with m1:
                        st.metric(
                            t.get("dash_metric_avg_glucose", "오늘 평균 혈당"),
                            f"{_avg_g} mg/dL" if _avg_g is not None else t.get("dash_no_record", "기록 없음"),
                        )
                    with m2:
                        st.metric(
                            t.get("dash_metric_total_carbs", "오늘 총 탄수화물"),
                            f"{_total_c} g",
                        )
                    m3, m4 = st.columns(2)
                    with m3:
                        st.metric(
                            t.get("dash_metric_meals", "오늘 식단 기록"),
                            f"{_meal_n}회",
                        )
                    with m4:
                        st.metric(
                            t.get("dash_metric_latest_glucose", "최근 측정 혈당"),
                            f"{_latest_g} mg/dL" if _latest_g is not None else t.get("dash_no_record", "기록 없음"),
                        )

                    if _latest_g is not None:
                        _hi = max(250, int(_latest_g) + 40, 300)
                        _fig_g = go.Figure(
                            go.Indicator(
                                mode="gauge+number",
                                value=float(_latest_g),
                                title={
                                    "text": t.get("dash_gauge_title", "혈당 계기판"),
                                    "font": {"size": 16},
                                },
                                number={"suffix": " mg/dL", "font": {"size": 34}},
                                gauge={
                                    "axis": {"range": [40, _hi], "tickwidth": 1},
                                    "bar": {"color": "#2c3e50"},
                                    "bgcolor": "white",
                                    "borderwidth": 1,
                                    "bordercolor": "#ecf0f1",
                                    "steps": [
                                        {"range": [40, 90], "color": "#3498db"},
                                        {"range": [90, 140], "color": "#2ecc71"},
                                        {"range": [140, _hi], "color": "#e74c3c"},
                                    ],
                                    "threshold": {
                                        "line": {"color": "#111", "width": 2},
                                        "thickness": 0.8,
                                        "value": float(_latest_g),
                                    },
                                },
                            )
                        )
                        _fig_g.update_layout(
                            margin=dict(l=8, r=8, t=48, b=8),
                            height=280,
                            paper_bgcolor="rgba(0,0,0,0)",
                        )
                        st.caption(t.get("dash_gauge_subtitle", "가장 최근 측정값 (오늘)"))
                        st.plotly_chart(_fig_g, use_container_width=True, config={"displayModeBar": False})
                    else:
                        st.caption(t.get("dash_gauge_empty", "오늘 측정한 혈당이 없어 계기판을 표시할 수 없습니다."))

                    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

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
                st.info(get_text("KO", "guest_remaining", n=total_remaining))
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
                st.caption("📊 지금 바로 **리포트**에서 방금 저장한 혈당 그래프를 확인할 수 있습니다.")
                if st.button("리포트로 이동", key="btn_glucose_go_report", use_container_width=True):
                    st.session_state["open_glucose"] = False
                    st.session_state["current_page"] = "report"
                    st.session_state["glucose_saved_portal"] = False
                    st.rerun()
            else:
                st.info(t.get("login_heading", "로그인 후 혈당을 기록할 수 있습니다."))

        elif st.session_state.get("current_page") == "report":
            # 리포트 전용 페이지: 탭 + Plotly
            if st.session_state.get("login_type") == "google" and st.session_state.get("user_id"):
                uid_r = st.session_state["user_id"]
                st.markdown(f"### 📊 {t.get('report_section_title', '나의 혈당 관리 리포트')}")
                tab_d, tab_w, tab_m, tab_mf = st.tabs([
                    t.get("glucose_tab_daily", "일간"),
                    t.get("glucose_tab_weekly", "주간"),
                    t.get("glucose_tab_monthly", "월간"),
                    t.get("glucose_tab_monthly_fasting_stats", "월별 평균 공복혈당 통계"),
                ])
                from datetime import timedelta
                import pytz
                _seoul_tz = pytz.timezone("Asia/Seoul")
                now_utc = datetime.now(timezone.utc)
                now_kr = now_utc.astimezone(_seoul_tz)

                def _render_glucose_tab(start, end, tab_scope_key):
                    glucose_list, meals_list = get_glucose_meals_cached(uid_r, start.isoformat(), end.isoformat())

                    # 조회 기간 내 데이터가 하나도 없을 때는, 사용자가 방금 입력한 값이라도 바로 보이도록
                    # 예외적으로 "최근 혈당 5건"을 가져와서 그래프에 사용한다.
                    if not glucose_list and not meals_list:
                        fallback = _get_glucose_last_n(uid_r, 5)
                        if fallback:
                            import pytz
                            seoul = pytz.timezone("Asia/Seoul")
                            _tmp = []
                            for row in fallback:
                                ts_str = row.get("timestamp")
                                try:
                                    ts_dt = datetime.fromisoformat(str(ts_str).replace("Z", "+00:00"))
                                except Exception:
                                    continue
                                if ts_dt.tzinfo is None:
                                    ts_dt = seoul.localize(ts_dt)
                                _tmp.append({
                                    "timestamp": ts_dt.astimezone(timezone.utc),
                                    "type": row.get("type", ""),
                                    "value": row.get("value", 0),
                                })
                            if _tmp:
                                glucose_list = _tmp
                                st.caption("※ 조회 기간에는 데이터가 없어서, 예외적으로 최근 혈당 5건을 기준으로 그래프를 표시합니다.")

                    # 주간/월간 탭에서는 공복혈당만 사용
                    if tab_scope_key in ("weekly", "monthly") and glucose_list:
                        glucose_list = [g for g in glucose_list if g.get("type") == "fasting"]

                    # 기본 지표 (모바일 2x2 그리드)
                    avg_c = sum(m.get("total_carbs", 0) for m in meals_list) / len(meals_list) if meals_list else 0
                    avg_g = sum(g.get("value", 0) for g in glucose_list) / len(glucose_list) if glucose_list else 0
                    _total_c_period = sum(m.get("total_carbs", 0) for m in meals_list)
                    _mr1a, _mr1b = st.columns(2)
                    with _mr1a:
                        st.metric(t.get("report_meals_count", "식단 수"), len(meals_list))
                    with _mr1b:
                        st.metric(t.get("report_avg_carbs", "평균 탄수화물"), f"{avg_c:.0f}g")
                    _mr2a, _mr2b = st.columns(2)
                    with _mr2a:
                        st.metric(t.get("glucose_value_mg", "혈당 (mg/dL)") + " avg", f"{avg_g:.0f}" if glucose_list else "-")
                    with _mr2b:
                        st.metric(t.get("report_period_carbs_total", "기간 탄수화물 합"), f"{_total_c_period:.0f}g")

                    if glucose_list or meals_list:
                        import plotly.graph_objects as go
                        from plotly.subplots import make_subplots
                        import statistics

                        # --- 그룹별 평균 혈당 및 탄수화물 합계 집계 ---
                        ohlc = defaultdict(list)
                        volume = defaultdict(float)

                        def _group_key(ts):
                            if ts is None:
                                return None
                            if hasattr(ts, "astimezone"):
                                ts_kr = ts.astimezone(_seoul_tz)
                            else:
                                ts_kr = ts
                            if tab_scope_key == "daily":
                                # 일간: 시간 단위까지 그대로 사용 (시계열)
                                return ts_kr
                            d = ts_kr.date()
                            if tab_scope_key == "weekly":
                                iso = d.isocalendar()
                                return (iso.year, iso.week)
                            else:
                                return (d.year, d.month)

                        # 혈당 값 모으기
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

                        # 정렬된 x 축 및 평균 혈당/탄수화물 배열 구성
                        sorted_keys = sorted(ohlc.keys())
                        if not sorted_keys:
                            st.info(t.get("report_no_data", "해당 기간 기록이 없습니다."))
                        else:
                            x = []
                            y_vals = []
                            vols = []

                            all_values_for_stats = []

                            for k in sorted_keys:
                                items = sorted(ohlc[k], key=lambda x: x[0])
                                vals = [v for _, v in items]
                                avg_v = statistics.mean(vals)
                                x.append(k)
                                y_vals.append(avg_v)
                                vols.append(volume.get(k, 0.0))
                                all_values_for_stats.extend(vals)

                            colors = ["#e74c3c" if v > 140 else "#2980b9" for v in y_vals]
                            texts = [f"{v:.0f}" for v in y_vals]

                            fig = make_subplots(
                                rows=2,
                                cols=1,
                                shared_xaxes=True,
                                row_heights=[0.7, 0.3],
                                vertical_spacing=0.05,
                            )

                            # 상단: 혈당 꺾은선 + 마커 + 텍스트
                            fig.add_trace(
                                go.Scatter(
                                    x=x,
                                    y=y_vals,
                                    mode="lines+markers+text",
                                    line=dict(color="#34495e", width=2),
                                    marker=dict(color=colors, size=8),
                                    text=texts,
                                    textposition="top center",
                                    name=t.get("glucose_value_mg", "혈당"),
                                ),
                                row=1,
                                col=1,
                            )

                            # Safe Zone: 90~140
                            fig.add_hrect(
                                y0=90,
                                y1=140,
                                fillcolor="#2ecc71",
                                opacity=0.12,
                                line_width=0,
                                row=1,
                                col=1,
                            )

                            # 하단: 탄수화물 막대
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

                            # X축 포맷
                            if tab_scope_key == "daily":
                                fig.update_xaxes(tickformat="%H:%M", row=2, col=1)
                            elif tab_scope_key == "weekly":
                                fig.update_xaxes(tickformat="%m/%d", row=2, col=1)
                            else:
                                fig.update_xaxes(tickformat="%Y-%m", row=2, col=1)

                            fig.update_layout(
                                margin=dict(l=10, r=10, t=28, b=48),
                                height=360,
                                xaxis_tickangle=-45,
                                autosize=True,
                                showlegend=True,
                                legend=dict(
                                    orientation="h",
                                    yanchor="top",
                                    y=-0.14,
                                    x=0.5,
                                    xanchor="center",
                                    font=dict(size=9),
                                    bgcolor="rgba(248,249,250,0.92)",
                                    borderwidth=0,
                                ),
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
                    # 일간: 날짜 선택 (기본값: 오늘)
                    sel_date = st.date_input("일간 기준 날짜", value=now_kr.date(), key="report_daily_date")
                    start_d_kr = datetime.combine(sel_date, datetime.min.time()).replace(tzinfo=_seoul_tz)
                    end_d_kr = datetime.combine(sel_date, datetime.max.time()).replace(tzinfo=_seoul_tz)
                    start_d = start_d_kr.astimezone(timezone.utc)
                    end_d = end_d_kr.astimezone(timezone.utc)
                    _render_glucose_tab(start_d, end_d, "daily")

                with tab_w:
                    # 주간: 시작일 선택 → 종료일 = 시작일 + 7일
                    default_start_w = now_kr.date() - timedelta(days=6)
                    sel_start_w = st.date_input("주간 시작일", value=default_start_w, key="report_weekly_start")
                    start_w_kr = datetime.combine(sel_start_w, datetime.min.time()).replace(tzinfo=_seoul_tz)
                    end_w_kr = start_w_kr + timedelta(days=7)
                    start_w = start_w_kr.astimezone(timezone.utc)
                    end_w = end_w_kr.astimezone(timezone.utc)
                    _render_glucose_tab(start_w, end_w, "weekly")

                with tab_m:
                    # 월간: 연/월 선택 (기본값: 이번 달)
                    current_year = now_kr.year
                    current_month = now_kr.month
                    years = list(range(current_year - 5, current_year + 1))
                    cols_m = st.columns(2)
                    with cols_m[0]:
                        sel_year = st.selectbox("연도", options=years, index=len(years) - 1, key="report_monthly_year")
                    with cols_m[1]:
                        sel_month = st.selectbox("월", options=list(range(1, 13)), index=current_month - 1, key="report_monthly_month")
                    start_m_kr = datetime(sel_year, sel_month, 1, tzinfo=_seoul_tz)
                    if sel_month == 12:
                        next_month_kr = datetime(sel_year + 1, 1, 1, tzinfo=_seoul_tz)
                    else:
                        next_month_kr = datetime(sel_year, sel_month + 1, 1, tzinfo=_seoul_tz)
                    end_m_kr = next_month_kr
                    start_m = start_m_kr.astimezone(timezone.utc)
                    end_m = end_m_kr.astimezone(timezone.utc)
                    _render_glucose_tab(start_m, end_m, "monthly")

                with tab_mf:
                    # 월별 평균 공복혈당 통계
                    import pytz as _pytz
                    seoul = _pytz.timezone("Asia/Seoul")
                    # 기간 선택: 퀵 버튼
                    mf_range = st.radio(
                        "기간",
                        options=["3m", "6m", "1y", "2y", "custom"],
                        format_func=lambda x: {
                            "3m": "최근 3개월",
                            "6m": "최근 6개월",
                            "1y": "최근 1년",
                            "2y": "최근 2년",
                            "custom": "직접 입력",
                        }.get(x, x),
                        horizontal=True,
                        key="report_monthly_fasting_range",
                    )
                    end_all_kr = now_kr.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                    if mf_range == "3m":
                        start_all_kr = (end_all_kr - timedelta(days=90)).replace(day=1)
                    elif mf_range == "6m":
                        start_all_kr = (end_all_kr - timedelta(days=180)).replace(day=1)
                    elif mf_range == "1y":
                        start_all_kr = (end_all_kr - timedelta(days=365)).replace(day=1)
                    elif mf_range == "2y":
                        start_all_kr = (end_all_kr - timedelta(days=730)).replace(day=1)
                    else:
                        c1, c2 = st.columns(2)
                        with c1:
                            custom_start = st.date_input("시작 연월", value=end_all_kr.date(), key="mf_custom_start")
                        with c2:
                            custom_end = st.date_input("종료 연월", value=end_all_kr.date(), key="mf_custom_end")
                        start_all_kr = datetime(custom_start.year, custom_start.month, 1, tzinfo=seoul)
                        end_all_kr = datetime(custom_end.year, custom_end.month, 1, tzinfo=seoul)
                    start_all = start_all_kr.astimezone(timezone.utc)
                    end_all = end_all_kr.astimezone(timezone.utc)

                    glucose_all, _meals_all = _get_glucose_and_meals(uid_r, start_all, end_all)
                    # 공복혈당만
                    fasting = [g for g in glucose_all if g.get("type") == "fasting"]
                    if not fasting:
                        st.info(t.get("report_no_data", "해당 기간 기록이 없습니다."))
                    else:
                        # 월별 평균
                        by_month = defaultdict(list)
                        for g in fasting:
                            ts = g.get("timestamp")
                            ts_kr = ts.astimezone(seoul) if hasattr(ts, "astimezone") else ts
                            y, m = ts_kr.year, ts_kr.month
                            by_month[(y, m)].append(g.get("value", 0))
                        keys = sorted(by_month.keys())
                        import statistics as _st
                        x = []
                        y_vals = []
                        for y, m in keys:
                            avg_v = _st.mean(by_month[(y, m)])
                            x.append(datetime(y, m, 1, tzinfo=seoul))
                            y_vals.append(avg_v)
                        colors = ["#e74c3c" if v > 140 else "#2980b9" for v in y_vals]
                        texts = [f"{v:.0f}" for v in y_vals]

                        import plotly.graph_objects as go
                        fig_mf = go.Figure()
                        fig_mf.add_trace(
                            go.Scatter(
                                x=x,
                                y=y_vals,
                                mode="lines+markers+text",
                                line=dict(color="#34495e", width=2),
                                marker=dict(color=colors, size=8),
                                text=texts,
                                textposition="top center",
                                name=t.get("glucose_fasting", "공복 혈당"),
                            )
                        )
                        fig_mf.add_hrect(
                            y0=90,
                            y1=140,
                            fillcolor="#2ecc71",
                            opacity=0.12,
                            line_width=0,
                        )
                        fig_mf.update_layout(
                            margin=dict(l=10, r=10, t=28, b=44),
                            height=340,
                            autosize=True,
                            showlegend=True,
                            legend=dict(
                                orientation="h",
                                yanchor="top",
                                y=-0.12,
                                x=0.5,
                                xanchor="center",
                                font=dict(size=9),
                                bgcolor="rgba(248,249,250,0.92)",
                                borderwidth=0,
                            ),
                        )
                        fig_mf.update_xaxes(tickformat="%y.%m")
                        fig_mf.update_yaxes(title_text=t.get("glucose_fasting", "공복 혈당") + " (mg/dL)")
                        st.plotly_chart(fig_mf, use_container_width=True, config=dict(responsive=True, displayModeBar=True))
            else:
                st.info(t.get("login_heading", "로그인 후 리포트를 볼 수 있습니다."))

        elif st.session_state.get("current_page") == "settings":
            # 설정 페이지: 언어, 목표, 로그아웃 (사이드바와 동일한 기능)
            st.subheader(t.get("btn_settings", "⚙️ 설정"))
            # KR 단일 타겟팅: 언어 설정 제거
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
        # main 단계와 분리되어 있어 게스트 여부를 여기서도 정의 (분석 실패 시 복구 로직용)
        is_guest = st.session_state.get("user_id") == "guest_user_demo"
        # 2페이지: 업로드 완료 & 분석 대기 페이지
        if st.button(t["btn_back_main"], key="btn_back_main_1", use_container_width=True):
            st.session_state['app_stage'] = 'main'
            st.session_state['current_page'] = 'main'
            st.session_state['current_img'] = None
            st.session_state["vision_analysis_status"] = "idle"
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
            st.session_state["vision_analysis_status"] = "running"
            import time
            import random
            
            max_retries = 3
            success = False
            last_err_msg = ""
            is_503 = False
            food_prompt, advice_prompt = get_analysis_prompt("KO")

            # Gemini 1.5 시리즈 폐기: gemini-2.5-flash → gemini-2.0-flash 만 사용 (google-genai SDK)
            _env_mm = os.environ.get("GEMINI_VISION_MODEL", "").strip()
            _model_candidates = []
            if _env_mm:
                _model_candidates.append(_env_mm)
            for _m in ("gemini-2.5-flash", "gemini-2.0-flash"):
                if _m not in _model_candidates:
                    _model_candidates.append(_m)

            for attempt in range(max_retries):
                try:
                    response = None
                    last_model_err = ""
                    for _mm_model in _model_candidates:
                        try:
                            try:
                                response = client.models.generate_content(
                                    model=_mm_model,
                                    contents=[food_prompt, st.session_state["current_img"]],
                                    config=gtypes.GenerateContentConfig(
                                        response_mime_type="application/json"
                                    ),
                                )
                            except Exception:
                                response = client.models.generate_content(
                                    model=_mm_model,
                                    contents=[food_prompt, st.session_state["current_img"]],
                                )
                            break
                        except Exception as _me:
                            last_model_err = str(_me)
                            # 모델 미지원/미존재는 다음 후보로 폴백
                            if "not found" in last_model_err.lower() or "not supported" in last_model_err.lower() or "NOT_FOUND" in last_model_err:
                                continue
                            raise
                    if response is None:
                        raise Exception(last_model_err or "No available Gemini multimodal model")

                    raw_text = (response.text or "").strip()
                    parsed_tuple = _parse_food_analysis_json_response(raw_text)
                    if not parsed_tuple:
                        _reset_vision_analysis_parse_error(is_guest, loading_placeholder)
                        success = True
                        break

                    sorted_items, total_carbs = parsed_tuple
                    if sorted_items:
                        # 혈당 스코어 계산
                        avg_gi = int(sum(i[1] for i in sorted_items) / len(sorted_items))
                        blood_sugar_score = min(100, avg_gi)
                        total_protein = sum(i[3] for i in sorted_items)
                        total_fat = sum((i[6] if len(i) > 6 else 0) for i in sorted_items)
                        total_kcal = sum((i[7] if len(i) > 7 else 0) for i in sorted_items)

                        # 소견 분석 (선택 언어로 응답하도록 prompts.get_advice_prompt 사용)
                        advice_res = None
                        last_model_err = ""
                        for _mm_model in _model_candidates:
                            try:
                                advice_res = client.models.generate_content(
                                    model=_mm_model,
                                    contents=[advice_prompt, st.session_state['current_img']]
                                )
                                break
                            except Exception as _me:
                                last_model_err = str(_me)
                                if "not found" in last_model_err.lower() or "not supported" in last_model_err.lower() or "NOT_FOUND" in last_model_err:
                                    continue
                                raise
                        if advice_res is None:
                            raise Exception(last_model_err or "No available Gemini model (advice)")

                        # 혈당 순서 가이드 엔진: 식이섬유 → 단백질 → 탄수화물
                        def _classify_bucket(name, gi, carbs, protein, fat):
                            n = (name or "").lower()
                            if any(k in n for k in ["salad","샐러드","나물","야채","채소","greens","spinach","lettuce","kimchi","김치","무침"]):
                                return "fiber"
                            if protein >= carbs and protein >= fat:
                                return "protein"
                            return "carb"
                        buckets = {"fiber": [], "protein": [], "carb": []}
                        for it in sorted_items:
                            # it: [name, gi, carbs, protein, color, order, fat?, kcal?]
                            name, gi, carbs, protein = it[0], it[1], it[2], it[3]
                            fat = it[6] if len(it) > 6 else 0
                            buckets[_classify_bucket(name, gi, carbs, protein, fat)].append(name)
                        order_comment = (
                            "이 식단은 "
                            f"{( ' · '.join(buckets['fiber']) if buckets['fiber'] else '식이섬유' )} "
                            "➡ "
                            f"{( ' · '.join(buckets['protein']) if buckets['protein'] else '단백질' )} "
                            "➡ "
                            f"{( ' · '.join(buckets['carb']) if buckets['carb'] else '탄수화물' )} "
                            "순서로 드시면 혈당 스파이크를 줄이는 데 도움이 됩니다!"
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
                            "advice": advice_res.text + "\n\n" + order_comment,
                            "raw_img": st.session_state['current_img'],
                            "blood_sugar_score": blood_sugar_score,
                            "total_carbs": total_carbs,
                            "total_protein": total_protein,
                            "total_fat": total_fat,
                            "total_kcal": total_kcal,
                            "avg_gi": avg_gi,
                        }
                        loading_placeholder.empty()
                        st.session_state["vision_analysis_status"] = "done"
                        st.session_state['app_stage'] = 'result'
                        success = True
                        st.rerun()
                        
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
                st.session_state["vision_analysis_status"] = "idle"
                # 에러로 인해 스캔이 실패했으므로, 게스트 유저인 경우 차감된 횟수를 1회 복구해줍니다.
                if is_guest and st.session_state['guest_usage_count'] > 0:
                    st.session_state['guest_usage_count'] -= 1
                    
                if is_503:
                    st.error(t["server_busy"])
                else:
                    st.error(get_text("KO", "analysis_error_generic", msg=last_err_msg))

    elif st.session_state['app_stage'] == 'result':
        # 세션 손실(다중 워커/타임아웃 등) 시 분석 결과가 없으면 메인으로 복귀
        if st.session_state.get('current_analysis') is None:
            st.session_state['app_stage'] = 'main'
            st.session_state['current_page'] = 'main'
            st.session_state['current_img'] = None
            st.session_state["vision_analysis_status"] = "idle"
            if 'uploader_key' in st.session_state:
                st.session_state['uploader_key'] += 1
            st.warning(t["session_reset_msg"])
            st.rerun()

        if st.button(t["btn_back_main_2"], key="btn_back_main_2", use_container_width=True):
            st.session_state['app_stage'] = 'main'
            st.session_state['current_page'] = 'main'
            st.session_state['current_img'] = None
            st.session_state['current_analysis'] = None
            st.session_state["vision_analysis_status"] = "idle"
            if 'uploader_key' in st.session_state:
                st.session_state['uploader_key'] += 1
            st.rerun()

        res = st.session_state['current_analysis']
        if st.session_state.get("retake_dialog_open"):
            confirm_retake_dialog()
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

        # ── 3. 혈당 스파이크 예측 바 + 하이브리드 경고 (한 컨테이너에 묶어서 시각적 덩어리화) ──
        with st.container():
            spike_label = t["spike_low"] if score <= 40 else t["spike_mid"] if score <= 65 else t["spike_high"]
            st.markdown(f"""
            <div style="background:white;border-radius:14px;padding:14px 14px 10px 14px;margin-bottom:6px;box-shadow:0 2px 8px rgba(0,0,0,0.06);border:1px solid #f0f0f0;">
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

            # 탄수화물 기반 예상 혈당 상승 하이브리드 경고 (그래프 바로 아래 밀착)
            try:
                _tc_for_spike = int(round(float(total_carbs)))
            except (TypeError, ValueError):
                _tc_for_spike = 0
            estimated_spike = int(round(_tc_for_spike * 2))
            if estimated_spike < 60:
                st.success(
                    "훌륭합니다! 식후 혈당이 완만하게 유지되는 착한 식단입니다. 마음 편히 즐기세요!"
                )
            elif estimated_spike < 120:
                st.warning(
                    "탄수화물이 꽤 포함되어 있습니다. 본격적인 식사 전, 샐러드나 나물 반찬을 한 입 먼저 드시면 혈당 곡선을 훨씬 부드럽게 만들 수 있습니다."
                )
            else:
                st.error(
                    "맛있는 대중 음식이지만 탄수화물 비중이 높아 혈당이 뛸 수 있습니다. 드시기 전에 주변 편의점에서 **감동란(계란), 스트링 치즈, 무가당 두유**를 곁들여 단백질 방어막을 쳐보세요!"
                )
            st.caption(
                "* 위 수치는 탄수화물 총량을 기반으로 한 단순 예측치이며, 개인의 대사량과 체질에 따라 다를 수 있습니다. 의학적 진단으로 사용될 수 없습니다."
            )
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

        # ── 7. 저장 실행 처리 (Bottom Bar에서 트리거) ──
        if st.session_state.get("login_type") != "guest" and st.session_state.get("meal_save_trigger"):
            uid = st.session_state.get("user_id")
            if not uid:
                st.toast("로그인된 사용자 정보가 없습니다.")
            else:
                st.session_state["meal_save_trigger"] = False
                st.session_state["meal_save_in_progress"] = True
                try:
                    import pytz

                    _seoul = pytz.timezone("Asia/Seoul")
                    now_utc = datetime.now(timezone.utc)
                    date_key = now_utc.astimezone(_seoul).strftime("%Y-%m-%d")
                    save_date = now_utc.astimezone(_seoul).strftime("%Y-%m-%d %H:%M")
                    save_date_utc = now_utc.isoformat()

                    estimated_spike = int(round(float(res.get("total_carbs", 0) or 0) * 2))
                    meal_data = {
                        "date": save_date,
                        "saved_at_utc": save_date_utc,
                        "sorted_items": res.get("sorted_items", []),
                        "advice": str(res.get("advice", "")),
                        "blood_sugar_score": int(res.get("blood_sugar_score", 0) or 0),
                        "total_carbs": int(res.get("total_carbs", 0) or 0),
                        "total_protein": int(res.get("total_protein", 0) or 0),
                        "total_fat": int(res.get("total_fat", 0) or 0),
                        "total_kcal": int(res.get("total_kcal", 0) or 0),
                        "avg_gi": int(res.get("avg_gi", 0) or 0),
                        "estimated_spike": estimated_spike,
                    }

                    with st.spinner("데이터를 안전하게 금고에 넣는 중입니다..."):
                        meal_id = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
                        image_url = upload_image_to_storage(uid, meal_id, res.get("raw_img"), max_width=800, quality=85)
                        meal_data["image_url"] = image_url
                        _saved_id = save_meal_and_summary(uid, date_key, meal_data)
                        meal_data["meal_id"] = _saved_id

                    # Optimistic update: 재조회 없이 메모리 대시보드 즉시 누적
                    _dash_local = st.session_state.get("daily_summary_today")
                    if not isinstance(_dash_local, dict) or st.session_state.get("daily_summary_today_key") != date_key:
                        _dash_local = {
                            "avg_glucose": None,
                            "latest_glucose": None,
                            "total_carbs": 0,
                            "meal_count": 0,
                            "avg_spike": 0,
                            "spike_sum": 0,
                        }
                    _dash_local["total_carbs"] = int(_dash_local.get("total_carbs", 0)) + int(meal_data["total_carbs"])
                    _dash_local["meal_count"] = int(_dash_local.get("meal_count", 0)) + 1
                    _dash_local["spike_sum"] = int(_dash_local.get("spike_sum", 0)) + int(estimated_spike)
                    _avg_spike = int(round(_dash_local["spike_sum"] / max(1, _dash_local["meal_count"])))
                    _dash_local["avg_spike"] = _avg_spike
                    _dash_local["avg_glucose"] = _avg_spike
                    _dash_local["latest_glucose"] = _avg_spike
                    st.session_state["daily_summary_today"] = _dash_local
                    st.session_state["daily_summary_today_key"] = date_key

                    st.session_state["app_stage"] = "main"
                    st.session_state["current_page"] = "main"
                    st.session_state["current_analysis"] = None
                    st.session_state["current_img"] = None
                    st.session_state["vision_analysis_status"] = "idle"
                    if "uploader_key" in st.session_state:
                        st.session_state["uploader_key"] += 1
                    get_today_summary.clear()
                    st.rerun()
                except Exception as e:
                    traceback.print_exc(file=sys.stderr)
                    st.error(f"저장 실패: {e}")
                finally:
                    st.session_state["meal_save_in_progress"] = False


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

    # st.expander: 이력 목록은 버튼 토글로 펼침 (CSS는 전역 <style>의 stExpander 규칙 적용)
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
            _lang = "KO"
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
