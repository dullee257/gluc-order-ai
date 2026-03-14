# 번역 분리 및 다국어 적용 — 코드 수정 사항 보고

Railway 등 서버 업로드 시 참고용으로, **추가·수정된 파일**과 **요약**을 정리했습니다.

---

## 1. 추가된 파일

| 파일 | 설명 |
|------|------|
| **`translation.py`** | 다국어 UI 텍스트 딕셔너리. `LANG_DICT` (KO, EN, ZH, JA, HI), `SUPPORTED_LANGS`, `LANG_LABELS`, `LANG_HTML_ATTR`, `get_text()`, `GOAL_INTERNAL_KEYS` |
| **`prompts.py`** | 제미나이(Gemini) 분석용 프롬프트. `get_analysis_prompt(lang)` → `(음식 목록 프롬프트, 소견 프롬프트)` 반환. 언어별 출력 지시 포함 |
| **`docs/CODE_CHANGES_TRANSLATION.md`** | 본 보고서 |

---

## 2. 수정된 파일

| 파일 | 주요 변경 |
|------|------------|
| **`app.py`** | • `translation`, `prompts` import 및 기존 인라인 `messages_ko`/`messages_en` 제거<br>• `t = LANG_DICT[lang]` 로 현재 언어 번역 사용<br>• 상단 언어 선택: `SUPPORTED_LANGS`, `LANG_LABELS` 사용, 선택 시 `st.session_state["lang"]` 갱신 후 `st.rerun()`<br>• HTML `lang` 속성: `LANG_HTML_ATTR`로 `<script>document.documentElement.lang="…";</script>` 주입 (브라우저 자동번역 방지)<br>• 목표 선택: `GOAL_INTERNAL_KEYS` + `t["goal_display"]` 기반으로 동일 로직 유지<br>• 로그인/체험/스캐너/결과 화면 문구 전부 `t["키"]` 또는 `get_text(lang, "키", …)` 로 치환<br>• 제미나이 호출: `get_analysis_prompt(st.session_state["lang"])` 로 음식 분석·소견 프롬프트 동적 사용 |

---

## 3. Railway 배포 시 확인 사항

- **의존성**: `requirements.txt`에 새 패키지는 없음. `translation.py`, `prompts.py`는 프로젝트 루트에 두면 `import translation`, `import prompts` 로 로드됨.
- **진입점**: 그대로 `app.py` (또는 기존 Procfile/진입점) 사용.
- **환경 변수 / 시크릿**: 기존과 동일 (GEMINI_API_KEY, Firebase 등). 번역/프롬프트는 코드 내부 처리.

---

## 4. 언어 추가 방법 (향후)

1. **`translation.py`**
   - `_xx()` 함수 추가 (예: `_de()` 독일어).
   - `LANG_DICT["DE"] = _de()` 등록.
   - `SUPPORTED_LANGS`에 `"DE"` 추가.
   - `LANG_LABELS["DE"] = "Deutsch"`, `LANG_HTML_ATTR["DE"] = "de"` 추가.
2. **`prompts.py`**
   - `get_food_analysis_prompt()`, `get_advice_prompt()` 에 `lang == "DE"` 분기 추가.
3. **`app.py**  
   - 수정 없이 `SUPPORTED_LANGS`/`LANG_DICT` 확장만으로 동작.

---

## 5. EN/ZH/JA/HI 번역 상태

- **EN**: 기존 문구 반영 + 전문적 톤으로 정리.
- **ZH, JA, HI**: 직역/임시 번역으로 채움. `translation.py`·`prompts.py` 내 주석에 “검토 필요” 표기. 필요 시 현지어로 교정 후 교체하면 됨.
