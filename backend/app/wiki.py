"""LLM Wiki loader.

The knowledge base is plain Markdown so it stays human-maintainable; this module parses its
tables and ``- key: value`` lists into typed records, and assembles excerpts as LLM context.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from .config import settings

NUTRIENT_KEYS = ("kcal", "protein", "fat", "carb", "fiber", "vc", "ca", "fe", "na")

SECTION_LABELS = {
    "vegetables": "蔬菜",
    "meat_eggs": "肉蛋",
    "seafood": "水产",
    "staples": "主食干货",
    "soy_dairy": "豆制品乳品",
    "seasonings": "调味品",
}
# Order used to sort shopping lists by supermarket area
SECTION_ORDER = ["vegetables", "meat_eggs", "seafood", "soy_dairy", "staples", "seasonings"]


def _none(v: str) -> str | None:
    v = v.strip()
    return None if v in ("", "-") else v


def _float(v: str) -> float | None:
    v = _none(v) if isinstance(v, str) else v
    if v is None:
        return None
    try:
        return float(v)
    except ValueError:
        return None


def _split(v: str | None, sep: str = "/") -> list[str]:
    v = _none(v or "")
    if v is None:
        return []
    return [p.strip() for p in re.split(rf"[{re.escape(sep)},，、]", v) if p.strip()]


def parse_tables(text: str) -> list[list[dict[str, str]]]:
    """Return every Markdown table in ``text`` as a list of row dicts keyed by header."""
    tables: list[list[dict[str, str]]] = []
    block: list[str] = []
    for line in text.splitlines() + [""]:
        if line.strip().startswith("|"):
            block.append(line.strip())
            continue
        if len(block) >= 2:
            header = [c.strip() for c in block[0].strip("|").split("|")]
            rows = []
            for row in block[2:]:
                cells = [c.strip() for c in row.strip("|").split("|")]
                cells += [""] * (len(header) - len(cells))
                rows.append(dict(zip(header, cells)))
            tables.append(rows)
        block = []
    return tables


def parse_bullets(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        m = re.match(r"^\s*-\s*([A-Za-z_][\w]*)\s*:\s*(.*)$", line)
        if m:
            out[m.group(1)] = m.group(2).strip()
    return out


@dataclass
class Ingredient:
    name: str
    en: str
    aliases: list[str]
    section: str
    shelf: str
    shelf_days: int | None
    nutrition: dict[str, float]
    price_min: float | None
    price_max: float | None
    piece_g: float | None
    piece_cm: float | None
    allergens: set[str]
    tags: set[str]
    source: str

    @property
    def price_mid(self) -> float | None:
        if self.price_min is None or self.price_max is None:
            return self.price_min or self.price_max
        return round((self.price_min + self.price_max) / 2, 2)

    @property
    def is_pantry(self) -> bool:
        return "pantry" in self.tags

    @property
    def labels(self) -> set[str]:
        """Tags and allergen keys together (used for constraint matching)."""
        return self.tags | self.allergens

    def brief(self) -> dict:
        return {
            "name": self.name, "en": self.en, "section": self.section,
            "kcal": self.nutrition.get("kcal"), "protein": self.nutrition.get("protein"),
            "price_mid": self.price_mid, "allergens": sorted(self.allergens), "tags": sorted(self.tags),
        }


@dataclass
class ShelfCategory:
    key: str
    name: str
    shelf_days: int
    near_expiry_days: int
    storage: str


@dataclass
class DietModel:
    id: str
    name: str
    params: dict[str, str]
    text: str
    file: str

    def num(self, key: str, default: float | None = None) -> float | None:
        v = _float(self.params.get(key, ""))
        return default if v is None else v

    def tags(self, key: str) -> set[str]:
        return set(_split(self.params.get(key, ""), ","))

    def flag(self, key: str) -> bool:
        return self.params.get(key, "").strip().lower() in ("true", "yes", "1")


@dataclass
class DishTemplate:
    name: str
    en: str
    kind: str
    meals: list[str]
    tags: set[str]
    spicy: int
    difficulty: str
    minutes: int
    ingredients: list[tuple[str, float]]
    steps: str
    source: str

    def to_dict(self) -> dict:
        return {
            "name": self.name, "en": self.en, "kind": self.kind, "meals": self.meals,
            "tags": sorted(self.tags), "spicy": self.spicy, "difficulty": self.difficulty,
            "minutes": self.minutes, "steps": self.steps, "source": self.source,
            "ingredients": [{"name": n, "grams": g} for n, g in self.ingredients],
        }


@dataclass
class ReferenceObject:
    key: str
    name: str
    size_cm: float
    weight_g: float | None


@dataclass
class Wiki:
    root: Path
    ingredients: dict[str, Ingredient] = field(default_factory=dict)
    alias_map: dict[str, str] = field(default_factory=dict)
    shelf: dict[str, ShelfCategory] = field(default_factory=dict)
    diet_models: dict[str, DietModel] = field(default_factory=dict)
    dishes: dict[str, DishTemplate] = field(default_factory=dict)
    reference_objects: dict[str, ReferenceObject] = field(default_factory=dict)
    default_targets: dict[str, dict] = field(default_factory=dict)
    activity_factors: dict[str, float] = field(default_factory=dict)
    meal_shares: dict[str, float] = field(default_factory=dict)

    # ------------------------------------------------------------------ loading
    @classmethod
    def load(cls, root: Path) -> Wiki:
        wiki = cls(root=root)
        wiki._load_ingredients()
        wiki._load_rules()
        wiki._load_diet_models()
        wiki._load_dishes()
        return wiki

    def _read(self, rel: str) -> str:
        p = self.root / rel
        return p.read_text(encoding="utf-8") if p.is_file() else ""

    def _load_ingredients(self) -> None:
        for path in sorted((self.root / "01_ingredients").glob("*.md")):
            rel = path.relative_to(self.root).as_posix()
            for table in parse_tables(path.read_text(encoding="utf-8")):
                for row in table:
                    if not row.get("name"):
                        continue
                    shelf_days = _float(row.get("shelf_days", ""))
                    ing = Ingredient(
                        name=row["name"],
                        en=row.get("en", ""),
                        aliases=_split(row.get("aliases")),
                        section=row.get("section", "") or "staples",
                        shelf=row.get("shelf", "") or "dry",
                        shelf_days=int(shelf_days) if shelf_days else None,
                        nutrition={k: _float(row.get(k, "")) or 0.0 for k in NUTRIENT_KEYS},
                        price_min=_float(row.get("price_min", "")),
                        price_max=_float(row.get("price_max", "")),
                        piece_g=_float(row.get("piece_g", "")),
                        piece_cm=_float(row.get("piece_cm", "")),
                        allergens=set(_split(row.get("allergens"))),
                        tags=set(_split(row.get("tags"))),
                        source=rel,
                    )
                    self.ingredients[ing.name] = ing
        for ing in self.ingredients.values():
            self.alias_map[ing.name] = ing.name
            self.alias_map[ing.en.lower()] = ing.name
            for a in ing.aliases:
                self.alias_map.setdefault(a, ing.name)

    def _load_rules(self) -> None:
        for table in parse_tables(self._read("03_rules/shelf_life.md")):
            for row in table:
                if row.get("key"):
                    self.shelf[row["key"]] = ShelfCategory(
                        key=row["key"], name=row.get("name", ""),
                        shelf_days=int(_float(row.get("shelf_days", "")) or 7),
                        near_expiry_days=int(_float(row.get("near_expiry_days", "")) or 1),
                        storage=row.get("storage", ""),
                    )
        for table in parse_tables(self._read("03_rules/portions.md")):
            for row in table:
                if row.get("key") and _float(row.get("size_cm", "")):
                    self.reference_objects[row["key"]] = ReferenceObject(
                        key=row["key"], name=row.get("name", ""),
                        size_cm=float(row["size_cm"]), weight_g=_float(row.get("weight_g", "")),
                    )
        for table in parse_tables(self._read("03_rules/nutrition_targets.md")):
            if not table:
                continue
            cols = set(table[0])
            for row in table:
                if "sex" in cols:
                    self.default_targets[row["key"]] = {
                        "kcal": _float(row["kcal"]), "protein_g": _float(row["protein_g"])}
                elif "factor" in cols:
                    self.activity_factors[row["key"]] = _float(row["factor"]) or 1.375
                elif "share" in cols:
                    self.meal_shares[row["meal"]] = _float(row["share"]) or 0.3

    def _load_diet_models(self) -> None:
        for path in sorted((self.root / "02_dietary_group_models").glob("*.md")):
            text = path.read_text(encoding="utf-8")
            m = re.search(r"##\s*Parameters\s*\n(.*?)(?=\n##\s|\Z)", text, re.S)
            params = parse_bullets(m.group(1)) if m else {}
            if "id" not in params:
                continue
            self.diet_models[params["id"]] = DietModel(
                id=params["id"], name=params.get("name", params["id"]), params=params, text=text,
                file=path.relative_to(self.root).as_posix(),
            )

    def _load_dishes(self) -> None:
        for path in sorted((self.root / "04_dish_templates").glob("*.md")):
            rel = path.relative_to(self.root).as_posix()
            text = path.read_text(encoding="utf-8")
            for chunk in re.split(r"\n(?=## )", text):
                if not chunk.startswith("## "):
                    continue
                name = chunk.splitlines()[0][3:].strip()
                b = parse_bullets(chunk)
                ingredients = []
                for part in _split(b.get("ingredients"), ","):
                    mm = re.match(r"^(.+?)\s+([\d.]+)$", part.strip())
                    if mm:
                        ingredients.append((mm.group(1).strip(), float(mm.group(2))))
                self.dishes[name] = DishTemplate(
                    name=name, en=b.get("en", ""), kind=b.get("kind", "main"),
                    meals=_split(b.get("meals"), ",") or ["lunch", "dinner"],
                    tags=set(_split(b.get("tags"), ",")), spicy=int(_float(b.get("spicy", "0")) or 0),
                    difficulty=b.get("difficulty", "easy"), minutes=int(_float(b.get("minutes", "20")) or 20),
                    ingredients=ingredients, steps=b.get("steps", ""), source=rel,
                )

    # ------------------------------------------------------------------ lookup
    def resolve(self, name: str) -> str | None:
        """Map a free-text ingredient name (alias / English / fuzzy) to its canonical wiki name."""
        if not name:
            return None
        key = name.strip()
        if key in self.alias_map:
            return self.alias_map[key]
        low = key.lower()
        if low in self.alias_map:
            return self.alias_map[low]
        # fuzzy: the longest known name contained in the text, or the text contained in a name
        best = None
        for alias, canon in self.alias_map.items():
            if len(alias) >= 1 and alias and alias in key and (best is None or len(alias) > len(best[0])):
                best = (alias, canon)
        if best and len(best[0]) >= 2:
            return best[1]
        for alias, canon in self.alias_map.items():
            if len(key) >= 2 and key in alias:
                return canon
        return best[1] if best else None

    def ingredient(self, name: str) -> Ingredient | None:
        canon = self.resolve(name)
        return self.ingredients.get(canon) if canon else None

    def find_in_text(self, text: str) -> list[tuple[str, int, int]]:
        """Longest-match scan for ingredient mentions: [(canonical, start, end)]."""
        names = sorted((a for a in self.alias_map if a and not a.isascii()), key=len, reverse=True)
        found, taken = [], [False] * len(text)
        for alias in names:
            for m in re.finditer(re.escape(alias), text):
                if any(taken[m.start():m.end()]):
                    continue
                for i in range(m.start(), m.end()):
                    taken[i] = True
                found.append((self.alias_map[alias], m.start(), m.end()))
        return sorted(found, key=lambda x: x[1])

    def shelf_for(self, ing: Ingredient | None) -> tuple[int, int]:
        """(shelf_days, near_expiry_days) for an ingredient."""
        if ing is None:
            return 7, 2
        cat = self.shelf.get(ing.shelf) or ShelfCategory("x", "", 7, 2, "")
        return (ing.shelf_days or cat.shelf_days), cat.near_expiry_days

    # ------------------------------------------------------------------ LLM context
    def file_text(self, rel: str) -> str:
        return self._read(rel)

    def context(self, diet_ids=(), rules=(), ingredient_names=(), max_ingredients: int = 80) -> str:
        """Assemble relevant knowledge-base excerpts to inject into an agent prompt."""
        parts = []
        for rid in rules:
            t = self._read(f"03_rules/{rid}.md")
            if t:
                parts.append(f"<!-- 03_rules/{rid}.md -->\n{t.strip()}")
        for did in diet_ids:
            dm = self.diet_models.get(did)
            if dm:
                parts.append(f"<!-- {dm.file} -->\n{dm.text.strip()}")
        names = [n for n in dict.fromkeys(ingredient_names) if n in self.ingredients][:max_ingredients]
        if names:
            rows = ["| 食材 | 分区 | kcal | 蛋白质 | 脂肪 | 碳水 | 参考价(元/kg) | 过敏原 | 标签 |", "|---|---|---|---|---|---|---|---|---|"]
            for n in names:
                i = self.ingredients[n]
                rows.append(
                    f"| {i.name} | {SECTION_LABELS.get(i.section, i.section)} | {i.nutrition['kcal']:g} | {i.nutrition['protein']:g} "
                    f"| {i.nutrition['fat']:g} | {i.nutrition['carb']:g} | {i.price_mid or '-'} | {'/'.join(sorted(i.allergens)) or '-'} "
                    f"| {'/'.join(sorted(i.tags)) or '-'} |")
            parts.append("<!-- 01_ingredients (excerpt, per 100 g) -->\n" + "\n".join(rows))
        return "\n\n".join(parts)

    def sources_text(self) -> str:
        t = self._read("00_index.md")
        m = re.search(r"## 数据来源.*", t, re.S)
        return m.group(0).strip() if m else ""


@lru_cache(maxsize=1)
def get_wiki() -> Wiki:
    return Wiki.load(settings.wiki_dir)
