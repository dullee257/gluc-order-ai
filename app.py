import streamlit as st
# 1. 카톡 및 네이버 인앱 브라우저 탈출 스크립트 (화면 깨짐 및 양식 중복 제출 방지)
st.components.v1.html(
    """
    <script>
    var agent = navigator.userAgent.toLowerCase();
    var currentUrl = window.location.href;
    
    if (agent.indexOf('kakao') > -1) {
        // 카카오톡 탈출
        location.href = 'kakaotalk://web/openExternal?url=' + encodeURIComponent(currentUrl);
    } else if (agent.indexOf('naver') > -1) {
        // 네이버 앱 탈출
        if (agent.indexOf('android') > -1) {
            // 안드로이드: 크롬 브라우저로 강제 이동
            location.href = 'intent://' + currentUrl.replace(/https?:\/\//i, '') + '#Intent;scheme=https;package=com.android.chrome;end';
        } else {
            // 아이폰(iOS): 캐시(과거 기록)를 무시하고 최신 화면을 불러오도록 주소에 난수 추가
            if (currentUrl.indexOf('?') === -1) {
                window.location.replace(currentUrl + '?reload=' + new Date().getTime());
            }
        }
    }
    </script>
    """,
    height=0,
)
from google import genai
from PIL import Image
from datetime import datetime

# 1. 페이지 설정 (모바일 최적화를 위해 centered 레이아웃 권장)
# 1. 페이지 설정 및 보안 옵션 적용
st.set_page_config(
    page_title="NutriSort AI",
    page_icon="🥗",
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

# 4. 피그마 디자인 완벽 이식 및 광채 효과 CSS
st.markdown(f"""
<style>
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
    /* 우측 상단 메뉴 버튼 및 스트림릿 워터마크 숨기기 */
    #MainMenu {{visibility: hidden;}}
    footer {{visibility: hidden;}}
    header {{visibility: hidden;}}
</style>
""", unsafe_allow_html=True)

# 5. 메인 화면 - 식단 스캐너
if menu == t["scanner_menu"]:
    # 1️⃣ 전문적인 3행 타이틀 디자인 (반응형 폰트 및 여백 적용)
    title_parts = t["description"].split("|")
    st.markdown(f"""
        <div style="text-align: center; margin-top: 10px; margin-bottom: 6vh;">
            <div style="font-size: clamp(35px, 10vw, 50px); margin-bottom: 1vh;">{title_parts[0]}</div>
            <div style="font-size: clamp(20px, 6vw, 26px); font-weight: 800; color: #333333; line-height: 1.2;">{title_parts[1]}</div>
            <div style="font-size: clamp(14px, 4vw, 18px); font-weight: 500; color: #86cc85; margin-top: 1vh;">{title_parts[2]}</div>
        </div>
    """, unsafe_allow_html=True)
    
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
        img = Image.open(uploaded_file) # PIL을 떼고 Image로 바로 호출합니다.
        st.image(img, caption="📷 스캔된 식단", use_container_width=True)
        
        # 분석 버튼 (피그마 스타일)
        if st.button(t["analyze_btn"], use_container_width=True):
            with st.spinner("AI 분석 중..."):
                try:
                    # 에러 방지: 모델명을 'gemini-flash-latest'로 고정
                    prompt = f"Analyze food for glucose management. Format: FoodName|TrafficColor|Order. Lang: {lang}"
                    response = client.models.generate_content(
                        model="gemini-flash-latest", 
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
                            model="gemini-flash-latest", 
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











