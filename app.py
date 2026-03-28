# -*- coding: utf-8 -*-
"""NutriSort AI - 한글 기본, UTF-8 소스·출력 통일."""
import sys
import os
import time
import json
import traceback
import urllib.parse
import html as html_module
import re
from collections import defaultdict
import statistics
import io
import base64
from PIL import Image
from datetime import datetime, timezone

from firebase_admin import storage as firebase_admin_storage

from translation import LANG_DICT, get_text, GOAL_INTERNAL_KEYS
from terms import TERMS_TOS, TERMS_PRIVACY, TERMS_HEALTH, TERMS_MARKETING, TERMS_CUSTOM_PRIV, TERMS_BIGDATA
from prompts import (
    get_analysis_prompt,
    PRE_MEAL_INSIGHTS_SYSTEM_PROMPT,
    PRE_MEAL_MENU_NAME_VISION_PROMPT,
    get_pre_meal_insights_user_prompt,
    POST_MEAL_FEEDBACK_SYSTEM_PROMPT,
    get_post_meal_feedback_user_prompt,
)
from firebase_db import (
    upload_image_to_storage,
    save_meal_and_summary,
    get_daily_summary,
    get_daily_pancreas_stress,
    save_daily_pancreas_stress,
    get_meal_feed,
    delete_meal_record,
    get_glucose_records,
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

# ══════════════════════════════════════════════════════════════════════════════
# ★ 최우선 처리 — Bottom Drawer 소셜 버튼 클릭 ?__auth=PROVIDER 감지
#   st.set_page_config 바로 아래에서 실행하여 다른 어떤 코드보다 먼저 처리.
#   이렇게 해야 localStorage 핸들러나 스플래시 렌더링이 먼저 실행되어
#   __auth 감지 코드 자체에 도달하지 못하는 데드락을 방지한다.
# ══════════════════════════════════════════════════════════════════════════════
_TOP_AUTH = st.query_params.get("__auth", "")
if _TOP_AUTH:
    try:
        st.cache_data.clear()
    except Exception:
        pass
    try:
        st.cache_resource.clear()
    except Exception:
        pass
    _TOP_INTENT = st.query_params.get("intent", "login")
    st.query_params.clear()                        # 즉시 제거 — 무한 루프 방지
    st.session_state["auth_splash_done"] = True
    st.session_state["auth_sheet_open"]  = True
    st.session_state["auth_mode"]        = _TOP_INTENT
    if _TOP_AUTH in ("google", "naver", "kakao"):
        st.session_state["pending_social_provider"] = _TOP_AUTH
        st.session_state["auth_phase"]              = "terms"
    else:  # email
        st.session_state["auth_phase"] = "sheet"
    st.rerun()                                     # 즉시 재렌더링 — 약관 or 이메일 폼
# ══════════════════════════════════════════════════════════════════════════════


def _reset_meal_feed_state():
    st.session_state["feed_items"] = []
    st.session_state["last_doc"] = None
    st.session_state["has_more"] = False
    st.session_state["meal_feed_uid"] = None
    st.session_state["meal_feed_hydrated_uid"] = None
    st.session_state["meal_feed_sort_field"] = None


def _ensure_pre_meal_state():
    """KST 기준 단일 dict — 추후 Firestore daily doc과 1:1 매핑 예정."""
    import pytz

    seoul = pytz.timezone("Asia/Seoul")
    today_kst = datetime.now(seoul).strftime("%Y-%m-%d")
    if "pre_meal" not in st.session_state:
        st.session_state["pre_meal"] = {
            "date_kst": today_kst,
            "meal_slot": "아침",
            "location": None,
            "menu_text": "",
            "step": 1,
            "pancreas_stress": 0.0,
            "mission_text": "",
            "analysis": "",
            "next_meal": "",
            # 식후 피드백 상태
            "post_meal_feedback": "",
            "post_meal_is_success": False,
            "post_meal_stress_change": 0,
        }
        return
    pm = st.session_state["pre_meal"]
    if pm.get("date_kst") != today_kst:
        pm["date_kst"] = today_kst
        pm["step"] = 1
        pm["mission_text"] = ""
        pm["analysis"] = ""
        pm["next_meal"] = ""
        pm["pancreas_stress"] = 0.0
        pm["post_meal_feedback"] = ""
        pm["post_meal_is_success"] = False
        pm["post_meal_stress_change"] = 0
        st.session_state.pop("pre_meal_pancreas_hydrated", None)
        st.session_state.pop("pre_meal_menu_img_hash", None)


def _ensure_pre_meal_owner_scope(uid):
    """user_id가 바뀌면 Firestore 하이드레이션 캐시 무효화. 게스트/비로그인은 로컬 점수 초기화."""
    slot = "pre_meal_owner_uid"
    prev = st.session_state.get(slot)
    if prev == uid:
        return
    st.session_state[slot] = uid
    st.session_state.pop("pre_meal_pancreas_hydrated", None)
    _ensure_pre_meal_state()
    pm = st.session_state["pre_meal"]
    if not uid or uid == "guest_user_demo":
        pm["pancreas_stress"] = 0.0


def _hydrate_pre_meal_pancreas_from_firestore(uid):
    """로그인(비게스트) 사용자: 오늘(KST) Firestore daily_summaries.pancreas_stress → 세션 (1회/일·uid)."""
    if not uid or uid == "guest_user_demo":
        return
    import pytz

    seoul = pytz.timezone("Asia/Seoul")
    today_kst = datetime.now(seoul).strftime("%Y-%m-%d")
    key = (str(uid), today_kst)
    if st.session_state.get("pre_meal_pancreas_hydrated") == key:
        return
    try:
        v = get_daily_pancreas_stress(uid, today_kst)
    except Exception:
        v = 0.0
    pm = st.session_state["pre_meal"]
    pm["pancreas_stress"] = min(100.0, max(0.0, float(v)))
    pm["date_kst"] = today_kst
    st.session_state["pre_meal_pancreas_hydrated"] = key


def _clamp_pancreas_stress_value(pm: dict) -> float:
    """췌장 피로도를 0~100으로 제한하고 세션에 반영."""
    v = float(pm.get("pancreas_stress") or 0)
    v = max(0.0, min(100.0, v))
    pm["pancreas_stress"] = v
    return v


def _render_pancreas_stress_gauge(pm: dict, t: dict) -> None:
    """식전 미션 블록 — 췌장 피로도 초소형 헬스 위젯 스타일 (Emerald 테마)."""
    score = _clamp_pancreas_stress_value(pm)
    ratio = score / 100.0 if score > 0 else 0.0
    emerald = "#10B981"
    if score <= 30:
        emoji_title = t.get("pre_meal_pancreas_comfort", "🌿 쾌적")
        sub = t.get("pre_meal_pancreas_comfort_sub", "인슐린 정상 가동 중")
        bar_color = emerald
        bar_bg = "rgba(16,185,129,0.12)"
        score_color = emerald
    elif score <= 70:
        emoji_title = t.get("pre_meal_pancreas_caution", "⚡ 주의")
        sub = t.get("pre_meal_pancreas_caution_sub", "혈당 롤러코스터 경고")
        bar_color = "#f59e0b"
        bar_bg = "rgba(245,158,11,0.12)"
        score_color = "#f59e0b"
    else:
        emoji_title = t.get("pre_meal_pancreas_danger", "🛑 휴식 필요")
        sub = t.get("pre_meal_pancreas_danger_sub", "췌장 파업 직전! 식이섬유 필수")
        bar_color = "#ef4444"
        bar_bg = "rgba(239,68,68,0.12)"
        score_color = "#ef4444"

    title = html_module.escape(t.get("pre_meal_pancreas_title", "췌장 피로도"))
    score_num = html_module.escape(f"{round(score):.0f}")
    emoji_esc = html_module.escape(emoji_title)
    sub_esc = html_module.escape(sub)

    st.markdown(
        f"""
<div class="pancreas-stress-gauge" style="margin:0 0 12px 0;padding:12px 14px;border-radius:20px;border:none;background:#ffffff;box-sizing:border-box;box-shadow:0 8px 24px rgba(0,0,0,0.08);">
  <div style="display:flex;flex-wrap:nowrap;align-items:flex-start;justify-content:space-between;gap:10px;">
    <div style="flex:1;min-width:0;">
      <div style="font-size:11px;font-weight:700;color:#64748b;letter-spacing:0.02em;text-transform:uppercase;">{title}</div>
      <div style="margin-top:4px;font-size:13px;font-weight:800;color:#0f172a;line-height:1.25;">{emoji_esc}</div>
      <div style="margin-top:2px;font-size:11px;color:#94a3b8;line-height:1.3;">{sub_esc}</div>
    </div>
    <div style="flex-shrink:0;text-align:right;">
      <div style="font-size:22px;font-weight:800;color:{score_color};letter-spacing:-0.03em;line-height:1;">{score_num}</div>
      <div style="font-size:10px;font-weight:600;color:#94a3b8;margin-top:2px;">/ 100</div>
    </div>
  </div>
  <div style="margin-top:10px;height:5px;border-radius:999px;background:{bar_bg};overflow:hidden;">
    <div style="width:{ratio * 100:.2f}%;height:100%;background:{bar_color};border-radius:999px;transition:width 0.35s ease;"></div>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )


@st.dialog("🥗 식전 미션")
def _pre_meal_mission_dialog(mission_text: str, t):
    st.markdown(mission_text)
    if st.button(t.get("pre_meal_dialog_close", "다음 단계"), key="pre_meal_dialog_close", use_container_width=True):
        pm = st.session_state.get("pre_meal") or {}
        pm["step"] = 3
        st.rerun()


@st.dialog("🛡️ 방어전 결과")
def _post_meal_result_dialog(t: dict):
    """식후 혈당 피드백 결과 다이얼로그 — 성공/실패 평가 + 피로도 정산."""
    pm = st.session_state.get("pre_meal") or {}
    feedback = pm.get("post_meal_feedback", "")
    is_success = pm.get("post_meal_is_success", False)
    change = int(pm.get("post_meal_stress_change", 0))

    esc = html_module.escape
    badge_color = "#10B981" if is_success else "#ef4444"
    result_label = esc(t.get("post_meal_success_label", "방어 성공!")) if is_success else esc(t.get("post_meal_fail_label", "방어 실패!"))
    result_icon = "🎉" if is_success else "💥"
    change_sign = "+" if change > 0 else ""
    change_text = esc(f"췌장 피로도 {change_sign}{change}점")
    badge_bg = "rgba(16,185,129,0.12)" if is_success else "rgba(239,68,68,0.12)"
    feedback_esc = esc(feedback)

    if is_success:
        st.balloons()

    st.markdown(
        f"""
<div style="text-align:center;margin-bottom:18px;">
  <div style="font-size:2.4rem;margin-bottom:6px;">{result_icon}</div>
  <div style="font-size:1.35rem;font-weight:800;color:{badge_color};margin-bottom:6px;">{result_label}</div>
  <div style="font-size:0.82rem;background:{badge_bg};color:{badge_color};
              border-radius:20px;display:inline-block;padding:4px 14px;font-weight:700;">
    {change_text}
  </div>
</div>
<div style="background:#f8f9fa;border-radius:14px;padding:14px 16px;
            font-size:0.95rem;line-height:1.75;color:#1e293b;white-space:pre-wrap;">
  {feedback_esc}
</div>
""",
        unsafe_allow_html=True,
    )

    if st.button(
        t.get("post_meal_dialog_close", "✅ 확인하고 다음 식사 준비"),
        key="post_meal_dialog_close_btn",
        use_container_width=True,
        type="primary",
    ):
        # 피로도 변화 반영
        new_stress = max(0.0, min(100.0, float(pm.get("pancreas_stress", 0)) + float(change)))
        pm["pancreas_stress"] = new_stress
        # Firestore 저장
        _uid_pm = st.session_state.get("user_id")
        if _uid_pm and _uid_pm != "guest_user_demo":
            try:
                save_daily_pancreas_stress(_uid_pm, pm.get("date_kst"), new_stress)
            except Exception:
                pass
        # 세션 전체 초기화 → 다음 식사 카메라 버튼으로 복귀
        pm["step"] = 1
        pm["menu_text"] = ""
        pm["analysis"] = ""
        pm["next_meal"] = ""
        pm["mission_text"] = ""
        pm["location"] = None
        pm["post_meal_feedback"] = ""
        pm["post_meal_is_success"] = False
        pm["post_meal_stress_change"] = 0
        st.session_state.pop("pre_meal_menu_img_hash", None)
        st.session_state.pop("pre_meal_menu_image_bytes", None)
        st.session_state.pop("pre_meal_menu_image_valid_for", None)
        st.session_state["pre_meal_capture_version"] = (
            st.session_state.get("pre_meal_capture_version", 0) + 1
        )
        for _k in ("pre_meal_menu_input", "pre_meal_slot_select"):
            if _k in st.session_state:
                del st.session_state[_k]
        st.rerun()


def _render_post_meal_feedback_card(t: dict, pm: dict) -> None:
    """식후 혈당 입력 카드 — step 3에서 미션 요약 카드 아래에 렌더."""
    esc = html_module.escape
    card_title = esc(t.get("post_meal_card_title", "🛡️ 방어전 결과 보고"))
    card_sub = esc(t.get("post_meal_card_sub", "식후 2시간 혈당을 입력하면 AI 코치가 방어 성공 여부를 평가해 드립니다"))
    menu_echo = (pm.get("menu_text") or "").strip()
    menu_echo_html = (
        f'<div class="ns-pm-menu-echo">📝 {esc(menu_echo)}</div>'
        if menu_echo
        else ""
    )

    with st.container(border=True):
        st.markdown(
            f"""
<div class="ns-postmeal-header">
  <div class="ns-postmeal-title">{card_title}</div>
  <div class="ns-postmeal-sub">{card_sub}</div>
  {menu_echo_html}
</div>
""",
            unsafe_allow_html=True,
        )

        glucose_val = st.number_input(
            t.get("post_meal_glucose_label", "식후 혈당 (mg/dL)"),
            min_value=40,
            max_value=500,
            value=120,
            step=1,
            key="post_meal_glucose_input",
        )

        if st.button(
            t.get("post_meal_submit_btn", "결과 확인 및 췌장 피로도 정산"),
            key="post_meal_submit",
            use_container_width=True,
            type="primary",
        ):
            try:
                with st.spinner(t.get("post_meal_spinner", "AI 코치가 방어전 결과를 분석 중입니다...")):
                    result = generate_post_meal_feedback(
                        menu_echo or t.get("pre_meal_menu_fallback", "오늘의 식사"),
                        int(glucose_val),
                        pm.get("meal_slot", "식사"),
                    )
                pm["post_meal_feedback"] = result["feedback_message"]
                pm["post_meal_is_success"] = result["is_success"]
                pm["post_meal_stress_change"] = result["stress_score_change"]
                _post_meal_result_dialog(t)
            except Exception as _e:
                st.error(t.get("post_meal_err_ai", "AI 분석에 실패했습니다.") + f" {_e}")


def _format_menu_lines_html(menu_text: str) -> str:
    """인식 메뉴 문자열을 줄별 HTML로 표시 (Vision이 붙인 이모지 유지)."""
    s = (menu_text or "").strip()
    if not s:
        return ""
    esc = html_module.escape
    parts = [p.strip() for p in re.split(r"[,，、]+", s) if p.strip()]
    if len(parts) <= 1:
        return f'<div class="ns-menu-line">{esc(s)}</div>'
    return "\n".join(f'<div class="ns-menu-line">{esc(p)}</div>' for p in parts)


def _render_pre_meal_result_card(t: dict, pm: dict, mt_run: str) -> None:
    """[2:3] 분석 결과 카드 — HTML flex 레이아웃 + st 버튼."""
    esc = html_module.escape
    mt_run = (mt_run or "").strip()
    _valid = (st.session_state.get("pre_meal_menu_image_valid_for") or "").strip()
    _img_bytes = st.session_state.get("pre_meal_menu_image_bytes")
    _show_img = bool(_img_bytes) and (_valid == mt_run)

    # 왼쪽(이미지) HTML 조각
    if _show_img:
        b64 = base64.b64encode(_img_bytes).decode()
        left_html = (
            '<div class="ns-rc-img-wrap">'
            f'<img src="data:image/jpeg;base64,{b64}" alt="" class="ns-rc-img" />'
            '</div>'
        )
    else:
        left_html = (
            f'<div class="ns-rc-img-wrap ns-rc-img-empty">'
            f'{esc(t.get("pre_meal_result_no_image", "사진을 올리면 더 정확해요"))}'
            f'</div>'
        )

    menu_lines_html = _format_menu_lines_html(mt_run)
    lbl_sub = esc(t.get("pre_meal_result_card_sub", "AI 인식 메뉴"))
    lbl_loc = esc(t.get("pre_meal_location_label", "어디서 드시나요?"))

    # 카드 전체 HTML (이미지 2 : 메뉴 3 가로 flex)
    st.markdown(
        f"""
<div class="ns-result-card">
  <div class="ns-result-card-row">
    <div class="ns-result-card-left">{left_html}</div>
    <div class="ns-result-card-right">
      <div class="ns-rc-menu-label">{lbl_sub}</div>
      <div class="ns-rc-menu-body">{menu_lines_html}</div>
      <div class="ns-rc-loc">{lbl_loc}</div>
    </div>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )
    # 버튼은 Streamlit 컴포넌트 (HTML 안에 배치 불가) — 카드 바로 아래 full-width 2열
    _bc1, _bc2 = st.columns(2, gap="small")
    with _bc1:
        if st.button(
            t.get("pre_meal_btn_home_big", "🏠 집밥"),
            key="pre_meal_loc_home_big",
            use_container_width=True,
            type="primary",
        ):
            _execute_pre_meal_insights_flow(pm, t, mt_run, "집밥")
    with _bc2:
        if st.button(
            t.get("pre_meal_btn_out_big", "🍽️ 외식·배달"),
            key="pre_meal_loc_out_big",
            use_container_width=True,
            type="primary",
        ):
            _execute_pre_meal_insights_flow(pm, t, mt_run, "외식")


# ════════════════════════════════════════════════════════════════════════════
# 성과 탭 — 주간 성적표 + 뱃지 컬렉션
# ════════════════════════════════════════════════════════════════════════════

_BADGES_DEF = [
    {"id": "defense_master",  "emoji": "🛡️", "name": "방어 마스터",    "desc": "연속 3회 방어 성공"},
    {"id": "morning_glow",    "emoji": "🌅", "name": "상쾌한 아침",     "desc": "공복 혈당 90 이하 달성"},
    {"id": "veggie_lover",    "emoji": "🥗", "name": "채소 러버",       "desc": "저GL 식단 5회 연속"},
    {"id": "week_warrior",    "emoji": "💪", "name": "주간 전사",       "desc": "이번 주 5회 이상 기록"},
    {"id": "low_spike",       "emoji": "📉", "name": "혈당 안정제",     "desc": "평균 혈당 점수 50 이하"},
    {"id": "consistent",      "emoji": "🔥", "name": "꾸준한 파이터",  "desc": "이번 주 3회 이상 기록"},
    {"id": "perfect_week",    "emoji": "⭐", "name": "퍼펙트 위크",    "desc": "방어 성공률 100%"},
    {"id": "early_bird",      "emoji": "🐦", "name": "아침형 인간",     "desc": "공복 혈당 3일 연속 기록"},
]

_GRADE_META = {
    "S": {"color": "#b8860b", "bg": "linear-gradient(135deg,#fffbe6 0%,#fff3c0 100%)",
          "border": "#f0c040", "label": "전설급",
          "comment": "완벽한 한 주! 췌장이 당신에게 절을 올립니다. 이 기세라면 혈관이 20대를 유지하겠네요! 🏆"},
    "A": {"color": "#065f46", "bg": "linear-gradient(135deg,#ecfdf5 0%,#d1fae5 100%)",
          "border": "#6ee7b7", "label": "우수",
          "comment": "훌륭한 한 주! 약간의 흔들림이 있었지만 전반적으로 완벽한 혈당 방어전이었습니다. 💪"},
    "B": {"color": "#1e40af", "bg": "linear-gradient(135deg,#eff6ff 0%,#dbeafe 100%)",
          "border": "#93c5fd", "label": "양호",
          "comment": "보통 수준의 한 주. 더 잘할 수 있어요! 식이섬유를 한 숟갈 더 얹어보세요. 🥗"},
    "C": {"color": "#92400e", "bg": "linear-gradient(135deg,#fffbeb 0%,#fef3c7 100%)",
          "border": "#fcd34d", "label": "노력 필요",
          "comment": "탄수화물 파티가 좀 잦았네요. 다음 주는 채소 먼저, 탄수화물 나중에! 🫡"},
    "D": {"color": "#991b1b", "bg": "linear-gradient(135deg,#fff1f2 0%,#ffe4e6 100%)",
          "border": "#fca5a5", "label": "위험",
          "comment": "이번 주는 췌장이 과로사 직전입니다. 제발 식이섬유 한 포기만요! 🚨"},
}


def _calc_weekly_grade(feed_items: list, blood_logs: list) -> dict:
    """최근 7일 feed_items + blood_logs 기반 주간 등급 산출."""
    import pytz as _pytz
    _seoul = _pytz.timezone("Asia/Seoul")
    _cutoff = datetime.now(_seoul).replace(hour=0, minute=0, second=0, microsecond=0)
    from datetime import timedelta as _td
    _cutoff -= _td(days=7)

    # 피드 필터링
    week_feed = []
    for _f in feed_items:
        try:
            _d = _f.get("date") or ""
            _dt = datetime.strptime(_d[:10], "%Y-%m-%d").replace(tzinfo=_seoul.localize(datetime.now()).tzinfo)
        except Exception:
            continue
        if _dt >= _cutoff:
            week_feed.append(_f)

    total = len(week_feed)
    avg_score = (sum(int(_f.get("blood_sugar_score", 0) or 0) for _f in week_feed) / total) if total else 0
    success_count = sum(1 for _f in week_feed if int(_f.get("blood_sugar_score", 0) or 0) < 60)
    success_rate = (success_count / total * 100) if total else 0

    # 공복 혈당 최솟값
    fasting_vals = [_b.get("value", 999) for _b in blood_logs if _b.get("type") == "fasting"]
    min_fasting = min(fasting_vals) if fasting_vals else 999

    # 등급 결정
    if success_rate >= 90:
        grade = "S"
    elif success_rate >= 75:
        grade = "A"
    elif success_rate >= 55:
        grade = "B"
    elif success_rate >= 35:
        grade = "C"
    else:
        grade = "D"
    if total == 0:
        grade = "D"

    # 뱃지 달성 여부
    consecutive = 0
    max_cons = 0
    for _f in sorted(week_feed, key=lambda x: x.get("date", "")):
        if int(_f.get("blood_sugar_score", 0) or 0) < 60:
            consecutive += 1
            max_cons = max(max_cons, consecutive)
        else:
            consecutive = 0

    badges = {
        "defense_master": max_cons >= 3,
        "morning_glow":   min_fasting <= 90,
        "veggie_lover":   sum(1 for _f in week_feed if int(_f.get("blood_sugar_score", 0) or 0) < 40) >= 5,
        "week_warrior":   total >= 5,
        "low_spike":      0 < avg_score <= 50,
        "consistent":     total >= 3,
        "perfect_week":   total > 0 and success_rate == 100,
        "early_bird":     len(fasting_vals) >= 3,
    }

    return {
        "grade": grade, "total": total, "avg_score": avg_score,
        "success_rate": success_rate, "min_fasting": min_fasting, "badges": badges,
    }


def _render_achievement_tab(t: dict) -> None:
    """성과 탭: 주간 성적표 + AI 코멘트 + 뱃지 컬렉션."""
    esc = html_module.escape
    feed_items = st.session_state.get("feed_items", [])
    blood_logs = st.session_state.get("blood_sugar_logs", [])
    _lt = st.session_state.get("login_type")

    stats = _calc_weekly_grade(feed_items, blood_logs)
    grade = stats["grade"]
    meta = _GRADE_META[grade]

    # ── 1. 다크 골드 프리미엄 헤더 ──────────────────────────────────────────
    st.markdown(
        """
<div class="ns-ach-header">
  <div class="ns-ach-header-sub">나의 건강 성적표</div>
  <div class="ns-ach-header-title">주간 혈당 성적표 🏆</div>
  <div class="ns-ach-header-hint">최근 7일간의 기록을 AI가 분석했습니다</div>
</div>
""",
        unsafe_allow_html=True,
    )

    # ── 2. 주간 종합 등급 카드 ──────────────────────────────────────────────
    _gcolor = esc(meta["color"])
    _gbg = esc(meta["bg"])
    _gborder = esc(meta["border"])
    _glabel = esc(meta["label"])
    _total = stats["total"]
    _rate = f"{stats['success_rate']:.0f}"
    _avg = f"{stats['avg_score']:.0f}"

    st.markdown(
        f"""
<div class="ns-ach-grade-card" style="background:{_gbg};border:2px solid {_gborder};">
  <div class="ns-ach-grade-label" style="color:{_gcolor};">{_glabel}</div>
  <div class="ns-ach-grade-letter" style="color:{_gcolor};">{esc(grade)}</div>
  <div class="ns-ach-grade-stats">
    <div class="ns-ach-stat-item">
      <div class="ns-ach-stat-val">{_total}회</div>
      <div class="ns-ach-stat-key">이번 주 기록</div>
    </div>
    <div class="ns-ach-stat-divider"></div>
    <div class="ns-ach-stat-item">
      <div class="ns-ach-stat-val">{_rate}%</div>
      <div class="ns-ach-stat-key">방어 성공률</div>
    </div>
    <div class="ns-ach-stat-divider"></div>
    <div class="ns-ach-stat-item">
      <div class="ns-ach-stat-val">{_avg}</div>
      <div class="ns-ach-stat-key">평균 점수</div>
    </div>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )

    # ── 3. AI 주간 코멘트 카드 ──────────────────────────────────────────────
    _comment = esc(meta["comment"])
    if _total == 0:
        _comment = esc("아직 이번 주 식단 기록이 없어요. 📸 카메라 버튼을 눌러 첫 기록을 남겨보세요!")
    st.markdown(
        f"""
<div class="ns-ach-comment-card">
  <div class="ns-ach-comment-icon">🤖</div>
  <div class="ns-ach-comment-text">{_comment}</div>
</div>
""",
        unsafe_allow_html=True,
    )

    # ── 4. 뱃지 컬렉션 그리드 ────────────────────────────────────────────────
    st.markdown(
        '<div class="ns-dashboard-section-title" style="margin-top:20px;">🏅 뱃지 컬렉션</div>',
        unsafe_allow_html=True,
    )

    badges_achieved = stats["badges"]
    badge_html_items = []
    for _b in _BADGES_DEF:
        _achieved = badges_achieved.get(_b["id"], False)
        if _achieved:
            badge_html_items.append(
                f'<div class="ns-ach-badge ns-ach-badge-on">'
                f'<div class="ns-ach-badge-emoji">{_b["emoji"]}</div>'
                f'<div class="ns-ach-badge-name">{esc(_b["name"])}</div>'
                f'<div class="ns-ach-badge-desc">{esc(_b["desc"])}</div>'
                f'</div>'
            )
        else:
            badge_html_items.append(
                f'<div class="ns-ach-badge ns-ach-badge-off">'
                f'<div class="ns-ach-badge-emoji" style="filter:grayscale(1);opacity:0.4;">{_b["emoji"]}</div>'
                f'<div class="ns-ach-badge-lock">🔒</div>'
                f'<div class="ns-ach-badge-name" style="color:#94a3b8;">{esc(_b["name"])}</div>'
                f'<div class="ns-ach-badge-desc" style="color:#cbd5e1;">{esc(_b["desc"])}</div>'
                f'</div>'
            )

    st.markdown(
        f'<div class="ns-ach-badge-grid">{"".join(badge_html_items)}</div>',
        unsafe_allow_html=True,
    )

    # 로그인 유도 (게스트)
    if _lt == "guest":
        st.info("🔐 로그인하면 Firestore에서 실제 7일 데이터를 연동해 더 정확한 성적표를 볼 수 있습니다!")


def _render_pre_meal_skeleton(t, is_guest=False, guest_remaining=0):
    """홈(스캐너 main) — 카메라 우선 식전 미션 → 장소 버튼 → AI 미션 팝업."""
    _ensure_pre_meal_state()
    _uid_pre = st.session_state.get("user_id")
    _ensure_pre_meal_owner_scope(_uid_pre)
    _hydrate_pre_meal_pancreas_from_firestore(_uid_pre)
    pm = st.session_state["pre_meal"]

    _render_pancreas_stress_gauge(pm, t)

    if pm.get("step") == 3:
        with st.container(border=True):
            st.markdown(t.get("pre_meal_step3_title", "### ✅ 미션 반영 · 요약"))
            st.markdown(pm.get("analysis") or "")
            st.markdown("---")
            st.markdown(pm.get("next_meal") or "")
            if st.button(t.get("pre_meal_reset", "다시 입력하기"), key="pre_meal_reset", use_container_width=True):
                pm["step"] = 1
                pm["menu_text"] = ""
                pm["analysis"] = ""
                pm["next_meal"] = ""
                pm["mission_text"] = ""
                pm["location"] = None
                pm["post_meal_feedback"] = ""
                pm["post_meal_is_success"] = False
                pm["post_meal_stress_change"] = 0
                st.session_state.pop("pre_meal_menu_img_hash", None)
                st.session_state.pop("pre_meal_menu_image_bytes", None)
                st.session_state.pop("pre_meal_menu_image_valid_for", None)
                st.session_state["pre_meal_capture_version"] = st.session_state.get("pre_meal_capture_version", 0) + 1
                for _k in ("pre_meal_menu_input", "pre_meal_slot_select"):
                    if _k in st.session_state:
                        del st.session_state[_k]
                st.rerun()
        # ── 식후 혈당 피드백 카드 (미션 완료 후 식후 2시간 결과 입력) ──────────
        _render_post_meal_feedback_card(t, pm)
        return

    # ── 조건부 렌더링 핵심: 인식된 메뉴가 있으면 카드 모드 ──────────────────
    _mt_existing = (
        st.session_state.get("pre_meal_menu_input") or pm.get("menu_text") or ""
    ).strip()
    _has_card = bool(_mt_existing)

    def _clear_and_retake():
        """이미지·메뉴 세션 완전 초기화 → 업로더 화면으로 복귀."""
        pm["menu_text"] = ""
        pm["step"] = 1
        for _k in ("pre_meal_menu_image_bytes", "pre_meal_menu_image_valid_for",
                   "pre_meal_menu_img_hash"):
            st.session_state.pop(_k, None)
        st.session_state["pre_meal_capture_version"] = (
            st.session_state.get("pre_meal_capture_version", 0) + 1
        )
        for _k in ("pre_meal_menu_input", "pre_meal_slot_select"):
            if _k in st.session_state:
                del st.session_state[_k]
        st.rerun()

    if _has_card:
        # ── 카드 모드: file_uploader 렌더링 완전 금지 ─────────────────────
        pm["menu_text"] = _mt_existing
        _render_pre_meal_result_card(t, pm, _mt_existing)
        st.markdown(
            '<div style="text-align:center;margin-top:6px;">',
            unsafe_allow_html=True,
        )
        if st.button(
            t.get("pre_meal_retake_label", "🔄 다른 사진으로 다시 찍기"),
            key="pre_meal_retake_photo",
            use_container_width=False,
        ):
            _clear_and_retake()
        st.markdown("</div>", unsafe_allow_html=True)

    else:
        # ── 업로더 모드: 카메라 버튼 표시 ────────────────────────────────
        if "pre_meal_slot_select" not in st.session_state:
            _opts_init = ["아침", "점심", "저녁", "간식"]
            _ds = pm.get("meal_slot", "아침")
            st.session_state["pre_meal_slot_select"] = _ds if _ds in _opts_init else "아침"
        if "pre_meal_menu_input" not in st.session_state:
            st.session_state["pre_meal_menu_input"] = pm.get("menu_text", "")

        _cap_v = int(st.session_state.get("pre_meal_capture_version", 0))

        # st.empty()로 감싸 → 파일 올라오는 순간 즉시 UI 교체 가능
        _upload_slot = st.empty()
        up = _upload_slot.file_uploader(
            t.get("pre_meal_upload_main_label", "📸 오늘 식단 찰칵!"),
            type=["jpg", "png", "jpeg", "webp"],
            key=f"pre_meal_up_{_cap_v}",
            label_visibility="collapsed",
        )

        pil_src = None
        if up is not None:
            try:
                pil_src = compress_image(Image.open(up), max_size_kb=500)
            except Exception:
                st.warning(t.get("pre_meal_err_image", "이미지를 열 수 없습니다."))

        if pil_src is not None:
            h = _pre_meal_image_hash(pil_src)
            if h != st.session_state.get("pre_meal_menu_img_hash"):
                if is_guest and guest_remaining <= 0:
                    st.warning(t.get("pre_meal_guest_vision_block", "무료 체험 횟수가 부족합니다."))
                else:
                    # ✅ 즉시 카메라 버튼·파일명 완전 제거
                    _upload_slot.empty()

                    # ✅ 세련된 pulse 로딩 카드 표시
                    _loading_slot = st.empty()
                    _scan_msg = html_module.escape(
                        t.get(
                            "pre_meal_spinner_vision",
                            "AI 코치가 메뉴를 정밀 스캔하고 맞춤형 방어막을 설계 중입니다...",
                        )
                    )
                    _loading_slot.markdown(
                        f"""
<div class="ns-loading-card">
  <div class="ns-loading-row">
    <div class="ns-loading-icon">🔍</div>
    <div class="ns-loading-text-wrap">
      <div class="ns-loading-title">{_scan_msg}</div>
      <div class="ns-loading-dots">
        <span></span><span></span><span></span>
      </div>
    </div>
  </div>
  <div class="ns-loading-bar-track">
    <div class="ns-loading-bar-fill"></div>
  </div>
</div>
""",
                        unsafe_allow_html=True,
                    )

                    _vision_ok = False
                    try:
                        name = extract_pre_meal_menu_name_from_image(pil_src)
                        if not name:
                            name = t.get("pre_meal_menu_fallback", "오늘의 식사")
                        pm["menu_text"] = name
                        st.session_state["pre_meal_menu_input"] = name
                        st.session_state["pre_meal_menu_img_hash"] = h
                        if is_guest:
                            st.session_state["guest_usage_count"] = (
                                st.session_state.get("guest_usage_count", 0) + 1
                            )
                        _vision_ok = True
                    except Exception as e:
                        _loading_slot.empty()
                        st.error(
                            t.get("pre_meal_err_vision", "메뉴 인식에 실패했습니다. ")
                            + str(e)
                        )

                    if _vision_ok:
                        _loading_slot.empty()

            # 이미지 bytes 세션 저장
            try:
                _buf = io.BytesIO()
                _p = pil_src.copy() if hasattr(pil_src, "copy") else pil_src
                if _p.mode in ("RGBA", "P"):
                    _p = _p.convert("RGB")
                _p.save(_buf, format="JPEG", quality=88)
                st.session_state["pre_meal_menu_image_bytes"] = _buf.getvalue()
                st.session_state["pre_meal_menu_image_valid_for"] = (
                    st.session_state.get("pre_meal_menu_input") or pm.get("menu_text") or ""
                ).strip()
            except Exception:
                pass

        # 직접 입력 expander
        with st.expander(t.get("pre_meal_expander_manual", "⌨️ 직접 입력하기"), expanded=False):
            _opts_slot = ["아침", "점심", "저녁", "간식"]
            meal_slot = st.selectbox(
                t.get("pre_meal_meal_slot", "현재 끼니"),
                _opts_slot,
                key="pre_meal_slot_select",
            )
            pm["meal_slot"] = meal_slot
            st.text_input(
                t.get("pre_meal_menu_label", "메뉴 (텍스트)"),
                key="pre_meal_menu_input",
                placeholder=t.get("pre_meal_menu_ph", "예: 김치찌개 + 현미밥"),
            )
            _mt_manual = (st.session_state.get("pre_meal_menu_input") or "").strip()
            if _mt_manual:
                pm["menu_text"] = _mt_manual

        pm["meal_slot"] = st.session_state.get("pre_meal_slot_select", pm.get("meal_slot", "아침"))

        # 이번 실행에서 메뉴가 확정되면 → 즉시 카드 모드로 전환 (rerun)
        _mt_now = (
            st.session_state.get("pre_meal_menu_input") or pm.get("menu_text") or ""
        ).strip()
        if _mt_now:
            pm["menu_text"] = _mt_now
            st.rerun()


def _render_dash_today_metrics_cards(t, avg_glucose, latest_glucose, total_carbs, meal_n):
    """홈 '오늘의 요약' — st.metric 대신 HTML(줄바꿈·잘림 완전 통제)."""
    esc = html_module.escape
    no_rec = esc(t.get("dash_no_record", "기록 없음"))
    v_avg = esc(f"{avg_glucose} mg/dL") if avg_glucose is not None else no_rec
    v_carbs = esc(f"{total_carbs} g")
    v_meals = esc(f"{meal_n}회")
    v_latest = esc(f"{latest_glucose} mg/dL") if latest_glucose is not None else no_rec
    lbl_avg = esc(t.get("dash_metric_avg_glucose", "오늘 평균 혈당"))
    lbl_carbs = esc(t.get("dash_metric_total_carbs", "오늘 총 탄수화물"))
    lbl_meals = esc(t.get("dash_metric_meals", "오늘 식단 기록"))
    lbl_latest = esc(t.get("dash_metric_latest_glucose", "최근 측정 혈당"))
    return f"""
    <div class="dash-today-metrics-root" style="width:100%;box-sizing:border-box;">
      <div style="display:flex;flex-wrap:wrap;gap:10px;justify-content:space-between;width:100%;">
        <div style="flex:1 1 calc(50% - 8px);min-width:0;box-sizing:border-box;padding:12px 10px;background:#ffffff;border-radius:16px;border:none;box-shadow:0 8px 24px rgba(0,0,0,0.08);">
          <div style="font-size:12px;color:#64748b;line-height:1.4;word-break:keep-all;white-space:normal;">{lbl_avg}</div>
          <div style="font-size:clamp(20px,4.5vw,28px);font-weight:800;color:#0f172a;line-height:1.25;margin-top:6px;word-break:break-word;overflow-wrap:anywhere;white-space:normal;">{v_avg}</div>
        </div>
        <div style="flex:1 1 calc(50% - 8px);min-width:0;box-sizing:border-box;padding:12px 10px;background:#ffffff;border-radius:16px;border:none;box-shadow:0 8px 24px rgba(0,0,0,0.08);">
          <div style="font-size:12px;color:#64748b;line-height:1.4;word-break:keep-all;white-space:normal;">{lbl_carbs}</div>
          <div style="font-size:clamp(20px,4.5vw,28px);font-weight:800;color:#0f172a;line-height:1.25;margin-top:6px;word-break:break-word;overflow-wrap:anywhere;white-space:normal;">{v_carbs}</div>
        </div>
        <div style="flex:1 1 calc(50% - 8px);min-width:0;box-sizing:border-box;padding:12px 10px;background:#ffffff;border-radius:16px;border:none;box-shadow:0 8px 24px rgba(0,0,0,0.08);">
          <div style="font-size:12px;color:#64748b;line-height:1.4;word-break:keep-all;white-space:normal;">{lbl_meals}</div>
          <div style="font-size:clamp(20px,4.5vw,28px);font-weight:800;color:#0f172a;line-height:1.25;margin-top:6px;word-break:break-word;overflow-wrap:anywhere;white-space:normal;">{v_meals}</div>
        </div>
        <div style="flex:1 1 calc(50% - 8px);min-width:0;box-sizing:border-box;padding:12px 10px;background:#ffffff;border-radius:16px;border:none;box-shadow:0 8px 24px rgba(0,0,0,0.08);">
          <div style="font-size:12px;color:#64748b;line-height:1.4;word-break:keep-all;white-space:normal;">{lbl_latest}</div>
          <div style="font-size:clamp(20px,4.5vw,28px);font-weight:800;color:#0f172a;line-height:1.25;margin-top:6px;word-break:break-word;overflow-wrap:anywhere;white-space:normal;">{v_latest}</div>
        </div>
      </div>
    </div>
    """


def get_today_str():
    """한국(서울) 기준 오늘 날짜 키 YYYY-MM-DD."""
    import pytz

    return datetime.now(pytz.timezone("Asia/Seoul")).strftime("%Y-%m-%d")


def _meal_feed_display_time(rec):
    """일지 카드 헤더용 YYYY-MM-DD HH:MM (서울)."""
    try:
        import pytz

        seoul = pytz.timezone("Asia/Seoul")
        saved = rec.get("saved_at_utc")
        if saved:
            s = str(saved).strip().replace("Z", "+00:00")
            dt_utc = datetime.fromisoformat(s)
            if dt_utc.tzinfo is None:
                dt_utc = dt_utc.replace(tzinfo=timezone.utc)
            return dt_utc.astimezone(seoul).strftime("%Y-%m-%d %H:%M")
        ca = rec.get("created_at")
        if ca is not None:
            if hasattr(ca, "timestamp"):
                dt_utc = datetime.fromtimestamp(ca.timestamp(), tz=timezone.utc)
            elif isinstance(ca, datetime):
                dt_utc = ca if ca.tzinfo else ca.replace(tzinfo=timezone.utc)
                if dt_utc.tzinfo is None:
                    dt_utc = dt_utc.replace(tzinfo=timezone.utc)
            else:
                dt_utc = None
            if dt_utc is not None:
                return dt_utc.astimezone(seoul).strftime("%Y-%m-%d %H:%M")
        date_str = (rec.get("date") or "").strip()
        if date_str and len(date_str) >= 16:
            dt_naive = datetime.strptime(date_str[:16], "%Y-%m-%d %H:%M")
            localized = seoul.localize(dt_naive)
            return localized.strftime("%Y-%m-%d %H:%M")
    except Exception:
        pass
    return (rec.get("date") or "") or str(rec.get("saved_at_utc") or rec.get("created_at") or "")


def _read_meal_feed_css():
    try:
        _p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "style.css")
        with open(_p, "r", encoding="utf-8") as _f:
            _s = _f.read()
        _a = _s.find("/* ===== MEAL_FEED_ISOLATED_CSS_START =====")
        _b = _s.find("/* ===== MEAL_FEED_ISOLATED_CSS_END =====", _a)
        if _a >= 0 and _b > _a:
            return _s[_a:_b]
    except Exception:
        pass
    return ""


def _extract_menu_names(rec: dict, max_items: int = 3) -> str:
    """sorted_items에서 음식명을 추출해 ' · '로 연결."""
    items = rec.get("sorted_items") or []
    names = []
    for it in items[:max_items]:
        if isinstance(it, list) and it:
            n = str(it[0]).strip()
        elif isinstance(it, dict):
            n = str(it.get("name", "")).strip()
        else:
            n = ""
        if n:
            names.append(n)
    return " · ".join(names)


def _render_history_summary_cards(t: dict, feed_items: list, pm: dict) -> None:
    """일지 상단 프리미엄 요약 위젯 3개 — 다크 그린 포인트 컬러 강화."""
    esc = html_module.escape

    scores = [int(r.get("blood_sugar_score", 0) or 0) for r in feed_items]
    avg_score = (sum(scores) / len(scores)) if scores else 0.0
    success_count = sum(1 for s in scores if s <= 40)
    total_count = len(scores)
    success_rate = (success_count / total_count * 100) if total_count else 0.0
    pancreas_stress = float((pm or {}).get("pancreas_stress", 0) or 0)

    if avg_score <= 40:
        sc_color, sc_bg, sc_label = "#065f46", "rgba(6,95,70,0.08)", "안정 🟢"
    elif avg_score <= 65:
        sc_color, sc_bg, sc_label = "#92400e", "rgba(146,64,14,0.08)", "주의 🟡"
    else:
        sc_color, sc_bg, sc_label = "#991b1b", "rgba(153,27,27,0.08)", "위험 🔴"

    if success_rate >= 70:
        sr_color, sr_bg = "#065f46", "rgba(6,95,70,0.08)"
    elif success_rate >= 40:
        sr_color, sr_bg = "#92400e", "rgba(146,64,14,0.08)"
    else:
        sr_color, sr_bg = "#991b1b", "rgba(153,27,27,0.08)"

    if pancreas_stress <= 30:
        ps_color, ps_bg, ps_label = "#065f46", "rgba(6,95,70,0.08)", "쾌적"
    elif pancreas_stress <= 70:
        ps_color, ps_bg, ps_label = "#92400e", "rgba(146,64,14,0.08)", "주의"
    else:
        ps_color, ps_bg, ps_label = "#991b1b", "rgba(153,27,27,0.08)", "과부하"

    sr_detail = esc(f"{success_count}/{total_count}식")

    def _card_html(icon, title, value, unit, sub, color, bg):
        return f"""
<div class="ns-hist-sum-card" style="background:{bg};">
  <div class="ns-hist-sum-icon">{icon}</div>
  <div class="ns-hist-sum-title">{esc(title)}</div>
  <div class="ns-hist-sum-value" style="color:{color};">{esc(str(value))}<span class="ns-hist-sum-unit">{esc(unit)}</span></div>
  <div class="ns-hist-sum-sub" style="color:{color};">{sub}</div>
</div>"""

    c1, c2, c3 = st.columns(3, gap="small")
    with c1:
        st.markdown(_card_html("📊", "평균 위험도", f"{avg_score:.0f}", "/100", sc_label, sc_color, sc_bg), unsafe_allow_html=True)
    with c2:
        st.markdown(_card_html("🛡️", "방어 성공률", f"{success_rate:.0f}", "%", sr_detail, sr_color, sr_bg), unsafe_allow_html=True)
    with c3:
        st.markdown(_card_html("🫀", "췌장 피로도", f"{pancreas_stress:.0f}", "/100", ps_label, ps_color, ps_bg), unsafe_allow_html=True)


def _parse_feed_timestamp(rec: dict):
    """feed_items 레코드의 타임스탬프를 서울 시각의 datetime으로 반환 (실패 시 None)."""
    import pytz
    seoul = pytz.timezone("Asia/Seoul")
    saved = rec.get("saved_at_utc")
    if saved:
        try:
            s = str(saved).strip().replace("Z", "+00:00")
            dt_utc = datetime.fromisoformat(s)
            if dt_utc.tzinfo is None:
                dt_utc = dt_utc.replace(tzinfo=timezone.utc)
            return dt_utc.astimezone(seoul)
        except Exception:
            pass
    ca = rec.get("created_at")
    if ca is not None:
        try:
            if hasattr(ca, "timestamp"):
                return datetime.fromtimestamp(ca.timestamp(), tz=timezone.utc).astimezone(seoul)
            elif isinstance(ca, datetime):
                dt = ca if ca.tzinfo else ca.replace(tzinfo=timezone.utc)
                return dt.astimezone(seoul)
        except Exception:
            pass
    return None


def _aggregate_feed_by_period(feed_items: list, period: str):
    """feed_items를 기간별로 집계 → (labels, avg_scores, full_timestamps) 반환."""
    groups: dict = {}       # key → [scores]
    labels_map: dict = {}   # key → display label

    for rec in feed_items:
        dt = _parse_feed_timestamp(rec)
        if dt is None:
            continue
        score = int(rec.get("blood_sugar_score", 0) or 0)

        if period == "일별":
            key = dt.strftime("%Y-%m-%d")
            label = dt.strftime("%m/%d")
        elif period == "주별":
            iso = dt.isocalendar()
            key = f"{iso[0]}-W{iso[1]:02d}"
            label = f"{iso[0] % 100}/{iso[1]}주"
        elif period == "월별":
            key = dt.strftime("%Y-%m")
            label = dt.strftime("%m월")
        else:  # 연별
            key = dt.strftime("%Y")
            label = dt.strftime("%Y년")

        groups.setdefault(key, []).append(score)
        labels_map[key] = label

    sorted_keys = sorted(groups.keys())
    labels = [labels_map[k] for k in sorted_keys]
    avgs = [sum(groups[k]) / len(groups[k]) for k in sorted_keys]
    return labels, avgs


def _render_history_trend_chart(t: dict, feed_items: list) -> None:
    """기간 선택 radio + Plotly 라인 차트를 하나의 프리미엄 카드 안에 렌더.
    드래그·줌 완전 차단으로 모바일 스크롤 깨짐 방지."""
    import plotly.graph_objects as go
    import pytz

    # ── 기간 세그먼트 컨트롤 (카드 내부) ───────────────────────────────────
    _PERIODS = ["오늘", "일별", "주별", "월별", "연별"]
    if "hist_period" not in st.session_state:
        st.session_state["hist_period"] = "일별"

    with st.container(border=True):
        st.markdown(
            '<div class="ns-chart-title">📈 혈당 위험도 추이</div>',
            unsafe_allow_html=True,
        )

        # 가로 한 줄 radio — 모바일에서 한 행에 꽉 차게
        period = st.radio(
            "기간",
            _PERIODS,
            index=_PERIODS.index(st.session_state["hist_period"]),
            horizontal=True,
            label_visibility="collapsed",
            key="hist_period_radio",
        )
        st.session_state["hist_period"] = period

        if not feed_items:
            st.markdown(
                '<div style="text-align:center;padding:30px 0;color:#94a3b8;font-size:0.88rem;">식사 기록이 없어 차트를 표시할 수 없습니다.</div>',
                unsafe_allow_html=True,
            )
            return

        # ── "오늘" 기간: 오늘 날짜 레코드만 필터 후 개별 표시 ──────────────
        if period == "오늘":
            seoul = pytz.timezone("Asia/Seoul")
            today_str = datetime.now(seoul).strftime("%Y-%m-%d")
            today_items = []
            for rec in feed_items:
                dt = _parse_feed_timestamp(rec)
                if dt and dt.strftime("%Y-%m-%d") == today_str:
                    today_items.append(rec)
            if not today_items:
                st.markdown(
                    '<div style="text-align:center;padding:30px 0;color:#94a3b8;font-size:0.88rem;">오늘의 식사 기록이 없습니다.</div>',
                    unsafe_allow_html=True,
                )
                return
            labels = [_meal_feed_display_time(r)[-5:] for r in reversed(today_items)]
            avgs   = [int(r.get("blood_sugar_score", 0) or 0) for r in reversed(today_items)]
        else:
            labels, avgs = _aggregate_feed_by_period(feed_items, period)

        if not labels:
            st.markdown(
                '<div style="text-align:center;padding:30px 0;color:#94a3b8;font-size:0.88rem;">해당 기간의 데이터가 없습니다.</div>',
                unsafe_allow_html=True,
            )
            return

        point_colors = ["#10B981" if s <= 40 else "#f59e0b" if s <= 65 else "#ef4444" for s in avgs]
        hover_unit = "" if period in ("오늘", "일별") else "평균 "

        fig = go.Figure()
        fig.add_hrect(y0=0,  y1=40,  fillcolor="rgba(16,185,129,0.07)", line_width=0)
        fig.add_hrect(y0=40, y1=65,  fillcolor="rgba(245,158,11,0.05)", line_width=0)
        fig.add_hrect(y0=65, y1=105, fillcolor="rgba(239,68,68,0.05)",  line_width=0)
        fig.add_hline(y=40, line_dash="dot", line_color="rgba(16,185,129,0.4)",
                      annotation_text="안정", annotation_position="top left",
                      annotation_font_size=10, annotation_font_color="#10B981")
        fig.add_hline(y=65, line_dash="dot", line_color="rgba(245,158,11,0.4)",
                      annotation_text="경계", annotation_position="top left",
                      annotation_font_size=10, annotation_font_color="#f59e0b")

        fig.add_trace(go.Scatter(
            x=labels, y=avgs,
            mode="lines+markers",
            line=dict(color="#10B981", width=2.5, shape="spline"),
            marker=dict(color=point_colors, size=11, line=dict(color="white", width=2)),
            hovertemplate=(
                f"<b>%{{x}}</b><br>"
                f"{hover_unit}혈당 위험도: <b>%{{y:.1f}}</b> pt<extra></extra>"
            ),
        ))

        fig.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            margin=dict(l=0, r=10, t=6, b=6),
            yaxis=dict(
                range=[0, 105],
                gridcolor="rgba(0,0,0,0.06)",
                tickfont=dict(size=10),
                title=dict(text="mg/dL (혈당 위험도 점수)", font=dict(size=10, color="#94a3b8")),
                fixedrange=True,          # 모바일 줌 차단
            ),
            xaxis=dict(
                gridcolor="rgba(0,0,0,0.06)",
                tickangle=-30,
                tickfont=dict(size=10),
                fixedrange=True,          # 모바일 줌 차단
            ),
            hoverlabel=dict(
                bgcolor="white",
                bordercolor="#e2e8f0",
                font_size=13,
                font_family="Noto Sans KR",
            ),
            dragmode=False,               # 드래그 완전 차단
            height=220,
            showlegend=False,
        )
        # x/y 두 축 모두 fixedrange 강제 적용
        fig.update_xaxes(fixedrange=True)
        fig.update_yaxes(fixedrange=True)

        st.plotly_chart(
            fig,
            use_container_width=True,
            config={
                "displayModeBar": False,   # 상단 툴바 숨김
                "scrollZoom": False,       # 스크롤 줌 차단
                "staticPlot": False,       # hover는 유지
            },
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


def _parse_pre_meal_insights_json(raw: str) -> dict:
    """LLM 응답 문자열 → mission/analysis/next_meal/added_stress 검증 (JSON만 파싱)."""
    text = (raw or "").strip()
    if not text:
        raise ValueError("모델 응답이 비어 있습니다.")
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I | re.M)
        text = re.sub(r"\s*```\s*$", "", text)
    text = text.strip()

    def _loads(s: str):
        return json.loads(s)

    try:
        data = _loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise
        data = _loads(text[start : end + 1])

    if not isinstance(data, dict):
        raise ValueError("JSON 최상위는 객체여야 합니다.")
    for k in ("mission", "analysis", "next_meal"):
        if k not in data:
            raise ValueError(f"필수 키 누락: {k}")
        data[k] = str(data[k] or "").strip()
    try:
        ai = int(round(float(data.get("added_stress", 0))))
    except (TypeError, ValueError):
        ai = 0
    data["added_stress"] = max(0, min(30, ai))
    return data


def generate_pre_meal_insights(menu: str, location: str, meal_slot: str, current_stress: float) -> dict:
    """Gemini 텍스트 모델로 식전 인사이트 JSON 생성·파싱 (내부에서 API 키로 클라이언트 생성)."""
    api_key = _get_secret("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY가 설정되어 있지 않습니다.")
    client = genai.Client(api_key=api_key)
    user_prompt = get_pre_meal_insights_user_prompt(menu, location, meal_slot, current_stress)
    _env = os.environ.get("GEMINI_TEXT_MODEL", "").strip()
    candidates = []
    if _env:
        candidates.append(_env)
    for _m in ("gemini-2.5-flash", "gemini-2.0-flash"):
        if _m not in candidates:
            candidates.append(_m)
    last_err = None
    for mm in candidates:
        try:
            response = client.models.generate_content(
                model=mm,
                contents=[user_prompt],
                config=gtypes.GenerateContentConfig(
                    response_mime_type="application/json",
                    system_instruction=PRE_MEAL_INSIGHTS_SYSTEM_PROMPT,
                ),
            )
            raw = (response.text or "").strip()
            return _parse_pre_meal_insights_json(raw)
        except json.JSONDecodeError as je:
            last_err = je
            continue
        except ValueError as ve:
            last_err = ve
            continue
        except Exception as e:
            last_err = e
            es = str(e)
            if "not found" in es.lower() or "not supported" in es.lower() or "NOT_FOUND" in es:
                continue
            raise
    if last_err:
        raise last_err
    raise RuntimeError("사용 가능한 Gemini 텍스트 모델이 없습니다.")


def _parse_post_meal_feedback_json(raw: str) -> dict:
    """식후 피드백 LLM 응답 → feedback_message/stress_score_change/is_success 검증."""
    text = (raw or "").strip()
    if not text:
        raise ValueError("모델 응답이 비어 있습니다.")
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I | re.M)
        text = re.sub(r"\s*```\s*$", "", text)
    text = text.strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise
        data = json.loads(text[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("JSON 최상위는 객체여야 합니다.")
    data["feedback_message"] = str(data.get("feedback_message") or "").strip()
    if not data["feedback_message"]:
        raise ValueError("필수 키 누락: feedback_message")
    try:
        sc = int(round(float(data.get("stress_score_change", 0))))
    except (TypeError, ValueError):
        sc = 0
    data["stress_score_change"] = max(-15, min(30, sc))
    data["is_success"] = bool(data.get("is_success", False))
    return data


def generate_post_meal_feedback(menu: str, glucose_value: int, meal_slot: str = "식사") -> dict:
    """Gemini 텍스트 모델로 식후 혈당 피드백 JSON 생성·파싱."""
    api_key = _get_secret("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY가 설정되어 있지 않습니다.")
    client = genai.Client(api_key=api_key)
    user_prompt = get_post_meal_feedback_user_prompt(menu, glucose_value, meal_slot)
    _env = os.environ.get("GEMINI_TEXT_MODEL", "").strip()
    candidates = []
    if _env:
        candidates.append(_env)
    for _m in ("gemini-2.5-flash", "gemini-2.0-flash"):
        if _m not in candidates:
            candidates.append(_m)
    last_err = None
    for mm in candidates:
        try:
            response = client.models.generate_content(
                model=mm,
                contents=[user_prompt],
                config=gtypes.GenerateContentConfig(
                    response_mime_type="application/json",
                    system_instruction=POST_MEAL_FEEDBACK_SYSTEM_PROMPT,
                ),
            )
            raw = (response.text or "").strip()
            return _parse_post_meal_feedback_json(raw)
        except json.JSONDecodeError as je:
            last_err = je
            continue
        except ValueError as ve:
            last_err = ve
            continue
        except Exception as e:
            last_err = e
            es = str(e)
            if "not found" in es.lower() or "not supported" in es.lower() or "NOT_FOUND" in es:
                continue
            raise
    if last_err:
        raise last_err
    raise RuntimeError("사용 가능한 Gemini 텍스트 모델이 없습니다.")


def _pre_meal_image_hash(pil_img: Image.Image) -> str:
    import hashlib

    buf = io.BytesIO()
    im = pil_img.copy() if hasattr(pil_img, "copy") else pil_img
    if im.mode in ("RGBA", "P"):
        im = im.convert("RGB")
    im.save(buf, format="JPEG", quality=88)
    return hashlib.md5(buf.getvalue()).hexdigest()


def _parse_menu_name_json(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return ""
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I | re.M)
        text = re.sub(r"\s*```\s*$", "", text)
    text = text.strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            return ""
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return ""
    if isinstance(data, dict):
        return str(data.get("menu_name") or "").strip()
    return ""


def extract_pre_meal_menu_name_from_image(pil_image: Image.Image) -> str:
    """Gemini Vision으로 음식 메뉴 짧은 문자열 추출."""
    api_key = _get_secret("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY가 설정되어 있지 않습니다.")
    client = genai.Client(api_key=api_key)
    _env_mm = os.environ.get("GEMINI_VISION_MODEL", "").strip()
    candidates = []
    if _env_mm:
        candidates.append(_env_mm)
    for _m in ("gemini-2.5-flash", "gemini-2.0-flash"):
        if _m not in candidates:
            candidates.append(_m)
    last_err = None
    for mm in candidates:
        try:
            response = client.models.generate_content(
                model=mm,
                contents=[PRE_MEAL_MENU_NAME_VISION_PROMPT, pil_image],
                config=gtypes.GenerateContentConfig(response_mime_type="application/json"),
            )
            raw = (response.text or "").strip()
            name = _parse_menu_name_json(raw)
            if name:
                return name[:120]
        except Exception as e:
            last_err = e
            es = str(e)
            if "not found" in es.lower() or "not supported" in es.lower() or "NOT_FOUND" in es:
                continue
            raise
    if last_err:
        raise last_err
    raise RuntimeError("메뉴 이름을 인식하지 못했습니다.")


def _execute_pre_meal_insights_flow(pm: dict, t: dict, menu_text: str, location_val: str) -> None:
    """식전 인사이트 생성 → 저장 → 미션 다이얼로그."""
    try:
        with st.spinner(
            t.get(
                "pre_meal_spinner_mission",
                "AI 코치가 메뉴를 스캔하고 방어막을 설계 중입니다…",
            )
        ):
            out = generate_pre_meal_insights(
                (menu_text or "").strip(),
                location_val,
                pm.get("meal_slot", "아침"),
                float(pm.get("pancreas_stress") or 0),
            )
    except json.JSONDecodeError as je:
        st.error(
            t.get(
                "pre_meal_err_json",
                "AI 응답을 JSON으로 해석하지 못했습니다. 잠시 후 다시 시도해 주세요.",
            )
            + f" ({je})"
        )
    except Exception as e:
        st.error(
            t.get("pre_meal_err_ai", "AI 호출에 실패했습니다.")
            + f" {e}"
        )
    else:
        pm["mission_text"] = out["mission"]
        pm["analysis"] = out["analysis"]
        pm["next_meal"] = out["next_meal"]
        pm["pancreas_stress"] = min(
            100.0,
            float(pm.get("pancreas_stress") or 0) + float(out.get("added_stress", 0)),
        )
        _uid_pm = st.session_state.get("user_id")
        if _uid_pm and _uid_pm != "guest_user_demo":
            save_daily_pancreas_stress(_uid_pm, pm.get("date_kst"), pm["pancreas_stress"])
        _pre_meal_mission_dialog(pm["mission_text"], t)


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
if "feed_items" not in st.session_state:
    st.session_state["feed_items"] = []
if "last_doc" not in st.session_state:
    st.session_state["last_doc"] = None
if "has_more" not in st.session_state:
    st.session_state["has_more"] = False
if "meal_feed_uid" not in st.session_state:
    st.session_state["meal_feed_uid"] = None
if "meal_feed_hydrated_uid" not in st.session_state:
    st.session_state["meal_feed_hydrated_uid"] = None
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


# 3. 사이드바 (로그인·목표 등 — 스캐너/기록 전환은 하단 바 session_state.nav_menu만 사용)
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
            _reset_meal_feed_state()
            st.session_state["auth_mode"] = "login"
            st.rerun()
    elif _lt == "google":
        if st.button(f"🚪 {t['sidebar_logout']}", key="sidebar_logout", use_container_width=True):
            st.session_state["logged_in"] = False
            st.session_state["login_type"] = None
            st.session_state["user_id"] = None
            st.session_state["user_email"] = None
            _reset_meal_feed_state()
            st.session_state["auth_mode"] = "login"
            st.rerun()
    st.divider()
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
_uploader_ph = (t.get("pre_meal_uploader_cta") or t.get("uploader_placeholder") or "📸 오늘 식단 찰칵!").replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
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

    .stApp {{ background-color: #f8f9fa !important; }}

    .ns-premium-hero {{
        font-size: clamp(1.05rem, 3.8vw, 1.35rem);
        font-weight: 800;
        letter-spacing: -0.03em;
        color: #0f172a;
        line-height: 1.45;
        margin: 4px 0 16px 0;
        padding: 0 2px;
    }}
    .ns-dashboard-section-title {{
        font-size: 0.95rem;
        font-weight: 800;
        color: #64748b;
        letter-spacing: -0.02em;
        margin: 8px 0 10px 0;
        text-transform: uppercase;
    }}

    /* 프리미엄 카드: Streamlit bordered 컨테이너 */
    [data-testid="stVerticalBlockBorderWrapper"] {{
        border: none !important;
        border-radius: 20px !important;
        background: #ffffff !important;
        box-shadow: 0 8px 24px rgba(0,0,0,0.08) !important;
        padding: 1rem 1.1rem !important;
    }}

    /* 메인 홈: 직접 입력 expander를 장소 버튼 아래로 (스크립트 순서는 위쪽 유지) */
    section.main:has(.ns-premium-home-shell) .block-container > div[data-testid="stVerticalBlock"],
    .stApp:has(.ns-premium-home-shell) .block-container > div[data-testid="stVerticalBlock"] {{
        display: flex;
        flex-direction: column;
    }}
    section.main:has(.ns-premium-home-shell) .block-container > div[data-testid="stVerticalBlock"] > div[data-testid="element-container"]:has([data-testid="stExpander"]),
    .stApp:has(.ns-premium-home-shell) .block-container > div[data-testid="stVerticalBlock"] > div[data-testid="element-container"]:has([data-testid="stExpander"]) {{
        order: 100;
    }}

    /* 파일 업로드 영역: 풀폭 에메랄드 액션 버튼 (카메라·갤러리 터치 유도) */
    [data-testid="stFileUploader"] {{
        display: flex;
        justify-content: stretch;
        margin: 0 auto;
        width: 100% !important;
        max-width: 100% !important;
    }}
    [data-testid="stFileUploader"] label {{
        display: none !important;
    }}
    [data-testid="stFileUploader"] section {{
        background: linear-gradient(145deg, #10B981 0%, #059669 55%, #047857 100%) !important;
        border: none !important;
        box-shadow: 0 10px 28px rgba(16, 185, 129, 0.38) !important;
        border-radius: 20px !important;
        width: 100% !important;
        min-height: 132px !important;
        height: auto !important;
        max-width: 100% !important;
        margin: 0 auto !important;
        display: flex;
        flex-direction: column;
        justify-content: center;
        align-items: center;
        position: relative;
        padding: 20px 16px !important;
        box-sizing: border-box !important;
        transition: transform 0.18s ease, box-shadow 0.18s ease !important;
    }}
    [data-testid="stFileUploader"] section:active {{
        transform: scale(0.98);
        box-shadow: 0 6px 20px rgba(16, 185, 129, 0.45) !important;
    }}
    [data-testid="stFileUploader"] section > div {{ display: none !important; }}
    [data-testid="stFileUploader"] section small {{ display: none !important; }}
    [data-testid="stFileUploader"] section span {{ display: none !important; }}
    [data-testid="stFileUploader"] section::before {{
        content: "📸";
        font-size: clamp(36px, 11vw, 48px);
        margin-bottom: 8px;
        line-height: 1;
        filter: drop-shadow(0 2px 4px rgba(0,0,0,0.12));
    }}
    [data-testid="stFileUploader"] section::after {{
        content: "{_uploader_ph}";
        font-size: clamp(17px, 4.8vw, 22px);
        font-weight: 800;
        color: #ffffff;
        text-align: center;
        line-height: 1.35;
        max-width: 92%;
        letter-spacing: -0.02em;
    }}
    [data-testid="stFileUploader"] section button {{
        opacity: 0 !important;
        position: absolute !important;
        inset: 0 !important;
        width: 100% !important;
        height: 100% !important;
        z-index: 10;
        cursor: pointer;
        margin: 0 !important;
    }}
    /* 업로드 카드 외곽 여백 */
    div[data-testid="element-container"]:has([data-testid="stFileUploader"]) {{
        margin-bottom: 6px !important;
    }}

    /* ──────────────────────────────────────────────────────────────────
       업로드 성공 후 Streamlit 기본 UI (초록 아이콘 + 파일명 행) 완전 제거
       - stUploadedFile 자체
       - 그것을 감싸는 모든 부모 wrapper div (> div:has)
       - 내부 썸네일·캡션·progress
    ────────────────────────────────────────────────────────────────── */
    [data-testid="stUploadedFile"] {{
        display: none !important;
        visibility: hidden !important;
        height: 0 !important;
        overflow: hidden !important;
        margin: 0 !important;
        padding: 0 !important;
    }}
    [data-testid="stFileUploader"] > div:has([data-testid="stUploadedFile"]) {{
        display: none !important;
    }}
    [data-testid="stFileUploader"] [data-testid="stFileDropzoneInstructions"],
    [data-testid="stFileUploader"] [data-testid="stImage"],
    [data-testid="stFileUploader"] [data-testid="stCaption"],
    [data-testid="stFileUploader"] [data-testid="stTick"],
    [data-testid="stFileUploader"] [data-baseweb="progress-bar"],
    [data-testid="stFileUploader"] span.uploadedFileData,
    [data-testid="stFileUploader"] small {{
        display: none !important;
    }}

    /* ──────────────────────────────────────────────────────────────────
       2:3 분석 결과 카드 (순수 HTML flex — Streamlit column 미의존)
    ────────────────────────────────────────────────────────────────── */
    .ns-result-card {{
        background: #ffffff;
        border-radius: 20px;
        box-shadow: 0 8px 24px rgba(0,0,0,0.08);
        padding: 14px 14px 6px 14px;
        margin: 0 0 4px 0;
        box-sizing: border-box;
        width: 100%;
    }}
    .ns-result-card-row {{
        display: flex;
        flex-direction: row;
        gap: 12px;
        align-items: stretch;
        width: 100%;
        box-sizing: border-box;
    }}
    .ns-result-card-left {{
        flex: 2 1 0;
        min-width: 0;
    }}
    .ns-result-card-right {{
        flex: 3 1 0;
        min-width: 0;
        display: flex;
        flex-direction: column;
        justify-content: flex-start;
    }}
    .ns-rc-img-wrap {{
        width: 100%;
        border-radius: 14px;
        overflow: hidden;
        box-shadow: 0 6px 18px rgba(15,23,42,0.13);
        border: 1px solid rgba(226,232,240,0.9);
        box-sizing: border-box;
        aspect-ratio: 1 / 1;
        background: #f1f5f9;
    }}
    .ns-rc-img {{
        width: 100%;
        height: 100%;
        display: block;
        object-fit: cover;
    }}
    .ns-rc-img-empty {{
        min-height: 90px;
        aspect-ratio: auto;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 11px;
        color: #64748b;
        text-align: center;
        line-height: 1.45;
        padding: 12px;
    }}
    .ns-rc-menu-label {{
        font-size: 10px;
        font-weight: 700;
        color: #64748b;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        margin-bottom: 5px;
    }}
    .ns-rc-menu-body {{ margin-bottom: 10px; flex: 1; }}
    .ns-menu-line {{
        font-size: clamp(1rem, 3.0vw, 1.2rem);
        font-weight: 800;
        color: #0f172a;
        line-height: 1.45;
        margin-bottom: 4px;
        letter-spacing: -0.03em;
    }}
    .ns-rc-loc {{
        font-size: 0.88rem;
        font-weight: 700;
        color: #475569;
        margin-bottom: 4px;
    }}

    /* ──────────────────────────────────────────────────────────────────
       Vision AI 로딩 카드 — pulse + bounce dots + sliding progress bar
    ────────────────────────────────────────────────────────────────── */
    .ns-loading-card {{
        background: #ffffff;
        border-radius: 20px;
        box-shadow: 0 8px 24px rgba(0,0,0,0.08);
        padding: 22px 18px 18px 18px;
        margin: 0 0 10px 0;
        box-sizing: border-box;
    }}
    .ns-loading-row {{
        display: flex;
        align-items: center;
        gap: 14px;
        margin-bottom: 16px;
    }}
    .ns-loading-icon {{
        font-size: 2.2rem;
        flex-shrink: 0;
        animation: ns-pulse 1.4s ease-in-out infinite;
        line-height: 1;
    }}
    .ns-loading-text-wrap {{ flex: 1; min-width: 0; }}
    .ns-loading-title {{
        font-size: clamp(0.85rem, 2.7vw, 0.98rem);
        font-weight: 700;
        color: #0f172a;
        line-height: 1.45;
        word-break: keep-all;
    }}
    .ns-loading-dots {{
        display: flex;
        gap: 5px;
        margin-top: 8px;
    }}
    .ns-loading-dots span {{
        width: 8px;
        height: 8px;
        border-radius: 50%;
        background: #10B981;
        display: inline-block;
        animation: ns-bounce 1.2s ease-in-out infinite;
    }}
    .ns-loading-dots span:nth-child(1) {{ animation-delay: 0s; }}
    .ns-loading-dots span:nth-child(2) {{ animation-delay: 0.2s; }}
    .ns-loading-dots span:nth-child(3) {{ animation-delay: 0.4s; }}
    .ns-loading-bar-track {{
        height: 4px;
        background: rgba(16,185,129,0.15);
        border-radius: 999px;
        overflow: hidden;
    }}
    .ns-loading-bar-fill {{
        height: 100%;
        width: 40%;
        background: linear-gradient(90deg, #10B981, #34d399);
        border-radius: 999px;
        animation: ns-loading-slide 1.8s ease-in-out infinite;
    }}
    @keyframes ns-pulse {{
        0%,100% {{ transform: scale(1); opacity: 1; }}
        50% {{ transform: scale(1.15); opacity: 0.7; }}
    }}
    @keyframes ns-bounce {{
        0%,100% {{ transform: translateY(0); opacity: 0.4; }}
        50% {{ transform: translateY(-6px); opacity: 1; }}
    }}
    @keyframes ns-loading-slide {{
        0%   {{ transform: translateX(-150%); }}
        100% {{ transform: translateX(350%); }}
    }}
    /* ── 식후 혈당 피드백 카드 ──────────────────────────────────────────── */
    .ns-postmeal-header {{
        margin-bottom: 14px;
    }}
    .ns-postmeal-title {{
        font-size: 1.05rem;
        font-weight: 800;
        color: #0f172a;
        margin-bottom: 4px;
        letter-spacing: -0.3px;
    }}
    .ns-postmeal-sub {{
        font-size: 0.82rem;
        color: #64748b;
        line-height: 1.5;
        margin-bottom: 6px;
    }}
    .ns-pm-menu-echo {{
        font-size: 0.8rem;
        color: #475569;
        background: #f1f5f9;
        border-radius: 8px;
        padding: 6px 10px;
        margin-top: 6px;
        word-break: keep-all;
    }}
    /* ── 일지 대시보드: 요약 위젯 카드 ────────────────────────────────────── */
    .ns-hist-sum-card {{
        background: #ffffff;
        border-radius: 20px;
        box-shadow: 0 6px 20px rgba(0,0,0,0.07);
        padding: 14px 10px 12px;
        text-align: center;
        min-height: 110px;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        gap: 2px;
    }}
    .ns-hist-sum-icon {{
        font-size: 1.5rem;
        margin-bottom: 2px;
    }}
    .ns-hist-sum-title {{
        font-size: 0.72rem;
        color: #64748b;
        font-weight: 600;
        letter-spacing: 0.01em;
        white-space: nowrap;
    }}
    .ns-hist-sum-value {{
        font-size: 1.7rem;
        font-weight: 900;
        line-height: 1.1;
        letter-spacing: -1px;
    }}
    .ns-hist-sum-unit {{
        font-size: 0.75rem;
        font-weight: 600;
        opacity: 0.7;
        margin-left: 1px;
    }}
    .ns-hist-sum-sub {{
        font-size: 0.72rem;
        font-weight: 700;
        margin-top: 1px;
    }}
    /* ── 일지 타임라인 아이템 ──────────────────────────────────────────────── */
    .ns-tl-time {{
        font-size: 0.75rem;
        color: #94a3b8;
        font-weight: 600;
        letter-spacing: 0.02em;
        margin-bottom: 8px;
    }}
    .ns-tl-row {{
        display: flex;
        align-items: flex-start;
        gap: 12px;
        margin-bottom: 6px;
    }}
    .ns-tl-badge {{
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        border-radius: 14px;
        padding: 8px 10px;
        min-width: 54px;
        flex-shrink: 0;
        gap: 1px;
    }}
    .ns-tl-badge-icon {{ font-size: 1.2rem; line-height: 1; }}
    .ns-tl-badge-score {{
        font-size: 1.1rem;
        font-weight: 900;
        line-height: 1;
    }}
    .ns-tl-badge-label {{
        font-size: 0.62rem;
        font-weight: 700;
        white-space: nowrap;
    }}
    .ns-tl-body {{ flex: 1 1 0; min-width: 0; }}
    .ns-tl-menu {{
        font-size: 0.95rem;
        font-weight: 700;
        color: #0f172a;
        word-break: keep-all;
        line-height: 1.35;
        margin-bottom: 5px;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }}
    .ns-tl-macros {{
        font-size: 0.78rem;
        color: #64748b;
        line-height: 1.5;
    }}
    .ns-tl-advice {{
        font-size: 0.88rem;
        color: #334155;
        line-height: 1.7;
        white-space: pre-wrap;
    }}
    /* ── 일지 환영 카드 (다크 그린 그라디언트) ──────────────────────────── */
    .ns-hist-welcome-card {{
        background: linear-gradient(135deg, #064e3b 0%, #065f46 50%, #047857 100%);
        border-radius: 20px;
        padding: 20px 22px 18px;
        margin-bottom: 16px;
        color: #ffffff;
        box-shadow: 0 8px 24px rgba(6,78,59,0.25);
    }}
    .ns-hist-welcome-sub {{
        font-size: 0.72rem;
        color: rgba(255,255,255,0.65);
        font-weight: 600;
        letter-spacing: 0.05em;
        text-transform: uppercase;
        margin-bottom: 6px;
    }}
    .ns-hist-welcome-title {{
        font-size: 1.2rem;
        font-weight: 800;
        line-height: 1.4;
        letter-spacing: -0.3px;
        margin-bottom: 8px;
    }}
    .ns-hist-welcome-hint {{
        font-size: 0.78rem;
        color: rgba(255,255,255,0.6);
    }}
    /* ── 차트 타이틀 ────────────────────────────────────────────────────── */
    .ns-chart-title {{
        font-size: 0.9rem;
        font-weight: 700;
        color: #0f172a;
        padding: 2px 0 8px;
        letter-spacing: -0.2px;
    }}

    /* ── 혈당 탭 전용 스타일 ────────────────────────────────────────────── */
    .ns-glucose-header {{
        background: linear-gradient(135deg, #0f172a 0%, #1e293b 60%, #1a2a40 100%);
        border-radius: 20px;
        padding: 20px 22px 18px;
        margin-bottom: 16px;
        color: #ffffff;
        box-shadow: 0 8px 28px rgba(15,23,42,0.30);
    }}
    .ns-glucose-header-sub {{
        font-size: 0.70rem;
        color: rgba(248,113,113,0.80);
        font-weight: 700;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        margin-bottom: 6px;
    }}
    .ns-glucose-header-title {{
        font-size: 1.25rem;
        font-weight: 800;
        line-height: 1.35;
        letter-spacing: -0.3px;
        margin-bottom: 7px;
    }}
    .ns-glucose-header-hint {{
        font-size: 0.76rem;
        color: rgba(255,255,255,0.55);
    }}
    /* 오늘의 공복 혈당 카드 */
    .ns-glucose-fasting-card {{
        background: #ffffff;
        border-radius: 18px;
        padding: 18px 20px 16px;
        margin-bottom: 14px;
        box-shadow: 0 4px 16px rgba(0,0,0,0.07);
    }}
    .ns-glucose-fasting-title {{
        font-size: 0.78rem;
        font-weight: 700;
        color: #64748b;
        letter-spacing: 0.03em;
        margin-bottom: 10px;
    }}
    .ns-glucose-fasting-body {{
        display: flex;
        align-items: baseline;
        gap: 8px;
    }}
    .ns-glucose-fasting-val {{
        font-size: 2.6rem;
        font-weight: 900;
        line-height: 1;
        letter-spacing: -1px;
    }}
    .ns-glucose-fasting-unit {{
        font-size: 0.85rem;
        font-weight: 600;
        color: #94a3b8;
        align-self: flex-end;
        padding-bottom: 4px;
    }}
    .ns-glucose-fasting-label {{
        font-size: 0.82rem;
        font-weight: 700;
        align-self: flex-end;
        padding-bottom: 4px;
        margin-left: 4px;
    }}
    .ns-glucose-fasting-empty {{
        font-size: 1rem;
        color: #cbd5e1;
        font-style: italic;
        padding: 6px 0;
    }}
    /* 입력 폼 */
    .ns-glucose-form-title {{
        font-size: 0.95rem;
        font-weight: 800;
        color: #0f172a;
        letter-spacing: -0.2px;
        margin-bottom: 12px;
        padding-bottom: 10px;
        border-bottom: 1.5px solid #f1f5f9;
    }}
    .ns-glucose-input-label {{
        font-size: 0.80rem;
        font-weight: 600;
        color: #475569;
        margin: 8px 0 4px;
    }}
    /* 기록 히스토리 아이템 */
    .ns-glucose-history-item {{
        display: flex;
        align-items: center;
        justify-content: space-between;
        background: #ffffff;
        border-radius: 14px;
        padding: 12px 16px;
        margin-bottom: 8px;
        box-shadow: 0 2px 10px rgba(0,0,0,0.05);
    }}
    .ns-glucose-history-left {{
        display: flex;
        flex-direction: column;
        gap: 2px;
    }}
    .ns-glucose-history-type {{
        font-size: 0.88rem;
        font-weight: 700;
        color: #1e293b;
    }}
    .ns-glucose-history-time {{
        font-size: 0.73rem;
        color: #94a3b8;
        font-weight: 500;
    }}
    .ns-glucose-history-val {{
        font-size: 1.5rem;
        font-weight: 900;
        letter-spacing: -0.5px;
    }}
    .ns-glucose-history-unit {{
        font-size: 0.72rem;
        color: #94a3b8;
        font-weight: 500;
    }}

    /* ── 성과 탭 전용 스타일 ─────────────────────────────────────────────── */
    .ns-ach-header {{
        background: linear-gradient(135deg, #1c1208 0%, #2d1f0a 50%, #3d2b10 100%);
        border-radius: 20px;
        padding: 20px 22px 18px;
        margin-bottom: 16px;
        color: #ffffff;
        box-shadow: 0 8px 28px rgba(184,134,11,0.22);
    }}
    .ns-ach-header-sub {{
        font-size: 0.70rem;
        color: rgba(240,192,64,0.85);
        font-weight: 700;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        margin-bottom: 6px;
    }}
    .ns-ach-header-title {{
        font-size: 1.25rem;
        font-weight: 800;
        line-height: 1.35;
        letter-spacing: -0.3px;
        margin-bottom: 7px;
    }}
    .ns-ach-header-hint {{
        font-size: 0.76rem;
        color: rgba(255,255,255,0.50);
    }}
    /* 등급 카드 */
    .ns-ach-grade-card {{
        border-radius: 20px;
        padding: 22px 20px 18px;
        margin-bottom: 14px;
        text-align: center;
    }}
    .ns-ach-grade-label {{
        font-size: 0.75rem;
        font-weight: 700;
        letter-spacing: 0.06em;
        text-transform: uppercase;
        margin-bottom: 8px;
    }}
    .ns-ach-grade-letter {{
        font-size: 5rem;
        font-weight: 900;
        line-height: 1;
        letter-spacing: -3px;
        margin-bottom: 18px;
        text-shadow: 0 4px 12px rgba(0,0,0,0.15);
    }}
    .ns-ach-grade-stats {{
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 0;
    }}
    .ns-ach-stat-item {{
        flex: 1;
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 4px;
    }}
    .ns-ach-stat-val {{
        font-size: 1.2rem;
        font-weight: 800;
        letter-spacing: -0.5px;
        color: #1e293b;
    }}
    .ns-ach-stat-key {{
        font-size: 0.68rem;
        color: #64748b;
        font-weight: 600;
    }}
    .ns-ach-stat-divider {{
        width: 1px;
        height: 32px;
        background: rgba(0,0,0,0.12);
        margin: 0 4px;
    }}
    /* AI 코멘트 카드 */
    .ns-ach-comment-card {{
        background: #ffffff;
        border-radius: 16px;
        padding: 16px 18px;
        margin-bottom: 4px;
        display: flex;
        align-items: flex-start;
        gap: 12px;
        box-shadow: 0 2px 10px rgba(0,0,0,0.06);
    }}
    .ns-ach-comment-icon {{
        font-size: 1.6rem;
        line-height: 1;
        flex-shrink: 0;
    }}
    .ns-ach-comment-text {{
        font-size: 0.88rem;
        font-weight: 600;
        color: #1e293b;
        line-height: 1.55;
    }}
    /* 뱃지 그리드 */
    .ns-ach-badge-grid {{
        display: grid;
        grid-template-columns: repeat(4, 1fr);
        gap: 10px;
        margin-top: 10px;
        margin-bottom: 20px;
    }}
    @media (max-width: 480px) {{
        .ns-ach-badge-grid {{
            grid-template-columns: repeat(4, 1fr);
            gap: 7px;
        }}
    }}
    .ns-ach-badge {{
        border-radius: 14px;
        padding: 12px 6px 10px;
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 5px;
        position: relative;
        text-align: center;
    }}
    .ns-ach-badge-on {{
        background: #ffffff;
        box-shadow: 0 4px 14px rgba(0,0,0,0.08);
        animation: ns-badge-shine 2.4s ease-in-out infinite alternate;
    }}
    .ns-ach-badge-off {{
        background: #f8fafc;
        box-shadow: inset 0 0 0 1.5px #e2e8f0;
    }}
    @keyframes ns-badge-shine {{
        from {{ box-shadow: 0 4px 14px rgba(0,0,0,0.07); }}
        to   {{ box-shadow: 0 4px 20px rgba(16,185,129,0.22); }}
    }}
    .ns-ach-badge-emoji {{
        font-size: 1.6rem;
        line-height: 1;
    }}
    .ns-ach-badge-lock {{
        position: absolute;
        top: 6px;
        right: 6px;
        font-size: 0.65rem;
        opacity: 0.5;
    }}
    .ns-ach-badge-name {{
        font-size: 0.62rem;
        font-weight: 700;
        color: #1e293b;
        line-height: 1.2;
    }}
    .ns-ach-badge-desc {{
        font-size: 0.55rem;
        color: #64748b;
        line-height: 1.3;
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
    
    /* ══════════════════════════════════════════════════════════════════════
       상단 공백 최소화 — Ghost 요소 제거 후 정상 CSS
       ══════════════════════════════════════════════════════════════════════ */

    /* Streamlit 기본 헤더 완전 삭제 */
    header[data-testid="stHeader"] {{
        display: none !important;
        height: 0px !important;
        overflow: hidden !important;
    }}

    /* 메인 컨테이너 상단 패딩 0px 강제 — 네이티브 앱 상단 밀착 */
    .block-container,
    [data-testid="stMainBlockContainer"],
    [data-testid="stAppViewBlockContainer"],
    .stMainBlockContainer,
    .main {{
        padding-top: 0px !important;
        margin-top: 0px !important;
        padding-left: 1rem !important;
        padding-right: 1rem !important;
        padding-bottom: 1rem !important;
        max-width: 100% !important;
    }}

    /* 첫 번째 요소(프리미엄 헤더) 상단 완전 밀착 */
    .block-container > div:first-child,
    [data-testid="stMainBlockContainer"] > div:first-child {{
        padding-top: 0px !important;
        margin-top: 0px !important;
    }}

    /* 모바일 + FAB 영역 확보 */
    @media screen and (max-width: 768px) {{
        .block-container,
        [data-testid="stMainBlockContainer"],
        .stMainBlockContainer,
        .main {{
            padding-top: 0px !important;
            margin-top: 0px !important;
            padding-left: 0.3rem !important;
            padding-right: 0.3rem !important;
            padding-bottom: calc(120px + env(safe-area-inset-bottom, 20px)) !important;
        }}
        .block-container > div:first-child,
        [data-testid="stMainBlockContainer"] > div:first-child {{
            padding-top: 0px !important;
            margin-top: 0px !important;
        }}
    }}
    /* 메트릭 내부 요소 텍스트 짤림 완벽 방지 */
    div[data-testid="stMetricValue"] > div,
    div[data-testid="stMetricLabel"] > div,
    div[data-testid="stMetricValue"],
    div[data-testid="stMetricLabel"] {{
        white-space: normal !important;
        word-break: keep-all !important;
        overflow-wrap: break-word !important;
        overflow: visible !important;
        text-overflow: clip !important;
        line-height: 1.2 !important;
    }}
    div[data-testid="stMetricLabel"] *, div[data-testid="stMetricValue"] * {{
        white-space: normal !important;
        word-break: keep-all !important;
        overflow-wrap: break-word !important;
        overflow: visible !important;
        text-overflow: clip !important;
        line-height: 1.2 !important;
    }}
    div[data-testid="stMetricLabel"] * {{ font-size: 13px !important; }}
    div[data-testid="stMetricValue"] * {{ font-size: 18px !important; }}
    /*
     * 하단 바: :has(> 첫째 element-container .bottom-bar-anchor.main-nav|result-nav) 만 매칭 → 본문 stVerticalBlock 전염 차단.
     */
    div[data-testid="stVerticalBlock"]:has(> div.element-container:nth-child(1) .bottom-bar-anchor.main-nav),
    div[data-testid="stVerticalBlock"]:has(> div.element-container:nth-child(1) .bottom-bar-anchor.result-nav),
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="element-container"]:nth-child(1) .bottom-bar-anchor.main-nav),
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="element-container"]:nth-child(1) .bottom-bar-anchor.result-nav) {{
        position: fixed !important;
        bottom: 0;
        left: 0;
        right: 0;
        display: flex !important;
        flex-direction: row !important;
        flex-wrap: nowrap !important;
        justify-content: space-around !important;
        align-items: center !important;
        height: 65px !important;
        min-height: 65px !important;
        background: #f4f5f7 !important;
        backdrop-filter: blur(15px);
        -webkit-backdrop-filter: blur(15px);
        z-index: 99999 !important;
        padding: 0 !important;
        padding-bottom: env(safe-area-inset-bottom, 0px) !important;
        border-top: 1px solid rgba(0, 0, 0, 0.06) !important;
        box-shadow: 0 -3px 15px rgba(0, 0, 0, 0.04) !important;
        gap: 0 !important;
        box-sizing: content-box !important;
        overflow: visible !important;
    }}
    div[data-testid="stVerticalBlock"]:has(> div.element-container:nth-child(1) .bottom-bar-anchor.main-nav) > div.element-container:nth-child(1),
    div[data-testid="stVerticalBlock"]:has(> div.element-container:nth-child(1) .bottom-bar-anchor.result-nav) > div.element-container:nth-child(1),
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="element-container"]:nth-child(1) .bottom-bar-anchor.main-nav) > div[data-testid="element-container"]:nth-child(1),
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="element-container"]:nth-child(1) .bottom-bar-anchor.result-nav) > div[data-testid="element-container"]:nth-child(1) {{
        display: none !important;
        width: 0 !important;
        flex: 0 0 0 !important;
        min-width: 0 !important;
        padding: 0 !important;
        margin: 0 !important;
        overflow: hidden !important;
    }}
    div[data-testid="stVerticalBlock"]:has(> div.element-container:nth-child(1) .bottom-bar-anchor.main-nav) > div.element-container,
    div[data-testid="stVerticalBlock"]:has(> div.element-container:nth-child(1) .bottom-bar-anchor.main-nav) > div[data-testid="element-container"],
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="element-container"]:nth-child(1) .bottom-bar-anchor.main-nav) > div.element-container,
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="element-container"]:nth-child(1) .bottom-bar-anchor.main-nav) > div[data-testid="element-container"] {{
        width: 16.667% !important;
        min-width: 16.667% !important;
        max-width: 16.667% !important;
        flex: 1 1 16.667% !important;
        display: flex !important;
        justify-content: center !important;
        align-items: center !important;
        box-sizing: border-box !important;
    }}
    /* nth-child(4) FAB 위치 기준 블록 제거 — 플랫 통일 디자인으로 대체 */
    div[data-testid="stVerticalBlock"]:has(> div.element-container:nth-child(1) .bottom-bar-anchor.result-nav) > div.element-container:not(:nth-child(1)),
    div[data-testid="stVerticalBlock"]:has(> div.element-container:nth-child(1) .bottom-bar-anchor.result-nav) > div[data-testid="element-container"]:not(:nth-child(1)),
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="element-container"]:nth-child(1) .bottom-bar-anchor.result-nav) > div.element-container:not(:nth-child(1)),
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="element-container"]:nth-child(1) .bottom-bar-anchor.result-nav) > div[data-testid="element-container"]:not(:nth-child(1)) {{
        width: 50% !important;
        min-width: 50% !important;
        max-width: 50% !important;
        flex: 1 1 50% !important;
        display: flex !important;
        justify-content: center !important;
        align-items: center !important;
        box-sizing: border-box !important;
    }}
    div[data-testid="stVerticalBlock"]:has(> div.element-container:nth-child(1) .bottom-bar-anchor.main-nav) button,
    div[data-testid="stVerticalBlock"]:has(> div.element-container:nth-child(1) .bottom-bar-anchor.result-nav) button,
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="element-container"]:nth-child(1) .bottom-bar-anchor.main-nav) button,
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="element-container"]:nth-child(1) .bottom-bar-anchor.result-nav) button {{
        background: transparent !important;
        border: none !important;
        box-shadow: none !important;
        width: 100% !important;
        height: 100% !important;
        padding: 10px 0 !important;
    }}
    div[data-testid="stVerticalBlock"]:has(> div.element-container:nth-child(1) .bottom-bar-anchor.main-nav) button p,
    div[data-testid="stVerticalBlock"]:has(> div.element-container:nth-child(1) .bottom-bar-anchor.result-nav) button p,
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="element-container"]:nth-child(1) .bottom-bar-anchor.main-nav) button p,
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="element-container"]:nth-child(1) .bottom-bar-anchor.result-nav) button p {{
        font-size: 13px !important;
        color: #444 !important;
        font-weight: 700 !important;
        line-height: 1.4 !important;
        margin: 0 !important;
        white-space: pre-line !important;
        display: flex;
        flex-direction: column;
        align-items: center;
        text-align: center !important;
    }}
    /* FAB 특수 스타일 제거 — 모든 6탭 플랫(Flat) 통일 디자인 적용 */
    div[data-testid="stVerticalBlock"]:has(> div > div > div[data-testid="stVerticalBlock"] .bottom-bar-anchor.main-nav),
    div[data-testid="stVerticalBlock"]:has(> div > div > div[data-testid="stVerticalBlock"] .bottom-bar-anchor.result-nav) {{
        position: static !important;
        display: block !important;
        background: transparent !important;
        box-shadow: none !important;
        padding: 0 !important;
        border-top: none !important;
        backdrop-filter: none !important;
        -webkit-backdrop-filter: none !important;
    }}
    @media screen and (max-width: 768px) {{
        div[data-testid="stVerticalBlock"]:has(> div.element-container:nth-child(1) .bottom-bar-anchor.main-nav),
        div[data-testid="stVerticalBlock"]:has(> div.element-container:nth-child(1) .bottom-bar-anchor.result-nav),
        div[data-testid="stVerticalBlock"]:has(> div[data-testid="element-container"]:nth-child(1) .bottom-bar-anchor.main-nav),
        div[data-testid="stVerticalBlock"]:has(> div[data-testid="element-container"]:nth-child(1) .bottom-bar-anchor.result-nav) {{
            display: flex !important;
            flex-direction: row !important;
            flex-wrap: nowrap !important;
        }}
        div[data-testid="stVerticalBlock"]:has(> div.element-container:nth-child(1) .bottom-bar-anchor.main-nav) > div.element-container,
        div[data-testid="stVerticalBlock"]:has(> div.element-container:nth-child(1) .bottom-bar-anchor.main-nav) > div[data-testid="element-container"],
        div[data-testid="stVerticalBlock"]:has(> div[data-testid="element-container"]:nth-child(1) .bottom-bar-anchor.main-nav) > div.element-container,
        div[data-testid="stVerticalBlock"]:has(> div[data-testid="element-container"]:nth-child(1) .bottom-bar-anchor.main-nav) > div[data-testid="element-container"] {{
            width: 16.667% !important;
            min-width: 16.667% !important;
            max-width: 16.667% !important;
            flex: 1 1 16.667% !important;
        }}
        div[data-testid="stVerticalBlock"]:has(> div.element-container:nth-child(1) .bottom-bar-anchor.result-nav) > div.element-container:not(:nth-child(1)),
        div[data-testid="stVerticalBlock"]:has(> div.element-container:nth-child(1) .bottom-bar-anchor.result-nav) > div[data-testid="element-container"]:not(:nth-child(1)),
        div[data-testid="stVerticalBlock"]:has(> div[data-testid="element-container"]:nth-child(1) .bottom-bar-anchor.result-nav) > div.element-container:not(:nth-child(1)),
        div[data-testid="stVerticalBlock"]:has(> div[data-testid="element-container"]:nth-child(1) .bottom-bar-anchor.result-nav) > div[data-testid="element-container"]:not(:nth-child(1)) {{
            width: 50% !important;
            min-width: 50% !important;
            max-width: 50% !important;
            flex: 1 1 50% !important;
        }}
    }}
    div[data-testid="stAppViewBlockContainer"] {{
        padding-bottom: calc(120px + env(safe-area-inset-bottom, 20px)) !important;
    }}
    /* Metric이 있는 가로 행: 모바일에서 2열(2x2) 강제 */
    @media screen and (max-width: 768px) {{
        div[data-testid="stHorizontalBlock"]:has([data-testid="stMetric"]) {{
            flex-wrap: nowrap !important;
            gap: 0.25rem !important;
        }}
        div[data-testid="stHorizontalBlock"]:has([data-testid="stMetric"]) > div[data-testid="column"] {{
            flex: 1 1 calc(50% - 4px) !important;
            min-width: 0 !important;
            max-width: 50% !important;
        }}
    }}

    /* stUploadedFile 숨김 — 위 블록과 중복 강화 */
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

# ──────────────────────────────────────────────────────────────────────────────
# PWA 메타 태그 + 스플래시 스크린 (Phase 7)
# ──────────────────────────────────────────────────────────────────────────────
import streamlit.components.v1 as _stc_pwa

# ① PWA 메타 태그: window.parent.document.head에 직접 주입 (JS via iframe)
_stc_pwa.html(
    """
<script>
(function() {
    try {
        var doc = window.parent.document;
        var head = doc.head;
        var _metas = [
            { name: "apple-mobile-web-app-capable",          content: "yes" },
            { name: "apple-mobile-web-app-status-bar-style", content: "black-translucent" },
            { name: "mobile-web-app-capable",                content: "yes" },
            { name: "apple-mobile-web-app-title",            content: "혈당스캐너" },
            { name: "theme-color",                           content: "#0f172a" },
            { name: "viewport",
              content: "width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover" },
        ];
        _metas.forEach(function(m) {
            var sel = m.name === "viewport"
                ? 'meta[name="viewport"]'
                : 'meta[name="' + m.name + '"]';
            if (!doc.querySelector(sel)) {
                var el = doc.createElement("meta");
                el.name    = m.name;
                el.content = m.content;
                head.appendChild(el);
            } else if (m.name === "viewport") {
                doc.querySelector(sel).content = m.content;
            }
        });

        // ② 스플래시 스크린: 2.5초 후 DOM에서 완전 제거
        setTimeout(function() {
            var splash = doc.getElementById("ns-splash-screen");
            if (splash) {
                splash.style.opacity    = "0";
                splash.style.transition = "opacity 0.55s ease";
                setTimeout(function() {
                    splash.style.display         = "none";
                    splash.style.pointerEvents   = "none";
                    splash.style.visibility      = "hidden";
                }, 580);
            }
        }, 2200);
    } catch(e) {}
})();
</script>
""",
    height=0,
    scrolling=False,
)

# ② 스플래시 스크린 HTML (첫 세션 로드 시 1회만 표시)
if "_pwa_splash_shown" not in st.session_state:
    st.session_state["_pwa_splash_shown"] = True
    st.markdown(
        """
<div id="ns-splash-screen">
  <div id="ns-splash-inner">
    <div class="ns-splash-emoji">🩸</div>
    <div class="ns-splash-title">나의 혈당 기록소</div>
    <div class="ns-splash-sub">AI 코치가 분석을 준비하고 있습니다</div>
    <div class="ns-splash-dots">
      <span></span><span></span><span></span>
    </div>
  </div>
</div>
<style>
#ns-splash-screen {
    position: fixed;
    top: 0; left: 0; right: 0; bottom: 0;
    background: #0f172a;
    z-index: 99999;
    display: flex;
    align-items: center;
    justify-content: center;
    animation: ns-splash-in 0.35s ease-out both;
}
#ns-splash-inner {
    text-align: center;
    animation: ns-splash-rise 0.55s cubic-bezier(0.22,1,0.36,1) 0.15s both;
}
.ns-splash-emoji {
    font-size: 4.5rem;
    line-height: 1;
    margin-bottom: 18px;
    animation: ns-splash-pulse 1.6s ease-in-out infinite;
}
.ns-splash-title {
    font-family: 'Noto Sans KR', sans-serif;
    font-size: 1.45rem;
    font-weight: 800;
    color: #ffffff;
    letter-spacing: -0.4px;
    margin-bottom: 8px;
}
.ns-splash-sub {
    font-size: 0.80rem;
    color: rgba(255,255,255,0.45);
    font-weight: 400;
    margin-bottom: 32px;
}
.ns-splash-dots {
    display: flex;
    justify-content: center;
    gap: 8px;
}
.ns-splash-dots span {
    width: 7px; height: 7px;
    border-radius: 50%;
    background: rgba(16,185,129,0.7);
    animation: ns-splash-dot 1.2s ease-in-out infinite;
}
.ns-splash-dots span:nth-child(2) { animation-delay: 0.2s; }
.ns-splash-dots span:nth-child(3) { animation-delay: 0.4s; }
@keyframes ns-splash-in {
    from { opacity: 0; } to { opacity: 1; }
}
@keyframes ns-splash-rise {
    from { transform: translateY(24px); opacity: 0; }
    to   { transform: translateY(0);    opacity: 1; }
}
@keyframes ns-splash-pulse {
    0%, 100% { transform: scale(1);    filter: drop-shadow(0 0 0px rgba(16,185,129,0)); }
    50%       { transform: scale(1.08); filter: drop-shadow(0 0 18px rgba(16,185,129,0.6)); }
}
@keyframes ns-splash-dot {
    0%, 80%, 100% { transform: scale(0.6); opacity: 0.3; }
    40%           { transform: scale(1.1); opacity: 1; }
}
</style>
""",
        unsafe_allow_html=True,
    )

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

    # ─── 영구 자동 로그인: localStorage 인증 정보 복원 ───────────────────────
    # 로그아웃 시 localStorage 클리어 JS 주입
    if st.session_state.pop("_logout_pending_ls_clear", False):
        st.session_state["_ls_auth_revoked"] = True
        st.components.v1.html(
            "<script>try{(window.parent||window).localStorage.removeItem('bgs_auth');}catch(e){}</script>",
            height=0,
        )
    # localStorage → query param 방식으로 세션 복원
    if "__al" in st.query_params and not st.session_state.get("_ls_auth_revoked"):
        try:
            _al_raw = st.query_params.get("__al", "")
            _pad = (4 - len(_al_raw) % 4) % 4
            _al_data = json.loads(base64.b64decode(_al_raw + "=" * _pad).decode("utf-8"))
            if _al_data.get("t") in ("google", "email") and _al_data.get("u"):
                st.session_state["logged_in"] = True
                st.session_state["user_id"] = _al_data["u"]
                st.session_state["user_email"] = _al_data.get("e") or ""
                st.session_state["login_type"] = _al_data["t"]
                st.query_params.clear()
                st.rerun()
        except Exception:
            try:
                st.query_params.clear()
            except Exception:
                pass
    # ─────────────────────────────────────────────────────────────────────────

    # (__auth 처리는 파일 최상단에서 이미 완료 — 이 위치에서는 항상 미감지 상태)

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
    /* ── 프리미엄 랜딩 페이지: 다크 네이비 스킨 ── */
    body.auth-login-splash .stApp {
      background: #0f172a !important;
      min-height: 100vh !important;
    }
    /* 랜딩 페이지 전체 배경 그라디언트 광원 */
    .ns-lp-wrap {
      display: flex;
      flex-direction: column;
      align-items: center;
      min-height: 82vh;
      padding: 2.5rem 1.4rem 1rem;
      text-align: center;
      position: relative;
      overflow: hidden;
    }
    .ns-lp-glow {
      position: absolute;
      top: -60px; left: 50%;
      transform: translateX(-50%);
      width: 340px; height: 340px;
      background: radial-gradient(ellipse at 50% 30%, rgba(16,185,129,0.18) 0%, transparent 70%);
      pointer-events: none;
    }
    /* 로고 & 타이틀 */
    .ns-lp-logo {
      font-size: 4rem;
      line-height: 1;
      margin-bottom: 14px;
      animation: ns-lp-rise 0.65s cubic-bezier(0.22,1,0.36,1) 0.1s both;
      filter: drop-shadow(0 0 22px rgba(239,68,68,0.45));
    }
    .ns-lp-title {
      font-family: 'Noto Sans KR', 'Pretendard', sans-serif;
      font-size: clamp(1.55rem, 6vw, 1.9rem);
      font-weight: 900;
      color: #ffffff;
      letter-spacing: -0.6px;
      margin-bottom: 6px;
      animation: ns-lp-rise 0.65s cubic-bezier(0.22,1,0.36,1) 0.22s both;
    }
    .ns-lp-tagline {
      font-family: 'Noto Sans KR', sans-serif;
      font-size: 0.82rem;
      font-weight: 500;
      color: rgba(255,255,255,0.45);
      letter-spacing: 0.04em;
      margin-bottom: 28px;
      animation: ns-lp-rise 0.65s cubic-bezier(0.22,1,0.36,1) 0.34s both;
    }
    /* 프리미엄 차트 비주얼 */
    .ns-lp-chart-wrap {
      width: 100%;
      max-width: 320px;
      margin: 0 auto 26px;
      animation: ns-lp-rise 0.7s cubic-bezier(0.22,1,0.36,1) 0.46s both;
    }
    .ns-lp-chart-svg { overflow: visible; }
    /* 그린 안정선 */
    .ns-lp-path-safe {
      stroke-dasharray: 160;
      stroke-dashoffset: 160;
      animation: ns-lp-draw 0.9s ease-out 0.8s forwards;
    }
    /* 레드 스파이크선 */
    .ns-lp-path-spike {
      stroke-dasharray: 120;
      stroke-dashoffset: 120;
      animation: ns-lp-draw 0.7s ease-in 1.7s forwards;
    }
    .ns-lp-chart-glow {
      opacity: 0;
      animation: ns-lp-fadein 0.5s ease-out 2.3s forwards;
    }
    /* 카피 텍스트 */
    .ns-lp-copy1 {
      font-size: clamp(1rem, 4vw, 1.08rem);
      font-weight: 700;
      color: rgba(255,255,255,0.75);
      line-height: 1.55;
      margin-bottom: 10px;
      animation: ns-lp-rise 0.6s cubic-bezier(0.22,1,0.36,1) 0.58s both;
    }
    .ns-lp-copy1 em {
      font-style: normal;
      color: #fbbf24;
      font-weight: 800;
    }
    .ns-lp-copy2 {
      font-size: clamp(1.05rem, 4.3vw, 1.2rem);
      font-weight: 800;
      color: #ffffff;
      line-height: 1.5;
      margin-bottom: 36px;
      animation: ns-lp-rise 0.6s cubic-bezier(0.22,1,0.36,1) 0.7s both;
    }
    .ns-lp-copy2 em {
      font-style: normal;
      color: #10b981;
    }
    /* 시작하기 버튼 오버라이드 */
    div[data-testid="stButton"] > button[kind="primary"].ns-lp-start-btn,
    .ns-lp-btn-wrap button {
      background: linear-gradient(135deg, #059669 0%, #10b981 50%, #34d399 100%) !important;
      color: #ffffff !important;
      border: none !important;
      border-radius: 16px !important;
      font-size: 1.05rem !important;
      font-weight: 800 !important;
      height: 56px !important;
      box-shadow: 0 0 28px rgba(16,185,129,0.40), 0 4px 16px rgba(16,185,129,0.25) !important;
      letter-spacing: -0.2px !important;
    }
    @keyframes ns-lp-rise {
      from { transform: translateY(22px); opacity: 0; }
      to   { transform: translateY(0);    opacity: 1; }
    }
    @keyframes ns-lp-draw  { to { stroke-dashoffset: 0; } }
    @keyframes ns-lp-fadein { to { opacity: 1; } }
    /* 구형 CSS 잔재 (호환용 빈 선언) */
    .splash-container, .splash-title, .splash-subtitle-line1,
    .splash-subtitle-line2, .spike-crash-animation { display: none !important; }
    @keyframes fade-in-up  { 0%{opacity:0}100%{opacity:1} }
    @keyframes fade-in     { to { opacity: 1; } }
    @keyframes draw-line   { to { stroke-dashoffset: 0; } }
    @keyframes flash-slash, break-and-fall, tracking-in {}
    .auth-sheet-enter main .block-container { animation: authSlideUp 0.42s ease-out; }
    @keyframes authSlideUp { from { transform: translateY(72%); opacity: 0.65; } to { transform: translateY(0); opacity: 1; } }
    /* ── 전체 배경 다크 네이비 강제 (약관/중간 화면 포함) ── */
    body.auth-login-splash section[tabindex="0"],
    body.auth-login-splash [data-testid="stAppViewContainer"],
    body.auth-login-splash .block-container {
      background: #0f172a !important;
    }
    /* ── 소셜/일반 버튼: 다크 글래스모피즘 ─────────────────────────────
       ★ 원인: Streamlit은 버튼 텍스트를 stMarkdownContainer>p 안에 렌더링.
               .auth-mark-* + div button 선택자는 DOM 구조상 매칭 불가.
               body 클래스 스코프로 [data-testid="stButton"] > button 직접 타겟팅.
    ───────────────────────────────────────────────────────────────── */
    /* ── 스플래시 [로그인] primary 버튼 ── */
    body.auth-login-splash .stApp [data-testid="stButton"] > button[kind="primary"] {
      background: linear-gradient(135deg, #059669 0%, #10b981 100%) !important;
      color: #ffffff !important;
      border: none !important;
      border-radius: 14px !important;
      height: 52px !important;
      font-weight: 800 !important;
      font-size: 0.96rem !important;
      letter-spacing: -0.2px !important;
      box-shadow: 0 0 20px rgba(16,185,129,0.35) !important;
    }
    /* ── 스플래시 secondary 버튼 (회원가입 / 소셜 버튼들) ── */
    body.auth-login-splash .stApp [data-testid="stButton"] > button:not([kind="primary"]) {
      background: rgba(255,255,255,0.10) !important;
      color: #ffffff !important;
      border: 1px solid rgba(255,255,255,0.22) !important;
      border-radius: 14px !important;
      height: 52px !important;
      font-weight: 700 !important;
      font-size: 0.96rem !important;
      letter-spacing: -0.2px !important;
      transition: background 0.2s ease, border-color 0.2s ease !important;
    }
    body.auth-login-splash .stApp [data-testid="stButton"] > button:not([kind="primary"]):hover {
      background: rgba(255,255,255,0.18) !important;
    }
    /* ★ stMarkdownContainer p 색상 누수 → 버튼 내부 p 흰색으로 명시 교정 */
    body.auth-login-splash .stApp [data-testid="stButton"] [data-testid="stMarkdownContainer"] p {
      color: #ffffff !important;
    }
    /* 뒤로가기 버튼 높이 자동 조정 (terms 페이지) */
    body.auth-login-splash .stApp [data-testid="stButton"] > button[kind="secondary"] {
      height: auto !important;
      min-height: 42px !important;
      padding: 8px 16px !important;
    }
    /* 소셜 버튼 3개는 전체 높이 유지 (auth-soc-row 내부) */
    body.auth-login-splash .stApp .auth-soc-row ~ * [data-testid="stButton"] > button:not([kind="primary"]),
    body.auth-login-splash .stApp [data-testid="stButton"]:nth-child(-n+6) > button:not([kind="primary"]) {
      height: 52px !important;
    }
    /* 캡션 다크 오버라이드 */
    body.auth-login-splash [data-testid="stCaptionContainer"] p {
      color: rgba(255,255,255,0.38) !important;
    }
    /* ── 약관 동의 / 로그인 폼: 다크 배경 텍스트 시인성 전면 강제 ── */
    body.auth-login-splash .stApp [data-testid="stMarkdownContainer"] h1,
    body.auth-login-splash .stApp [data-testid="stMarkdownContainer"] h2,
    body.auth-login-splash .stApp [data-testid="stMarkdownContainer"] h3,
    body.auth-login-splash .stApp [data-testid="stMarkdownContainer"] h4 {
      color: #ffffff !important;
    }
    body.auth-login-splash .stApp [data-testid="stMarkdownContainer"] p,
    body.auth-login-splash .stApp [data-testid="stMarkdownContainer"] li,
    body.auth-login-splash .stApp [data-testid="stMarkdownContainer"] a {
      color: rgba(255,255,255,0.80) !important;
    }
    body.auth-login-splash .stApp [data-testid="stCheckbox"] label,
    body.auth-login-splash .stApp [data-testid="stCheckbox"] label p,
    body.auth-login-splash .stApp [data-testid="stCheckbox"] span {
      color: rgba(255,255,255,0.88) !important;
    }
    body.auth-login-splash .stApp [data-testid="stExpander"] > details {
      background: rgba(255,255,255,0.05) !important;
      border: 1px solid rgba(255,255,255,0.13) !important;
      border-radius: 12px !important;
    }
    body.auth-login-splash .stApp [data-testid="stExpander"] summary p,
    body.auth-login-splash .stApp [data-testid="stExpander"] summary span,
    body.auth-login-splash .stApp [data-testid="stExpander"] summary {
      color: rgba(255,255,255,0.78) !important;
    }
    body.auth-login-splash .stApp [data-testid="stSpinner"] p,
    body.auth-login-splash .stApp [data-testid="stSpinner"] span {
      color: #34d399 !important;
    }
    body.auth-login-splash .stApp [data-testid="stNotification"] p,
    body.auth-login-splash .stApp [data-testid="stAlert"] p {
      color: rgba(15,23,42,0.9) !important;
    }
    /* KR 단일: Facebook 버튼 제거 */
    .auth-terms-panel { border: 1px solid rgba(255,255,255,0.12); border-radius: 12px; padding: 0.75rem; background: rgba(255,255,255,0.05); max-height: 220px; overflow-y: auto; margin-top: 0.35rem; }
    /* ── 약관 동의 화면: 전체 스크롤 차단 + 박스 내부 스크롤 ── */
    body.auth-login-splash.auth-terms-page {
      overflow: hidden !important;
      height: 100dvh !important;
    }
    body.auth-login-splash.auth-terms-page .stApp,
    body.auth-login-splash.auth-terms-page [data-testid="stAppViewContainer"],
    body.auth-login-splash.auth-terms-page section[tabindex="0"] {
      overflow: hidden !important;
      height: 100dvh !important;
    }
    /* 약관: 전체 페이지 스크롤 금지 — 체크+expander는 테두리 컨테이너 안만 스크롤 */
    body.auth-login-splash.auth-terms-page .block-container {
      height: 100dvh !important;
      overflow: hidden !important;
      padding-bottom: 140px !important;
      display: flex !important;
      flex-direction: column !important;
      scrollbar-width: thin !important;
      min-height: 0 !important;
    }
    /* #59: 45vh 스크롤은 약관 6개 박스에만 (JS로 .tc-terms-scroll-only 부여) */
    body.auth-login-splash.auth-terms-page .tc-terms-scroll-only {
      max-height: 45vh !important;
      min-height: 0 !important;
      overflow-y: auto !important;
      overflow-x: hidden !important;
      flex: 0 1 auto !important;
      border-color: rgba(255,255,255,0.14) !important;
      margin: 0 0 10px 0 !important;
      -webkit-overflow-scrolling: touch !important;
    }
    body.auth-login-splash.auth-terms-page .tc-terms-scroll-only::-webkit-scrollbar {
      width: 5px;
    }
    body.auth-login-splash.auth-terms-page .tc-terms-scroll-only::-webkit-scrollbar-thumb {
      background: rgba(16,185,129,0.35);
      border-radius: 3px;
    }
    /* #59: 전체 동의 — 고정 CTA에 가리지 않도록 + flex에서 잘리지 않게 */
    body.auth-login-splash.auth-terms-page .block-container .tc-master-wrap {
      flex: 0 0 auto !important;
      min-height: 0 !important;
      max-height: none !important;
      overflow: visible !important;
      position: relative !important;
      z-index: 120 !important;
      margin-bottom: 120px !important;
    }
    /* CTA 버튼 영역: 화면 최하단 고정 */
    body.auth-login-splash.auth-terms-page div:has(> [data-testid="stButton"] > button[kind="primary"]) {
      position: fixed !important;
      bottom: 0 !important;
      left: 0 !important; right: 0 !important;
      z-index: 99 !important;
      background: linear-gradient(to top, #0f172a 70%, transparent) !important;
      padding: 12px 16px 20px !important;
    }
    /* ── 스플래시 화면 스크롤 제로 + Streamlit 크롬 완전 숨김 ── */
    body.auth-login-splash.auth-splash-screen {
      overflow: hidden !important;
      height: 100dvh !important;
      max-height: 100dvh !important;
    }
    body.auth-login-splash.auth-splash-screen .stApp,
    body.auth-login-splash.auth-splash-screen [data-testid="stAppViewContainer"],
    body.auth-login-splash.auth-splash-screen section[tabindex="0"],
    body.auth-login-splash.auth-splash-screen .block-container {
      overflow: hidden !important;
      height: 100dvh !important;
      max-height: 100dvh !important;
      padding: 0 !important;
    }
    body.auth-login-splash.auth-splash-screen header[data-testid="stHeader"],
    body.auth-login-splash.auth-splash-screen #MainMenu,
    body.auth-login-splash.auth-splash-screen footer,
    body.auth-login-splash.auth-splash-screen [data-testid="stToolbar"],
    body.auth-login-splash.auth-splash-screen [data-testid="stDecoration"],
    body.auth-login-splash.auth-splash-screen [data-testid="stStatusWidget"] {
      display: none !important;
    }
    body.auth-login-splash.auth-splash-screen .block-container {
      max-width: 100% !important;
      padding-top: 0 !important;
      padding-bottom: 0 !important;
    }
    /* ── 약관 expander 다크 스타일 (모바일 100% 안정) ── */
    body.auth-login-splash .stApp [data-testid="stExpander"] > details {
      background: rgba(255,255,255,0.04) !important;
      border: 1px solid rgba(255,255,255,0.10) !important;
      border-radius: 8px !important;
      margin-bottom: 2px !important;
    }
    body.auth-login-splash .stApp [data-testid="stExpander"] summary {
      color: rgba(52,211,153,0.85) !important;
      font-size: 0.76rem !important;
      font-weight: 600 !important;
      padding: 6px 10px !important;
    }
    body.auth-login-splash .stApp [data-testid="stExpander"] summary p,
    body.auth-login-splash .stApp [data-testid="stExpander"] summary span {
      color: rgba(52,211,153,0.85) !important;
      font-size: 0.76rem !important;
    }
    body.auth-login-splash .stApp [data-testid="stExpander"] [data-testid="stExpanderDetails"] {
      max-height: 260px !important;
      overflow-y: auto !important;
      padding: 8px 10px !important;
    }
    /* ── 마스터 "전체 동의" 체크박스 — 크고 굵게 + Glow 배경 ── */
    body.auth-login-splash .stApp .tc-master-wrap {
      background: linear-gradient(135deg,
        rgba(16,185,129,0.12) 0%,
        rgba(251,191,36,0.08) 100%) !important;
      border: 1px solid rgba(16,185,129,0.30) !important;
      border-radius: 14px !important;
      padding: 12px 14px !important;
      margin: 4px 0 8px !important;
      box-shadow: 0 0 18px rgba(16,185,129,0.18),
                  0 0 40px rgba(16,185,129,0.06) !important;
    }
    body.auth-login-splash .stApp .tc-master-wrap [data-testid="stCheckbox"] label p,
    body.auth-login-splash .stApp .tc-master-wrap [data-testid="stCheckbox"] label span,
    body.auth-login-splash .stApp .tc-master-wrap [data-testid="stCheckbox"] label {
      font-size: 1.1rem !important;
      font-weight: 900 !important;
      color: #ffffff !important;
      letter-spacing: -0.01em !important;
    }
    /* ── "동의하고 가입완료" CTA 버튼 — 활성/비활성 모두 명확한 직사각형 ── */
    body.auth-login-splash .stApp [data-testid="stButton"] > button[kind="primary"] {
      background: #10b981 !important;
      border: none !important;
      color: #ffffff !important;
      font-weight: 800 !important;
      font-size: 1.0rem !important;
      border-radius: 12px !important;
      padding: 14px 0 !important;
      min-height: 52px !important;
      box-shadow: 0 4px 22px rgba(16,185,129,0.38) !important;
      letter-spacing: -0.01em !important;
    }
    body.auth-login-splash .stApp [data-testid="stButton"] > button[kind="primary"]:disabled,
    body.auth-login-splash .stApp [data-testid="stButton"] > button[kind="primary"][disabled] {
      background: #374151 !important;
      color: rgba(255,255,255,0.40) !important;
      box-shadow: none !important;
      cursor: not-allowed !important;
    }
    body.auth-login-splash .stApp [data-testid="stButton"] > button[kind="primary"] p,
    body.auth-login-splash .stApp [data-testid="stButton"] > button[kind="primary"] span {
      color: inherit !important;
      font-weight: 800 !important;
    }
    </style>
    """,
        unsafe_allow_html=True,
    )

    # 랜딩 페이지 + 로그인 폼 전체: 다크 네이비 배경 유지 + Material Icons 폰트 강제 로딩
    st.components.v1.html(
        """
    <script>
    try { window.parent.document.body.classList.add("auth-login-splash"); } catch(e) {}
    try {
      var _pd = window.parent.document;
      if (!_pd.querySelector('link[href*="Material+Icons"]')) {
        var _lk = _pd.createElement('link');
        _lk.rel = 'stylesheet';
        _lk.href = 'https://fonts.googleapis.com/icon?family=Material+Icons+Outlined';
        _pd.head.appendChild(_lk);
      }
    } catch(e) {}
    </script>
    """,
        height=0,
    )

    # ---------- 약관 동의 화면 (소셜 클릭 후) — 토스/카카오 수준 상용 폼팩터 ----------
    if st.session_state.get("auth_phase") == "terms" and st.session_state.get("pending_social_provider"):
        prov = st.session_state["pending_social_provider"]

        # 약관 페이지 전용 body 클래스 + URL 정리(뒤로가기 시 ?__auth 잔상 방지)
        st.components.v1.html(
            """<script>
try {
  window.parent.document.body.classList.add('auth-terms-page');
  window.parent.document.body.classList.remove('auth-splash-screen');
  var _pw = window.parent;
  var _u = new URL(_pw.location.href);
  if (_u.searchParams.has('__auth') || _u.searchParams.has('intent')) {
    _u.search = '';
    _pw.history.replaceState({}, '', _u.pathname + _u.hash);
  }
} catch(e) {}
</script>""",
            height=0,
        )

        # #59: 약관 6개만 45vh 스크롤 — 첫 border 래퍼에 클래스 부여 (전역 border 셀렉터 제거)
        st.components.v1.html(
            """<script>
(function() {
  function tagTermsScroll() {
    try {
      var m = window.parent.document.querySelector('section[data-testid="stMain"]');
      if (!m) return;
      var w = m.querySelector('[data-testid="stVerticalBlockBorderWrapper"]');
      if (w) w.classList.add('tc-terms-scroll-only');
    } catch(e) {}
  }
  tagTermsScroll();
  setTimeout(tagTermsScroll, 50);
  setTimeout(tagTermsScroll, 200);
})();
</script>""",
            height=0,
        )

        # ── 헤더 ─────────────────────────────────────────────────────────────
        st.markdown(
            """
            <div style="text-align:center;margin:0 0 20px;">
              <div style="font-size:1.35rem;font-weight:900;color:#fff;letter-spacing:-0.02em;">
                📋 서비스 약관 동의
              </div>
              <div style="font-size:0.78rem;color:rgba(255,255,255,0.46);margin-top:6px;">
                필수 항목에 모두 동의해야 서비스를 이용하실 수 있습니다.
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        # ── 체크박스 상태 초기화 (필수 3 + 선택 3 = 총 6개) ──────────────────
        _sub_keys = ("tc_tos", "tc_priv", "tc_health", "tc_mkt", "tc_custom_priv", "tc_bigdata")
        _req_keys = ("tc_tos", "tc_priv", "tc_health")

        for _k in _sub_keys:
            st.session_state.setdefault(_k, False)

        # 마스터 on_change 콜백 (하위 6개 동기화)
        def _on_all_change():
            _v = st.session_state.get("tc_all_master", False)
            for _k2 in _sub_keys:
                st.session_state[_k2] = _v

        _all_currently = all(st.session_state.get(k, False) for k in _sub_keys)
        st.session_state["tc_all_master"] = _all_currently

        # ── 약관 항목 6개 — 테두리 컨테이너 안에서만 스크롤(max-height:45vh, CSS) ─
        with st.container(border=True):
            # [필수 1] 서비스 이용약관
            st.checkbox("[필수] 서비스 이용약관 동의", key="tc_tos")
            with st.expander("내용 보기", expanded=False):
                st.markdown(TERMS_TOS)

            # [필수 2] 개인정보 수집·이용
            st.checkbox("[필수] 개인정보 수집 및 이용 동의", key="tc_priv")
            with st.expander("내용 보기", expanded=False):
                st.markdown(TERMS_PRIVACY)

            # [필수 3] 민감정보(건강정보) 처리
            st.checkbox("[필수] 민감정보(건강정보) 처리 동의", key="tc_health")
            with st.expander("내용 보기", expanded=False):
                st.markdown(TERMS_HEALTH)

            st.markdown(
                "<div style='height:1px;background:rgba(255,255,255,0.06);margin:8px 0;'></div>",
                unsafe_allow_html=True,
            )

            # [선택 1] 마케팅 정보 수신
            st.checkbox("[선택] 맞춤형 혜택 및 마케팅 정보 수신 동의", key="tc_mkt")
            with st.expander("내용 보기", expanded=False):
                st.markdown(TERMS_MARKETING)

            # [선택 2] 맞춤형 서비스 개인정보 추가 수집
            st.checkbox("[선택] 맞춤형 서비스 제공을 위한 개인정보 추가 수집·이용 동의", key="tc_custom_priv")
            with st.expander("내용 보기", expanded=False):
                st.markdown(TERMS_CUSTOM_PRIV)

            # [선택 3] 빅데이터 분석 및 신규 서비스 개발
            st.checkbox("[선택] 빅데이터 분석 및 신규 서비스 개발을 위한 건강정보 처리 동의", key="tc_bigdata")
            with st.expander("내용 보기", expanded=False):
                st.markdown(TERMS_BIGDATA)

        # ── 구분선 ─────────────────────────────────────────────────────────
        st.markdown(
            "<div style='height:1px;background:rgba(255,255,255,0.12);margin:12px 0 10px;'></div>",
            unsafe_allow_html=True,
        )

        # ── 마스터 "전체 동의" — 맨 아래 배치, 크고 굵게 ──────────────────────
        st.markdown("<div class='tc-master-wrap'>", unsafe_allow_html=True)
        st.checkbox(
            "약관 전체 동의",
            key="tc_all_master",
            on_change=_on_all_change,
        )
        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)

        # ── 진행 조건 체크 (필수 3개만) ──────────────────────────────────────
        _can_proceed = all(st.session_state.get(k, False) for k in _req_keys)

        if not _can_proceed:
            _missing = []
            if not st.session_state.get("tc_tos"):
                _missing.append("서비스 이용약관")
            if not st.session_state.get("tc_priv"):
                _missing.append("개인정보 수집·이용")
            if not st.session_state.get("tc_health"):
                _missing.append("민감정보 처리")
            st.markdown(
                f"<div style='font-size:0.76rem;color:rgba(255,180,0,0.9);text-align:center;"
                f"margin-bottom:6px;'>⚠️ 미동의 필수 항목: {' / '.join(_missing)}</div>",
                unsafe_allow_html=True,
            )

        if st.button(
            "동의하고 가입완료",
            type="primary",
            use_container_width=True,
            key="terms_submit",
            disabled=not _can_proceed,
        ):
            st.session_state["terms_accepted_provider"] = prov
            st.session_state["terms_marketing_agreed"] = st.session_state.get("tc_mkt", False)
            st.session_state["terms_custom_priv_agreed"] = st.session_state.get("tc_custom_priv", False)
            st.session_state["terms_bigdata_agreed"] = st.session_state.get("tc_bigdata", False)
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

    # ---------- 프리미엄 랜딩 화면 (풀스크린 Zero-Scroll + Bottom Drawer) ----------
    if not st.session_state.get("auth_splash_done"):
        if "splash_drawer_open" not in st.session_state:
            st.session_state["splash_drawer_open"] = False
        if "splash_auth_intent" not in st.session_state:
            st.session_state["splash_auth_intent"] = "login"
        if "auth_intent" not in st.session_state:
            st.session_state["auth_intent"] = st.session_state.get("splash_auth_intent", "login")

        # ── #63 Plan-C: Native Input Setter — on_change 콜백 ──
        def _on_splash_trigger():
            _val = str(st.session_state.get("gluc_splash_trigger", "") or "").strip()
            if not _val:
                return
            # 즉시 초기화 (다음 rerun에서 재실행 방지)
            st.session_state["gluc_splash_trigger"] = ""
            action = _val.split(":")[0]
            if action == "open_login":
                st.session_state["splash_drawer_open"] = True
                st.session_state["splash_auth_intent"] = "login"
                st.session_state["auth_intent"] = "login"
            elif action == "open_signup":
                st.session_state["splash_drawer_open"] = True
                st.session_state["splash_auth_intent"] = "signup"
                st.session_state["auth_intent"] = "signup"
            elif action == "close_drawer":
                st.session_state["splash_drawer_open"] = False
            elif action in ("google", "naver", "kakao", "email"):
                _intent = st.session_state.get("splash_auth_intent", "login")
                st.session_state["auth_intent"] = _intent
                st.session_state["auth_mode"] = _intent
                st.session_state["auth_splash_done"] = True
                st.session_state["auth_sheet_open"] = True
                if action in ("google", "naver", "kakao"):
                    st.session_state["pending_social_provider"] = action
                    st.session_state["auth_phase"] = "terms"
                else:
                    st.session_state["auth_phase"] = "sheet"
                st.session_state["splash_drawer_open"] = False

        _ov = " open" if st.session_state.get("splash_drawer_open") else ""
        _dr = " open" if st.session_state.get("splash_drawer_open") else ""
        # #59: 인텐트 단일 소스 — splash_auth_intent만 사용 (회원가입 드로어 문구 불일치 방지)
        _splash_intent = str(st.session_state.get("splash_auth_intent", "login")).strip()
        if _splash_intent not in ("login", "signup"):
            _splash_intent = "login"
        st.session_state["splash_auth_intent"] = _splash_intent
        st.session_state["auth_intent"] = _splash_intent
        _ai = _splash_intent
        _int_js = _splash_intent.replace("\\", "\\\\").replace("'", "\\'")
        if _ai == "signup":
            _ph_d_title = "처음이신가요? Sign Up"
            _ph_d_sub = "3초 가입하기 → 7일 PRO 무료 체험 시작"
            _ph_bg_lbl = "Google로 가입하기"
            _ph_bn_lbl = "네이버로 가입하기"
            _ph_bk_lbl = "카카오로 가입하기"
            _ph_be_lbl = "이메일로 가입하기"
        else:
            _ph_d_title = "반가워요! 로그인"
            _ph_d_sub = "3초 소셜 로그인으로 바로 시작하세요"
            _ph_bg_lbl = "Google로 계속하기"
            _ph_bn_lbl = "네이버로 계속하기"
            _ph_bk_lbl = "카카오로 계속하기"
            _ph_be_lbl = "이메일로 계속하기"

        # ── #61 Plan-B: st.markdown → Parent DOM 직접 주입 (cross-iframe 제거) ──
        st.components.v1.html(
            """<script>
try { window.parent.document.body.classList.add('auth-splash-screen'); } catch(e) {}
</script>""",
            height=0,
        )

        # noinspection HtmlRequiredLangAttribute
        st.markdown(
            (
                """
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;700;900&display=swap');
#gluc-splash-root*{margin:0;padding:0;box-sizing:border-box;-webkit-tap-highlight-color:transparent;}
#gluc-splash-root{position:fixed;inset:0;z-index:999998;background:#0f172a;font-family:'Noto Sans KR',-apple-system,sans-serif;overflow:hidden;-webkit-tap-highlight-color:transparent;}
#gluc-splash-root .screen{position:relative;width:100%;height:100%;overflow:hidden;text-align:center;}
#gluc-splash-root .visual{position:absolute;top:0;left:0;right:0;bottom:160px;height:calc(100% - 160px);min-height:0;display:flex;flex-direction:column;align-items:center;justify-content:center;overflow:hidden;padding:12px 20px 0;z-index:1;}
#gluc-splash-root .glow-bg{position:fixed;top:0;left:50%;transform:translateX(-50%);width:100%;max-width:500px;height:52%;background:radial-gradient(ellipse at 50% 22%,rgba(16,185,129,0.19) 0%,transparent 65%);pointer-events:none;z-index:0;}
#gluc-splash-root .logo{font-size:clamp(2.6rem,9vw,3.6rem);line-height:1;margin-bottom:9px;filter:drop-shadow(0 0 18px rgba(239,68,68,0.52));animation:rise 0.6s cubic-bezier(0.22,1,0.36,1) 0.05s both;}
#gluc-splash-root .title{font-size:clamp(1.25rem,5.2vw,1.65rem);font-weight:900;color:#ffffff;letter-spacing:-0.5px;margin-bottom:3px;animation:rise 0.65s cubic-bezier(0.22,1,0.36,1) 0.18s both;}
#gluc-splash-root .tagline{font-size:clamp(0.6rem,2.3vw,0.7rem);font-weight:500;color:rgba(255,255,255,0.34);letter-spacing:0.12em;margin-bottom:14px;animation:rise 0.6s cubic-bezier(0.22,1,0.36,1) 0.3s both;}
#gluc-splash-root .chart-wrap{width:100%;max-width:280px;max-height:40%;overflow:hidden;display:flex;align-items:center;justify-content:center;margin:0 auto 10px;flex-shrink:1;animation:rise 0.7s cubic-bezier(0.22,1,0.36,1) 0.42s both;}
#gluc-splash-root .chart-wrap svg{width:100%;height:auto;}
#gluc-splash-root .path-safe{stroke-dasharray:180;stroke-dashoffset:180;animation:draw 1.0s ease-out 0.75s forwards;}
#gluc-splash-root .path-spike{stroke-dasharray:140;stroke-dashoffset:140;animation:draw 0.75s ease-in 1.75s forwards;}
#gluc-splash-root .glow-line{opacity:0;animation:fadein 0.5s ease-out 2.4s forwards;}
#gluc-splash-root .copy1{font-size:clamp(0.79rem,3.3vw,0.90rem);font-weight:700;color:rgba(255,255,255,0.66);line-height:1.5;margin-bottom:4px;animation:rise 0.6s cubic-bezier(0.22,1,0.36,1) 0.54s both;}
#gluc-splash-root .copy1 em{font-style:normal;color:#fbbf24;font-weight:800;}
#gluc-splash-root .copy2{font-size:clamp(0.84rem,3.6vw,0.97rem);font-weight:800;color:#ffffff;line-height:1.45;animation:rise 0.6s cubic-bezier(0.22,1,0.36,1) 0.66s both;}
#gluc-splash-root .copy2 em{font-style:normal;color:#10b981;}
#gluc-splash-root .btn-section{position:absolute;bottom:0;left:0;right:0;height:160px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:10px;padding:8px 20px;padding-bottom:max(20px,env(safe-area-inset-bottom,0px));z-index:2;animation:rise 0.7s cubic-bezier(0.22,1,0.36,1) 0.88s both;}
#gluc-splash-root .btn-main{width:100%;max-width:420px;height:54px;background:rgba(255,255,255,0.11);border:1px solid rgba(255,255,255,0.24);border-radius:16px;color:#ffffff;font-family:'Noto Sans KR',sans-serif;font-size:clamp(0.9rem,3.5vw,1.0rem);font-weight:800;cursor:pointer;backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);transition:background 0.15s,transform 0.09s;touch-action:manipulation;-webkit-tap-highlight-color:transparent;}
#gluc-splash-root .btn-sub{width:100%;max-width:420px;height:46px;background:transparent;border:1.5px solid rgba(16,185,129,0.50);border-radius:14px;color:#34d399;font-family:'Noto Sans KR',sans-serif;font-size:clamp(0.80rem,3.1vw,0.88rem);font-weight:700;cursor:pointer;transition:background 0.15s,transform 0.09s;touch-action:manipulation;-webkit-tap-highlight-color:transparent;}
#gluc-splash-root .overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,0.58);z-index:50;}
#gluc-splash-root .overlay.open{display:block;}
#gluc-splash-root .drawer{position:fixed;bottom:-100%;left:0;right:0;background:linear-gradient(180deg,#1e293b 0%,#0f1f30 100%);border-radius:24px 24px 0 0;border-top:1px solid rgba(255,255,255,0.10);padding:14px 22px max(28px,env(safe-area-inset-bottom,0px));z-index:100;transition:bottom 0.40s cubic-bezier(0.22,1,0.36,1);box-shadow:0 -10px 48px rgba(0,0,0,0.58);max-height:72vh;overflow-y:auto;}
#gluc-splash-root .drawer.open{bottom:0;}
#gluc-splash-root .handle{width:38px;height:4px;background:rgba(255,255,255,0.17);border-radius:2px;margin:0 auto 16px;}
#gluc-splash-root .drawer-title{font-size:clamp(1.0rem,4.2vw,1.12rem);font-weight:900;color:#ffffff;text-align:center;margin-bottom:5px;letter-spacing:-0.02em;}
#gluc-splash-root .drawer-sub{font-size:0.70rem;color:rgba(255,255,255,0.36);text-align:center;margin-bottom:16px;}
#gluc-splash-root .social-btn{width:100%;height:52px;border-radius:14px;font-family:'Noto Sans KR',sans-serif;font-size:clamp(0.82rem,3.2vw,0.91rem);font-weight:700;cursor:pointer;display:flex;align-items:center;gap:10px;padding:0 18px;margin-bottom:9px;border:none;transition:transform 0.09s,filter 0.12s;letter-spacing:-0.01em;text-align:left;touch-action:manipulation;-webkit-tap-highlight-color:transparent;}
#gluc-splash-root .social-btn:last-child{margin-bottom:0;}
#gluc-splash-root .social-btn .ico{width:22px;height:22px;flex-shrink:0;display:flex;align-items:center;justify-content:center;}
#gluc-splash-root .social-btn .lbl{flex:1;text-align:center;}
#gluc-splash-root .btn-google{background:#ffffff;color:#3c4043;}
#gluc-splash-root .btn-naver{background:#03C75A;color:#ffffff;}
#gluc-splash-root .btn-kakao{background:#FEE500;color:#191919;}
#gluc-splash-root .btn-email{background:rgba(16,185,129,0.18);color:#34d399;border:1px solid rgba(16,185,129,0.35);}
@keyframes spin{to{transform:rotate(360deg);}}
@keyframes rise{from{transform:translateY(22px);opacity:0;}to{transform:translateY(0);opacity:1;}}
@keyframes draw{to{stroke-dashoffset:0;}}
@keyframes fadein{to{opacity:1;}}
@media screen and (max-height:750px){
  #gluc-splash-root .logo{font-size:2.0rem!important;margin-bottom:5px;}
  #gluc-splash-root .title{font-size:1.05rem!important;margin-bottom:2px;}
  #gluc-splash-root .tagline{font-size:0.57rem!important;margin-bottom:8px;}
  #gluc-splash-root .copy1{font-size:0.70rem!important;margin-bottom:2px;line-height:1.3;}
  #gluc-splash-root .copy2{font-size:0.72rem!important;line-height:1.3;}
  #gluc-splash-root .btn-main{height:48px!important;}
  #gluc-splash-root .btn-sub{height:40px!important;}
  #gluc-splash-root .chart-wrap{max-height:120px;}
}
@media screen and (max-height:600px){
  #gluc-splash-root .logo{font-size:1.5rem!important;margin-bottom:3px;}
  #gluc-splash-root .title{font-size:0.92rem!important;}
  #gluc-splash-root .tagline{display:none!important;}
  #gluc-splash-root .copy1,#gluc-splash-root .copy2{font-size:0.66rem!important;margin-bottom:1px;}
  #gluc-splash-root .btn-main{height:44px!important;font-size:0.88rem!important;}
  #gluc-splash-root .btn-sub{height:36px!important;font-size:0.78rem!important;}
}
</style>
<div id="gluc-splash-root">
<div class="glow-bg"></div>
<div class="screen">
  <div class="visual">
    <div class="logo">🩸</div>
    <div class="title">나의 혈당 기록소</div>
    <div class="tagline">BLOOD GLUCOSE SCANNER AI</div>
    <div class="chart-wrap">
      <svg viewBox="0 0 280 108" width="100%" style="overflow:visible;height:auto;display:block;" aria-hidden="true">
        <rect x="0" y="0" width="280" height="108" rx="14" fill="rgba(255,255,255,0.04)" stroke="rgba(255,255,255,0.08)" stroke-width="1"/>
        <line x1="12" y1="26" x2="268" y2="26" stroke="rgba(255,255,255,0.07)" stroke-width="1"/>
        <line x1="12" y1="52" x2="268" y2="52" stroke="rgba(255,255,255,0.07)" stroke-width="1"/>
        <line x1="12" y1="78" x2="268" y2="78" stroke="rgba(255,255,255,0.07)" stroke-width="1"/>
        <rect x="12" y="4" width="256" height="22" rx="4" fill="rgba(239,68,68,0.07)"/>
        <text x="16" y="15" font-size="8" fill="rgba(239,68,68,0.55)" font-family="sans-serif">위험 &gt;140</text>
        <rect x="12" y="46" width="256" height="32" rx="4" fill="rgba(16,185,129,0.07)"/>
        <text x="16" y="58" font-size="8" fill="rgba(16,185,129,0.55)" font-family="sans-serif">정상 &lt;100</text>
        <polyline class="glow-line" points="20,64 60,62 100,60 140,57 180,59 220,58 260,60" stroke="rgba(16,185,129,0.28)" stroke-width="9" stroke-linecap="round" fill="none"/>
        <polyline class="path-safe" points="20,64 60,62 100,60 140,57 180,59 220,58 260,60" stroke="#10b981" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" fill="none"/>
        <polyline class="glow-line" points="20,64 55,60 90,50 120,18 145,6 168,22 200,46 235,57 260,60" stroke="rgba(239,68,68,0.22)" stroke-width="9" stroke-linecap="round" fill="none"/>
        <polyline class="path-spike" points="20,64 55,60 90,50 120,18 145,6 168,22 200,46 235,57 260,60" stroke="#ef4444" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" fill="none"/>
        <circle cx="22" cy="101" r="4" fill="#10b981"/>
        <text x="30" y="104" font-size="8.5" fill="rgba(255,255,255,0.52)" font-family="sans-serif">식이섬유 먼저</text>
        <circle cx="122" cy="101" r="4" fill="#ef4444"/>
        <text x="130" y="104" font-size="8.5" fill="rgba(255,255,255,0.52)" font-family="sans-serif">탄수화물 먼저</text>
      </svg>
    </div>
    <div class="copy1"><em>AI</em>가 당신의 식단을 감시합니다</div>
    <div class="copy2"><em>먹는 순서</em>가 바꾸는 <em>혈당 변화</em></div>
  </div>
  <div class="btn-section">
    <button class="btn-main" id="gluc-main-login">로그인</button>
    <button class="btn-sub" id="gluc-main-signup">회원가입</button>
  </div>
</div>
<div class="overlay__OVERLAY_OPEN__" id="gluc-overlay"></div>
<div class="drawer__DRAWER_OPEN__" id="gluc-drawer">
  <div class="handle"></div>
  <div class="drawer-title" id="gluc-d-title">__D_TITLE__</div>
  <div class="drawer-sub" id="gluc-d-sub">__D_SUB__</div>
  <button class="social-btn btn-google" id="gluc-bg">
    <span class="ico"><svg viewBox="0 0 24 24" width="20" height="20" xmlns="http://www.w3.org/2000/svg"><path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/><path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/><path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l3.66-2.84z"/><path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/></svg></span>
    <span class="lbl" id="gluc-bg-lbl">__BG_LBL__</span>
  </button>
  <button class="social-btn btn-naver" id="gluc-bn">
    <span class="ico"><svg viewBox="0 0 24 24" width="20" height="20" xmlns="http://www.w3.org/2000/svg"><path fill="#ffffff" d="M16.273 12.845L7.376 0H0v24h7.727V11.155L16.624 24H24V0h-7.727z"/></svg></span>
    <span class="lbl" id="gluc-bn-lbl">__BN_LBL__</span>
  </button>
  <button class="social-btn btn-kakao" id="gluc-bk">
    <span class="ico"><svg viewBox="0 0 24 24" width="20" height="20" xmlns="http://www.w3.org/2000/svg"><path fill="#191919" d="M12 3C6.477 3 2 6.477 2 10.8c0 2.7 1.617 5.077 4.077 6.523l-.985 3.677 4.246-2.8A11.8 11.8 0 0 0 12 18.6c5.523 0 10-3.477 10-7.8S17.523 3 12 3z"/></svg></span>
    <span class="lbl" id="gluc-bk-lbl">__BK_LBL__</span>
  </button>
  <button class="social-btn btn-email" id="gluc-be">
    <span class="ico"><svg viewBox="0 0 24 24" width="20" height="20" fill="none" xmlns="http://www.w3.org/2000/svg"><rect x="2" y="4" width="20" height="16" rx="3" stroke="#34d399" stroke-width="1.8"/><path d="M2 8l10 7 10-7" stroke="#34d399" stroke-width="1.8" stroke-linecap="round"/></svg></span>
    <span class="lbl" id="gluc-be-lbl">__BE_LBL__</span>
  </button>
</div>
</div>
<script>
/* #63 Plan-C JS Bridge — 같은 document 컨텍스트, 크로스프레임 불필요 */
(function() {
  function getTrigger() {
    var wrap = document.querySelector('[data-testid="stTextInput"]');
    return wrap ? wrap.querySelector('input') : null;
  }
  function fireAction(action) {
    var inp = getTrigger();
    if (!inp) return;
    try {
      var setter = Object.getOwnPropertyDescriptor(
        window.HTMLInputElement.prototype, 'value'
      ).set;
      setter.call(inp, action + ':' + Date.now());
      inp.dispatchEvent(new Event('input', { bubbles: true }));
      inp.dispatchEvent(new Event('change', { bubbles: true }));
    } catch(e) {}
  }
  function bindAll() {
    var btnLogin  = document.getElementById('gluc-main-login');
    var btnSignup = document.getElementById('gluc-main-signup');
    if (btnLogin && !btnLogin.__gBound) {
      btnLogin.__gBound = true;
      btnLogin.addEventListener('click', function(e) {
        e.stopPropagation(); fireAction('open_login');
      });
      btnLogin.addEventListener('touchend', function(e) {
        e.preventDefault(); e.stopPropagation(); fireAction('open_login');
      }, { passive: false });
    }
    if (btnSignup && !btnSignup.__gBound) {
      btnSignup.__gBound = true;
      btnSignup.addEventListener('click', function(e) {
        e.stopPropagation(); fireAction('open_signup');
      });
      btnSignup.addEventListener('touchend', function(e) {
        e.preventDefault(); e.stopPropagation(); fireAction('open_signup');
      }, { passive: false });
    }
    [['gluc-bg','google'],['gluc-bn','naver'],
     ['gluc-bk','kakao'],['gluc-be','email']].forEach(function(p) {
      var btn = document.getElementById(p[0]);
      if (btn && !btn.__gBound) {
        btn.__gBound = true;
        (function(prov) {
          btn.addEventListener('click', function(e) {
            e.stopPropagation(); fireAction(prov);
          });
          btn.addEventListener('touchend', function(e) {
            e.preventDefault(); e.stopPropagation(); fireAction(prov);
          }, { passive: false });
        })(p[1]);
      }
    });
    var ov = document.getElementById('gluc-overlay');
    if (ov && !ov.__gBound) {
      ov.__gBound = true;
      ov.addEventListener('click', function(e) {
        e.stopPropagation(); fireAction('close_drawer');
      });
      ov.addEventListener('touchend', function(e) {
        e.preventDefault(); e.stopPropagation(); fireAction('close_drawer');
      }, { passive: false });
    }
  }
  bindAll();
  [50, 150, 300, 500, 800, 1200].forEach(function(t) {
    setTimeout(bindAll, t);
  });
  try {
    new MutationObserver(function() { bindAll(); }).observe(
      document.body || document.documentElement,
      { childList: true, subtree: true }
    );
  } catch(e) {}
})();
</script>
"""
            ).replace("__OVERLAY_OPEN__", _ov)
            .replace("__DRAWER_OPEN__", _dr)
            .replace("__D_TITLE__", html_module.escape(_ph_d_title))
            .replace("__D_SUB__", html_module.escape(_ph_d_sub))
            .replace("__BG_LBL__", html_module.escape(_ph_bg_lbl))
            .replace("__BN_LBL__", html_module.escape(_ph_bn_lbl))
            .replace("__BK_LBL__", html_module.escape(_ph_bk_lbl))
            .replace("__BE_LBL__", html_module.escape(_ph_be_lbl)),
            unsafe_allow_html=True,
        )


        # ── #63 Plan-C: Native Input Setter (Hidden Trigger) ──
        # 숨김 트리거 input을 화면 밖으로 추방하는 CSS
        st.markdown(
            """
<style>
body.auth-splash-screen [data-testid="stTextInput"] {
  position: fixed !important;
  left: -9999px !important;
  top: 0 !important;
  width: 1px !important;
  height: 1px !important;
  overflow: hidden !important;
  pointer-events: none !important;
  opacity: 0 !important;
}
</style>
""",
            unsafe_allow_html=True,
        )

        # 숨김 트리거 입력창 — JS Native Setter로 값을 주입해 on_change 실행
        st.text_input(
            "gluc_trigger",
            key="gluc_splash_trigger",
            label_visibility="collapsed",
            on_change=_on_splash_trigger,
        )

        # ── #63 Plan-C 안전망: st.markdown <script> 미실행 시 iframe fallback ──
        # (크로스프레임 Event 생성 시 window.parent.Event 사용 → React 인식 보장)
        st.components.v1.html(
            """<script>
(function() {
  var pd = window.parent.document;
  var pw = window.parent;

  function getTrigger() {
    var wrap = pd.querySelector('[data-testid="stTextInput"]');
    return wrap ? wrap.querySelector('input') : null;
  }
  function fireAction(action) {
    var inp = getTrigger();
    if (!inp) return;
    try {
      var setter = Object.getOwnPropertyDescriptor(
        pw.HTMLInputElement.prototype, 'value'
      ).set;
      setter.call(inp, action + ':' + Date.now());
      /* pw.Event: 부모 window 컨텍스트로 생성 → React 이벤트 시스템이 확실히 인식 */
      inp.dispatchEvent(new pw.Event('input',  { bubbles: true }));
      inp.dispatchEvent(new pw.Event('change', { bubbles: true }));
    } catch(e) {}
  }
  function bindAll() {
    var btnLogin  = pd.getElementById('gluc-main-login');
    var btnSignup = pd.getElementById('gluc-main-signup');
    if (btnLogin && !btnLogin.__gBound) {
      btnLogin.__gBound = true;
      btnLogin.addEventListener('click', function(e) {
        e.stopPropagation(); fireAction('open_login');
      });
      btnLogin.addEventListener('touchend', function(e) {
        e.preventDefault(); e.stopPropagation(); fireAction('open_login');
      }, { passive: false });
    }
    if (btnSignup && !btnSignup.__gBound) {
      btnSignup.__gBound = true;
      btnSignup.addEventListener('click', function(e) {
        e.stopPropagation(); fireAction('open_signup');
      });
      btnSignup.addEventListener('touchend', function(e) {
        e.preventDefault(); e.stopPropagation(); fireAction('open_signup');
      }, { passive: false });
    }
    [['gluc-bg','google'],['gluc-bn','naver'],
     ['gluc-bk','kakao'],['gluc-be','email']].forEach(function(p) {
      var btn = pd.getElementById(p[0]);
      if (btn && !btn.__gBound) {
        btn.__gBound = true;
        (function(prov) {
          btn.addEventListener('click', function(e) {
            e.stopPropagation(); fireAction(prov);
          });
          btn.addEventListener('touchend', function(e) {
            e.preventDefault(); e.stopPropagation(); fireAction(prov);
          }, { passive: false });
        })(p[1]);
      }
    });
    var ov = pd.getElementById('gluc-overlay');
    if (ov && !ov.__gBound) {
      ov.__gBound = true;
      ov.addEventListener('click', function(e) {
        e.stopPropagation(); fireAction('close_drawer');
      });
      ov.addEventListener('touchend', function(e) {
        e.preventDefault(); e.stopPropagation(); fireAction('close_drawer');
      }, { passive: false });
    }
  }
  bindAll();
  [50, 150, 300, 500, 800, 1200].forEach(function(t) {
    setTimeout(bindAll, t);
  });
  try {
    new pw.MutationObserver(function() { bindAll(); }).observe(
      pd.body || pd.documentElement, { childList: true, subtree: true }
    );
  } catch(e) {}
})();
</script>""",
            height=0,
        )

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
          <div style="font-weight:900;font-size:1.3rem;letter-spacing:-0.03em;color:#ffffff;line-height:1.2;">
            AI 췌장 비서, 혈당스캐너
          </div>
          <div style="font-size:0.82rem;color:rgba(255,255,255,0.58);font-weight:500;
                      margin-top:10px;line-height:1.7;padding:0 6px;">
            3초 로그인으로 소중한 데이터를 평생 지키고,<br>
            <span style="color:#fbbf24;font-weight:800;">7일 PRO 무료 체험</span>을 시작하세요!
          </div>
        </div>
        """.replace("{LOGIN_TITLE}", html_module.escape(_t.get("login_sheet_title", ""))),
        unsafe_allow_html=True,
    )

    # ── 프리미엄 AI 방어 쉴드 비주얼 (로고 ↔ 소셜 버튼 사이) ──
    st.components.v1.html(
        """
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
* { margin:0; padding:0; box-sizing:border-box; }
html, body {
  background: #0f172a;
  overflow: hidden;
  display: flex;
  justify-content: center;
  align-items: center;
  height: 158px;
}
@keyframes domeGlow {
  0%,100% { opacity:0.62; }
  50%      { opacity:1.0; }
}
@keyframes sparkle {
  0%,100% { opacity:0.28; }
  50%      { opacity:0.92; }
}
.dome { animation: domeGlow 3.8s ease-in-out infinite; }
.s1   { animation: sparkle 2.3s ease-in-out infinite; }
.s2   { animation: sparkle 2.9s ease-in-out infinite 0.65s; }
.s3   { animation: sparkle 2.1s ease-in-out infinite 1.3s; }
</style>
</head>
<body>
<svg viewBox="0 0 280 152" width="280" height="152" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <radialGradient id="domeFill" cx="50%" cy="100%" r="70%">
      <stop offset="0%" stop-color="rgba(16,185,129,0.16)"/>
      <stop offset="100%" stop-color="rgba(16,185,129,0.02)"/>
    </radialGradient>
    <radialGradient id="plateBase" cx="50%" cy="40%" r="60%">
      <stop offset="0%" stop-color="rgba(255,255,255,0.10)"/>
      <stop offset="100%" stop-color="rgba(255,255,255,0.03)"/>
    </radialGradient>
    <filter id="glow" x="-30%" y="-30%" width="160%" height="160%">
      <feGaussianBlur stdDeviation="2.5" result="b"/>
      <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
  </defs>
  <!-- Ground shadow -->
  <ellipse cx="140" cy="144" rx="78" ry="8" fill="rgba(0,0,0,0.28)"/>
  <!-- Plate rim -->
  <ellipse cx="140" cy="137" rx="78" ry="10" fill="url(#plateBase)" stroke="rgba(255,255,255,0.14)" stroke-width="1.2"/>
  <ellipse cx="140" cy="134" rx="69" ry="8"  fill="rgba(255,255,255,0.04)"/>
  <!-- Salad - dark green base -->
  <ellipse cx="128" cy="120" rx="30" ry="13" fill="#064e3b" opacity="0.93"/>
  <ellipse cx="143" cy="118" rx="24" ry="11" fill="#059669" opacity="0.88"/>
  <ellipse cx="121" cy="123" rx="16" ry="7"  fill="#047857" opacity="0.85"/>
  <!-- Tomato -->
  <circle cx="165" cy="115" r="10.5" fill="#991b1b" opacity="0.88"/>
  <circle cx="165" cy="115" r="8.5"  fill="#dc2626" opacity="0.82"/>
  <circle cx="162" cy="112" r="3"    fill="rgba(255,255,255,0.14)"/>
  <!-- Egg/protein -->
  <ellipse cx="138" cy="112" rx="13" ry="7.5" fill="rgba(253,224,71,0.90)"/>
  <circle  cx="138" cy="112" r="5"              fill="rgba(234,179,8,0.84)"/>
  <!-- Avocado -->
  <circle cx="112" cy="120" r="9"   fill="#166534" opacity="0.88"/>
  <circle cx="112" cy="120" r="6"   fill="#15803d" opacity="0.76"/>
  <circle cx="112" cy="120" r="3.5" fill="#92400e" opacity="0.58"/>
  <!-- Herb dots -->
  <circle cx="151" cy="108" r="2.2" fill="#34d399" opacity="0.95"/>
  <circle cx="130" cy="107" r="1.8" fill="#10b981" opacity="0.90"/>
  <circle cx="156" cy="127" r="3.5" fill="#c2410c" opacity="0.82"/>
  <!-- AI Emerald Shield Dome -->
  <path class="dome"
        d="M 65 137 Q 65 28 140 18 Q 215 28 215 137 Z"
        fill="url(#domeFill)"
        stroke="rgba(52,211,153,0.60)"
        stroke-width="1.8"
        filter="url(#glow)"/>
  <path d="M 82 137 Q 82 44 140 36 Q 198 44 198 137 Z"
        fill="none" stroke="rgba(52,211,153,0.15)" stroke-width="1"/>
  <!-- Dome top glow -->
  <ellipse cx="140" cy="25" rx="11" ry="4.5" fill="rgba(52,211,153,0.38)"/>
  <!-- AI label -->
  <text x="140" y="49" text-anchor="middle" font-size="7.5"
        fill="rgba(52,211,153,0.85)" font-family="'-apple-system','Helvetica Neue',sans-serif"
        font-weight="700" letter-spacing="2">AI DEFENSE</text>
  <!-- Scan grid lines -->
  <line x1="92"  y1="88"  x2="188" y2="88"  stroke="rgba(52,211,153,0.10)" stroke-width="1"/>
  <line x1="84"  y1="103" x2="196" y2="103" stroke="rgba(52,211,153,0.07)" stroke-width="1"/>
  <line x1="78"  y1="118" x2="202" y2="118" stroke="rgba(52,211,153,0.05)" stroke-width="1"/>
  <!-- Gold sparkles -->
  <circle class="s1" cx="80"  cy="65" r="2.8" fill="#fbbf24"/>
  <circle class="s2" cx="200" cy="68" r="2.8" fill="#fbbf24"/>
  <circle class="s3" cx="140" cy="24" r="3.2" fill="#fbbf24" opacity="0.65"/>
  <!-- GL badge -->
  <rect x="210" y="78" width="34" height="28" rx="7"
        fill="rgba(16,185,129,0.12)" stroke="rgba(52,211,153,0.32)" stroke-width="1"/>
  <text x="227" y="90" text-anchor="middle" font-size="6.5"
        fill="rgba(52,211,153,0.68)" font-family="'-apple-system',sans-serif" font-weight="600">GL</text>
  <text x="227" y="101" text-anchor="middle" font-size="8.5"
        fill="#34d399" font-family="'-apple-system',sans-serif" font-weight="800">LOW</text>
</svg>
</body>
</html>
""",
        height=162,
        scrolling=False,
    )

    # ── [로그인 섹션] 기존 회원 ───────────────────────────────────────
    st.markdown(
        """
        <div style="text-align:center;margin:18px 0 10px;
                    font-size:0.82rem;font-weight:700;
                    color:rgba(255,255,255,0.55);letter-spacing:0.02em;">
          기존 회원이신가요? &nbsp;빠르게 로그인하세요
        </div>
        """,
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
    st.markdown("</div>", unsafe_allow_html=True)

    with st.expander("✉️ 이메일로 계속하기"):
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

    # ── [회원가입 섹션] 처음이신가요? ─────────────────────────────────
    st.markdown(
        """
        <div style="text-align:center;margin:22px 0 4px;">
          <div style="height:1px;background:linear-gradient(90deg,transparent,rgba(255,255,255,0.12),transparent);margin-bottom:18px;"></div>
          <div style="font-size:0.82rem;font-weight:700;color:rgba(255,255,255,0.55);letter-spacing:0.02em;">
            처음이신가요? &nbsp;3초 만에 무료로 시작하세요
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.expander("✨ 3초 만에 회원가입 시작하기", expanded=False):
        st.markdown(
            "<div style='font-size:0.78rem;color:rgba(255,255,255,0.50);text-align:center;"
            "margin-bottom:12px;'>아래 채널 중 하나로 가입하면 바로 AI 분석이 시작됩니다!</div>",
            unsafe_allow_html=True,
        )
        st.markdown('<div class="auth-soc-row">', unsafe_allow_html=True)
        st.markdown('<div class="auth-mark-google"></div>', unsafe_allow_html=True)
        if st.button("🔵 Google로 회원가입하기", key="reg_ko_g", use_container_width=True):
            st.session_state["pending_social_provider"] = "google"
            st.session_state["auth_phase"] = "terms"
            st.rerun()
        st.markdown('<div class="auth-mark-naver"></div>', unsafe_allow_html=True)
        if st.button("🟢 Naver로 회원가입하기", key="reg_ko_n", use_container_width=True):
            st.session_state["pending_social_provider"] = "naver"
            st.session_state["auth_phase"] = "terms"
            st.rerun()
        st.markdown('<div class="auth-mark-kakao"></div>', unsafe_allow_html=True)
        if st.button("🟡 Kakao로 회원가입하기", key="reg_ko_k", use_container_width=True):
            st.session_state["pending_social_provider"] = "kakao"
            st.session_state["auth_phase"] = "terms"
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)
        st.markdown("<div style='height:6px;'></div>", unsafe_allow_html=True)
        if st.button("✉️ 이메일로 회원가입하기", key="reg_ko_email", use_container_width=True):
            st.session_state["auth_mode"] = "signup"
            st.rerun()

    st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)

    # ─── localStorage 자동 로그인 체크 JS (로그인 화면 진입 시 실행) ──────────
    st.components.v1.html(
        """
<script>
(function(){
  try{
    var s=(window.parent||window).localStorage;
    var a=s.getItem('bgs_auth');
    if(!a)return;
    var d=JSON.parse(a);
    if(!d||!d.u||!d.t)return;
    var url=new URL(window.parent.location.href);
    if(url.searchParams.has('__al'))return;
    var raw=JSON.stringify(d);
    var enc=btoa(unescape(encodeURIComponent(raw)));
    url.searchParams.set('__al',enc);
    window.parent.location.replace(url.toString());
  }catch(e){}
})();
</script>
""",
        height=0,
    )
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


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_image_bytes_direct(image_url):
    """URL에서 정교하게 버킷과 경로를 추출해 Admin SDK로 다운로드하는 함수."""
    if not image_url:
        return None, "URL이 없습니다."
    try:
        _get_firestore_db()
        s = str(image_url).strip()
        match = re.search(r"(users(?:%2F|/)[^?]+)", s)
        if not match:
            return None, "URL에서 'users/' 경로를 파싱할 수 없습니다."
        blob_path = urllib.parse.unquote(match.group(1))
        bucket_name = None
        if "storage.googleapis.com/" in s:
            bucket_name = s.split("storage.googleapis.com/")[1].split("/")[0]
        elif "/b/" in s:
            bucket_name = s.split("/b/")[1].split("/")[0]
        if bucket_name:
            bucket = firebase_admin_storage.bucket(bucket_name)
        else:
            bucket = firebase_admin_storage.bucket()
        blob = bucket.blob(blob_path)
        if blob.exists():
            return blob.download_as_bytes(), "성공"
        return None, f"해당 경로에 파일이 존재하지 않음: {blob_path}"
    except Exception as e:
        return None, f"Admin SDK 다운로드 에러: {str(e)}"


_GLUCOSE_VALID_TYPES = {"fasting", "postprandial", "pre_meal", "bedtime", "other"}


def _save_glucose(uid, type_, value, note=None, timestamp=None):
    """users/{uid}/glucose 컬렉션에 혈당 저장.
    type_ in ('fasting','postprandial','pre_meal','bedtime','other').
    timestamp는 반드시 timezone-aware Python datetime으로 전달."""
    if not uid or type_ not in _GLUCOSE_VALID_TYPES:
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


def _hydrate_history_daily_from_firestore(uid):
    """일지 탭: daily_summary·대시보드 스칼라를 Firestore(오늘)와 동기화. daily_summary_today 캐시가 있어도 스칼라는 항상 맞춤."""
    if not uid:
        return
    try:
        import pytz

        _seoul = pytz.timezone("Asia/Seoul")
        _date_key = datetime.now(_seoul).strftime("%Y-%m-%d")
        _cached = st.session_state.get("daily_summary_today")
        _key = st.session_state.get("daily_summary_today_key")
        if not (isinstance(_cached, dict) and _key == _date_key):
            _dash = get_today_summary(uid, _date_key)
            st.session_state["daily_summary_today"] = dict(_dash)
            st.session_state["daily_summary_today_key"] = _date_key
        if not st.session_state.get("daily_summary") or st.session_state.get("daily_summary_date_key") != _date_key:
            st.session_state["daily_summary"] = get_daily_summary(uid, _date_key)
            st.session_state["daily_summary_date_key"] = _date_key
        ds = st.session_state["daily_summary"]
        st.session_state["daily_meals_count"] = int(ds.get("meal_count") or 0)
        st.session_state["daily_carbs"] = int(ds.get("total_carbs") or 0)
        st.session_state["daily_protein"] = int(ds.get("total_protein") or 0)
        st.session_state["daily_blood_sugar_score"] = int(ds.get("avg_spike") or 0)
    except Exception as e:
        sys.stderr.write(f"[일지 오늘 요약 hydrate] {e}\n")


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


@st.dialog("⚠️ 저장하지 않고 이동하시겠습니까?")
def confirm_retake_dialog():
    """분석 결과 화면에서 '다시 촬영' 시 이탈 방지 (하단 바에서 직접 호출 가능하도록 전역 정의)."""
    st.write(
        "아직 식단을 기록하지 않았습니다. 이대로 새 사진을 촬영하면 현재 분석된 혈당 스파이크 데이터가 모두 사라집니다."
    )
    c_left, c_right = st.columns(2)
    with c_left:
        if st.button("아니요, 돌아가서 저장할게요", key="retake_cancel_global"):
            pass
    with c_right:
        if st.button("네, 삭제하고 새로 촬영합니다", key="retake_confirm_global", type="primary"):
            st.session_state["current_analysis"] = None
            st.session_state["current_img"] = None
            st.session_state["vision_analysis_status"] = "idle"
            st.session_state["meal_save_trigger"] = False
            st.session_state["meal_save_in_progress"] = False
            st.session_state["app_stage"] = "main"
            st.session_state["current_page"] = "main"
            if "uploader_key" in st.session_state:
                st.session_state["uploader_key"] += 1
            else:
                st.session_state["uploader_key"] = 0
            st.rerun()


def render_bottom_bar():
    """하단 네비 (No-Columns): st.columns 없이 버튼만 나열, CSS가 stVerticalBlock을 flex row로 고정.
    탭 구성: 홈 / 일지 / 📸촬영 / 혈당 / 성과 / 설정 (6탭 플랫 통일)"""
    menu_key = st.session_state.get("nav_menu") or "scanner"
    if menu_key not in ("scanner", "history", "glucose", "achievement"):
        return
    bottom_bar_container = st.container()
    with bottom_bar_container:
        _stage = st.session_state.get("app_stage", "main")
        _login_type = st.session_state.get("login_type")
        _is_guest = _login_type == "guest"

        if menu_key == "scanner" and _stage == "result":
            st.markdown(
                '<div class="bottom-bar-anchor result-nav"></div>',
                unsafe_allow_html=True,
            )
            if st.button(
                "💾\n기록하기",
                key="bb_tab_save",
                type="primary",
                use_container_width=True,
                disabled=_is_guest,
            ):
                st.session_state["meal_save_trigger"] = True
                st.rerun()
            if st.button("📸\n다시 촬영", key="bb_tab_retake", use_container_width=True):
                confirm_retake_dialog()
        else:
            st.markdown(
                '<div class="bottom-bar-anchor main-nav"></div>',
                unsafe_allow_html=True,
            )
            if st.button("🏠\n홈", key="bb_nav_home", use_container_width=True):
                st.session_state["nav_menu"] = "scanner"
                st.session_state["app_stage"] = "main"
                st.session_state["current_page"] = "main"
                st.rerun()
            if st.button("📊\n일지", key="bb_nav_record", use_container_width=True):
                st.session_state["nav_menu"] = "history"
                st.session_state["app_stage"] = "main"
                st.rerun()
            if st.button("📸\n촬영", key="bb_nav_capture", use_container_width=True):
                st.session_state["nav_menu"] = "scanner"
                st.session_state["current_page"] = "main"
                st.session_state["app_stage"] = "main"
                st.rerun()
            if st.button("🩹\n혈당", key="bb_nav_glucose", use_container_width=True):
                st.session_state["nav_menu"] = "glucose"
                st.session_state["current_page"] = "main"
                st.session_state["app_stage"] = "main"
                st.rerun()
            if st.button("🏆\n성과", key="bb_nav_achievement", use_container_width=True):
                st.session_state["nav_menu"] = "achievement"
                st.session_state["current_page"] = "main"
                st.session_state["app_stage"] = "main"
                st.rerun()
            if st.button("⚙️\n설정", key="bb_nav_settings", use_container_width=True):
                st.session_state["nav_menu"] = "scanner"
                st.session_state["current_page"] = "settings"
                st.session_state["app_stage"] = "main"
                st.rerun()


# ─── 영구 자동 로그인: 로그인 직후 localStorage에 인증 정보 저장 (1회) ─────
if not st.session_state.get("_ls_auth_saved") and st.session_state.get("login_type") in ("google", "email"):
    st.session_state["_ls_auth_saved"] = True
    _ls_u = json.dumps(st.session_state.get("user_id") or "")
    _ls_e = json.dumps(st.session_state.get("user_email") or "")
    _ls_t = json.dumps(st.session_state.get("login_type") or "")
    st.components.v1.html(
        f"<script>try{{(window.parent||window).localStorage.setItem('bgs_auth',"
        f"JSON.stringify({{u:{_ls_u},e:{_ls_e},t:{_ls_t}}}));}}catch(e){{}}</script>",
        height=0,
    )
# ─────────────────────────────────────────────────────────────────────────────

# 5. 메인 영역 — 스캐너/기록 전환은 하단 바 + session_state.nav_menu만 사용 (상단 중복 탭 제거)
menu_key = st.session_state.get("nav_menu") or "scanner"

# 5-1. 식단 스캐너
if menu_key == "scanner":
    # Ghost 제거: render_login_badge() + 빈 col_top1 컬럼 완전 삭제
    # 로그인/로그아웃 버튼은 current_page == "main" 블록 내 헤더 아래로 이동
    _lt = st.session_state.get("login_type")
    if 'app_stage' not in st.session_state:
        st.session_state['app_stage'] = 'main'
    if 'current_page' not in st.session_state:
        st.session_state['current_page'] = 'main'
    if "vision_analysis_status" not in st.session_state:
        st.session_state["vision_analysis_status"] = "idle"

    API_KEY = _get_secret("GEMINI_API_KEY")
    if not API_KEY:
        st.error(t["gemini_key_error"])
        render_bottom_bar()
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
            # 1️⃣ 메인: 프리미엄 히어로 (Ghost 제거 후 최상단 첫 요소)
            st.markdown(
                f'<div class="ns-premium-home-shell" aria-hidden="true"></div>'
                f'<div class="ns-premium-hero">{html_module.escape(t.get("main_hero_welcome", "오늘도 쾌적하게 혈당 방어, 시작해 볼까요? 🛡️"))}</div>',
                unsafe_allow_html=True,
            )
            # 로그인/로그아웃 버튼 (헤더 아래 인라인 — 빈 col_top1 Ghost 제거)
            if _lt == "guest":
                if st.button(f"🔐 {t['sidebar_go_login']}", key="main_go_login", use_container_width=True):
                    st.session_state["logged_in"] = False
                    st.session_state["login_type"] = None
                    st.session_state["user_id"] = None
                    st.session_state["user_email"] = None
                    _reset_meal_feed_state()
                    st.session_state["auth_mode"] = "login"
                    st.rerun()
            elif _lt == "google":
                if st.button(f"🚪 {t['sidebar_logout']}", key="main_logout", use_container_width=True):
                    st.session_state["logged_in"] = False
                    st.session_state["login_type"] = None
                    st.session_state["user_id"] = None
                    st.session_state["user_email"] = None
                    st.session_state["_ls_auth_saved"] = False
                    st.session_state["_ls_auth_revoked"] = False
                    st.session_state["_logout_pending_ls_clear"] = True
                    _reset_meal_feed_state()
                    st.session_state["auth_mode"] = "login"
                    st.rerun()

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
                    _reset_meal_feed_state()
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

                    st.markdown(
                        f'<div class="ns-dashboard-section-title">{html_module.escape(t.get("dash_today_title", "오늘의 요약"))}</div>',
                        unsafe_allow_html=True,
                    )
                    st.markdown(
                        _render_dash_today_metrics_cards(t, _avg_g, _latest_g, _total_c, _meal_n),
                        unsafe_allow_html=True,
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

                    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

                _render_pre_meal_skeleton(t, is_guest=is_guest, guest_remaining=total_remaining)

        elif st.session_state.get("current_page") == "diet_scan":
            st.session_state["current_page"] = "main"
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
            # 설정 페이지: 계정 → 구독 → 앱 환경 3단 구조
            st.markdown(
                """
                <div style="background:linear-gradient(135deg,#0f172a 0%,#1e293b 100%);
                            border-radius:18px;padding:20px 18px 14px;margin-bottom:18px;">
                  <div style="font-size:1.5rem;font-weight:900;color:#fff;letter-spacing:-0.5px;">
                    ⚙️ 설정
                  </div>
                  <div style="font-size:0.82rem;color:rgba(255,255,255,0.45);margin-top:4px;">
                    계정·구독·앱 환경을 관리합니다
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            # ━━ [1단] 계정 섹션 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            _login_type_s = st.session_state.get("login_type")
            _user_email_s = st.session_state.get("user_email") or ""
            if _login_type_s == "google":
                _s_icon, _s_label = "🌐", "Google 로그인"
                _s_display = _user_email_s or "구글 계정"
            elif _login_type_s == "email":
                _s_icon, _s_label = "✉️", "이메일 로그인"
                _s_display = _user_email_s or "이메일 계정"
            else:
                _s_icon, _s_label = "🔐", "로그인 필요"
                _s_display = "로그인하여 데이터를 저장하세요"
            st.markdown(
                f"""
                <div style="background:#fff;border-radius:16px;padding:16px 18px 14px;
                            box-shadow:0 4px 18px rgba(0,0,0,0.07);margin-bottom:12px;">
                  <div style="font-size:0.95rem;font-weight:800;color:#1e293b;margin-bottom:12px;">
                    👤 계정
                  </div>
                  <div style="display:flex;align-items:center;gap:12px;padding:11px 14px;
                              background:#f8fafc;border-radius:12px;">
                    <div style="width:42px;height:42px;border-radius:50%;
                                background:linear-gradient(135deg,#0ea5e9 0%,#6366f1 100%);
                                display:flex;align-items:center;justify-content:center;
                                font-size:1.15rem;flex-shrink:0;">{_s_icon}</div>
                    <div style="min-width:0;flex:1;">
                      <div style="font-size:0.9rem;font-weight:700;color:#1e293b;
                                  overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">
                        {html_module.escape(_s_display)}
                      </div>
                      <div style="font-size:0.75rem;color:#64748b;margin-top:2px;">{_s_label}</div>
                    </div>
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            if _login_type_s in ("google", "email"):
                if st.button(f"🚪 {t['sidebar_logout']}", key="settings_logout", use_container_width=True):
                    st.session_state["logged_in"] = False
                    st.session_state["login_type"] = None
                    st.session_state["user_id"] = None
                    st.session_state["user_email"] = None
                    st.session_state["_ls_auth_saved"] = False
                    st.session_state["_ls_auth_revoked"] = False
                    st.session_state["_logout_pending_ls_clear"] = True
                    _reset_meal_feed_state()
                    st.session_state["auth_mode"] = "login"
                    st.session_state["current_page"] = "main"
                    st.rerun()
            else:
                if st.button(f"🔐 {t['sidebar_go_login']}", key="settings_go_login", use_container_width=True):
                    st.session_state["logged_in"] = False
                    st.session_state["login_type"] = None
                    st.session_state["user_id"] = None
                    st.session_state["user_email"] = None
                    st.session_state["_ls_auth_saved"] = False
                    st.session_state["_ls_auth_revoked"] = False
                    st.session_state["_logout_pending_ls_clear"] = True
                    _reset_meal_feed_state()
                    st.session_state["auth_mode"] = "login"
                    st.session_state["current_page"] = "main"
                    st.rerun()

            st.divider()

            # ━━ [2단] 구독 섹션 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            # ── 👑 PRO 구독 카드 ─────────────────────────────────────────
            _is_premium = st.session_state.get("is_premium", False)

            if _is_premium:
                # ▶ 이미 PRO 구독 중인 경우: 상태 배지 카드만 표시
                st.markdown(
                    """
                    <div style="background:linear-gradient(135deg,#1e1b4b 0%,#312e81 100%);
                                border-radius:20px;padding:20px 22px;margin-bottom:18px;
                                border:2px solid #fbbf24;
                                box-shadow:0 0 28px rgba(251,191,36,0.3),0 4px 20px rgba(0,0,0,0.45);">
                      <div style="display:flex;align-items:center;gap:12px;">
                        <span style="font-size:2.4rem;flex-shrink:0;">👑</span>
                        <div>
                          <div style="font-size:1.1rem;font-weight:900;
                                      background:linear-gradient(90deg,#fbbf24 0%,#fff7ed 50%,#f59e0b 100%);
                                      -webkit-background-clip:text;-webkit-text-fill-color:transparent;
                                      background-clip:text;">
                            현재 PRO 구독 중입니다
                          </div>
                          <div style="font-size:0.8rem;color:rgba(255,255,255,0.6);margin-top:4px;">
                            혈당스캐너 PRO의 모든 기능을 이용 중이에요 🎉
                          </div>
                        </div>
                      </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
            else:
                # ▶ 무료 유저: PRO Paywall 카드 + 결제 버튼 표시
                st.markdown(
                    """
                    <style>
                    div[data-testid="stHorizontalBlock"]:has(.pro-sub-marker)
                      div[data-testid="stButton"] > button {
                        background: linear-gradient(135deg,#7c3aed 0%,#4f46e5 50%,#6d28d9 100%) !important;
                        color: #fffbeb !important;
                        font-weight: 900 !important;
                        font-size: 1.07rem !important;
                        border: none !important;
                        border-radius: 14px !important;
                        padding: 0.85rem 1rem !important;
                        box-shadow: 0 8px 28px rgba(124,58,237,0.55) !important;
                        letter-spacing: 0.3px !important;
                        transition: transform 0.15s ease, box-shadow 0.15s ease !important;
                        width: 100% !important;
                    }
                    div[data-testid="stHorizontalBlock"]:has(.pro-sub-marker)
                      div[data-testid="stButton"] > button:hover {
                        transform: translateY(-2px) !important;
                        box-shadow: 0 12px 36px rgba(124,58,237,0.72) !important;
                    }
                    div[data-testid="stHorizontalBlock"]:has(.pro-sub-marker)
                      div[data-testid="stButton"] > button:active {
                        transform: translateY(0px) !important;
                        box-shadow: 0 4px 16px rgba(124,58,237,0.6) !important;
                    }
                    </style>
                    <div style="background:linear-gradient(135deg,#1e1b4b 0%,#312e81 55%,#2d1b69 100%);
                                border-radius:22px;padding:26px 22px 20px;margin-bottom:0px;
                                border:1.5px solid rgba(251,191,36,0.85);
                                box-shadow:0 0 40px rgba(251,191,36,0.18),0 8px 40px rgba(0,0,0,0.55);">
                      <!-- 왕관 + 타이틀 -->
                      <div style="text-align:center;margin-bottom:6px;">
                        <div style="font-size:2.6rem;line-height:1.1;margin-bottom:4px;">👑</div>
                        <div style="font-size:1.55rem;font-weight:900;letter-spacing:-0.5px;
                                    background:linear-gradient(90deg,#fbbf24 0%,#fff7ed 42%,#f59e0b 100%);
                                    -webkit-background-clip:text;-webkit-text-fill-color:transparent;
                                    background-clip:text;line-height:1.2;">
                          혈당스캐너 PRO
                        </div>
                      </div>
                      <!-- 가격 -->
                      <div style="text-align:center;margin-bottom:18px;">
                        <div style="font-size:2.2rem;font-weight:900;color:#ffffff;line-height:1.1;">
                          월 ₩4,900
                        </div>
                        <div style="font-size:0.78rem;color:rgba(255,255,255,0.48);margin-top:6px;line-height:1.5;">
                          ☕ 커피 한 잔 값으로 췌장을 평생 지키세요
                        </div>
                      </div>
                      <!-- 혜택 리스트 -->
                      <div style="background:rgba(255,255,255,0.07);border-radius:14px;
                                  padding:14px 16px;margin-bottom:4px;">
                        <div style="font-size:0.9rem;color:#e0f2fe;line-height:2.1;font-weight:500;">
                          ✅&nbsp;<b style="color:#fff;">AI 식단·혈당 분석 무제한</b>
                          <span style="color:rgba(255,255,255,0.36);font-size:0.74rem;font-weight:400;">(무료 = 일 1회)</span><br>
                          ✅&nbsp;<b style="color:#fff;">췌장 피로도 심층 주간 리포트</b><br>
                          ✅&nbsp;<b style="color:#fff;">광고 없는 쾌적한 프리미엄 환경</b><br>
                          ✅&nbsp;<b style="color:#fff;">가족 연동 알림 기능</b>
                          <span style="color:#fbbf24;font-size:0.74rem;font-weight:700;">(오픈 예정)</span>
                        </div>
                      </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                st.markdown("<div style='margin-bottom:10px;'></div>", unsafe_allow_html=True)
                # 결제 버튼 — marker 기반 CSS 스코프로 그라데이션 스타일 적용
                _pro_col = st.columns([1])[0]
                with _pro_col:
                    st.markdown(
                        '<span class="pro-sub-marker" style="display:none"></span>',
                        unsafe_allow_html=True,
                    )
                    if st.button(
                        "✨ 7일 무료 체험 시작하기",
                        key="subscribe_pro_btn",
                        use_container_width=True,
                    ):
                        st.session_state["is_premium"] = True
                        st.toast("👑 PRO 버전으로 업그레이드 되었습니다!", icon="🎉")
                        st.balloons()
                        st.rerun()

            st.divider()

            # ━━ [3단] 앱 환경 설정 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            st.markdown(
                """
                <div style="background:#fff;border-radius:16px;padding:16px 18px 6px;
                            box-shadow:0 4px 18px rgba(0,0,0,0.07);margin-bottom:14px;">
                  <div style="font-size:0.95rem;font-weight:800;color:#1e293b;margin-bottom:2px;">
                    🔔 앱 환경 설정
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            _push_prev = st.session_state.get("push_notif_enabled", False)
            push_enabled = st.toggle(
                "🔔 식사 시간 푸시 알림",
                value=_push_prev,
                key="push_notif_toggle",
            )
            st.caption("점심, 저녁 식사 시간에 맞춰 식단 촬영 리마인더를 보내드립니다.")

            # 토글이 OFF → ON 으로 바뀐 순간에만 권한 요청 + 테스트 알림 발송
            if push_enabled and not _push_prev:
                st.session_state["push_notif_enabled"] = True
                st.components.v1.html(
                    """
<script>
(function () {
  try {
    // Streamlit iframe 안에서 부모 window 를 통해 Notification API 접근
    var win   = window.parent || window;
    var nav   = win.navigator;
    var Notif = win.Notification;

    if (!Notif) return; // 알림 미지원 브라우저

    function fireTestNotification() {
      // ServiceWorker 가 활성화되어 있으면 showNotification 으로 발송
      if (nav.serviceWorker && nav.serviceWorker.controller) {
        nav.serviceWorker.ready.then(function (reg) {
          reg.showNotification('혈당스캐너 AI 🩸', {
            body   : '쾌적한 혈당 방어전, 지금 식단 촬영을 시작하세요!',
            icon   : '/app/static/icon-192.png',
            badge  : '/app/static/icon-192.png',
            vibrate: [200, 100, 200]
          });
        }).catch(function (e) {
          // SW ready 실패 → 일반 Notification fallback
          new Notif('혈당스캐너 AI 🩸', {
            body: '쾌적한 혈당 방어전, 지금 식단 촬영을 시작하세요!',
            icon: '/app/static/icon-192.png'
          });
        });
      } else {
        // SW 없이 즉시 Notification 발송
        new Notif('혈당스캐너 AI 🩸', {
          body: '쾌적한 혈당 방어전, 지금 식단 촬영을 시작하세요!',
          icon: '/app/static/icon-192.png'
        });
      }
    }

    // 1) ServiceWorker 등록 (이미 등록된 경우 재등록 없이 패스)
    if (nav.serviceWorker) {
      nav.serviceWorker.register('/app/static/sw.js').catch(function (e) {
        console.warn('[SW] 등록 실패:', e);
      });
    }

    // 2) 권한 분기
    if (Notif.permission === 'granted') {
      fireTestNotification();
    } else if (Notif.permission !== 'denied') {
      Notif.requestPermission().then(function (perm) {
        if (perm === 'granted') fireTestNotification();
      });
    }
  } catch (e) {
    console.warn('[PushNotif] 오류:', e);
  }
})();
</script>
""",
                    height=0,
                    scrolling=False,
                )
                st.success("✅ 알림 권한이 요청되었습니다. 브라우저 팝업에서 '허용'을 눌러주세요.")

            elif not push_enabled and _push_prev:
                st.session_state["push_notif_enabled"] = False
                st.info("🔕 알림이 꺼졌습니다. 브라우저 설정에서도 알림을 차단할 수 있습니다.")

            st.markdown("<div style='margin-bottom:10px;'></div>", unsafe_allow_html=True)

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
                <img src="data:image/jpeg;base64,{_b64}" alt="" role="presentation" decoding="async" style="max-height:350px;width:100%;object-fit:contain;" />
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
                    <img src="data:image/jpeg;base64,{_res_b64}" alt="" role="presentation" decoding="async" style="max-height:350px;width:100%;object-fit:contain;" />
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
                st.session_state["meal_save_trigger"] = False
            else:
                st.session_state["meal_save_trigger"] = False
                st.session_state["meal_save_in_progress"] = True
                st.toast("⏳ 데이터를 금고에 안전하게 저장 중입니다...", icon="⏳")
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

                    st.toast("✅ 저장 완료되었습니다!", icon="🎉")
                    time.sleep(0.8)

                    st.session_state["nav_menu"] = "history"
                    st.session_state["app_stage"] = "main"
                    st.session_state["current_page"] = "main"
                    st.session_state["current_analysis"] = None
                    st.session_state["current_img"] = None
                    st.session_state["vision_analysis_status"] = "idle"
                    if "uploader_key" in st.session_state:
                        st.session_state["uploader_key"] += 1
                    get_today_summary.clear()
                    _reset_meal_feed_state()
                    st.rerun()
                except Exception as e:
                    traceback.print_exc(file=sys.stderr)
                    st.toast("❌ 저장에 실패했습니다. 다시 시도해 주세요.", icon="🚨")
                finally:
                    st.session_state["meal_save_in_progress"] = False


# ── 혈당 탭 (기간 필터 + 산점도) ──
elif menu_key == "glucose":
    import pytz as _pytz_gl
    current_uid = st.session_state.get("user_id")
    _lt_gl = st.session_state.get("login_type")

    # ── 1. 다크 프리미엄 헤더 (Ghost 제거: 최상단 첫 번째 요소로 끌어올림) ──
    st.markdown(
        """
<div class="ns-glucose-header">
  <div class="ns-glucose-header-sub">나의 건강 데이터</div>
  <div class="ns-glucose-header-title">나의 혈당 기록소 🩸</div>
  <div class="ns-glucose-header-hint">혈당을 기록하면 AI가 패턴을 분석합니다</div>
</div>
""",
        unsafe_allow_html=True,
    )

    # 로그인/로그아웃 버튼 (헤더 아래 인라인 — 빈 col_top1 Ghost 제거 후 단독 배치)
    if _lt_gl == "guest":
        if st.button(f"🔐 {t['sidebar_go_login']}", key="glucose_go_login", use_container_width=True):
            st.session_state["logged_in"] = False
            st.session_state["login_type"] = None
            st.session_state["user_id"] = None
            st.session_state["user_email"] = None
            _reset_meal_feed_state()
            st.session_state["auth_mode"] = "login"
            st.rerun()
    elif _lt_gl == "google":
        if st.button(f"🚪 {t['sidebar_logout']}", key="glucose_logout", use_container_width=True):
            st.session_state["logged_in"] = False
            st.session_state["login_type"] = None
            st.session_state["user_id"] = None
            st.session_state["user_email"] = None
            _reset_meal_feed_state()
            st.session_state["auth_mode"] = "login"
            st.rerun()

    # ── 2. 오늘의 공복 혈당 요약 위젯 ────────────────────────────────────────
    _gl_seoul = _pytz_gl.timezone("Asia/Seoul")
    _gl_today_str = datetime.now(_gl_seoul).strftime("%Y-%m-%d")
    _blood_logs: list = st.session_state.get("blood_sugar_logs", [])
    _today_fasting_val = None
    for _lg in reversed(_blood_logs):
        if _lg.get("type") == "fasting" and _lg.get("date") == _gl_today_str:
            _today_fasting_val = _lg.get("value")
            break

    esc = html_module.escape
    if _today_fasting_val is not None:
        _fv = int(_today_fasting_val)
        _fc = "#10B981" if _fv < 100 else "#f59e0b" if _fv < 126 else "#ef4444"
        _fl = "정상 🟢" if _fv < 100 else "주의 🟡" if _fv < 126 else "고혈당 🔴"
        _fasting_inner = (
            f'<div class="ns-glucose-fasting-val" style="color:{_fc};">{_fv}</div>'
            f'<div class="ns-glucose-fasting-unit">mg/dL</div>'
            f'<div class="ns-glucose-fasting-label" style="color:{_fc};">{esc(_fl)}</div>'
        )
    else:
        _fasting_inner = '<div class="ns-glucose-fasting-empty">아직 기록되지 않음</div>'

    st.markdown(
        f"""
<div class="ns-glucose-fasting-card">
  <div class="ns-glucose-fasting-title">🌅 오늘의 공복 혈당</div>
  <div class="ns-glucose-fasting-body">{_fasting_inner}</div>
</div>
""",
        unsafe_allow_html=True,
    )

    # ── 3. 새 혈당 기록 입력 폼 ──────────────────────────────────────────────
    _MTYPE_OPTIONS = [
        "🌅 기상 직후(공복)", "🍽️ 식전", "🏃 식후 2시간", "🌙 취침 전", "❓ 기타",
    ]
    _MTYPE_KEYS = {
        "🌅 기상 직후(공복)": "fasting",
        "🍽️ 식전":           "pre_meal",
        "🏃 식후 2시간":      "postprandial",
        "🌙 취침 전":         "bedtime",
        "❓ 기타":            "other",
    }

    with st.container(border=True):
        st.markdown(
            '<div class="ns-glucose-form-title">💉 새 혈당 기록</div>',
            unsafe_allow_html=True,
        )
        mtype_label = st.radio(
            "측정 시점",
            _MTYPE_OPTIONS,
            horizontal=True,
            label_visibility="collapsed",
            key="glucose_mtype",
        )
        mtype_key = _MTYPE_KEYS[mtype_label]

        st.markdown(
            '<div class="ns-glucose-input-label">혈당 수치 입력 (mg/dL)</div>',
            unsafe_allow_html=True,
        )
        glucose_val = st.number_input(
            "혈당 수치 (mg/dL)",
            min_value=40,
            max_value=500,
            value=100,
            step=1,
            key="glucose_value_input",
            label_visibility="collapsed",
        )

        if st.button(
            "💾 기록 저장하기",
            key="glucose_save_btn",
            use_container_width=True,
            type="primary",
        ):
            _val = int(glucose_val)
            _now_seoul = datetime.now(_gl_seoul)
            _log_entry = {
                "type":        mtype_key,
                "type_label":  mtype_label,
                "value":       _val,
                "date":        _gl_today_str,
                "time":        _now_seoul.strftime("%H:%M"),
                "timestamp":   _now_seoul.isoformat(),
            }

            if "blood_sugar_logs" not in st.session_state:
                st.session_state["blood_sugar_logs"] = []
            st.session_state["blood_sugar_logs"].append(_log_entry)

            # Firestore 저장 (로그인 유저만)
            if current_uid and _lt_gl == "google":
                _now_utc = datetime.now(timezone.utc)
                _save_glucose(current_uid, mtype_key, _val, timestamp=_now_utc)
                try:
                    get_glucose_meals_cached.clear()
                except Exception:
                    pass

            # ── 도파민 피드백 ────────────────────────────────────────────────
            if mtype_key == "fasting":
                if _val < 100:
                    st.toast("🎉 완벽한 공복 혈당! 오늘 하루도 쾌적하게 시작하세요!", icon="🌿")
                elif _val < 126:
                    st.toast("✅ 공복 혈당이 정상 범위입니다. 오늘도 방어 잘 해봐요!", icon="✅")
                else:
                    st.toast("⚠️ 공복 혈당이 높습니다. 오늘 식이섬유를 꼭 챙기세요!", icon="⚠️")
            elif mtype_key == "postprandial":
                if _val < 140:
                    st.toast("🛡️ 방어 성공! 식후 혈당이 안정적입니다!", icon="🛡️")
                elif _val < 180:
                    st.toast("⚡ 식후 혈당이 살짝 올랐어요. 15분 걸어보세요!", icon="⚡")
                else:
                    st.toast("🚨 식후 혈당이 높습니다! 지금 당장 15분 빠르게 걷기!", icon="🚨")
            elif mtype_key == "pre_meal":
                if _val < 100:
                    st.toast("🌱 식전 혈당 완벽! 방어막 준비 완료입니다!", icon="🌱")
                else:
                    st.toast("📋 식전 혈당 기록 완료. 식이섬유 먼저 드세요!", icon="📋")
            elif mtype_key == "bedtime":
                if _val < 120:
                    st.toast("🌙 취침 전 혈당 안정적! 오늘 하루 수고하셨습니다!", icon="🌙")
                else:
                    st.toast("🌙 취침 전 혈당을 확인했습니다. 내일 아침 공복 혈당도 체크해보세요!", icon="🌙")
            else:
                st.toast("✅ 혈당이 기록되었습니다!", icon="✅")
            st.rerun()

    # ── 4. 오늘의 최근 기록 미니 히스토리 ───────────────────────────────────
    _today_logs = [_l for _l in _blood_logs if _l.get("date") == _gl_today_str]
    if _today_logs:
        st.markdown(
            '<div class="ns-dashboard-section-title" style="margin-top:16px;">📋 오늘의 기록</div>',
            unsafe_allow_html=True,
        )
        for _lg in reversed(_today_logs):
            _lv = int(_lg.get("value", 0))
            _lt_lbl = str(_lg.get("type_label", _lg.get("type", "")))
            _lt_time = str(_lg.get("time", ""))
            if _lv < 100:
                _lvc = "#10B981"
            elif _lv < 140:
                _lvc = "#f59e0b"
            else:
                _lvc = "#ef4444"
            st.markdown(
                f"""
<div class="ns-glucose-history-item">
  <div class="ns-glucose-history-left">
    <div class="ns-glucose-history-type">{esc(_lt_lbl)}</div>
    <div class="ns-glucose-history-time">{esc(_lt_time)}</div>
  </div>
  <div class="ns-glucose-history-val" style="color:{_lvc};">
    {_lv}<span class="ns-glucose-history-unit"> mg/dL</span>
  </div>
</div>
""",
                unsafe_allow_html=True,
            )

    # ── 5. 혈당 트렌드 차트 (로그인 유저 + Firestore 기록 있을 때만) ─────────
    if current_uid and _lt_gl == "google":
        st.markdown(
            '<div class="ns-dashboard-section-title" style="margin-top:18px;">📈 혈당 트렌드</div>',
            unsafe_allow_html=True,
        )
        _gl_period = st.radio(
            "조회 기간",
            ["오늘", "주간", "월간", "연간"],
            horizontal=True,
            label_visibility="collapsed",
            index=1,
            key="glucose_chart_period",
        )
        _gl_records = get_glucose_records(current_uid, _gl_period)
        if _gl_records:
            import pandas as pd
            import plotly.graph_objects as go

            _gl_df = pd.DataFrame(_gl_records)
            _gl_df["recorded_at_utc"] = pd.to_datetime(_gl_df["recorded_at_utc"], errors="coerce", utc=True)
            _gl_df = _gl_df.dropna(subset=["recorded_at_utc"])
            if not _gl_df.empty:
                _gl_df["시간"] = _gl_df["recorded_at_utc"].dt.tz_convert("Asia/Seoul")
                if _gl_period in ["오늘", "주간"]:
                    _gl_df["표시"] = _gl_df["시간"].dt.strftime("%m-%d %H:%M")
                else:
                    _gl_df["표시"] = _gl_df["시간"].dt.strftime("%m-%d")

                _color_map = {"fasting": "#10B981", "postprandial": "#ef4444",
                              "pre_meal": "#f59e0b", "bedtime": "#8b5cf6", "other": "#94a3b8"}
                _gl_fig = go.Figure()
                for _gtype, _gdf in _gl_df.groupby("type"):
                    _gl_fig.add_trace(go.Scatter(
                        x=_gdf["표시"], y=_gdf["value"],
                        mode="lines+markers",
                        name=str(_gtype),
                        line=dict(color=_color_map.get(str(_gtype), "#94a3b8"), width=2),
                        marker=dict(size=8),
                        hovertemplate="<b>%{x}</b><br>혈당: <b>%{y} mg/dL</b><extra></extra>",
                    ))
                _gl_fig.add_hline(y=100, line_dash="dot", line_color="rgba(16,185,129,0.5)",
                                  annotation_text="공복 정상", annotation_font_size=9)
                _gl_fig.add_hline(y=140, line_dash="dot", line_color="rgba(239,68,68,0.5)",
                                  annotation_text="식후 경계", annotation_font_size=9)
                _gl_fig.update_layout(
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    margin=dict(l=0, r=10, t=10, b=6),
                    yaxis=dict(
                        title=dict(text="mg/dL", font=dict(size=10, color="#94a3b8")),
                        gridcolor="rgba(0,0,0,0.06)", tickfont=dict(size=10), fixedrange=True,
                    ),
                    xaxis=dict(gridcolor="rgba(0,0,0,0.06)", tickangle=-30,
                               tickfont=dict(size=10), fixedrange=True),
                    hoverlabel=dict(bgcolor="white", bordercolor="#e2e8f0",
                                   font_size=13, font_family="Noto Sans KR"),
                    dragmode=False, height=230, showlegend=True,
                    legend=dict(orientation="h", y=1.1, font=dict(size=11)),
                )
                _gl_fig.update_xaxes(fixedrange=True)
                _gl_fig.update_yaxes(fixedrange=True)
                with st.container(border=True):
                    st.plotly_chart(_gl_fig, use_container_width=True,
                                    config={"displayModeBar": False, "scrollZoom": False})
            else:
                st.info("유효한 시간 데이터가 없습니다.")
        else:
            st.markdown(
                '<div style="text-align:center;padding:24px 0;color:#94a3b8;font-size:0.88rem;">📊 Firestore에 저장된 혈당 기록이 없습니다.<br>위 폼으로 기록하면 차트가 나타납니다.</div>',
                unsafe_allow_html=True,
            )

# ── 나의 기록 탭 (Cal AI 스타일 히스토리) ──
elif menu_key == "history":
    # 1. 로그인 UID (앱 전역은 st.session_state["user_id"] 사용 — Firebase UID / 게스트 demo ID)
    current_uid = st.session_state.get("user_id")
    current_uid_str = str(current_uid) if current_uid else ""

    if current_uid:
        # 2. [강제 직결] daily_summary 없으면 Firestore에서 즉시 채움 (login_type 분기와 무관)
        if st.session_state.get("daily_summary") is None:
            st.session_state["daily_summary"] = get_daily_summary(current_uid, get_today_str())
            st.session_state["daily_summary_date_key"] = get_today_str()
        _hydrate_history_daily_from_firestore(current_uid)

        _MEAL_FEED_LOGIC_V = 2
        if st.session_state.get("_meal_feed_client_v") != _MEAL_FEED_LOGIC_V:
            st.session_state["_meal_feed_client_v"] = _MEAL_FEED_LOGIC_V
            st.session_state["meal_feed_hydrated_uid"] = None
            st.session_state["meal_feed_sort_field"] = None

        # 3. [강제 직결] 이 세션·유저에서 피드 미로드면 get_meal_feed (hydrated_uid는 문자열로 통일)
        if str(st.session_state.get("meal_feed_hydrated_uid")) != current_uid_str:
            try:
                feed, last_snap, used_sf = get_meal_feed(current_uid, 5, None, sort_field=None)
                if used_sf:
                    st.session_state["meal_feed_sort_field"] = used_sf
                st.session_state["feed_items"] = feed
                st.session_state["last_doc"] = last_snap.id if last_snap else None
                st.session_state["has_more"] = len(feed) >= 5
                st.session_state["meal_feed_hydrated_uid"] = current_uid_str
                st.session_state["meal_feed_uid"] = current_uid_str
            except Exception as _hydr_feed_e:
                traceback.print_exc(file=sys.stderr)
                st.session_state["feed_items"] = []
                st.session_state["last_doc"] = None
                st.session_state["has_more"] = False
                st.error(f"일지를 불러오지 못했습니다: {_hydr_feed_e}")
    else:
        st.error("🚨 진단: 유저 인증 ID를 세션에서 찾을 수 없습니다. (Key 오류)")

    _lt_h = st.session_state.get("login_type")

    # ── 다크 그린 프리미엄 환영 카드 (Ghost 제거: 최상단 첫 번째 요소로 끌어올림) ──
    st.markdown(
        """
<div class="ns-hist-welcome-card">
  <div class="ns-hist-welcome-sub">혈당 방어 리포트 센터</div>
  <div class="ns-hist-welcome-title">오늘도 쾌적하게<br/>혈당 방어전, 결과 보고 🛡️</div>
  <div class="ns-hist-welcome-hint">최근 식사 기록을 AI가 분석했습니다</div>
</div>
""",
        unsafe_allow_html=True,
    )

    # 로그인/로그아웃 버튼 (헤더 아래 인라인 — 빈 c1 Ghost 제거 후 단독 배치)
    if _lt_h == "guest":
        if st.button(f"🔐 {t['sidebar_go_login']}", key="history_go_login", use_container_width=True):
            st.session_state["logged_in"] = False
            st.session_state["login_type"] = None
            st.session_state["user_id"] = None
            st.session_state["user_email"] = None
            _reset_meal_feed_state()
            st.session_state["auth_mode"] = "login"
            st.rerun()
    elif _lt_h == "google":
        if st.button(f"🚪 {t['sidebar_logout']}", key="history_logout", use_container_width=True):
            st.session_state["logged_in"] = False
            st.session_state["login_type"] = None
            st.session_state["user_id"] = None
            st.session_state["user_email"] = None
            _reset_meal_feed_state()
            st.session_state["auth_mode"] = "login"
            st.rerun()

    _uid_hist = st.session_state.get("user_id")
    feed_items = st.session_state.get("feed_items", [])
    _pm_hist = st.session_state.get("pre_meal") or {}

    # ── Top 3 요약 위젯 ──────────────────────────────────────────────────────
    _render_history_summary_cards(t, feed_items, _pm_hist)

    # ── 트렌드 차트 + 기간 컨트롤 (카드 내부에서 통합 렌더) ──────────────────
    _render_history_trend_chart(t, feed_items)

    # ── 타임라인 히스토리 섹션 타이틀 ────────────────────────────────────────
    if feed_items:
        st.markdown(
            '<div class="ns-dashboard-section-title" style="margin-top:18px;">🗓️ 식사 기록</div>',
            unsafe_allow_html=True,
        )

    if len(feed_items) > 0:
        for i, rec in enumerate(feed_items):
            esc = html_module.escape
            rec_score = int(rec.get("blood_sugar_score", 0) or 0)
            rec_carbs = int(rec.get("total_carbs", 0) or 0)
            rec_protein = int(rec.get("total_protein", 0) or 0)
            rec_fat = int(rec.get("total_fat", 0) or 0)
            est_spike = int(rec.get("estimated_spike", 0) or 0)
            _when = _meal_feed_display_time(rec)
            _doc_id = rec.get("doc_id") or ""
            _menu_name = _extract_menu_names(rec) or t.get("pre_meal_menu_fallback", "기록된 식단")
            _adv = str(rec.get("advice") or "")
            image_url = rec.get("image_url")

            # 위험도 색상·라벨·이모지
            if rec_score <= 40:
                _rc = "#10B981"; _rl = "방어 성공"; _re = "🛡️"
                _rc_bg = "rgba(16,185,129,0.1)"
            elif rec_score <= 65:
                _rc = "#f59e0b"; _rl = "주의"; _re = "⚠️"
                _rc_bg = "rgba(245,158,11,0.1)"
            else:
                _rc = "#ef4444"; _rl = "위험"; _re = "💥"
                _rc_bg = "rgba(239,68,68,0.1)"

            with st.container(border=True):
                # 헤더: 시간 + 삭제 버튼
                _th1, _th2 = st.columns([8, 1])
                with _th1:
                    st.markdown(
                        f'<div class="ns-tl-time">{esc(_when)}</div>',
                        unsafe_allow_html=True,
                    )
                with _th2:
                    if _doc_id and st.button(
                        "🗑️", key=f"meal_del_{_doc_id}_{i}",
                        help=t.get("delete_record", "기록 삭제"),
                    ):
                        ok_del, failed_step = delete_meal_record(_uid_hist, _doc_id)
                        if ok_del:
                            _reset_meal_feed_state()
                            st.success(t.get("delete_record_full", "기록이 삭제되었습니다."))
                            st.rerun()
                        else:
                            st.error(t.get("delete_record_failed", "삭제 실패.") + (f" ({failed_step})" if failed_step else ""))

                # 메인 타임라인 로우: 배지 + 메뉴명 + 매크로
                st.markdown(
                    f"""
<div class="ns-tl-row">
  <div class="ns-tl-badge" style="background:{_rc_bg};color:{_rc};">
    <span class="ns-tl-badge-icon">{_re}</span>
    <span class="ns-tl-badge-score">{rec_score}</span>
    <span class="ns-tl-badge-label">{esc(_rl)}</span>
  </div>
  <div class="ns-tl-body">
    <div class="ns-tl-menu">{esc(_menu_name)}</div>
    <div class="ns-tl-macros">
      🍚 <b>{rec_carbs}g</b>&nbsp;·&nbsp;💪 <b>{rec_protein}g</b>&nbsp;·&nbsp;🧈 <b>{rec_fat}g</b>&nbsp;·&nbsp;⚡ 스파이크 <b>{est_spike}</b>
    </div>
  </div>
</div>
""",
                    unsafe_allow_html=True,
                )

                # AI 코치 분석 (접기/펼치기)
                if _adv:
                    with st.expander("💡 AI 코치 분석", expanded=False):
                        st.markdown(
                            f'<div class="ns-tl-advice">{esc(_adv)}</div>',
                            unsafe_allow_html=True,
                        )

                # 식단 사진 (접기/펼치기)
                if image_url:
                    with st.expander("📷 식단 사진", expanded=False):
                        image_bytes, debug_msg = fetch_image_bytes_direct(image_url)
                        if image_bytes:
                            st.image(image_bytes, use_container_width=True)
                        else:
                            st.caption(f"이미지 로드 실패: {debug_msg}")

        # 더 보기
        if st.session_state.get("has_more") and _uid_hist:
            if st.button("더 보기 🔽", key="meal_feed_load_more", use_container_width=True):
                try:
                    _sf = st.session_state.get("meal_feed_sort_field")
                    if not _sf:
                        st.error("정렬 필드가 없어 추가 페이지를 불러올 수 없습니다.")
                    else:
                        more, last_snap, _ = get_meal_feed(
                            _uid_hist, 5,
                            st.session_state.get("last_doc"),
                            sort_field=_sf,
                        )
                        st.session_state["feed_items"].extend(more)
                        st.session_state["last_doc"] = last_snap.id if last_snap else None
                        st.session_state["has_more"] = len(more) >= 5
                except Exception as _e2:
                    traceback.print_exc(file=sys.stderr)
                    st.error(f"추가 불러오기 실패: {_e2}")
                st.rerun()

    elif not _uid_hist:
        st.info(t.get("no_history_msg", "기록이 없습니다."))
    else:
        st.markdown(
            """
<div style="text-align:center;padding:40px 20px;color:#94a3b8;">
  <div style="font-size:3rem;margin-bottom:12px;">🍽️</div>
  <div style="font-size:1rem;font-weight:600;color:#475569;margin-bottom:6px;">아직 기록된 식단이 없어요</div>
  <div style="font-size:0.85rem;">분석 후 '기록하기' 버튼을 눌러 보세요</div>
</div>
""",
            unsafe_allow_html=True,
        )

elif menu_key == "achievement":
    _render_achievement_tab(t)

# Native Bottom Bar: 본문(스캐너/기록) 이후 렌더 → DOM 맨 아래 (fixed 미적용 시에도 상단에 깔리지 않음)
render_bottom_bar()
