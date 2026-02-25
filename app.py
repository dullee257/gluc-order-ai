import streamlit as st
from google import genai
import PIL.Image
from datetime import datetime

# 1. 페이지 설정 (모바일 최적화를 위해 centered 레이아웃 권장)
st.set_page_config(
    page_title="NutriSort AI", # 앱 이름
    page_icon="🥗",            # 앱 아이콘 (이모지 대신 나중에 로고 파일로 교체 가능)
    layout="centered"          # 모바일 앱처럼 가운데 정렬
)

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

    # 탭을 없애고 피그마 디자인처럼 하나의 통합 버튼으로 구성합니다.
    # 모바일에서 이 버튼을 누르면 [카메라 / 미디어 보관함] 메뉴가 즉시 뜹니다.
    uploaded_file = st.file_uploader(
        t["uploader_label"], # "음식 스캔하기"
        type=["jpg", "png", "jpeg"]
    )

    if uploaded_file:
        img = PIL.Image.open(uploaded_file)
        st.image(img, caption="📷 스캔된 식단", use_container_width=True)
        
        # 분석 버튼 (피그마 스타일)
        if st.button(t["analyze_btn"], use_container_width=True):
            with st.spinner("AI 분석 중..."):
                try:
                    # 에러 방지: 모델명을 'gemini-1.5-flash'로 고정
                    prompt = f"Analyze food for glucose management. Format: FoodName|TrafficColor|Order. Lang: {lang}"
                    response = client.models.generate_content(
                        model="gemini-1.5-flash", 
                        contents=[prompt, img]
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
                        # 소견 분석도 동일 모델로 수행
                        advice_res = client.models.generate_content(
                            model="gemini-1.5-flash", 
                            contents=[t["advice_prompt"], img]
                        )
                        
                        st.session_state['current_analysis'] = {
                            "sorted_items": sorted_items,
                            "advice": advice_res.text,
                            "raw_img": uploaded_file
                        }
                except Exception as e:
                    st.error(f"분석 엔진 오류가 발생했습니다. 잠시 후 다시 시도해 주세요. ({str(e)})")

    # 결과 출력 (피그마 카드 디자인)
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
                "image": res['raw_img'],
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




