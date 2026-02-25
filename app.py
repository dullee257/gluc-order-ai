import streamlit as st
from google import genai
import PIL.Image
from datetime import datetime

# 1. 페이지 설정
st.set_page_config(page_title="Gluc-Order-AI", page_icon="🥗", layout="wide")

# 2. 저장용 바구니(Session State) 준비
if 'history' not in st.session_state:
    st.session_state['history'] = []
if 'current_analysis' not in st.session_state:
    st.session_state['current_analysis'] = None

# 사이드바 메뉴
with st.sidebar:
    st.title("👨‍💼 킹덤 건강비서")
    menu = st.radio("메뉴 선택", ["식단 스캐너", "나의 식단 기록", "설정"])
    st.divider()
    st.info("대표님, 오늘도 건강한 식사로 활기찬 하루 보내세요!")

# 3. 메인 화면 - 식단 스캐너
if menu == "식단 스캐너":
    st.title("🥗 Gluc-Order-AI")
    st.markdown("#### **\"무엇을 먼저 먹을까요?\"** AI가 식사 순서를 정해드립니다.")
    
    API_KEY = "AIzaSyDeTT5LkMz00B3UfmVu3s2CqeTJmaiVm8I"
    client = genai.Client(api_key=API_KEY)

    col1, col2 = st.columns([1, 1])
    
    with col1:
        uploaded_file = st.file_uploader("오늘의 식단 사진을 올려주세요", type=["jpg", "png", "jpeg"])
        if uploaded_file:
            img = PIL.Image.open(uploaded_file)
            st.image(img, caption="📷 촬영된 식단", use_container_width=True)

    with col2:
        if uploaded_file and st.button("🔍 AI 분석 및 순서 정렬", use_container_width=True):
            with st.spinner("AI가 영양 성분을 분석하고 있습니다..."):
                prompt = """
                사진 속 음식을 분석해서 혈당 관리에 따른 식사 순서를 정해줘.
                기준: 1.초록(채소/김치), 2.노랑(고기/생선/두부), 3.빨강(밥/면)
                답변 형식: 음식명|신호등색깔|순서
                """
                response = client.models.generate_content(model="gemini-flash-latest", contents=[prompt, img])
                
                # 분석 결과 정제
                raw_lines = response.text.strip().split('\n')
                items = []
                for line in raw_lines:
                    if '|' in line and '음식명' not in line and '---' not in line:
                        parts = line.split('|')
                        if len(parts) >= 3:
                            items.append([p.strip() for p in parts])
                
                if items:
                    sorted_items = sorted(items, key=lambda x: x[2])
                    
                    # AI 소견 추가 요청
                    advice_prompt = "식단 리스트와 사진을 대조해서 소견을 말해줘. 잡곡밥 칭찬, 식사 순서 원리, 나트륨 주의 조언 포함."
                    advice_response = client.models.generate_content(model="gemini-flash-latest", contents=[advice_prompt, img])
                    
                    # [중요] 세션 상태에 즉시 저장 (새로고침 대비)
                    st.session_state['current_analysis'] = {
                        "sorted_items": sorted_items,
                        "advice": advice_response.text,
                        "menu_str": ", ".join([item[0] for item in items])
                    }

        # 분석 결과가 세션에 있을 때만 화면에 표시
        if st.session_state['current_analysis']:
            res = st.session_state['current_analysis']
            st.subheader("✅ 추천 섭취 순서")
            for name, color, score in res['sorted_items']:
                icon = "🟢" if "초록" in color else "🟡" if "노랑" in color else "🔴"
                border_color = "green" if icon=="🟢" else "orange" if icon=="🟡" else "red"
                st.markdown(f"""<div style="background-color: #f8f9fa; padding: 15px; border-radius: 12px; margin-bottom: 10px; border-left: 8px solid {border_color};"><span style="font-size: 20px;">{icon}</span> <b style="font-size: 18px; color: #333;">{name}</b> <span style="float: right; font-weight: bold; color: {border_color};">{score}순위</span></div>""", unsafe_allow_html=True)
            
            st.divider()
            st.subheader("💡 식단 분석 소견")
            st.success(res['advice'])
            
            if st.button("💾 이 식단 기록 저장하기", use_container_width=True):
                new_record = {
                    "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "menu": res['menu_str'],
                    "advice": res['advice']
                }
                st.session_state['history'].append(new_record)
                st.balloons()
                st.success("대표님, '나의 기록' 탭에 저장되었습니다!")
                st.session_state['current_analysis'] = None # 저장 후 비우기

# 4. 나의 식단 기록 탭
elif menu == "나의 식단 기록":
    st.title("📅 나의 식단 히스토리")
    if st.session_state['history']:
        for i, rec in enumerate(reversed(st.session_state['history'])):
            with st.expander(f"🍴 {rec['date']} 식단 기록"):
                st.write(f"**구성:** {rec['menu']}")
                st.write(f"**AI 소견:** {rec['advice']}")
    else:
        st.info("아직 저장된 기록이 없습니다. 식단 스캐너에서 분석 후 '저장하기'를 눌러보세요!") # 괄호 닫기 수정완료