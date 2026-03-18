# -*- coding: utf-8 -*-
"""
NutriSort AI - 제미나이(Gemini) 분석용 프롬프트.
st.session_state.lang 또는 전달된 lang에 따라 해당 언어로 분석 결과를 작성하도록 프롬프트 생성.
"""
# KO: 한국어로 친절하게, EN: 영어로 전문적으로, ZH/JA/HI: 해당 언어로 (임시 지시문 포함, 검토 필요)

def get_food_analysis_prompt(lang):
    """음식 목록 구조화용 프롬프트. 반환 형식은 언어별로 출력 지시만 다름.
    요구 포맷(정확히 1줄=1항목, 데이터만):
    음식이름|GI|탄수화물g|단백질g|지방g|칼로리kcal|혈당신호|섭취순서
    """
    if lang == "KO":
        return """사진 속 음식들을 혈당 관리 관점에서 분석해줘.
각 음식을 아래 형식으로 정확히 반환해 (헤더 없이 데이터만, 한 줄에 하나):
음식이름|GI|탄수화물g|단백질g|지방g|칼로리kcal|혈당신호|섭취순서

규칙:
- GI수치: 0~100 정수 (혈당지수)
- 탄수화물g/단백질g/지방g: 해당 음식 예상 섭취량 기준 정수
- 칼로리kcal: 정수
- 혈당신호: 초록/노랑/빨강 중 하나
- 섭취순서: 1부터 시작

예시:
나물반찬|22|8|3|1|55|초록|1
잡곡밥|55|45|5|2|260|노랑|2
닭가슴살|30|0|25|3|150|초록|3"""
    if lang == "EN":
        return """Analyze foods in the photo for blood sugar management.
Return each food in this exact format (data only, one line each):
FoodName|GI|Carbs_g|Protein_g|Fat_g|Kcal|Signal|EatingOrder
- GI: integer 0-100
- Carbs_g, Protein_g, Fat_g: estimated grams (integer)
- Kcal: integer calories
- Signal: Green/Yellow/Red
- EatingOrder: integer from 1"""
    if lang == "ZH":
        # 中文：输出格式同EN，便于解析；说明用中文
        return """Analyze foods in the photo for blood sugar management.
Return each food in this exact format (data only, one line each):
FoodName|GI|Carbs_g|Protein_g|Fat_g|Kcal|Signal|EatingOrder
- GI: 0-100 integer. Carbs/Protein/Fat (g) integers, Kcal integer. Signal: Green/Yellow/Red. EatingOrder: from 1.
Use same format as above."""
    if lang == "JA":
        return """Analyze foods in the photo for blood sugar management.
Return each food in this exact format (data only, one line each):
FoodName|GI|Carbs_g|Protein_g|Fat_g|Kcal|Signal|EatingOrder
- GI: 0-100 integer. Signal: Green/Yellow/Red. EatingOrder: from 1."""
    if lang == "HI":
        return """Analyze foods in the photo for blood sugar management.
Return each food in this exact format (data only, one line each):
FoodName|GI|Carbs_g|Protein_g|Fat_g|Kcal|Signal|EatingOrder
- GI: 0-100 integer. Signal: Green/Yellow/Red. EatingOrder: from 1."""
    # fallback
    return """Analyze foods in the photo for blood sugar management.
Return each food: FoodName|GI|Carbs_g|Protein_g|Fat_g|Kcal|Signal|EatingOrder (one per line, data only)."""


def get_advice_prompt(lang):
    """AI 소견(4단계 조언)용 프롬프트. 선택된 언어로 답변하도록 지시."""
    # 한국어: 친절한 한글, 맞춤법·띄어쓰기 지시
    ko = """모든 답변은 맞춤법에 맞는 자연스러운 한글로 작성해 주세요. 오타와 잘못된 띄어쓰기를 사용하지 마세요.

사진 속 음식을 분석하여 혈당 관리를 위한 조언을 다음 4단계 카테고리로 나누어 반드시 순서대로 작성해 주세요. 각 카테고리 앞에 번호와 제목을 적어 주세요.

1. 사진 속 메뉴 확인
- '사진 속 메뉴를 보니...'로 시작하여 사진의 음식에 대한 간략한 기본 분석을 진행해 주세요.
- 실제로 사진에 잡곡밥, 채소 등 칭찬할 요소가 있을 때만 칭찬하고, 없으면 지어내지 마세요.

2. 장소 유추 및 실전 메뉴 꿀팁
- 음식(배경·로고 등)을 기반으로 식사 장소를 유추해 주세요.
- [중요] 유추한 장소가 카페나 디저트 전문점처럼 채소·단백질 메뉴가 메인이 아닌 곳이라면, 굳이 채소 샐러드나 샌드위치를 억지로 추가 주문하라고 제안하지 마세요. 해당 장소에 적합한 가벼운 팁(예: 시럽 빼기, 우유 대신 오트밀크 변경 등)만 주세요.
- 밥집·고깃집 등 추가 반찬 주문이 자연스러운 곳에서만 보완 음식을 적극 제안해 주세요.

3. 권장 식사 순서
- 2번 단계에서 실제로 추가를 제안한 음식이 있을 경우에만, 원래 상차림과 합쳐서 섭취 순서를 안내해 주세요.
- 억지로 채소나 단백질을 먹으라는 문구를 쓰지 말고, 오직 지금 사진에 찍힌 음식(과 자연스러운 추가 메뉴)에 한해서만, 어떻게 순서대로 먹는 것이 혈당 관리에 좋은지 설명해 주세요. (커피만 있으면 커피 마시는 방법만 설명하세요.)

4. 그밖에 부가 설명
- 음식의 나트륨, 조리법 주의사항, 식후 10분 걷기 등 추가적인 혈당 조언을 자연스럽게 덧붙여 주세요."""

    # 영어: 전문적·간결한 영어
    en = """Write your entire response in clear, professional English.

Analyze the food in the photo and give blood-sugar management advice in exactly 4 sections, in order, with numbered headings:

1. Menu in the photo
- Start with "In this photo..." and briefly describe the foods.
- Only praise elements that are actually present (e.g. whole grains, vegetables); do not invent.

2. Venue and practical tips
- Infer where the meal might be from (background, logos, etc.).
- Do not suggest adding salads or sandwiches if the venue is clearly a café or dessert place; only give tips that fit (e.g. skip syrup, use oat milk).
- Suggest extra sides only where it is natural (e.g. at a rice or meat restaurant).

3. Recommended eating order
- Combine the current plate (and any suggested additions from section 2) and explain the order to eat for better blood sugar. Do not push "eat vegetables first" if the photo does not support it (e.g. if only coffee, explain only the coffee).

4. Additional notes
- Add brief notes on sodium, cooking, or post-meal walking if relevant."""

    # 중국어 (간체) — 임시 지시, 검토 필요
    zh = """请全部用简体中文、专业且易懂地作答。

根据照片中的食物，按以下4个部分依次写出血糖管理建议，每部分前加序号和标题：

1. 照片中的菜单：简要描述食物，只表扬实际存在的优点。
2. 场所推断与实用建议：根据背景等推断用餐场所，只给符合该场所的轻量建议，不强行建议加沙拉等。
3. 推荐进食顺序：仅就照片中的食物（及你在第2步中自然建议的补充）说明进食顺序。
4. 其他说明：钠、烹调注意、餐后步行等可简要补充。"""

    # 日本語 — 仮、要検討
    ja = """回答はすべて日本語で、親しみやすく専門的に書いてください。

写真の食事を分析し、血糖管理のアドバイスを次の4項目で順に書いてください。各項目に番号と見出しをつけてください。

1. 写真のメニュー確認：「写真のメニューを見ると…」で始め、食事の概要を簡潔に。褒める場合は実際に写っている要素だけにしてください。
2. 場所の推測と実践的なヒント：背景・ロゴなどから場所を推測し、その場所に合った軽いアドバイスのみ（カフェやデザート店では無理にサラダを勧めない）。
3. 推奨する食べる順序：写真の料理（と自然な追加メニュー）に限り、順番に食べる方法を説明してください。
4. その他：塩分、調理の注意、食後10分歩行なども自然に補足してください。"""

    # हिन्दी — draft, review needed
    hi = """Write your entire response in Hindi, in a clear and helpful tone.

Analyze the food in the photo and give blood sugar management advice in exactly 4 sections, in order, with numbered headings:

1. Photo mein menu: Briefly describe the foods. Only praise what is actually in the photo.
2. Venue aur tips: Infer where the meal might be from. Give only tips that fit that place (e.g. do not suggest salad at a dessert shop).
3. Khane ka recommended order: Explain the order to eat for better blood sugar, only for the foods in the photo (and any natural additions you suggested).
4. Extra notes: Sodium, cooking, or walking tips if relevant."""

    m = {"KO": ko, "EN": en, "ZH": zh, "JA": ja, "HI": hi}
    return m.get(lang, en)


def get_analysis_prompt(lang):
    """
    (음식 목록 프롬프트, 소견 프롬프트) 튜플 반환.
    제미나이 호출 시 st.session_state.lang 또는 인자 lang 사용.
    """
    return (get_food_analysis_prompt(lang), get_advice_prompt(lang))
