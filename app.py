import streamlit as st
from google import genai
import PIL.Image
from datetime import datetime

# 1. 페이지 설정 (모바일 최적화를 위해 centered 레이아웃 권장)
st.set_page_config(page_title="NutriSort AI", page_icon="🥗", layout="centered")

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
        "description": "오늘의 혈당 상황도", 
        "uploader_label": "음식 스캔하기",
        "analyze_btn": "혈당관리 솔루션 및 섭취순서 분석",
        "save_btn": "💾 이 식단 기록 저장하기",
        "scanner_menu": "식단 스캐너",
        "history_menu": "나의 식단 기록",
        "analysis_title": "섭취순서",
        "advice_title": "식단분석",
        "advice_prompt": "사진 속 음식을 분석해서 혈당 관리에 따른 식사 순서를 정해줘. 잡곡밥 칭찬, 식사 순서 원리(식이섬유 그물망), 나트륨 주의 조언 포함.",
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

# 4. CSS 주입 (모바일 터치 및 피그마 디자인 반영)
st.markdown(f"""
    <style>
    .stApp {{ background-color: #f8f9fa; }}
    div.stButton > button {{
        background-color: #fefefe !important;
        color: #000000 !important;
        border: 2px solid #86cc85 !important;
        border-radius: 15px !important;
        height: 70px !important; /* 터치하기 쉽게 높이 조절 */
        font-weight: bold !important;
        font-size: 18px !important;
        width: 100% !important;
    }}
    [data-testid="stFileUploader"] section {{
        background-color: #fefefe !important;
        border: 2px dashed #86cc85 !important;
        border-radius: 20px !important;
    }}
    .result-card {{
        background-color: #ffffff;
        padding: 20px;
        border-radius: 15px;
        margin-bottom: 12px;
        box-shadow: 0px 4px 6px rgba(0, 0, 0, 0.05);
        display: flex;
        justify-content: space-between;
        align-items: center;
        border-left: 10px solid #86cc85;
    }}
    </style>
""", unsafe_allow_html=True)

# 5. 메인 화면 - 식단 스캐너
if menu == t["scanner_menu"]:
    st.title(t["description"]) # "오늘의 혈당 상황도"
    
    API_KEY = st.secrets["GEMINI_API_KEY"]
    client = genai.Client(api_key=API_KEY)

    # 모바일은 한 줄로 쭉 배치하는 것이 가장 깔끔합니다.
    input_tab1, input_tab2 = st.tabs(["📸 직접 촬영", "📁 갤러리 선택"])
    
    img = None
    current_file = None

    with input_tab1:
        camera_photo = st.camera_input("오늘의 식단을 촬영해 주세요")
        if camera_photo:
            img = PIL.Image.open(camera_photo)
            current_file = camera_photo

    with input_tab2:
        uploaded_file = st.file_uploader(t["uploader_label"], type=["jpg", "png", "jpeg"])
        if uploaded_file:
            img = PIL.Image.open(uploaded_file)
            current_file = uploaded_file

    if img:
        st.image(img, caption="📷 스캔된 식단", use_container_width=True)
        
        if st.button(t["analyze_btn"], use_container_width=True):
            with st.spinner("AI 분석 중..."):
                prompt = f"Analyze food for blood sugar management. Criteria: 1.Green(Fiber), 2.Yellow(Protein), 3.Red(Carbs). Format: FoodName|TrafficColor|Order. Lang: {lang}"
                response = client.models.generate_content(model="gemini-1.5-flash", contents=[prompt, img])
                
                raw_lines = response.text.strip().split('\n')
                items = []
                for line in raw_lines:
                    if '|' in line and not any(x in line for x in ['---', 'Food', '음식']):
                        parts = line.split('|')
                        if len(parts) >= 3:
                            items.append([p.strip() for p in parts])
                
                if items:
                    sorted_items = sorted(items, key=lambda x: x[2])
                    advice_response = client.models.generate_content(model="gemini-1.5-flash", contents=[t["advice_prompt"], img])
                    
                    st.session_state['current_analysis'] = {
                        "sorted_items": sorted_items,
                        "advice": advice_response.text,
                        "menu_str": ", ".join([item[0] for item in items]),
                        "saved_file": current_file # 실제 분석에 쓰인 파일 저장
                    }

    if st.session_state['current_analysis']:
        res = st.session_state['current_analysis']
        st.divider()
        st.subheader(f"✅ {t['analysis_title']}")
        
        for name, color, score in res['sorted_items']:
            icon_color = "#00FF00" if any(x in color for x in ["초록", "Green"]) else "#FFFF00" if any(x in color for x in ["노랑", "Yellow"]) else "#FF0000"
            st.markdown(f"""
                <div class="result-card">
                    <span style="font-size: 18px; font-weight: 600;">{name}</span>
                    <div style="width: 22px; height: 22px; background-color: {icon_color}; border-radius: 50%;"></div>
                </div>
            """, unsafe_allow_html=True)
        
        st.divider()
        st.subheader(f"💡 {t['advice_title']}")
        st.info(res['advice'])
        
        if st.button(t["save_btn"], use_container_width=True):
            st.session_state['history'].append({
                "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "image": res['saved_file'],
                "sorted_items": res['sorted_items'],
                "advice": res['advice']
            })
            st.balloons()
            st.success(t["save_msg"])
            st.session_state['current_analysis'] = None

# (나의 기록 탭은 기존 로직 유지하되 디자인 가이드 적용)
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
