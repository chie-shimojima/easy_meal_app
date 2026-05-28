"""メニュー名から料理画像URLを取得する（無料API + プレースホルダー）。"""

from __future__ import annotations

import hashlib
import json
import re
import urllib.parse
import urllib.request

THEMEALDB_SEARCH_URL = "https://www.themealdb.com/api/json/v1/1/search.php?s={query}"
FOODISH_BASE_URL = "https://foodish-api.com/api"
WIKIMEDIA_API_URL = "https://commons.wikimedia.org/w/api.php"

# メニュー名に含まれるキーワード → 画像検索用（英語）
MENU_KEYWORD_MAP: tuple[tuple[str, str], ...] = (
    ("味噌汁", "miso soup"),
    ("味噌", "miso soup"),
    ("おにぎり", "onigiri rice ball"),
    ("ごはん", "steamed rice bowl"),
    ("ご飯", "steamed rice bowl"),
    ("カレー", "japanese curry"),
    ("うどん", "udon noodles"),
    ("そば", "soba noodles"),
    ("ラーメン", "ramen noodles"),
    ("パスタ", "pasta"),
    ("サラダ", "salad"),
    ("スープ", "soup"),
    ("汁", "soup"),
    ("豆腐", "tofu dish"),
    ("卵", "egg dish"),
    ("玉子", "egg dish"),
    ("チキン", "chicken dish"),
    ("鶏", "chicken dish"),
    ("豚", "pork dish"),
    ("牛肉", "beef dish"),
    ("魚", "grilled fish"),
    ("サバ", "mackerel fish"),
    ("鮭", "salmon"),
    ("焼き", "grilled food japanese"),
    ("トースト", "toast breakfast"),
    ("サンドイッチ", "sandwich"),
    ("ヨーグルト", "yogurt breakfast"),
    ("シリアル", "cereal breakfast"),
    ("鍋", "hot pot japanese"),
    ("丼", "rice bowl japanese"),
    ("弁当", "bento box"),
    ("惣菜", "japanese side dishes"),
    ("おでん", "oden japanese"),
    ("天ぷら", "tempura"),
    ("餃子", "gyoza dumpling"),
    ("ピザ", "pizza"),
    ("ハンバーグ", "hamburger steak"),
    ("野菜", "vegetable dish"),
    ("フルーツ", "fruit plate"),
)

# メニュー名の個別補正（精度優先）
MENU_OVERRIDE_QUERIES: tuple[tuple[str, str], ...] = (
    ("味噌汁", "miso soup and rice japanese breakfast homemade"),
    ("卵焼き", "japanese tamagoyaki homemade bento"),
    ("だし巻き", "japanese rolled omelette homemade"),
    ("鶏肉と野菜炒め", "chicken and vegetable stir fry japanese homemade"),
    ("野菜炒め", "japanese stir fried vegetables homemade"),
    ("焼き魚", "japanese grilled fish homemade meal"),
    ("鮭", "japanese grilled salmon homemade"),
    ("親子丼", "oyakodon japanese chicken egg rice bowl homemade"),
    ("カレー", "japanese curry rice homemade"),
    ("肉じゃが", "nikujaga japanese home cooking"),
)

MEAL_TYPE_QUERY: dict[str, str] = {
    "朝食": "breakfast japanese",
    "昼食": "lunch japanese",
    "夕食": "dinner japanese",
}

FOODISH_CATEGORY_MAP: dict[str, str] = {
    "pizza": "pizza",
    "パスタ": "pasta",
    "カレー": "butter-chicken",
    "ハンバーグ": "burger",
    "デザート": "dessert",
    "スイーツ": "dessert",
}


def _http_get_json(url: str, timeout: float = 6.0) -> dict | list | None:
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "YasashiiMealApp/1.0 (educational)"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def guess_image_query(menu_name: str, meal_type: str) -> str:
    """メニュー名・食事区分から画像検索クエリを推定。"""
    normalized = re.sub(r"\s+", " ", menu_name.strip())

    for keyword, query in MENU_OVERRIDE_QUERIES:
        if keyword in normalized:
            return query

    for keyword, query in MENU_KEYWORD_MAP:
        if keyword in normalized:
            return f"{query} japanese homemade meal realistic food photo"

    if normalized:
        # ユーザー要望: メニュー名を活かして家庭料理らしい写真に寄せる
        return f"{normalized} japanese homemade meal realistic food photo"
    return f"{MEAL_TYPE_QUERY.get(meal_type, 'japanese home cooking')} realistic food photo"


def build_query_candidates(menu_name: str, meal_type: str) -> list[str]:
    """段階的に検索するクエリ候補（精度優先）。"""
    primary = guess_image_query(menu_name, meal_type)
    candidates: list[str] = [primary]

    base = re.sub(r"[（(].*?[）)]", "", menu_name).strip()
    if base and base != primary:
        candidates.append(f"{base} japanese homemade meal")
        candidates.append(f"{base} realistic food photo")

    # キーワードベースにもフォールバック
    for keyword, query in MENU_KEYWORD_MAP:
        if keyword in menu_name and query not in " ".join(candidates):
            candidates.append(f"{query} japanese home cooking")
            break

    candidates.append(MEAL_TYPE_QUERY.get(meal_type, "japanese home cooking"))

    # 重複除去しつつ順序維持
    deduped: list[str] = []
    seen: set[str] = set()
    for q in candidates:
        qn = q.strip()
        if qn and qn not in seen:
            deduped.append(qn)
            seen.add(qn)
    return deduped


def _fetch_themealdb(query: str) -> str | None:
    url = THEMEALDB_SEARCH_URL.format(query=urllib.parse.quote(query))
    data = _http_get_json(url)
    if not isinstance(data, dict):
        return None
    meals = data.get("meals")
    if meals and isinstance(meals, list):
        thumb = meals[0].get("strMealThumb")
        if isinstance(thumb, str) and thumb.startswith("http"):
            return thumb
    return None


def _fetch_loremflickr(query: str, menu_name: str) -> str:
    """タグベースの無料フード写真（キー不要）。"""
    tags = re.sub(r"[^\w\s]", "", query).replace(" ", ",")
    if not tags:
        tags = "food,japanese"
    seed = hashlib.md5(f"{menu_name}|{query}".encode()).hexdigest()[:10]
    return f"https://loremflickr.com/800/400/{tags}/all?lock={seed}"


def _fetch_wikimedia(query: str) -> str | None:
    params = urllib.parse.urlencode(
        {
            "action": "query",
            "generator": "search",
            "gsrsearch": query,
            "gsrnamespace": 6,
            "gsrlimit": 3,
            "prop": "pageimages",
            "format": "json",
            "pithumbsize": 800,
        }
    )
    data = _http_get_json(f"{WIKIMEDIA_API_URL}?{params}", timeout=8.0)
    if not isinstance(data, dict):
        return None
    pages = data.get("query", {}).get("pages", {})
    for page in pages.values():
        title = (page.get("title") or "").lower()
        if any(skip in title for skip in ("logo", "icon", "diagram", "map")):
            continue
        thumb = page.get("thumbnail", {}).get("source")
        if isinstance(thumb, str) and thumb.startswith("http"):
            return thumb
    return None


def _fetch_themealdb_random() -> str | None:
    data = _http_get_json("https://www.themealdb.com/api/json/v1/1/random.php")
    if isinstance(data, dict):
        meals = data.get("meals")
        if meals and isinstance(meals, list):
            thumb = meals[0].get("strMealThumb")
            if isinstance(thumb, str) and thumb.startswith("http"):
                return thumb
    return None


def _guess_foodish_category(menu_name: str) -> str | None:
    for keyword, category in FOODISH_CATEGORY_MAP.items():
        if keyword in menu_name:
            return category
    return None


def _fetch_foodish(menu_name: str) -> str | None:
    category = _guess_foodish_category(menu_name)
    if not category:
        return None
    url = f"{FOODISH_BASE_URL}/images/{category}"
    data = _http_get_json(url)
    if isinstance(data, dict):
        image = data.get("image")
        if isinstance(image, str) and image.startswith("http"):
            return image
    return None


def placeholder_image_url(menu_name: str, meal_type: str) -> str:
    """テーマに合わせた横長プレースホルダー（常に表示可能）。"""
    label = re.sub(r"\s+", " ", menu_name.strip())[:24] or meal_type
    text = urllib.parse.quote(label)
    return f"https://placehold.co/800x400/e8f5ec/4a7a5c?text={text}&font=noto-sans"


def get_meal_image_urls(menu_name: str, meal_type: str) -> tuple[str, str]:
    """
    料理画像URLを取得する。

    Returns:
        (primary_url, fallback_url) — primary が失敗したとき fallback を使う
    """
    fallback = placeholder_image_url(menu_name, meal_type)
    if not menu_name.strip():
        return fallback, fallback

    query_candidates = build_query_candidates(menu_name, meal_type)

    # 1) 料理名一致のAPIを最優先
    for query in query_candidates[:4]:
        url = _fetch_themealdb(query)
        if url:
            return url, fallback

    # 2) カテゴリが合う場合のみFoodish
    foodish_url = _fetch_foodish(menu_name)
    if foodish_url:
        return foodish_url, fallback

    # 3) 候補クエリ順に家庭料理寄りの写真を使用
    for query in query_candidates:
        flickr_url = _fetch_loremflickr(query, menu_name)
        if flickr_url:
            return flickr_url, fallback

    # 4) Wikimediaは最後（ショーケース画像回避）
    for query in query_candidates[:2]:
        url = _fetch_wikimedia(query)
        if url:
            return url, fallback

    random_url = _fetch_themealdb_random()
    if random_url:
        return random_url, fallback

    return fallback, fallback
