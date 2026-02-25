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

# 다국어 텍스트 사전 정의 (피그마 디자인 반영 버전)
texts = {
    "KO": {
        "title": "🥗 NutriSort AI",
        "sidebar_title": "💡 NutriSort 관리 시스템",
        "description": "#### **\"오늘의 혈당 상황도\"**", # 피그마 상단 타이틀
        "uploader_label": "음식 스캔하기", # 카메라 원형 영역 라벨
        "analyze_btn": "먹을 순서 정렬하기", # 피그마 메인 버튼 문구
        "save_btn": "💾 이 식단 기록 저장하기",
        "scanner_menu": "식단 스캐너",
        "history_menu": "나의 식단 기록",
        "analysis_title": "섭취순서", # 피그마 중간 타이틀
        "advice_title": "식단분석", # 피그마 하단 타이틀
        "advice_prompt": "사진 속 음식을 분석해서 혈당 관리에 따른 식사 순서를 정해줘. 잡곡밥 칭찬, 식사 순서 원리(식이섬유 그물망), 나트륨 주의 조언 포함.",
        "save_msg": "대표님, '나의 기록' 탭에 저장되었습니다!",
        "browse_text": "파일 찾기",
        "drag_text": "여기에 사진을 드래그하세요"
    },
    "EN": {
        "title": "🥗 NutriSort AI",
        "sidebar_title": "💡 NutriSort Admin",
        "description": "#### **\"Daily Glucose Status\"**",
        "uploader_label": "Scan Food",
        "analyze_btn": "Sort Eating Order",
        "save_btn": "💾 Save this record",
        "scanner_menu": "Meal Scanner",
        "history_menu": "My History",
        "analysis_title": "Eating Order",
        "advice_title": "Nutritional Analysis",
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

# 4. 언어 설정 및 피그마 디자인(민트 테마) CSS 주입
st.markdown(f"""
    <style>
    /* 전체 배경색 조정 (피그마 느낌의 연한 그레이/화이트) */
    .stApp {{
        background-color: #f8f9fa;
    }}

    /* 버튼 공통 스타일 (배경 흰색 #fefefe, 테두리 민트 #86cc85) */
    div.stButton > button {{
        background-color: #fefefe !important;
        color: #000000 !important;
        border: 2px solid #86cc85 !important;
        border-radius: 15px !important; /* 피그마의 둥근 모서리 */
        height: 60px !important;
        font-weight: bold !important;
        font-size: 18px !important;
        transition: all 0.3s ease;
    }}
    
    /* 버튼 호버 효과 */
    div.stButton > button:hover {{
        background-color: #86cc85 !important;
        color: #ffffff !important;
    }}

    /* 업로드 칸 디자인 커스텀 (카메라 아이콘 색상 반영) */
    [data-testid="stFileUploader"] section {{
        background-color: #fefefe !important;
        border: 2px dashed #86cc85 !important;
        border-radius: 20px !important;
    }}

    /* 업로드 칸 내부 텍스트 및 버튼 */
    [data-testid="stFileUploader"] section button div::before {{
        content: "{t['browse_text']}";
        color: #000000;
    }}
    
    /* 분석 결과 카드 디자인 (피그마 리스트 형태) */
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
    st.title(t["title"])
    st.markdown(t["description"])
    
    API_KEY = st.secrets["GEMINI_API_KEY"]
    client = genai.Client(api_key=API_KEY)

    col1, col2 = st.columns([1, 1])
    
    with col1:
        # 1️⃣ 파일 업로드
        uploaded_file = st.file_uploader(
            t["uploader_label"],
            type=["jpg", "png", "jpeg"]
        )
    
        # 2️⃣ 카메라 촬영 추가
        camera_photo = st.camera_input(
            "📸 사진 촬영" if lang == "KO" else "📸 Take Photo"
        )
    
        # 3️⃣ 실제 사용할 이미지 결정
        img = None
        if camera_photo is not None:
            img = PIL.Image.open(camera_photo)
        elif uploaded_file is not None:
            img = PIL.Image.open(uploaded_file)
    
        # 4️⃣ 이미지 미리보기
        if img is not None:
            caption_text = "📷 촬영된 식단" if lang == "KO" else "📷 Captured Photo"
            st.image(img, caption=caption_text, use_container_width=True)
    
    
    with col2:
        # 🔥 uploaded_file → img 로 변경 (중요)
        if img is not None and st.button(t["analyze_btn"], use_container_width=True):
            with st.spinner("Processing..."):
                prompt = f"""
                Analyze the food in the photo for blood sugar management.
                Criteria: 1.Green(Fiber), 2.Yellow(Protein), 3.Red(Carbs)
                Output Format: FoodName|TrafficColor|Order
                Language: {lang}
                """
    
                response = client.models.generate_content(
                    model="gemini-flash-latest",
                    contents=[prompt, img]
                )
    
                raw_lines = response.text.strip().split('\n')
                items = []
                for line in raw_lines:
                    if '|' in line and not any(x in line for x in ['---', 'Food', '음식']):
                        parts = line.split('|')
                        if len(parts) >= 3:
                            items.append([p.strip() for p in parts])
    
                if items:
                    sorted_items = sorted(items, key=lambda x: x[2])
    
                    advice_response = client.models.generate_content(
                        model="gemini-flash-latest",
                        contents=[t["advice_prompt"], img]
                    )
    
                    st.session_state['current_analysis'] = {
                        "sorted_items": sorted_items,
                        "advice": advice_response.text,
                        "menu_str": ", ".join([item[0] for item in items])
                    }

        if st.session_state['current_analysis']:
            res = st.session_state['current_analysis']
            
            # 피그마 디자인 타이틀 적용 (섭취순서)
            st.markdown(f"### {t['analysis_title']}")
            
            for name, color, score in res['sorted_items']:
                # 피그마 디자인처럼 우측에 동그란 신호등 배치
                # 피그마 신호등 색상 적용 (초록: #00FF00, 노랑: #FFFF00, 빨강: #FF0000)
                icon_color = "#00FF00" if any(x in color for x in ["초록", "Green"]) else "#FFFF00" if any(x in color for x in ["노랑", "Yellow"]) else "#FF0000"
                
                # HTML/CSS를 이용해 피그마 카드 스타일 구현
                st.markdown(f"""
                    <div class="result-card">
                        <span style="font-size: 18px; font-weight: 600; color: #333;">{name}</span>
                        <div style="width: 22px; height: 22px; background-color: {icon_color}; border-radius: 50%; box-shadow: inset 0 0 5px rgba(0,0,0,0.1);"></div>
                    </div>
                """, unsafe_allow_html=True)
            
            st.divider()
            
            # 피그마 디자인 타이틀 적용 (식단분석)
            st.markdown(f"### {t['advice_title']}")
            st.info(res['advice'])
            
            # 저장 버튼 부분
            if st.button(t["save_btn"], use_container_width=True):
                st.session_state['history'].append({
                    "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "image": uploaded_file, # 원본 이미지 데이터 저장
                    "sorted_items": res['sorted_items'], # 분석된 순서 리스트 저장
                    "advice": res['advice'] # AI 소견 저장
                })
                st.balloons()
                st.success(t["save_msg"])
                st.session_state['current_analysis'] = None

# 5. 나의 기록 탭
elif menu == t["history_menu"]:
    st.title(f"📅 {t['history_menu']}")
    if st.session_state['history']:
        for rec in reversed(st.session_state['history']):
            with st.expander(f"🍴 {rec['date']} 식단 기록"):
                # 1. 저장된 사진 표시
                if rec['image']:
                    st.image(rec['image'], use_container_width=True)
                
                # 2. 저장된 섭취 순서 카드 표시
                st.markdown(f"**{t['analysis_title']}**")
                for name, color, score in rec['sorted_items']:
                    icon_color = "#00FF00" if any(x in color for x in ["초록", "Green"]) else "#FFFF00" if any(x in color for x in ["노랑", "Yellow"]) else "#FF0000"
                    st.markdown(f"""
                        <div class="result-card">
                            <span style="font-size: 16px; font-weight: 500;">{name}</span>
                            <div style="width: 18px; height: 18px; background-color: {icon_color}; border-radius: 50%;"></div>
                        </div>
                    """, unsafe_allow_html=True)
                
                # 3. 저장된 소견 표시
                st.divider()
                st.markdown(f"**{t['advice_title']}**")
                st.info(rec['advice'])
    else:
        st.info("No records found.")

