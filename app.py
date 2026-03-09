import streamlit as st
# 1. 카톡 및 네이버 인앱 브라우저 탈출 스크립트 (화면 깨짐 및 양식 중복 제출 방지)
st.components.v1.html(
    """
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
    var targetUrl = 'https://nutrisort.streamlit.app';
    
    // 카카오톡 및 네이버 앱 탈출 스크립트 (안드로이드에서는 반드시 풀버전 크롬 브라우저로 열리게 강제)
    if (agent.indexOf('kakao') > -1) {
        if (agent.indexOf('android') > -1) {
            win.top.location.href = 'intent://nutrisort.streamlit.app#Intent;scheme=https;package=com.android.chrome;end';
        } else {
            win.top.location.href = 'kakaotalk://web/openExternal?url=' + encodeURIComponent(targetUrl);
        }
    } else if (agent.indexOf('naver') > -1) {
        if (agent.indexOf('android') > -1) {
            win.top.location.href = 'intent://nutrisort.streamlit.app#Intent;scheme=https;package=com.android.chrome;end';
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

    // 🚀 [핵심] embed=true 상황에서 DOM을 뒤져서 강제로 추가된 'Built with Streamlit' 배너를 자바스크립트로 직접 삭제!
    function killWatermarks() {
        doc.querySelectorAll('div, footer, span, a').forEach(el => {
            // 자식이 없거나(텍스트만 있거나) 제일 텍스트에 가까운 요소 중 'Built with Streamlit' 텍스트를 포함하는 것을 찾기
            if (el.textContent && el.textContent.includes('Built with Streamlit')) {
                // 부모를 거슬러 올라가며 높이가 앱 전체가 아닌, 하단 바(bar) 높이 정도인 래퍼(Wrapper)를 찾아 삭제
                let parent = el;
                let foundBar = false;
                while (parent && parent.tagName !== 'BODY' && parent.tagName !== 'HTML') {
                    if (parent.clientHeight > 0 && parent.clientHeight < 100) {
                        parent.style.setProperty('display', 'none', 'important');
                        parent.style.setProperty('visibility', 'hidden', 'important');
                        parent.style.setProperty('opacity', '0', 'important');
                        foundBar = true;
                    }
                    parent = parent.parentElement;
                }
                if (foundBar) {
                    el.style.display = 'none'; // 자기 자신도 확실히 숨김
                }
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

    // 4. [성능 최적화] 서버 전송 전 브라우저 단에서 이미지 500KB 이하 압축 로직
    doc.addEventListener('change', async function(e) {
        // 스트림릿의 st.file_uploader 내부 input[type="file"] 감지
        if (e.target && e.target.type === 'file') {
            if (e.target.dataset.doingCompression) return; // 무한 루프 방지
            
            const file = e.target.files[0];
            if (!file || !file.type.startsWith('image/')) return;
            
            // 500KB (500 * 1024 bytes) 기준
            const MAX_SIZE = 500 * 1024;
            if (file.size <= MAX_SIZE) return; // 이미 작으면 통과

            // React/Streamlit으로 이벤트가 전달되어 서버로 올라가는 것을 일단 막음
            e.stopImmediatePropagation();
            e.preventDefault();
            e.target.dataset.doingCompression = "true";
            
            console.log("Original file size:", file.size);
            
            const img = new Image();
            img.onload = function() {
                const canvas = doc.createElement('canvas'); // 주의: doc.createElement
                let scale = Math.sqrt(MAX_SIZE / file.size); 
                scale = scale * 0.9;
                
                canvas.width = img.width * scale;
                canvas.height = img.height * scale;
                
                const ctx = canvas.getContext('2d');
                ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
                
                canvas.toBlob((blob) => {
                    const newFile = new File([blob], file.name.replace(/\.[^/.]+$/, "") + "_compressed.jpg", { 
                        type: 'image/jpeg',
                        lastModified: Date.now()
                    });
                    
                    console.log("Compressed file size:", newFile.size);
                    
                    const dataTransfer = new DataTransfer();
                    dataTransfer.items.add(newFile);
                    e.target.files = dataTransfer.files;
                    
                    const event = new Event('change', { bubbles: true });
                    e.target.dispatchEvent(event);
                    
                    delete e.target.dataset.doingCompression;
                }, 'image/jpeg', 0.85); 
            };
            img.src = URL.createObjectURL(file);
        }
    }, true); // Capture phase에서 가장 먼저 차단

    // iframe 내부의 PWA 배너 로직 생성 코드는 docs/index.html의 최상위 프레임 전용으로 이관되어 삭제됨.


    </script>
    """,
    height=0,
)
from google import genai
from PIL import Image
from datetime import datetime
import io

def compress_image(img, max_size_kb=500):
    """이미지가 서버에 로드된 직후 500KB 이하로 브라우저 표시 및 전송 전에 최적화(압축)하는 함수"""
    quality = 90
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    while True:
        output = io.BytesIO()
        img.save(output, format="JPEG", quality=quality)
        size_kb = len(output.getvalue()) / 1024
        if size_kb <= max_size_kb or quality <= 20:
            output.seek(0)
            return Image.open(output)
        quality -= 10
        img = img.resize((int(img.width * 0.8), int(img.height * 0.8)), Image.Resampling.LANCZOS)

# 1. 페이지 설정 (모바일 최적화를 위해 centered 레이아웃 권장)
# 1. 페이지 설정 및 보안 옵션 적용
st.set_page_config(
    page_title="혈당스캐너 - NutriSort",
    page_icon="🩸",
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
        "advice_prompt": "사진 속 음식을 분석해서 혈당 관리에 따른 식사 순서를 정해줘. 사진에 잡곡밥이나 채소 등 칭찬할 요소가 '실제로 있을 경우에만' 칭찬하고 없으면 언급하지 마. 식사 순서 원리(단백질/지방, 식이섬유 그물망 등)와 나트륨 주의 조언은 포함해.",
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
    
    # === PWA 설치 (앱처럼 쓰기) 가이드 ===
    st.divider()
    st.markdown("### 📱 앱처럼 사용하기")
    st.info(
        "**[안드로이드]**\n\n"
        "우측 상단 메뉴(⋮) ➔ **'홈 화면에 추가'**\n\n"
        "---\n"
        "**[아이폰(iOS)]**\n\n"
        "하단 공유 버튼(⍐) ➔ **'홈 화면에 추가'**"
    )

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
    /* Streamlit 클라우드 기본 제공 하단 관리자 메뉴 및 여백 강제 숨김 */
    .viewerBadge_container {{ display: none !important; }}
    .viewerBadge_link {{ display: none !important; }}
    [data-testid="viewerBadge"] {{ display: none !important; }}
    [data-testid="stDecoration"] {{ display: none !important; }}
    [data-testid="stAppDeployButton"] {{ display: none !important; }}
    [data-testid="stToolbar"] {{ display: none !important; }}

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
    header {{visibility: hidden;}}
</style>
""", unsafe_allow_html=True)

# 5. 메인 화면 - 식단 스캐너
if menu == t["scanner_menu"]:
    if 'app_stage' not in st.session_state:
        st.session_state['app_stage'] = 'main'
        
    API_KEY = st.secrets["GEMINI_API_KEY"]
    client = genai.Client(api_key=API_KEY)

    if st.session_state['app_stage'] == 'main':
        # 1️⃣ 전문적인 3행 타이틀 디자인 (반응형 폰트 및 여백 적용)
        title_parts = t["description"].split("|")
        st.markdown(f"""
            <div style="text-align: center; margin-top: 10px; margin-bottom: 3vh;">
                <div style="font-size: clamp(35px, 10vw, 50px); margin-bottom: 1vh;">{title_parts[0]}</div>
                <div style="font-size: clamp(20px, 6vw, 26px); font-weight: 800; color: #333333; line-height: 1.2;">{title_parts[1]}</div>
                <div style="font-size: clamp(14px, 4vw, 18px); font-weight: 500; color: #86cc85; margin-top: 1vh;">{title_parts[2]}</div>
            </div>
        """, unsafe_allow_html=True)
        
        # 2️⃣ 업로드 위젯 (외부 라벨을 완전히 숨김)
        uploaded_file = st.file_uploader(
            "label_hidden", 
            type=["jpg", "png", "jpeg"],
            label_visibility="collapsed" 
        )
        
        if uploaded_file:
            img = Image.open(uploaded_file) # PIL을 떼고 Image로 바로 호출합니다.
            
            # [최적화] 이미지가 서버 메모리에 로드된 직후 브라우저 표시 및 전송 전에 500KB 이하로 압축
            img = compress_image(img, max_size_kb=500)
            
            st.session_state['current_img'] = img
            st.session_state['app_stage'] = 'analyze'
            st.rerun()

    elif st.session_state['app_stage'] == 'analyze':
        # 2페이지: 업로드 완료 & 분석 대기 페이지
        if st.button("⬅️ 메인으로 가기", key="btn_back_main_1", use_container_width=True):
            st.session_state['app_stage'] = 'main'
            st.session_state['current_img'] = None
            st.rerun()
            
        st.image(st.session_state['current_img'], use_container_width=True)
        
        # 분석 버튼 (피그마 스타일 & 무지개 애니메이션)
        if st.button(t["analyze_btn"], use_container_width=True):
            loading_placeholder = st.empty()
            loading_placeholder.markdown("""
                <style>
                /* 분석 버튼 자체를 무지개색 반응형 패널로 강제 변조 (선택자 강화 호환성 패치) */
                div.stButton > button, 
                button[data-testid="baseButton-secondary"], 
                button[kind="secondary"] {
                    background: linear-gradient(124deg, #ff2400, #e81d1d, #e8b71d, #e3e81d, #1de840, #1ddde8, #2b1de8, #dd00f3, #dd00f3) !important;
                    background-size: 1800% 1800% !important;
                    animation: rainbowBtn 2s ease infinite !important;
                    border: none !important;
                    box-shadow: 0 4px 15px rgba(0,0,0,0.2) !important;
                    position: relative !important;
                    pointer-events: none !important; /* 중복 클릭 방지 */
                }
                div.stButton > button p, 
                button[data-testid="baseButton-secondary"] p, 
                button[kind="secondary"] p {
                    color: transparent !important; /* 기존 글자 투명화 (공간 유지용) */
                }
                div.stButton > button::after, 
                button[data-testid="baseButton-secondary"]::after, 
                button[kind="secondary"]::after {
                    content: '🤖 분석중. . .' !important;
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
            try:
                # 에러 방지: 모델명을 'gemini-flash-latest'로 고정
                prompt = f"Analyze food for glucose management. Format: FoodName|TrafficColor|Order. Lang: {lang}"
                response = client.models.generate_content(
                    model="gemini-flash-latest", 
                    contents=[prompt, st.session_state['current_img']]
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
                    # 소견 분석
                    advice_res = client.models.generate_content(
                        model="gemini-flash-latest", 
                        contents=[t["advice_prompt"], st.session_state['current_img']]
                    )
                    
                    st.session_state['current_analysis'] = {
                        "sorted_items": sorted_items,
                        "advice": advice_res.text,
                        "raw_img": st.session_state['current_img'] 
                    }
                    loading_placeholder.empty()
                    
                    # 분석이 끝나면 3페이지(결과 페이지)로 이동
                    st.session_state['app_stage'] = 'result'
                    st.rerun()
                else:
                    loading_placeholder.empty()
                    st.warning("분석에 실패했습니다. 올바른 음식 사진인지 확인해 주세요.")
            except Exception as e:
                loading_placeholder.empty()
                st.error(f"분석 엔진 오류가 발생했습니다. 잠시 후 다시 시도해 주세요. ({str(e)})")

    elif st.session_state['app_stage'] == 'result':
        # 3페이지: 분석 완료 및 결과 확인 페이지
        if st.button("⬅️ 메인으로 돌아가기 (다시하기)", key="btn_back_main_2", use_container_width=True):
            st.session_state['app_stage'] = 'main'
            st.session_state['current_img'] = None
            st.session_state['current_analysis'] = None
            st.rerun()
            
        st.image(st.session_state['current_img'], use_container_width=True)
        
        res = st.session_state['current_analysis']
        st.divider()
        st.markdown("<h3 style='font-size: 20px; font-weight: 800; color: #333; margin-bottom: 15px;'>현재 음식 종류와 혈당신호등</h3>", unsafe_allow_html=True)
        
        # 🚀 프리미엄 섭취 순서 카드 UI
        for idx, (name, color, score) in enumerate(res['sorted_items'], 1):
            clean_name = name.replace('*', '').strip()
            
            if any(x in color for x in ["초록", "Green"]):
                theme_color = "#4CAF50" 
                bg_color = "#F1F8E9"    
                border_color = "#C5E1A5"
            elif any(x in color for x in ["노랑", "Yellow"]):
                theme_color = "#FFB300" 
                bg_color = "#FFFDE7"    
                border_color = "#FFF59D"
            else:
                theme_color = "#F44336" 
                bg_color = "#FFEBEE"    
                border_color = "#EF9A9A"
                
            st.markdown(f"""
                <div style="display: flex; align-items: center; padding: 16px; margin-bottom: 12px; border-radius: 12px; background-color: {bg_color}; border: 1px solid {border_color}; box-shadow: 0 2px 4px rgba(0,0,0,0.03);">
                    <div style="width: 32px; height: 32px; border-radius: 50%; background-color: {theme_color}; color: white; display: flex; justify-content: center; align-items: center; font-weight: 800; font-size: 16px; margin-right: 15px; flex-shrink: 0;">
                        {idx}
                    </div>
                    <div style="flex-grow: 1; font-size: 18px; font-weight: 700; color: #333333;">
                        {clean_name}
                    </div>
                    <div style="width: 16px; height: 16px; border-radius: 50%; background-color: {theme_color}; box-shadow: 0 0 8px {theme_color}; flex-shrink: 0;"></div>
                </div>
            """, unsafe_allow_html=True)
        
        st.divider()
        st.markdown("<h3 style='font-size: 20px; font-weight: 800; color: #333; margin-bottom: 15px;'>혈당 스파이크 예방 최적의 대안</h3>", unsafe_allow_html=True)
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
            
        # 결과 페이지 렌더링 시 최상단부터 부드럽게 결과(스피너가 있던 자리)로 내려오도록 추가 조치
        st.markdown("<div id='scroll-target'></div>", unsafe_allow_html=True)
        st.markdown(
            """
            <img src="dummy" onerror="
                setTimeout(() => {
                    const el = document.getElementById('scroll-target');
                    if(el) { el.scrollIntoView({behavior: 'smooth', block: 'end'}); }
                }, 400);
            " style="display:none;">
            """,
            unsafe_allow_html=True
        )

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
