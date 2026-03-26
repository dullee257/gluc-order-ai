# -*- coding: utf-8 -*-
"""
NutriSort AI - 제미나이(Gemini) 분석용 프롬프트.
st.session_state.lang 또는 전달된 lang에 따라 해당 언어로 분석 결과를 작성하도록 프롬프트 생성.
"""
# KO: 한국어로 친절하게, EN: 영어로 전문적으로, ZH/JA/HI: 해당 언어로 (임시 지시문 포함, 검토 필요)

def get_food_analysis_prompt_json(lang):
    """비전 분석용: 단일 JSON 객체만 반환하도록 지시 (파싱·total_carbs 연동용)."""
    _json_rules = """
반드시 JSON 객체 하나만 출력하세요. 앞뒤 설명, 마크다운, 코드펜스(```) 사용 금지.
스키마:
{
  "total_carbs": <정수, 모든 항목 carbs 합과 동일>,
  "items": [
    {
      "name": "음식 이름 문자열",
      "gi": <0~100 정수>,
      "carbs": <탄수화물 g 정수>,
      "protein": <단백질 g 정수>,
      "fat": <지방 g 정수>,
      "kcal": <칼로리 정수>,
      "signal": "초록" | "노랑" | "빨강" (또는 영문 신호),
      "order": <섭취 순서, 1부터 정수>
    }
  ]
}
규칙: 사진에 보이는 음식만 포함. 숫자 필드는 모두 정수. total_carbs는 items의 carbs 합과 일치."""
    if lang == "KO":
        return (
            "사진 속 음식들을 혈당 관리 관점에서 분석해줘.\n"
            + _json_rules
            + "\n한글 음식명 사용. signal은 가능하면 초록/노랑/빨강 중 하나."
        )
    if lang == "EN":
        return """Analyze foods in the photo for blood sugar management.
""" + _json_rules + """
Use English food names. signal: Green, Yellow, or Red."""
    if lang == "ZH":
        return """Analyze foods in the photo for blood sugar management.
""" + _json_rules + """
Use Chinese food names where natural. signal: Green/Yellow/Red or 绿/黄/红 as strings."""
    if lang == "JA":
        return """Analyze foods in the photo for blood sugar management.
""" + _json_rules + """
Use Japanese food names. signal: Green/Yellow/Red."""
    if lang == "HI":
        return """Analyze foods in the photo for blood sugar management.
""" + _json_rules + """
Use Hindi or English food names. signal: Green/Yellow/Red."""
    return (
        "Analyze foods in the photo for blood sugar management.\n"
        + _json_rules
        + "\nSignal: Green/Yellow/Red."
    )


def get_advice_prompt(lang):
    """AI 소견(4단계 조언)용 프롬프트. 선택된 언어로 답변하도록 지시."""
    # 한국어: 친절한 한글, 맞춤법·띄어쓰기 지시
    ko = """모든 답변은 맞춤법에 맞는 자연스러운 한글로 작성해 주세요. 오타와 잘못된 띄어쓰기를 사용하지 마세요.

사진 속 음식을 분석하여 혈당 관리를 위한 조언을 다음 4단계 카테고리로 나누어 반드시 순서대로 작성해 주세요. 각 카테고리 앞에 번호와 제목을 적어 주세요.

중요: 어떤 문장에서도 '~을(를) 막을 수 있습니다', '~을(를) 예방합니다'처럼 단정적인 의학적 효능 표현을 쓰지 마세요.
'~을(를) 줄이는 데 도움이 됩니다', '~을(를) 완화하는 데 도움이 될 수 있습니다'와 같이 조심스러운 표현만 사용하세요.

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

Analyze the food in the photo and give blood-sugar management advice in exactly 4 sections, in order, with numbered headings.

Important: Never claim that something \"prevents\" or \"completely stops\" blood sugar spikes. Instead, use softer language such as \"may help reduce\" or \"can help smooth blood sugar response\".

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
    (음식 JSON 분석 프롬프트, 소견 프롬프트) 튜플 반환.
    제미나이 호출 시 st.session_state.lang 또는 인자 lang 사용.
    """
    return (get_food_analysis_prompt_json(lang), get_advice_prompt(lang))


# 식전 인사이트: Gemini systemInstruction — 1타 헬스 코치 페르소나·JSON 스키마·필드 규칙
PRE_MEAL_INSIGHTS_SYSTEM_PROMPT = """너는 지루한 영양사가 아니라, 사용자의 도파민을 자극하고 혈당 방어를 돕는 1타 헬스 코치다.
공포 마케팅·비난·죄책감 유발은 금지. 응답은 반드시 JSON 객체 하나만 (설명·마크다운·코드펜스 금지).

스키마:
{
  "mission": "<문자열>",
  "analysis": "<문자열>",
  "next_meal": "<문자열>",
  "added_stress": <정수, 0 이상 30 이하>
}

필드별 지시:

1) "mission" (식전 퀘스트)
- [외식/배달]이면: 그 식당에 있을 법한 채소·단백질 밑반찬·전채를 구체적으로 집어, 메인 전에 먼저 먹으라고 활기차게 지시한다.
- [집밥]이면: 냉장고에 있는 간단한 재료나 실천 가능한 팁(예: "식사 5분 전 사과식초 한 스푼을 물에 타 먹기", "밥을 전자레인지로 데워 저항성 전분 만들기")을 RPG 퀘스트처럼 짧고 신나게 준다.

2) "analysis" (메인 메뉴 분석 — GL·칭찬 결합)
- 절대 혼내지 마라. 사용자가 1번 mission을 완료했다고 가정하고 "방어막 구축 완료!" 느낌으로 안심시켜라.
- 그 전제 위에서 **혈당부하(GL) 지수**와 **양 조절**을 위트 있게 짚어라. (예: 식초물 방어막은 좋지만 짜장면은 GL 폭탄이니 면은 두 젓가락만 남기고, 액상과당이 숨은 소스는 덜어내라 등)
- 의학적 단정·치료 효과 주장은 피하고 '도움이 될 수 있다' 수준으로 쓴다.

3) "next_meal" (동적 다음 끼니 추천)
- 방금 메뉴가 고탄수화물·고GL 쪽이면: 다음 끼니는 인슐린이 쉴 수 있도록 식이섬유·단백질 위주(예: 닭가슴살 샐러드, 두부구이, 나물·국물 맑은 찌개)로 구체적으로 추천한다.
- 방금 잘 방어한 편이면: 보상 톤으로 다음엔 건강한 복합 탄수화물(현미, 고구마, 통곡물 등)을 곁들여도 좋다고 말한다.
- 사용자가 알려준 현재 끼니(아침/점심/저녁/간식) 맥락을 한두 문장에 자연스럽게 녹인다.

4) "added_stress" (혈당 피로도 가산점)
- 메인 요리의 **예상 GL 부담**만 반영해 0~30 정수로 매긴다. mission 성공 여부와 무관하다.
- 액상과당, 흰쌀, 떡, 면류·튀김면 등은 상대적으로 높게 책정한다.

JSON 이스케이프를 지키고, 문자열 안 따옴표는 이스케이프하거나 문장을 짧게 줄여라."""


def get_pre_meal_insights_user_prompt(menu: str, location: str, meal_slot: str, current_stress: float) -> str:
    """식전 인사이트 — 사용자 입력만 전달 (시스템 프롬프트와 분리)."""
    loc_raw = (location or "").strip()
    loc_label = "외식/배달" if loc_raw in ("외식", "외식/배달") else "집밥"
    return f"""아래 입력을 반영해 위 시스템 지시대로 JSON만 출력하라.

- 메뉴(텍스트): {menu!r}
- 장소: {loc_label}
- 현재 끼니: {meal_slot!r}
- 현재까지 누적 혈당 피로도(참고): {current_stress}"""
