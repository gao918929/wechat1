from datetime import date
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, str_strip_whitespace=True)


class Target(Model):
    kcal_min: float = Field(gt=0, le=5000)
    kcal_max: float = Field(gt=0, le=5000)
    protein_min: float = Field(ge=0, le=300)
    protein_max: float = Field(gt=0, le=300)
    carbs_min: float = Field(ge=0, le=600)
    carbs_max: float = Field(gt=0, le=600)
    fat_min: float = Field(ge=0, le=200)
    fat_max: float = Field(gt=0, le=200)

    @model_validator(mode="after")
    def ordered(self):
        for key in ("kcal", "protein", "carbs", "fat"):
            if getattr(self, key + "_min") > getattr(self, key + "_max"):
                raise ValueError(f"{key}: minimum cannot exceed maximum")
        return self


class Profile(Model):
    height_cm: float | None = Field(None, ge=50, le=250)
    weight_kg: float | None = Field(None, ge=5, le=400)
    body_fat_pct: float | None = Field(None, ge=2, le=75)
    age: int | None = Field(None, ge=1, le=110)
    sex: Literal["female", "male", "unspecified"] = "unspecified"
    goal: Literal["fat_loss", "muscle_gain", "maintenance", "stomach_friendly"] = "maintenance"
    tags: list[Literal["student", "family", "stomach_friendly", "chronic", "pregnant", "lactating", "child", "fitness", "vegetarian", "halal"]] = Field(default_factory=list, max_length=10)
    allergens: list[Literal["egg", "milk", "peanut", "tree_nut", "soy", "wheat", "fish", "shellfish", "sesame", "mango"]] = Field(default_factory=list, max_length=10)
    forbidden_ingredients: list[str] = Field(default_factory=list, max_length=60)
    dislikes: list[str] = Field(default_factory=list, max_length=40)
    likes: list[str] = Field(default_factory=list, max_length=40)
    # Explicit per-meal targets. Special populations require professionally set targets.
    meal_target: Target | None = None


class GroupCreate(Model):
    name: str = Field(min_length=1, max_length=60)
    budget_cents: int = Field(default=8000, ge=1, le=10000000)
    budget_mode: Literal["per_person", "total"] = "per_person"


class GroupSettings(Model):
    budget_cents: int = Field(ge=1, le=10000000)
    budget_mode: Literal["per_person", "total"]
    twin_visibility: Literal["owner", "selected", "all"] = "owner"
    twin_members: list[str] = Field(default_factory=list, max_length=30)


class InventoryInput(Model):
    ingredient_id: str = Field(min_length=1, max_length=80)
    grams: float = Field(gt=0, le=1000000)
    purchased_on: date = Field(default_factory=date.today)
    expires_on: date
    freshness: Literal["unknown", "fresh", "not_fresh"] = "unknown"
    estimated: bool = False
    version: int | None = Field(None, ge=1)

    @model_validator(mode="after")
    def dates(self):
        if self.expires_on < self.purchased_on:
            raise ValueError("Expiry precedes purchase date")
        if self.purchased_on > date.today():
            raise ValueError("Purchase date cannot be in the future")
        return self


class Consumption(Model):
    inventory_id: str
    grams: float = Field(gt=0, le=1000000)


class ConsumptionRequest(Model):
    request_id: str = Field(min_length=8, max_length=80)
    items: list[Consumption] = Field(min_length=1, max_length=100)


class ReceiptItem(Model):
    ingredient_id: str
    grams: float = Field(gt=0, le=1000000)
    line_cents: int | None = Field(None, ge=0, le=10000000)
    estimated: bool = False
    expires_on: date


class ReceiptConfirm(Model):
    request_id: str = Field(min_length=8, max_length=80)
    paid_cents: int = Field(ge=0, le=10000000)
    purchased_on: date = Field(default_factory=date.today)
    items: list[ReceiptItem] = Field(default_factory=list, max_length=100)
    draft_id: str | None = None
    actual_payment_confirmed: Literal[True]


class PlanRequest(Model):
    prompt: str = Field(min_length=2, max_length=3000)
    start_date: date = Field(default_factory=date.today)
    days: int = Field(default=7, ge=1, le=7)
    diners: list[str] = Field(min_length=1, max_length=20)
    budget_mode: Literal["per_person", "total"] = "per_person"
    budget_cents: int = Field(ge=1, le=10000000)
    # Only ordinary dislikes can be overridden, explicitly, by the plan creator.
    override_soft: bool = False
    request_id: str = Field(min_length=8, max_length=80)


class Portion(Model):
    ingredient_id: str
    grams: float = Field(gt=0, le=10000)


class Dish(Model):
    name: str = Field(min_length=1, max_length=100)
    ingredients: list[Portion] = Field(min_length=1, max_length=30)
    steps: list[str] = Field(min_length=1, max_length=15)
    # Empty means everyone. Amounts above are TOTAL dish weights, not per serving.
    suitable_for: list[str] = Field(default_factory=list, max_length=20)


class Day(Model):
    date: date
    dishes: list[Dish] = Field(min_length=1, max_length=8)


class Variant(Model):
    mode: Literal["health", "balanced", "budget"]
    title: str = Field(min_length=1, max_length=100)
    tradeoffs: list[str] = Field(default_factory=list, max_length=10)
    days: list[Day] = Field(min_length=1, max_length=7)


class PlanBundle(Model):
    variants: list[Variant] = Field(min_length=2, max_length=3)


class MealInput(Model):
    request_id: str = Field(min_length=8, max_length=80)
    context: Literal["home", "out"]
    eaten_on: date = Field(default_factory=date.today)
    # Portions are the current user's intake; household consumption is separate.
    items: list[Portion] = Field(min_length=1, max_length=40)
    consumption: list[Consumption] = Field(default_factory=list, max_length=100)
    estimated: bool = True
    draft_id: str | None = None


class Feedback(Model):
    action: Literal["rate", "favorite", "delete", "substitute", "select", "note"]
    job_id: str | None = None
    mode: Literal["health", "balanced", "budget"] | None = None
    rating: int | None = Field(None, ge=1, le=5)
    text: str = Field(default="", max_length=600)
    shared: bool = False


class TextInput(Model):
    text: str = Field(min_length=1, max_length=1500)


class LoginInput(Model):
    code: str = Field(min_length=1, max_length=300)
    name: str = Field(default="MealAgent user", min_length=1, max_length=60)


class DevLogin(Model):
    name: str = Field(min_length=1, max_length=60)
    key: str = Field(min_length=16, max_length=200)


class InviteInput(Model):
    code: str = Field(min_length=16, max_length=100)


class Selection(Model):
    mode: Literal["health", "balanced", "budget"]
