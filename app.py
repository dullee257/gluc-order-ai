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

# 4. 피그마 디자인(민트 테마) 완벽 이식 CSS
# 4. CSS 주입 (중앙 정렬 및 불필요 요소 완전 제거)
st.markdown(f"""
    <style>
    /* 전체 배경색 */
    .stApp {{ background-color: #f8f9fa; }}

    /* 1. 업로드 섹션: 크기를 줄이고 입체감 부여 */
    [data-testid="stFileUploader"] section {
        background-color: #ffffff !important;
        /* 민트 테두리 + 바깥으로 퍼지는 다중 글로우 효과 */
        border: 10px solid #86cc85 !important; 
        box-shadow: 
            0 0 15px rgba(134, 204, 133, 0.4), 
            0 0 30px rgba(134, 204, 133, 0.2) !important;
        border-radius: 50% !important;
        width: 240px !important;  /* 버튼 크기 약간 축소 */
        height: 240px !important;
        min-width: 240px !important;
        transition: all 0.2s ease-in-out !important; /* 애니메이션 속도 */
    }

    /* 2. 클릭 제스처: 누를 때 살짝 작아지며 빛이 강해짐 */
    [data-testid="stFileUploader"] section:active {
        transform: scale(0.95); /* 5% 작아짐 */
        box-shadow: 0 0 40px rgba(134, 204, 133, 0.6) !important;
        border-color: #75b874 !important;
    }

    /* 3. 원 내부 아이콘 스타일 보정 */
    [data-testid="stFileUploader"] section::before {
        content: "📷"; 
        font-size: 60px; /* 아이콘 크기 조절 */
        margin-bottom: 2px;
        filter: drop-shadow(0px 2px 4px rgba(0,0,0,0.1));
    }

    /* 4. 원 내부 텍스트 스타일 보정 */
    [data-testid="stFileUploader"] section::after {
        content: "음식 스캔하기"; 
        font-size: 18px;
        color: #555555;
        letter-spacing: -0.5px;
    }

    /* 결과 카드 디자인 */
    .result-card {{
        background-color: #ffffff; padding: 20px; border-radius: 15px;
        margin-bottom: 12px; box-shadow: 0px 4px 6px rgba(0, 0, 0, 0.05);
        display: flex; justify-content: space-between; align-items: center;
        border-left: 10px solid #86cc85;
    }}
    </style>
""", unsafe_allow_html=True)

# 5. 메인 화면 - 식단 스캐너
if menu == t["scanner_menu"]:
    # 상단 여백 확보를 위해 margin-top 조정
    st.markdown(f"<h1 style='text-align:center; margin-top: 20px; margin-bottom: 40px;'>{t['description']}</h1>", unsafe_allow_html=True)
    
    API_KEY = st.secrets["GEMINI_API_KEY"]
    client = genai.Client(api_key=API_KEY)

    # 2️⃣ 업로드 위젯 (외부 라벨을 완전히 숨김)
    uploaded_file = st.file_uploader(
        "label_hidden", 
        type=["jpg", "png", "jpeg"],
        label_visibility="collapsed" 
    )
    
    # 3️⃣ 사진 분석 및 결과 출력 로직 (기존과 동일하지만 들여쓰기 주의)
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









