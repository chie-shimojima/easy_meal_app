import html
import os
from datetime import date

import streamlit as st
from dotenv import load_dotenv
from openai import OpenAI

from pdf_export import (
    MealBlock,
    NutritionInfo,
    ParsedWeeklyPlan,
    create_weekly_plan_pdf,
    parse_nutrition_line,
    parse_weekly_plan_markdown,
    strip_markdown_inline,
)

load_dotenv()

CONDITION_OPTIONS = [
    "減塩",
    "低脂質",
    "高たんぱく",
    "低たんぱく",
    "糖質制限",
    "妊婦向け",
    "離乳食",
    "時短",
    "普通",
]
CALORIE_PRESETS = [1200, 1500, 1800, 2000, 2200]
EASY_MODE_OPTIONS = {
    "no_knife": "包丁なし",
    "under_5min": "5分以内",
    "convenience_ok": "コンビニOK",
}
DEFAULT_MODEL = "gpt-4o-mini"

MEAL_ICONS = {"朝食": "🌅", "昼食": "☀️", "夕食": "🌙"}
DETAIL_META: dict[str, tuple[str, str]] = {
    "材料": ("🧺", "detail-ingredient"),
    "調味料": ("🧂", "detail-seasoning"),
    "作り方": ("📝", "detail-recipe"),
    "手順": ("📝", "detail-recipe"),
    "調理時間": ("⏱️", "detail-time"),
    "使う冷蔵庫": ("🥬", "detail-fridge"),
    "買い足す": ("🛒", "detail-shopping"),
}

APP_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@400;500;600;700&display=swap');

html, body, [class*="css"] {
  font-family: "Noto Sans JP", "Hiragino Sans", sans-serif;
}

.stApp {
  background: linear-gradient(160deg, #f4faf6 0%, #edf7f0 45%, #fffaf3 100%);
  color: #2b3d30;
}

.block-container {
  max-width: 1320px;
  padding-top: 1.1rem;
  padding-bottom: 2.2rem;
}

h1, h2, h3 {
  color: #2f4d3d !important;
  font-weight: 700 !important;
}

.ui-card {
  background: rgba(255, 255, 255, 0.95);
  border: 1px solid #d9ebe0;
  border-radius: 18px;
  box-shadow: 0 8px 22px rgba(63, 105, 82, 0.08);
  padding: 0.95rem 1rem;
  margin-bottom: 0.9rem;
}

.left-title {
  margin: 0.15rem 0 0.45rem;
  font-size: 1.02rem;
  color: #2c5f46;
  font-weight: 700;
}

.helper-text {
  margin: 0;
  color: #5a7061;
  line-height: 1.65;
  font-size: 0.9rem;
}

.status-ok {
  background: #e8f6ec;
  border: 1px solid #bce1c8;
  border-radius: 12px;
  padding: 0.65rem 0.8rem;
  color: #2d6f45;
  font-size: 0.88rem;
  font-weight: 600;
}

.status-ng {
  background: #fff4f4;
  border: 1px solid #f1cfd1;
  border-radius: 12px;
  padding: 0.65rem 0.8rem;
  color: #8d4a4a;
  font-size: 0.88rem;
  font-weight: 600;
}

.hero-head {
  margin-top: 0;
  margin-bottom: 0.35rem;
  color: #264c39;
}

.hero-caption {
  margin: 0;
  color: #50675a;
  line-height: 1.7;
  font-size: 0.95rem;
}

.meal-card {
  background: #ffffff;
  border: 1px solid #e1efe6;
  border-radius: 16px;
  margin: 0.85rem 0;
  overflow: hidden;
}

.meal-card-body {
  background: #f9fcfa;
  padding: 0.85rem 0.95rem 0.9rem;
}

.meal-card-header {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  flex-wrap: wrap;
  margin-bottom: 0.65rem;
}

.meal-type-badge {
  display: inline-block;
  font-size: 0.78rem;
  font-weight: 700;
  color: #2f6849;
  background: #e8f6ec;
  border: 1px solid #cee5d7;
  border-radius: 999px;
  padding: 0.16rem 0.55rem;
}

.meal-menu-name {
  margin: 0;
  color: #2f483a;
  font-size: 1rem;
  font-weight: 700;
}

.nutrition-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.42rem;
  margin: 0.6rem 0 0.75rem;
}

.nutrition-box {
  flex: 1 1 84px;
  min-width: 82px;
  background: #fff;
  border: 1px solid #d5e7db;
  border-radius: 10px;
  text-align: center;
  padding: 0.35rem 0.25rem;
}

.nutrition-label {
  display: block;
  color: #678070;
  font-size: 0.65rem;
  margin-bottom: 0.1rem;
}

.nutrition-value {
  display: block;
  color: #2c4738;
  font-size: 0.8rem;
  font-weight: 700;
}

.detail-block {
  background: #fff;
  border-radius: 11px;
  padding: 0.6rem 0.72rem;
  margin: 0.48rem 0;
  border-left: 3px solid #b6d7c2;
}
.detail-ingredient { border-left-color: #98c6a7; }
.detail-seasoning { border-left-color: #d8c88f; }
.detail-recipe { border-left-color: #90be9e; }
.detail-time { border-left-color: #9fc2db; }
.detail-fridge { border-left-color: #9acba4; }
.detail-shopping { border-left-color: #d4c5af; }

.detail-label {
  margin: 0 0 0.2rem;
  color: #3f5f4d;
  font-size: 0.81rem;
  font-weight: 700;
}

.detail-body {
  color: #425a4b;
  font-size: 0.9rem;
  line-height: 1.62;
  white-space: pre-wrap;
  word-break: break-word;
}

.day-card {
  background: rgba(255, 255, 255, 0.96);
  border: 1px solid #d4e7da;
  border-radius: 18px;
  padding: 1rem;
  margin-bottom: 1rem;
  box-shadow: 0 7px 20px rgba(58, 100, 76, 0.08);
}

.day-card-title {
  margin: 0 0 0.65rem;
  font-size: 1.2rem;
  color: #2f5b43;
  border-bottom: 2px solid #e5f1e8;
  padding-bottom: 0.45rem;
}

.day-summary-box {
  margin-top: 0.45rem;
  border-radius: 11px;
  background: #f1f8f3;
  color: #425a4c;
  padding: 0.6rem 0.75rem;
  font-size: 0.9rem;
  line-height: 1.56;
}

.nutritionist-comment-box {
  margin-top: 0.7rem;
  border-radius: 12px;
  background: linear-gradient(140deg, #fffcea, #f3fae7);
  border: 1px solid #e3e8bb;
  padding: 0.72rem 0.82rem;
}

.nutritionist-comment-title {
  margin: 0 0 0.28rem;
  color: #796e39;
  font-size: 0.79rem;
  font-weight: 700;
}

.nutritionist-comment-body {
  margin: 0;
  color: #4e5742;
  line-height: 1.66;
  font-size: 0.9rem;
}

.shopping-card {
  background: #fff;
  border: 1px dashed #b9d5c1;
  border-radius: 14px;
  padding: 0.8rem 0.9rem;
  margin-top: 0.8rem;
}

.shopping-title {
  margin: 0 0 0.45rem;
  color: #2e5e44;
  font-size: 1rem;
  font-weight: 700;
}

.shopping-item {
  margin: 0;
  padding: 0.32rem 0;
  color: #445a4c;
  border-bottom: 1px solid #edf4ef;
}

.right-small-note {
  color: #5e7465;
  line-height: 1.58;
  margin: 0;
  font-size: 0.88rem;
}

div[data-testid="stCheckbox"] label *,
div[data-testid="stCheckbox"] p,
div[data-testid="stCheckbox"] span {
  color: #284233 !important;
  opacity: 1 !important;
}

.stButton > button,
div[data-testid="stDownloadButton"] > button {
  border-radius: 12px !important;
  border: none !important;
  padding: 0.58rem 0.95rem !important;
  font-weight: 700 !important;
}

.stButton > button[kind="primary"],
div[data-testid="stDownloadButton"] > button {
  background: linear-gradient(135deg, #6aa97a 0%, #4f9265 100%) !important;
  color: #fff !important;
  box-shadow: 0 5px 16px rgba(78, 137, 98, 0.26) !important;
}

.stButton > button[kind="secondary"] {
  background: #fff !important;
  border: 1px solid #b7d6c2 !important;
  color: #3b6a50 !important;
}

@media (max-width: 900px) {
  .block-container {
    max-width: 100%;
    padding-left: 0.8rem;
    padding-right: 0.8rem;
  }

  div[data-testid="stHorizontalBlock"] {
    flex-direction: column !important;
  }

  div[data-testid="column"] {
    width: 100% !important;
    flex: 1 1 100% !important;
  }

  .ui-card, .day-card {
    padding: 0.8rem 0.85rem;
  }
}
</style>
"""


@st.cache_resource
def get_client() -> OpenAI | None:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None
    return OpenAI(api_key=api_key)


def build_weekly_prompt(
    conditions: list[str],
    ingredients: str,
    daily_calories: int,
    extra_notes: str,
) -> str:
    condition_text = "、".join(conditions) if conditions else "特になし（バランス重視）"
    has_ingredients = bool(ingredients.strip())
    ingredient_text = ingredients.strip() if has_ingredients else "指定なし"
    ingredient_rules = (
        """
## 冷蔵庫食材を優先
- 入力食材を1週間で70%以上使う
- 買い足しは最小限にする
"""
        if has_ingredients
        else """
## 食材
- スーパーで揃う一般食材中心
- 買い足しは最小限
"""
    )

    return f"""あなたは料理初心者にやさしい管理栄養士アシスタントです。
1週間の献立を、無理なく作れる形で日本語で提案してください。

## ユーザー条件
- 食事条件: {condition_text}
- 目標カロリー: 約{daily_calories}kcal/日
- 冷蔵庫食材: {ingredient_text}
- その他希望: {extra_notes or "なし"}
{ingredient_rules}
## 必須ルール
- 簡単・洗い物少なめ・疲れていても作れる
- 各食事に「材料（1人分）」「調味料（1人分）」「作り方（手順）」を必ず記載
- 材料と調味料は g・個・大さじ・小さじ を明記
- 「適量」はできるだけ使わない
- 作り方は短い番号手順（1. 2. 3.）
- 栄養価を毎食記載: カロリー / たんぱく質 / 脂質 / 炭水化物 / 塩分

## 出力形式（Markdown）
- `### 月曜日`
- `#### 朝食：メニュー名`
- `- **栄養価（目安）**: ...`
- `- **材料（1人分）**: ...`
- `- **調味料（1人分）**: ...`
- `- **作り方（手順）**: 1. ... 2. ... 3. ...`
- `- **調理時間**: ...`
- `- **使う冷蔵庫の食材**: ...`
- `- **買い足す食材**: ...`
- `> **栄養士コメント**: ...`

最後に `### 今週の買い物メモ` をまとめてください。"""


def build_easy_mode_prompt(conditions: list[str], ingredients: str, easy_modes: list[str]) -> str:
    mode_labels = [EASY_MODE_OPTIONS[m] for m in easy_modes]
    mode_text = "、".join(mode_labels)
    condition_text = "、".join(conditions) if conditions else "特になし"
    ingredient_text = ingredients.strip() if ingredients.strip() else "指定なし"
    return f"""あなたは「今日はもう料理したくない」人向けの献立アドバイザーです。
今日1日分の楽な食事案を3つ（朝・昼・夕）提案してください。

条件:
- モード: {mode_text}
- 食事条件: {condition_text}
- 手元の食材: {ingredient_text}

ルール:
- 包丁なし・5分以内・コンビニ活用OK
- 罪悪感を与えないトーン
- 各食事にメニュー名 / 簡単手順 / 所要時間 / 栄養のひとこと
Markdownで `### 今日の楽ちん献立` から書く。"""


def generate_meal_plan(client: OpenAI, prompt: str) -> str:
    response = client.chat.completions.create(
        model=DEFAULT_MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "あなたは優しく実用的な日本の献立・管理栄養士アドバイザーです。"
                    "調味料の分量や手順は省略しません。"
                    "ユーザーを責めず、無理のない献立を提案します。"
                ),
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.6,
    )
    return response.choices[0].message.content or ""


def _esc(text: str) -> str:
    return html.escape(text or "", quote=True)


def _detail_style(label: str) -> tuple[str, str]:
    for key, (icon, css) in DETAIL_META.items():
        if key in label:
            return icon, css
    return "📌", ""


def _to_number(value: str | float | int | None) -> float:
    if value is None:
        return 0.0
    text = str(value).replace("kcal", "").replace("g", "").replace("約", "").replace(",", "").strip()
    try:
        return float(text)
    except ValueError:
        return 0.0


def calculate_daily_totals(meals: list[MealBlock]) -> dict[str, float]:
    totals = {"calories": 0.0, "protein": 0.0, "fat": 0.0, "carbs": 0.0, "salt": 0.0}
    for meal in meals:
        if not meal.nutrition:
            continue
        totals["calories"] += _to_number(meal.nutrition.calories)
        totals["protein"] += _to_number(meal.nutrition.protein)
        totals["fat"] += _to_number(meal.nutrition.fat)
        totals["carbs"] += _to_number(meal.nutrition.carbs)
        totals["salt"] += _to_number(meal.nutrition.salt)
    return totals


def calculate_weekly_average(parsed: ParsedWeeklyPlan) -> dict[str, float]:
    if not parsed.days:
        return {"calories": 0.0, "protein": 0.0, "fat": 0.0, "carbs": 0.0, "salt": 0.0}
    agg = {"calories": 0.0, "protein": 0.0, "fat": 0.0, "carbs": 0.0, "salt": 0.0}
    for day in parsed.days:
        day_totals = calculate_daily_totals(day.meals)
        for k in agg:
            agg[k] += day_totals[k]
    n = float(len(parsed.days))
    for k in agg:
        agg[k] /= n
    return agg


def render_nutrition_boxes(nutrition: NutritionInfo) -> None:
    items = [
        ("カロリー", f"{nutrition.calories} kcal"),
        ("たんぱく質", f"{nutrition.protein} g"),
        ("脂質", f"{nutrition.fat} g"),
        ("炭水化物", f"{nutrition.carbs} g"),
        ("塩分", f"{nutrition.salt} g"),
    ]
    html_boxes = "".join(
        f'<div class="nutrition-box"><span class="nutrition-label">{_esc(k)}</span>'
        f'<span class="nutrition-value">{_esc(v)}</span></div>'
        for k, v in items
    )
    st.markdown(f'<div class="nutrition-row">{html_boxes}</div>', unsafe_allow_html=True)


def render_detail_block(label: str, body: str) -> None:
    icon, css = _detail_style(label)
    cls = f"detail-block {css}".strip()
    st.markdown(
        f'<div class="{cls}">'
        f'<p class="detail-label">{_esc(icon)} {_esc(label or "メモ")}</p>'
        f'<div class="detail-body">{_esc(body)}</div>'
        "</div>",
        unsafe_allow_html=True,
    )


def render_meal_card(meal: MealBlock) -> None:
    icon = MEAL_ICONS.get(meal.meal_type, "🍽️")
    menu = meal.menu_name or "—"
    st.markdown(
        '<div class="meal-card"><div class="meal-card-body">'
        '<div class="meal-card-header">'
        f'<span class="meal-type-badge">{_esc(icon)} {_esc(meal.meal_type)}</span>'
        f'<p class="meal-menu-name">{_esc(menu)}</p>'
        "</div>",
        unsafe_allow_html=True,
    )

    if meal.nutrition:
        render_nutrition_boxes(meal.nutrition)

    for label, body in meal.details:
        if not body.strip():
            continue
        if parse_nutrition_line(body):
            continue
        render_detail_block(label or "メモ", body)

    st.markdown("</div></div>", unsafe_allow_html=True)


def render_nutritionist_comment(comment: str) -> None:
    st.markdown(
        '<div class="nutritionist-comment-box">'
        '<p class="nutritionist-comment-title">💚 栄養士コメント</p>'
        f'<p class="nutritionist-comment-body">{_esc(comment)}</p>'
        "</div>",
        unsafe_allow_html=True,
    )


def render_day_card(day_name: str, meals: list[MealBlock], day_summary: str, comment: str) -> None:
    st.markdown(
        '<div class="day-card">'
        f'<h3 class="day-card-title">{_esc(day_name or "献立")}</h3>',
        unsafe_allow_html=True,
    )
    for meal in meals:
        render_meal_card(meal)

    if day_summary:
        summary = strip_markdown_inline(day_summary)
        st.markdown(
            '<div class="day-summary-box">'
            f"<strong>1日の合計（目安）</strong><br>{_esc(summary)}"
            "</div>",
            unsafe_allow_html=True,
        )

    if comment:
        render_nutritionist_comment(comment)
    st.markdown("</div>", unsafe_allow_html=True)


def render_shopping_card(items: list[str]) -> None:
    st.markdown('<div class="shopping-card"><p class="shopping-title">🛒 今週の買い物メモ</p>', unsafe_allow_html=True)
    if items:
        for item in items:
            st.markdown(f'<p class="shopping-item">・ {_esc(item)}</p>', unsafe_allow_html=True)
    else:
        st.markdown('<p class="shopping-item">買い足しはほとんどありません。</p>', unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)


def render_weekly_tabs(parsed: ParsedWeeklyPlan) -> None:
    if not parsed.days:
        return
    tabs = st.tabs([d.day_name or f"Day {i+1}" for i, d in enumerate(parsed.days)])
    for tab, day in zip(tabs, parsed.days):
        with tab:
            render_day_card(day.day_name, day.meals, day.day_summary, day.nutritionist_comment)


def render_easy_mode_result(markdown: str) -> None:
    parsed = parse_weekly_plan_markdown(markdown)
    if parsed.days:
        for day in parsed.days:
            render_day_card(day.day_name or "今日", day.meals, day.day_summary, day.nutritionist_comment)
    else:
        st.markdown('<div class="day-card">', unsafe_allow_html=True)
        st.markdown(markdown)
        st.markdown("</div>", unsafe_allow_html=True)


def render_right_nutrition_panel(parsed: ParsedWeeklyPlan, daily_calories: int) -> None:
    st.markdown('<div class="ui-card">', unsafe_allow_html=True)
    st.markdown("#### 今日の栄養バランス")
    if not parsed.days:
        st.markdown('<p class="right-small-note">献立生成後に栄養バランスを表示します。</p>', unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)
        return

    avg = calculate_weekly_average(parsed)
    goals = {"protein": 70.0, "fat": 60.0, "carbs": 240.0, "salt": 6.0}
    st.write(f"平均カロリー: **{avg['calories']:.0f} kcal/日**（目標 {daily_calories} kcal）")
    st.progress(min(avg["calories"] / max(daily_calories, 1), 1.0))

    labels = {"protein": "たんぱく質", "fat": "脂質", "carbs": "炭水化物", "salt": "塩分"}
    for key in ["protein", "fat", "carbs", "salt"]:
        st.caption(f"{labels[key]}: {avg[key]:.1f}g / 目安 {goals[key]:.1f}g")
        st.progress(min(avg[key] / goals[key], 1.0))
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown(
        '<div class="ui-card"><p class="right-small-note">'
        "栄養士コメント: 完璧じゃなくて大丈夫。疲れた日は1品でもOKです。"
        "</p></div>",
        unsafe_allow_html=True,
    )


def main() -> None:
    st.set_page_config(page_title="やさしい献立AI", page_icon="🍽️", layout="wide")
    st.markdown(APP_CSS, unsafe_allow_html=True)
    client = get_client()

    if "weekly_plan" not in st.session_state:
        st.session_state["weekly_plan"] = ""
    if "easy_plan" not in st.session_state:
        st.session_state["easy_plan"] = ""

    left_col, center_col, right_col = st.columns([1.05, 1.8, 1.05], gap="large")

    with left_col:
        st.markdown('<div class="ui-card">', unsafe_allow_html=True)
        st.markdown('<p class="left-title">使い方</p>', unsafe_allow_html=True)
        st.markdown(
            '<p class="helper-text">'
            "1. 条件を選ぶ<br>2. 食材を入力<br>3. 生成ボタンを押す<br>4. PDF保存"
            "</p>",
            unsafe_allow_html=True,
        )
        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown('<div class="ui-card">', unsafe_allow_html=True)
        st.markdown("#### 今日は無理モード 🛋️")
        easy_selected = []
        for k, label in EASY_MODE_OPTIONS.items():
            if st.checkbox(label, key=f"easy_{k}"):
                easy_selected.append(k)
        if st.button("今日の楽ちん献立を提案", use_container_width=True, disabled=client is None):
            if not client:
                st.error("OpenAI API キーが未設定です。")
            else:
                with st.spinner("今日の献立を作成中..."):
                    prompt = build_easy_mode_prompt(
                        st.session_state.get("selected_conditions", []),
                        st.session_state.get("ingredients", ""),
                        easy_selected or list(EASY_MODE_OPTIONS.keys()),
                    )
                    st.session_state["easy_plan"] = generate_meal_plan(client, prompt)
        st.markdown("</div>", unsafe_allow_html=True)

        if os.getenv("OPENAI_API_KEY"):
            st.markdown('<div class="status-ok">✅ OpenAI 接続: 設定済み</div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="status-ng">⚠️ OpenAI 接続: 未設定（.env を確認）</div>', unsafe_allow_html=True)

    with right_col:
        st.markdown('<div class="ui-card">', unsafe_allow_html=True)
        st.markdown("#### 目標設定")
        preset_cal = st.select_slider("目標カロリー（kcal）", options=CALORIE_PRESETS, value=1800)
        daily_calories = int(
            st.number_input(
                "または直接入力",
                min_value=800,
                max_value=4000,
                value=int(preset_cal),
                step=50,
            )
        )
        extra_notes = st.text_input("その他の希望", placeholder="例: 電子レンジ中心、魚苦手")
        st.markdown("</div>", unsafe_allow_html=True)

        parsed_weekly = parse_weekly_plan_markdown(st.session_state["weekly_plan"]) if st.session_state["weekly_plan"] else ParsedWeeklyPlan()
        render_right_nutrition_panel(parsed_weekly, daily_calories)

    with center_col:
        st.markdown('<div class="ui-card">', unsafe_allow_html=True)
        st.markdown('<h2 class="hero-head">🍽️ やさしい献立AI</h2>', unsafe_allow_html=True)
        st.markdown(
            '<p class="hero-caption">'
            "初心者でも作れるよう、1人分の材料・調味料・手順つきで献立を提案します。"
            "</p>",
            unsafe_allow_html=True,
        )
        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown('<div class="ui-card">', unsafe_allow_html=True)
        st.markdown("#### 食事条件")
        selected_conditions: list[str] = []
        cond_cols = st.columns(3)
        for i, option in enumerate(CONDITION_OPTIONS):
            with cond_cols[i % 3]:
                if st.checkbox(option, key=f"cond_{option}"):
                    selected_conditions.append(option)
        st.session_state["selected_conditions"] = selected_conditions

        ingredients = st.text_area(
            "冷蔵庫にある食材",
            placeholder="例: 卵、豆腐、鶏むね肉、キャベツ、ブロッコリー",
            height=110,
        )
        st.session_state["ingredients"] = ingredients

        if st.button("✨ 1週間の献立を生成する", type="primary", use_container_width=True, disabled=client is None):
            if not client:
                st.error("OpenAI API キーが未設定です。")
            else:
                with st.spinner("献立を作成中..."):
                    prompt = build_weekly_prompt(selected_conditions, ingredients, daily_calories, extra_notes)
                    st.session_state["weekly_plan"] = generate_meal_plan(client, prompt)
        st.markdown("</div>", unsafe_allow_html=True)

        if st.session_state["weekly_plan"]:
            st.markdown('<div class="ui-card">', unsafe_allow_html=True)
            st.markdown("#### 今週の献立")
            try:
                pdf_bytes = create_weekly_plan_pdf(
                    st.session_state["weekly_plan"],
                    subtitle=f"作成日: {date.today().isoformat()} / 目標 {daily_calories}kcal/日",
                )
                st.download_button(
                    label="📄 今週の献立をPDF保存",
                    data=pdf_bytes,
                    file_name=f"献立_{date.today().isoformat()}.pdf",
                    mime="application/pdf",
                    use_container_width=True,
                )
            except Exception as e:
                st.warning(f"PDFの準備に失敗しました: {e}")
            st.markdown("</div>", unsafe_allow_html=True)

            parsed = parse_weekly_plan_markdown(st.session_state["weekly_plan"])
            if parsed.days or parsed.shopping_items:
                render_weekly_tabs(parsed)
                if parsed.shopping_items or "買い物" in st.session_state["weekly_plan"]:
                    render_shopping_card(parsed.shopping_items)
            else:
                st.markdown('<div class="day-card">', unsafe_allow_html=True)
                st.markdown(st.session_state["weekly_plan"])
                st.markdown("</div>", unsafe_allow_html=True)

        if st.session_state["easy_plan"]:
            st.markdown('<div class="ui-card">', unsafe_allow_html=True)
            st.markdown("#### 今日の楽ちん献立")
            st.markdown("</div>", unsafe_allow_html=True)
            render_easy_mode_result(st.session_state["easy_plan"])

    st.caption(
        "※ 本アプリの提案は一般的な食生活の参考です。"
        "アレルギー・持病・妊婦の方は医師や管理栄養士にご相談ください。"
    )


if __name__ == "__main__":
    main()
