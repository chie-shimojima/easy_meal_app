"""今週の献立をPDF専用レイアウトでエクスポートするユーティリティ。"""

from __future__ import annotations

import re
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from fpdf import FPDF
from fpdf.enums import XPos, YPos

FONT_DIR = Path(__file__).parent / "fonts"
FONT_REGULAR = FONT_DIR / "NotoSansJP-Regular.otf"
FONT_BOLD = FONT_DIR / "NotoSansJP-Bold.otf"
FONT_REGULAR_URL = (
    "https://github.com/notofonts/noto-cjk/raw/main/Sans/SubsetOTF/JP/"
    "NotoSansJP-Regular.otf"
)
FONT_BOLD_URL = (
    "https://github.com/notofonts/noto-cjk/raw/main/Sans/SubsetOTF/JP/"
    "NotoSansJP-Bold.otf"
)

# A4（mm）— 印刷向け余白（ゆったり）
MARGIN_LEFT = 22
MARGIN_RIGHT = 22
MARGIN_TOP = 18
MARGIN_BOTTOM = 20

# カード内余白
CARD_INSET = 5
MEAL_INSET = 4
CARD_RADIUS = 4
MEAL_RADIUS = 3

DAY_ORDER = ("月曜日", "火曜日", "水曜日", "木曜日", "金曜日", "土曜日", "日曜日")
MEAL_ORDER = ("朝食", "昼食", "夕食")

NUTRITION_RE = re.compile(
    r"カロリー\s*([\d.]+)\s*kcal\s*/\s*"
    r"たんぱく質\s*([\d.]+)\s*g\s*/\s*"
    r"脂質\s*([\d.]+)\s*g\s*/\s*"
    r"炭水化物\s*([\d.]+)\s*g\s*/\s*"
    r"塩分\s*([\d.]+)\s*g",
    re.IGNORECASE,
)
MEAL_HEADER_RE = re.compile(r"^(朝食|昼食|夕食)\s*[：:]\s*(.+)$")
SECTION_HEADER_RE = re.compile(r"^#{1,4}\s*(.+)$")
BULLET_RE = re.compile(r"^[-*]\s+(.+)$")
BLOCKQUOTE_RE = re.compile(r"^>\s*(.+)$")

# 栄養価テーブル列幅（合計 = 利用可能幅）
NUTRITION_COL_RATIOS = (0.22, 0.20, 0.16, 0.24, 0.18)


@dataclass
class NutritionInfo:
    calories: str = "—"
    protein: str = "—"
    fat: str = "—"
    carbs: str = "—"
    salt: str = "—"


@dataclass
class MealBlock:
    meal_type: str
    menu_name: str
    nutrition: NutritionInfo | None = None
    details: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class DayBlock:
    day_name: str
    meals: list[MealBlock] = field(default_factory=list)
    day_summary: str = ""
    nutritionist_comment: str = ""


@dataclass
class ParsedWeeklyPlan:
    days: list[DayBlock] = field(default_factory=list)
    shopping_items: list[str] = field(default_factory=list)
    preamble: str = ""


def ensure_noto_sans_jp_font() -> tuple[Path, Path | None]:
    """Noto Sans JP（Regular / Bold）を fonts/ に用意する。"""
    FONT_DIR.mkdir(parents=True, exist_ok=True)

    if not FONT_REGULAR.exists():
        urllib.request.urlretrieve(FONT_REGULAR_URL, FONT_REGULAR)

    bold_path: Path | None = FONT_BOLD if FONT_BOLD.exists() else None
    if bold_path is None:
        try:
            urllib.request.urlretrieve(FONT_BOLD_URL, FONT_BOLD)
            bold_path = FONT_BOLD
        except Exception:
            bold_path = None

    return FONT_REGULAR, bold_path


def strip_markdown_inline(text: str) -> str:
    """インラインMarkdown（** など）を除去する。"""
    cleaned = text.strip()
    cleaned = re.sub(r"\*\*(.+?)\*\*", r"\1", cleaned)
    cleaned = re.sub(r"\*(.+?)\*", r"\1", cleaned)
    cleaned = re.sub(r"`(.+?)`", r"\1", cleaned)
    return cleaned.strip()


def parse_nutrition_line(text: str) -> NutritionInfo | None:
    """栄養価1行から数値を抽出する。"""
    match = NUTRITION_RE.search(text)
    if not match:
        return None
    cal, pro, fat, carb, salt = match.groups()
    return NutritionInfo(
        calories=f"{cal}",
        protein=f"{pro}",
        fat=f"{fat}",
        carbs=f"{carb}",
        salt=f"{salt}",
    )


def _normalize_section_title(raw: str) -> str:
    title = strip_markdown_inline(raw)
    title = re.sub(r"^#+\s*", "", title).strip()
    return title


def _is_shopping_section(title: str) -> bool:
    return "買い物" in title or "買い足し" in title


def _is_day_section(title: str) -> bool:
    return any(day in title for day in DAY_ORDER)


def _extract_day_name(title: str) -> str:
    for day in DAY_ORDER:
        if day in title:
            return day
    return title


def _parse_meal_header(line: str) -> tuple[str, str] | None:
    """#### 朝食：メニュー名 形式を解析。"""
    stripped = line.strip()
    header_match = SECTION_HEADER_RE.match(stripped)
    if not header_match:
        return None

    body = strip_markdown_inline(header_match.group(1))
    meal_match = MEAL_HEADER_RE.match(body)
    if meal_match:
        return meal_match.group(1), meal_match.group(2).strip()

    for meal_type in MEAL_ORDER:
        if body.startswith(meal_type):
            name = body[len(meal_type) :].lstrip("：:").strip()
            return meal_type, name or meal_type
    return None


def _parse_detail_line(line: str) -> tuple[str, str] | None:
    """箇条書き行をラベルと本文に分ける。"""
    bullet = BULLET_RE.match(line.strip())
    if not bullet:
        return None

    content = strip_markdown_inline(bullet.group(1))
    if "栄養価" in content and "カロリー" in content:
        return None

    for sep in ("：", ":"):
        if sep in content:
            label, body = content.split(sep, 1)
            label = label.strip().strip("*")
            body = body.strip()
            if label and body:
                return label, body

    return "", content


def parse_weekly_plan_markdown(markdown: str) -> ParsedWeeklyPlan:
    """AI出力MarkdownをPDF用の構造データに変換する。"""
    plan = ParsedWeeklyPlan()
    current_day: DayBlock | None = None
    current_meal: MealBlock | None = None
    in_shopping = False

    for raw_line in markdown.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue

        if line.lstrip().startswith("#"):
            section_title = _normalize_section_title(line)
            meal_header = _parse_meal_header(line)

            if _is_shopping_section(section_title):
                in_shopping = True
                current_day = None
                current_meal = None
                continue

            if meal_header:
                in_shopping = False
                meal_type, menu_name = meal_header
                if current_day is None:
                    current_day = DayBlock(day_name="")
                    plan.days.append(current_day)
                current_meal = MealBlock(meal_type=meal_type, menu_name=menu_name)
                current_day.meals.append(current_meal)
                continue

            if _is_day_section(section_title):
                in_shopping = False
                current_day = DayBlock(day_name=_extract_day_name(section_title))
                plan.days.append(current_day)
                current_meal = None
                continue

            if in_shopping:
                plan.shopping_items.append(section_title)
            elif current_day is not None:
                current_day.day_summary = section_title
            else:
                plan.preamble += section_title + "\n"
            continue

        if in_shopping:
            bullet = BULLET_RE.match(line.strip())
            text = strip_markdown_inline(bullet.group(1)) if bullet else strip_markdown_inline(line)
            if text and text not in ("買い足しなし", "なし"):
                plan.shopping_items.append(text)
            continue

        quote = BLOCKQUOTE_RE.match(line.strip())
        if quote:
            comment = strip_markdown_inline(quote.group(1))
            comment = re.sub(r"^栄養士コメント\s*[：:]\s*", "", comment)
            if current_day is not None:
                current_day.nutritionist_comment = comment
            continue

        bullet = BULLET_RE.match(line.strip())
        if bullet:
            content = strip_markdown_inline(bullet.group(1))

            nutrition = parse_nutrition_line(content)
            if nutrition and current_meal is not None:
                current_meal.nutrition = nutrition
                continue

            if "1日の栄養合計" in content or "1日の合計" in content:
                if current_day is not None:
                    current_day.day_summary = content
                continue

            detail = _parse_detail_line(line)
            if detail and current_meal is not None:
                label, body = detail
                if label:
                    current_meal.details.append((label, body))
                else:
                    current_meal.details.append(("", body))
            elif current_meal is not None:
                current_meal.details.append(("", content))
            elif current_day is not None and not current_meal:
                current_day.day_summary = content
            continue

        plain = strip_markdown_inline(line)
        if current_meal is not None:
            nutrition = parse_nutrition_line(plain)
            if nutrition:
                current_meal.nutrition = nutrition
            else:
                current_meal.details.append(("", plain))
        elif current_day is not None:
            if not current_day.nutritionist_comment and "栄養士コメント" in plain:
                plain = re.sub(r"^栄養士コメント\s*[：:]\s*", "", plain)
                current_day.nutritionist_comment = plain
            else:
                current_day.day_summary = plain

    plan.days.sort(key=lambda d: DAY_ORDER.index(d.day_name) if d.day_name in DAY_ORDER else 99)
    for day in plan.days:
        day.meals.sort(
            key=lambda m: MEAL_ORDER.index(m.meal_type) if m.meal_type in MEAL_ORDER else 99
        )

    return plan


class WeeklyPlanPDF(FPDF):
    """やさしいヘルスケア風・Webに近い献立PDF。"""

    # ページ・カード（薄緑・ベージュ系）
    COLOR_PAGE_BG = (244, 250, 246)
    COLOR_CARD_BG = (255, 255, 255)
    COLOR_CARD_BORDER = (207, 230, 214)
    COLOR_MEAL_BG = (249, 252, 250)
    COLOR_MEAL_BORDER = (224, 239, 230)

    # 文字
    COLOR_TITLE = (47, 79, 63)
    COLOR_SUBTITLE = (107, 128, 116)
    COLOR_DAY = (47, 92, 66)
    COLOR_MEAL = (61, 90, 75)
    COLOR_BODY = (68, 90, 80)
    COLOR_MUTED = (130, 155, 140)

    # 栄養表
    COLOR_TABLE_HEAD = (232, 245, 236)
    COLOR_TABLE_BORDER = (212, 230, 218)
    COLOR_TABLE_BODY = (255, 255, 255)

    # 栄養士コメント（吹き出し・薄黄）
    COLOR_COMMENT_BG = (255, 251, 235)
    COLOR_COMMENT_BORDER = (229, 221, 184)
    COLOR_COMMENT_TITLE = (122, 107, 46)

    # タイポグラフィ（pt）— 見出し大きめ
    SIZE_TITLE = 20
    SIZE_DAY = 17
    SIZE_MEAL = 13
    SIZE_MENU = 11
    SIZE_LABEL = 9
    SIZE_BODY = 9.5
    SIZE_TABLE = 7.5
    SIZE_COMMENT = 10
    SIZE_BADGE = 8

    def __init__(self, font_regular: Path, font_bold: Path | None) -> None:
        super().__init__(orientation="P", unit="mm", format="A4")
        self._font_regular = font_regular
        self._font_bold = font_bold
        self.set_margins(MARGIN_LEFT, MARGIN_TOP, MARGIN_RIGHT)
        self.set_auto_page_break(auto=False)
        self._current_day_name = ""
        self._text_inset = 0.0

    def setup_fonts(self) -> None:
        self.add_font("NotoSansJP", "", str(self._font_regular))
        if self._font_bold and self._font_bold.exists():
            self.add_font("NotoSansJP", "B", str(self._font_bold))
        else:
            self.add_font("NotoSansJP", "B", str(self._font_regular))

    @property
    def content_width(self) -> float:
        """描画可能幅（左右余白を除いた幅）。"""
        return self.w - self.l_margin - self.r_margin

    @property
    def text_width(self) -> float:
        """テキスト折り返し幅（カード内余白を考慮）。"""
        return self.content_width - 2 * self._text_inset

    @property
    def text_left(self) -> float:
        return self.l_margin + self._text_inset

    @property
    def bottom_limit(self) -> float:
        return self.h - self.b_margin

    def _reset_x(self) -> None:
        self.set_x(self.text_left)

    def _draw_page_background(self) -> None:
        self.set_fill_color(*self.COLOR_PAGE_BG)
        self.rect(0, 0, self.w, self.h, style="F")

    def _fill_rounded_rect(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        radius: float,
        fill: tuple[int, int, int],
        border: tuple[int, int, int] | None = None,
    ) -> None:
        if h <= 0 or w <= 0:
            return
        self.set_fill_color(*fill)
        if border:
            self.set_draw_color(*border)
            self.set_line_width(0.25)
            self.rect(x, y, w, h, style="FD", round_corners=True, corner_radius=radius)
        else:
            self.set_draw_color(*fill)
            self.rect(x, y, w, h, style="F", round_corners=True, corner_radius=radius)

    def _set_regular(self, size: float) -> None:
        self.set_font("NotoSansJP", size=size)

    def _set_bold(self, size: float) -> None:
        self.set_font("NotoSansJP", style="B", size=size)

    def _estimate_text_height(
        self,
        text: str,
        *,
        size: float,
        line_height: float,
        width: float | None = None,
    ) -> float:
        if not text:
            return 0.0
        w = width if width is not None else self.text_width
        char_per_line = max(10, int(w / (size * 0.42)))
        lines = max(1, (len(text) + char_per_line - 1) // char_per_line)
        return lines * line_height

    def _estimate_meal_height(self, meal: MealBlock) -> float:
        inner_w = self.content_width - 2 * MEAL_INSET - 2 * CARD_INSET
        height = 16.0 + MEAL_INSET * 2
        if meal.nutrition:
            height += 5.0 + 15.0
        for label, body in meal.details:
            if label:
                height += 5.0
            height += self._estimate_text_height(
                body, size=self.SIZE_BODY, line_height=5.2, width=inner_w - 4
            )
            height += 3.0
        return height + 4.0

    def _estimate_comment_height(self, comment: str) -> float:
        return 20.0 + self._estimate_text_height(
            comment, size=self.SIZE_COMMENT, line_height=5.2, width=self.text_width - 6
        )

    def _estimate_day_height(self, day: DayBlock) -> float:
        h = 22.0 + CARD_INSET * 2
        for meal in day.meals:
            h += self._estimate_meal_height(meal) + 3.0
        if day.day_summary:
            h += 14.0
        if day.nutritionist_comment:
            h += self._estimate_comment_height(day.nutritionist_comment) + 4.0
        return h + 8.0

    def ensure_vertical_space(self, required_mm: float) -> None:
        """残りスペースが足りなければ改ページする。"""
        if self.get_y() + required_mm > self.bottom_limit:
            self.add_page()
            self._draw_page_background()
            if self._current_day_name:
                self._draw_day_continuation_banner()

    def _draw_day_continuation_banner(self) -> None:
        self._draw_page_background()
        self._reset_x()
        y0 = self.get_y()
        self._fill_rounded_rect(
            self.l_margin,
            y0,
            self.content_width,
            9,
            2,
            self.COLOR_TABLE_HEAD,
            self.COLOR_CARD_BORDER,
        )
        self.set_text_color(*self.COLOR_DAY)
        self._set_bold(self.SIZE_LABEL)
        self.set_xy(self.text_left, y0 + 2)
        self.cell(self.text_width, 6, f"{self._current_day_name}（つづき）", align="L")
        self.set_y(y0 + 11)
        self.set_text_color(*self.COLOR_BODY)
        self._reset_x()

    def write_wrapped(
        self,
        text: str,
        *,
        size: float = SIZE_BODY,
        line_height: float = 5.0,
        bold: bool = False,
        align: str = "L",
        color: tuple[int, int, int] | None = None,
    ) -> None:
        """カード内でも右にはみ出さないよう折り返す。"""
        if not text:
            return
        if bold:
            self._set_bold(size)
        else:
            self._set_regular(size)
        if color:
            self.set_text_color(*color)
        self._reset_x()
        self.multi_cell(self.text_width, line_height, text, align=align)
        self.set_text_color(*self.COLOR_BODY)
        self._reset_x()

    def _nutrition_col_widths_for(self, total_width: float) -> list[float]:
        widths = [total_width * ratio for ratio in NUTRITION_COL_RATIOS]
        widths[-1] = total_width - sum(widths[:-1])
        return widths

    def _draw_table_row(
        self,
        cells: list[str],
        col_widths: list[float],
        *,
        row_h: float,
        bold: bool = False,
        font_size: float = SIZE_TABLE,
        fill_color: tuple[int, int, int] | None = None,
        x_start: float | None = None,
    ) -> None:
        x0 = x_start if x_start is not None else self.text_left
        self.set_xy(x0, self.get_y())
        self.set_draw_color(*self.COLOR_TABLE_BORDER)
        self.set_line_width(0.15)
        if bold:
            self._set_bold(font_size)
            self.set_text_color(*self.COLOR_DAY)
        else:
            self._set_regular(font_size)
            self.set_text_color(*self.COLOR_BODY)
        if fill_color:
            self.set_fill_color(*fill_color)

        for i, (text, width) in enumerate(zip(cells, col_widths)):
            is_last = i == len(cells) - 1
            self.cell(
                width,
                row_h,
                text,
                border=1,
                align="C",
                fill=fill_color is not None,
                new_x=XPos.RIGHT,
                new_y=YPos.TOP,
            )
        self.set_xy(self.l_margin + self._text_inset, self.get_y() + row_h)

    def draw_nutrition_table(self, nutrition: NutritionInfo) -> None:
        """柔らかい薄緑ヘッダーの栄養価表。"""
        table_w = self.text_width
        col_widths = self._nutrition_col_widths_for(table_w)
        headers = ["カロリー", "たんぱく", "脂質", "炭水物", "塩分"]
        units = ["kcal", "g", "g", "g", "g"]
        values = [
            nutrition.calories,
            nutrition.protein,
            nutrition.fat,
            nutrition.carbs,
            nutrition.salt,
        ]
        value_cells = [f"{v} {u}" if v != "—" else "—" for v, u in zip(values, units)]
        row_h = 7.0

        self.ensure_vertical_space(row_h * 2 + 6)
        self.ln(1)
        x0 = self.text_left
        self._draw_table_row(
            headers,
            col_widths,
            row_h=row_h,
            bold=True,
            font_size=self.SIZE_TABLE,
            fill_color=self.COLOR_TABLE_HEAD,
            x_start=x0,
        )
        self._draw_table_row(
            value_cells,
            col_widths,
            row_h=row_h,
            bold=False,
            font_size=self.SIZE_TABLE,
            fill_color=self.COLOR_TABLE_BODY,
            x_start=x0,
        )
        self.ln(3)

    def draw_title_page(self, title: str, subtitle: str) -> None:
        self.add_page()
        self._draw_page_background()
        self._text_inset = 0

        card_y = 28
        card_h = 52
        self._fill_rounded_rect(
            self.l_margin + 8,
            card_y,
            self.content_width - 16,
            card_h,
            6,
            self.COLOR_CARD_BG,
            self.COLOR_CARD_BORDER,
        )

        self.set_y(card_y + 14)
        self.set_text_color(*self.COLOR_TITLE)
        self._set_bold(self.SIZE_TITLE)
        self._reset_x()
        self.multi_cell(self.content_width, 10, title, align="C")
        self._reset_x()

        if subtitle:
            self.ln(3)
            self.set_text_color(*self.COLOR_SUBTITLE)
            self._set_regular(9.5)
            self._reset_x()
            self.multi_cell(self.content_width, 5.5, subtitle, align="C")
            self._reset_x()

        self.set_y(card_y + card_h + 14)
        self.set_text_color(*self.COLOR_MUTED)
        self.write_wrapped(
            "※ 栄養価は1食分の目安です。無理のない食生活の参考としてご利用ください。",
            size=8.5,
            line_height=4.8,
            color=self.COLOR_MUTED,
        )

    def _draw_day_title(self, day_name: str) -> None:
        """曜日見出し（大きく・帯付き）。"""
        y0 = self.get_y()
        band_h = 12.0
        self._fill_rounded_rect(
            self.text_left,
            y0,
            self.text_width,
            band_h,
            2.5,
            self.COLOR_TABLE_HEAD,
            None,
        )
        self.set_text_color(*self.COLOR_DAY)
        self._set_bold(self.SIZE_DAY)
        self.set_xy(self.text_left + 3, y0 + 2.5)
        self.cell(self.text_width - 6, 8, day_name, align="L")
        self.set_y(y0 + band_h + 5)
        self.set_text_color(*self.COLOR_BODY)
        self._reset_x()

    def _draw_meal_badge(self, meal_type: str) -> None:
        """朝食・昼食・夕食バッジ。"""
        badge_w = 22
        y0 = self.get_y()
        self._fill_rounded_rect(
            self.text_left,
            y0,
            badge_w,
            6.5,
            2,
            self.COLOR_TABLE_HEAD,
            self.COLOR_MEAL_BORDER,
        )
        self.set_text_color(*self.COLOR_DAY)
        self._set_bold(self.SIZE_BADGE)
        self.set_xy(self.text_left, y0 + 1.2)
        self.cell(badge_w, 5, meal_type, align="C")
        self.set_xy(self.text_left, y0 + 8)
        self.set_text_color(*self.COLOR_BODY)

    def _draw_detail_block(self, label: str, body: str) -> None:
        """作り方など項目ブロック（左アクセント線）。"""
        self.ensure_vertical_space(14)
        y0 = self.get_y()
        block_h = max(
            12.0,
            6.0
            + self._estimate_text_height(body, size=self.SIZE_BODY, line_height=5.2, width=self.text_width - 8),
        )
        self._fill_rounded_rect(
            self.text_left,
            y0,
            self.text_width,
            block_h,
            2,
            (255, 255, 255),
            self.COLOR_MEAL_BORDER,
        )
        self.set_fill_color(*self.COLOR_TABLE_HEAD)
        self.rect(self.text_left, y0, 1.2, block_h, style="F")

        self.set_xy(self.text_left + 4, y0 + 2.5)
        if label:
            self.set_text_color(*self.COLOR_MEAL)
            self._set_bold(self.SIZE_LABEL)
            self.cell(self.text_width - 8, 4.5, label, align="L")
            self.ln(5)
        self.set_text_color(*self.COLOR_BODY)
        self._set_regular(self.SIZE_BODY)
        self.set_x(self.text_left + 4)
        self.multi_cell(self.text_width - 8, 5.2, body)
        self.set_y(y0 + block_h + 2)
        self._reset_x()

    def draw_meal_block(self, meal: MealBlock) -> None:
        """食事小カード（角丸・薄緑背景）。"""
        needed = self._estimate_meal_height(meal)
        self.ensure_vertical_space(needed)

        card_x = self.l_margin + CARD_INSET
        card_w = self.content_width - 2 * CARD_INSET
        y0 = self.get_y()
        saved_inset = self._text_inset
        self._text_inset = CARD_INSET + MEAL_INSET

        self._fill_rounded_rect(
            card_x,
            y0,
            card_w,
            needed - 2,
            MEAL_RADIUS,
            self.COLOR_MEAL_BG,
            self.COLOR_MEAL_BORDER,
        )
        self.set_xy(self.text_left, y0 + MEAL_INSET)

        self._draw_meal_badge(meal.meal_type)
        menu_label = meal.menu_name if meal.menu_name else "—"
        self.set_text_color(*self.COLOR_MEAL)
        self._set_bold(self.SIZE_MENU)
        self.write_wrapped(menu_label, size=self.SIZE_MENU, line_height=5.5, bold=True)
        self.ln(2)

        if meal.nutrition:
            self.set_text_color(*self.COLOR_MUTED)
            self.write_wrapped("栄養価（目安）", size=self.SIZE_LABEL, line_height=4.5, color=self.COLOR_MUTED)
            self.draw_nutrition_table(meal.nutrition)

        for label, body in meal.details:
            if not body.strip():
                continue
            if label:
                self._draw_detail_block(label, body)
            else:
                self.write_wrapped(body, size=self.SIZE_BODY, line_height=5.2)

        self._text_inset = saved_inset
        self.set_y(y0 + needed + 1)
        self._reset_x()
        self.ln(2)

    def draw_nutritionist_comment(self, comment: str) -> None:
        """栄養士コメント（吹き出し風・薄黄）。"""
        self.ensure_vertical_space(self._estimate_comment_height(comment))
        self.ln(3)

        pad = 5.0
        y_start = self.get_y()
        inner_w = self.text_width - pad * 2
        text_h = self._estimate_text_height(
            comment, size=self.SIZE_COMMENT, line_height=5.2, width=inner_w
        )
        box_h = text_h + 16.0

        self._fill_rounded_rect(
            self.text_left,
            y_start,
            self.text_width,
            box_h,
            CARD_RADIUS,
            self.COLOR_COMMENT_BG,
            self.COLOR_COMMENT_BORDER,
        )

        self.set_fill_color(*self.COLOR_COMMENT_BORDER)
        bubble_x = self.text_left + 10
        self.ellipse(bubble_x, y_start - 2.5, 5, 4, style="F")

        self.set_xy(self.text_left + pad, y_start + 4)
        self.set_text_color(*self.COLOR_COMMENT_TITLE)
        self._set_bold(self.SIZE_LABEL)
        self.cell(inner_w, 5, "栄養士コメント", align="L")
        self.ln(7)

        self.set_text_color(*self.COLOR_BODY)
        self._set_regular(self.SIZE_COMMENT)
        self.set_x(self.text_left + pad)
        self.multi_cell(inner_w, 5.2, comment)
        self.set_y(y_start + box_h + 4)
        self.set_text_color(*self.COLOR_BODY)
        self._reset_x()

    def draw_day_page(self, day: DayBlock) -> None:
        """曜日カード（1ページ・余白多め）。"""
        self.add_page()
        self._draw_page_background()
        self._current_day_name = day.day_name

        y_card = self.get_y() + 4
        est_h = self._estimate_day_height(day)
        self._fill_rounded_rect(
            self.l_margin,
            y_card,
            self.content_width,
            min(est_h, self.bottom_limit - y_card - 6),
            CARD_RADIUS,
            self.COLOR_CARD_BG,
            self.COLOR_CARD_BORDER,
        )

        self._text_inset = CARD_INSET
        self.set_xy(self.text_left, y_card + CARD_INSET)
        self._draw_day_title(day.day_name)

        for meal in day.meals:
            self.draw_meal_block(meal)

        if day.day_summary:
            self.ensure_vertical_space(16)
            summary = strip_markdown_inline(day.day_summary)
            summary = re.sub(r"^1日の栄養合計\s*[（(]目安[）)]\s*[：:]\s*", "", summary)
            y0 = self.get_y()
            self._fill_rounded_rect(
                self.text_left,
                y0,
                self.text_width,
                12
                + self._estimate_text_height(
                    summary, size=self.SIZE_BODY, line_height=5.0, width=self.text_width - 6
                ),
                2,
                self.COLOR_TABLE_HEAD,
                None,
            )
            self.set_xy(self.text_left + 3, y0 + 2)
            self.set_text_color(*self.COLOR_DAY)
            self._set_bold(self.SIZE_LABEL)
            self.cell(self.text_width - 6, 4.5, "1日の合計（目安）", align="L")
            self.ln(5)
            self.set_text_color(*self.COLOR_BODY)
            self.write_wrapped(summary, size=self.SIZE_BODY, line_height=5.0)
            self.ln(3)

        if day.nutritionist_comment:
            self.draw_nutritionist_comment(day.nutritionist_comment)

        self._text_inset = 0
        self.ln(6)

    def draw_shopping_page(self, items: list[str]) -> None:
        self.add_page()
        self._draw_page_background()
        self._current_day_name = ""

        y_card = self.get_y() + 4
        self._fill_rounded_rect(
            self.l_margin,
            y_card,
            self.content_width,
            40 + len(items) * 8,
            CARD_RADIUS,
            self.COLOR_CARD_BG,
            self.COLOR_CARD_BORDER,
        )
        self._text_inset = CARD_INSET
        self.set_xy(self.text_left, y_card + CARD_INSET)
        self._draw_day_title("今週の買い物メモ")

        if not items:
            self.write_wrapped(
                "買い足しはほとんどありません。お手持ちの食材で今週を乗り切れそうです。",
                size=self.SIZE_BODY,
                color=self.COLOR_MUTED,
            )
        else:
            for item in items:
                self.ensure_vertical_space(10)
                self.write_wrapped(f"・  {item}", size=self.SIZE_BODY, line_height=5.2)

        self._text_inset = 0

    def draw_plain_content(self, markdown: str) -> None:
        """パースできなかった場合のフォールバック。"""
        self.add_page()
        self._draw_page_background()
        self._text_inset = CARD_INSET
        for raw_line in markdown.splitlines():
            line = raw_line.rstrip()
            if not line.strip():
                self.ln(3)
                continue

            if line.lstrip().startswith("#"):
                title = _normalize_section_title(line)
                self.ensure_vertical_space(12)
                self.write_wrapped(title, size=self.SIZE_MEAL, line_height=6, bold=True)
                self.ln(2)
                continue

            quote = BLOCKQUOTE_RE.match(line.strip())
            if quote:
                text = strip_markdown_inline(quote.group(1))
                self.ensure_vertical_space(10)
                self.write_wrapped(text, size=self.SIZE_COMMENT)
                self.ln(2)
                continue

            bullet = BULLET_RE.match(line.strip())
            text = strip_markdown_inline(bullet.group(1) if bullet else line)
            prefix = "・ " if bullet else ""
            self.ensure_vertical_space(8)
            self.write_wrapped(f"{prefix}{text}", size=self.SIZE_BODY)


def create_weekly_plan_pdf(
    plan_markdown: str,
    *,
    title: str = "やさしい献立AI — 今週の献立",
    subtitle: str = "",
) -> bytes:
    """献立MarkdownからA4印刷向けPDF bytes を生成する。"""
    font_regular, font_bold = ensure_noto_sans_jp_font()
    parsed = parse_weekly_plan_markdown(plan_markdown)

    pdf = WeeklyPlanPDF(font_regular, font_bold)
    pdf.setup_fonts()
    pdf.draw_title_page(title, subtitle)

    if parsed.days:
        for day in parsed.days:
            pdf.draw_day_page(day)
        if parsed.shopping_items or "買い物" in plan_markdown:
            pdf.draw_shopping_page(parsed.shopping_items)
    else:
        pdf.draw_plain_content(plan_markdown)

    return bytes(pdf.output())
