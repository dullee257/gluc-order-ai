import streamlit as st
from google import genai
import PIL.Image
from datetime import datetime

# 1. 페이지 설정
st.set_page_config(page_title="NutriSort AI", page_icon="🥗", layout="wide")

# 2. 세션 상태 초기화
if 'history' not in st.session_state:
    st.session_state['history'] = []
if 'current_analysis' not in st.session_state:
    st.session_state['current_analysis'] = None

# 다국어 텍스트 사전 정의
texts = {
    "KO": {
        "title": "🥗 NutriSort AI",
        "sidebar_title": "💡 NutriSort 관리 시스템",
        "description": "#### **\"무엇을 먼저 먹을까요?\"** AI가 식사 순서를 정렬합니다.",
        "uploader_label": "오늘의 식단 사진을 올려주세요",
        "analyze_btn": "🔍 AI 분석 및 순서 정렬",
        "save_btn": "💾 이 식단 기록 저장하기",
        "scanner_menu": "식단 스캐너",
        "history_menu": "나의 식단 기록",
        "analysis_title": "✅ 추천 섭취 순서",
        "advice_title": "💡 식단 분석 소견",
        "advice_prompt": "사진 속 음식을 분석해서 혈당 관리에 따른 식사 순서를 정해줘. 잡곡밥 칭찬, 식사 순서 원리(식이섬유 그물망), 나트륨 주의 조언 포함.",
        "save_msg": "대표님, '나의 기록' 탭에 저장되었습니다!",
        "browse_text": "파일 찾기",
        "drag_text": "여기에 사진을 드래그하세요 (JPG, PNG)"
    },
    "EN": {
        "title": "🥗 NutriSort AI",
        "sidebar_title": "💡 NutriSort Admin",
        "description": "#### **\"What to eat first?\"** AI sorts your eating order for better health.",
        "uploader_label": "Upload your meal photo",
        "analyze_btn": "🔍 AI Analysis & Sorting",
        "save_btn": "💾 Save this record",
        "scanner_menu": "Meal Scanner",
        "history_menu": "My History",
        "analysis_title": "✅ Recommended Eating Order",
        "advice_title": "💡 AI Nutrition Advice",
        "advice_prompt": "Analyze the food in the photo and set the eating order for blood sugar management. Explain the 'fiber mesh' principle and give expert advice on sodium intake.",
        "save_msg": "Successfully saved to 'My History'!",
        "browse_text": "Browse files",
        "drag_text": "Drag and drop file here"
    }
}

# 3. 사이드바 메뉴 (언어 선택을 먼저 배치하여 변수 생성)
with st.sidebar:
    st.title("Settings")
    lang = st.radio("Language / 언어 선택", ["KO", "EN"])
    t = texts[lang] # 여기서 lang 변수가 생성됨
    st.divider()
    
    st.title(t["sidebar_title"])
    menu = st.radio("Menu", [t["scanner_menu"], t["history_menu"]])
    st.divider()
    st.info("NutriSort: Smart Eating, Healthy Living")

# 4. 언어 설정 후 CSS 주입 (더 광범위한 타겟팅 적용)
st.markdown(f"""
    <style>
    /* 1. 업로드 버튼 내 'Browse files' 글자 숨기기 및 대체 */
    [data-testid="stFileUploader"] section button div::before {{
        content: "{t['browse_text']}";
        position: absolute;
        left: 50%;
        transform: translateX(-50%);
        background-color: #ffffff; /* 버튼 배경색과 일치시켜 글자를 덮음 */
        width: 80%;
        text-align: center;
        z-index: 10;
    }}

    /* 2. 'Drag and drop file here' 텍스트 강제 변환 */
    [data-testid="stFileUploader"] section > div:first-child {{
        font-size: 0 !important;
    }}
    [data-testid="stFileUploader"] section > div:first-child::before {{
        content: "{t['drag_text']}";
        font-size: 16px !important;
        display: block;
        margin-bottom: 10px;
    }}

    /* 3. 하단 파일 제한 문구(Limit 200MB 등) 숨기기 */
    [data-testid="stFileUploader"] section > div:last-child {{
        display: none !important;
    }}
    
    /* 4. 기존 텍스트들이 겹치지 않게 투명도 조절 */
    [data-testid="stFileUploader"] section button span {{
        opacity: 0;
    }}
    </style>
""", unsafe_allow_html=True)

# 5. 메인 화면 - 식단 스캐너
if menu == t["scanner_menu"]:
    st.title(t["title"])
    st.markdown(t["description"])
    
    API_KEY = "AIzaSyDeTT5LkMz00B3UfmVu3s2CqeTJmaiVm8I"
    client = genai.Client(api_key=API_KEY)

    col1, col2 = st.columns([1, 1])
    
    with col1:
        uploaded_file = st.file_uploader(t["uploader_label"], type=["jpg", "png", "jpeg"])
        if uploaded_file:
            img = PIL.Image.open(uploaded_file)
            caption_text = "📷 촬영된 식단" if lang == "KO" else "📷 Photo"
            st.image(img, caption=caption_text, use_container_width=True)

    with col2:
        if uploaded_file and st.button(t["analyze_btn"], use_container_width=True):
            with st.spinner("Processing..."):
                prompt = f"""
                Analyze the food in the photo for blood sugar management.
                Criteria: 1.Green(Fiber), 2.Yellow(Protein), 3.Red(Carbs)
                Output Format: FoodName|TrafficColor|Order
                Language: {lang}
                """
                response = client.models.generate_content(model="gemini-flash-latest", contents=[prompt, img])
                
                raw_lines = response.text.strip().split('\n')
                items = []
                for line in raw_lines:
                    if '|' in line and not any(x in line for x in ['---', 'Food', '음식']):
                        parts = line.split('|')
                        if len(parts) >= 3:
                            items.append([p.strip() for p in parts])
                
                if items:
                    sorted_items = sorted(items, key=lambda x: x[2])
                    advice_response = client.models.generate_content(model="gemini-flash-latest", contents=[t["advice_prompt"], img])
                    
                    st.session_state['current_analysis'] = {
                        "sorted_items": sorted_items,
                        "advice": advice_response.text,
                        "menu_str": ", ".join([item[0] for item in items])
                    }

        if st.session_state['current_analysis']:
            res = st.session_state['current_analysis']
            st.subheader(t["analysis_title"])
            for name, color, score in res['sorted_items']:
                icon = "🟢" if any(x in color for x in ["초록", "Green"]) else "🟡" if any(x in color for x in ["노랑", "Yellow"]) else "🔴"
                b_color = "green" if icon=="🟢" else "orange" if icon=="🟡" else "red"
                st.markdown(f'<div style="background-color: #f8f9fa; padding: 15px; border-radius: 12px; margin-bottom: 10px; border-left: 8px solid {b_color};">{icon} <b>{name}</b> <span style="float: right;">{score}</span></div>', unsafe_allow_html=True)
            
            st.divider()
            st.subheader(t["advice_title"])
            st.success(res['advice'])
            
            if st.button(t["save_btn"], use_container_width=True):
                st.session_state['history'].append({
                    "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "menu": res['menu_str'],
                    "advice": res['advice']
                })
                st.balloons()
                st.success(t["save_msg"])
                st.session_state['current_analysis'] = None

elif menu == t["history_menu"]:
    st.title(f"📅 {t['history_menu']}")
    if st.session_state['history']:
        for rec in reversed(st.session_state['history']):
            with st.expander(f"🍴 {rec['date']}"):
                st.write(f"**Menu:** {rec['menu']}")
                st.write(f"**Advice:** {rec['advice']}")
    else:
        st.info("No records found.")
