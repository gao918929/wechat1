"""ORM models: users, groups, inventory, expenses, plans, meal records, twins."""
from __future__ import annotations

import secrets
from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now()


def new_invite_code() -> str:
    return secrets.token_hex(3).upper()


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    openid: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    nickname: Mapped[str] = mapped_column(String(64), default="")
    sex: Mapped[str] = mapped_column(String(8), default="")  # male / female / ""
    age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height_cm: Mapped[float | None] = mapped_column(Float, nullable=True)
    weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    body_fat_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    activity_level: Mapped[str] = mapped_column(String(16), default="light")
    goal: Mapped[str] = mapped_column(String(32), default="maintain")  # fat_loss / muscle_gain / maintain / stomach
    dietary_groups: Mapped[list] = mapped_column(JSON, default=list)  # ids from 02_dietary_group_models
    allergens: Mapped[list] = mapped_column(JSON, default=list)  # hard constraints
    avoidances: Mapped[list] = mapped_column(JSON, default=list)  # soft constraints (taste)
    likes: Mapped[list] = mapped_column(JSON, default=list)
    max_spicy: Mapped[int] = mapped_column(Integer, default=3)
    city: Mapped[str] = mapped_column(String(32), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    memberships: Mapped[list[Membership]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Group(Base):
    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(16), default="household")  # household / dorm / personal
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    invite_code: Mapped[str] = mapped_column(String(16), unique=True, default=new_invite_code)
    budget_mode: Mapped[str] = mapped_column(String(16), default="per_person")  # per_person / total
    budget_amount: Mapped[float] = mapped_column(Float, default=0.0)  # weekly, CNY
    twin_visibility: Mapped[str] = mapped_column(String(16), default="all")  # owner / selected / all
    twin_visible_member_ids: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    memberships: Mapped[list[Membership]] = relationship(back_populates="group", cascade="all, delete-orphan")


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("group_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(16), default="member")  # admin / member
    joined_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    group: Mapped[Group] = relationship(back_populates="memberships")
    user: Mapped[User] = relationship(back_populates="memberships")


class InventoryItem(Base):
    __tablename__ = "inventory_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"), index=True)
    name: Mapped[str] = mapped_column(String(64))
    category: Mapped[str] = mapped_column(String(32), default="")  # wiki section
    quantity: Mapped[float | None] = mapped_column(Float, nullable=True)  # pieces
    weight_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_estimated: Mapped[bool] = mapped_column(Boolean, default=False)
    estimate_note: Mapped[str] = mapped_column(String(128), default="")
    purchase_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    added_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    shelf_life_days: Mapped[int | None] = mapped_column(Integer, nullable=True)  # user override
    freshness: Mapped[str] = mapped_column(String(16), default="fresh")  # fresh / not_fresh (visual)
    source: Mapped[str] = mapped_column(String(16), default="manual")  # photo / receipt / manual / chat / plan
    price_paid: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="active")  # active / consumed / discarded


class Expense(Base):
    __tablename__ = "expenses"

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    total_amount: Mapped[float] = mapped_column(Float)  # actual amount paid (ledger, never altered)
    paid_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    source: Mapped[str] = mapped_column(String(16), default="manual")  # receipt / label / manual
    merchant: Mapped[str] = mapped_column(String(64), default="")
    upload_id: Mapped[int | None] = mapped_column(ForeignKey("uploads.id"), nullable=True)
    note: Mapped[str] = mapped_column(String(128), default="")

    items: Mapped[list[ExpenseItem]] = relationship(back_populates="expense", cascade="all, delete-orphan")


class ExpenseItem(Base):
    __tablename__ = "expense_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    expense_id: Mapped[int] = mapped_column(ForeignKey("expenses.id"), index=True)
    name: Mapped[str] = mapped_column(String(64))
    category: Mapped[str] = mapped_column(String(32), default="other")
    quantity: Mapped[float | None] = mapped_column(Float, nullable=True)
    weight_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit_price: Mapped[float | None] = mapped_column(Float, nullable=True)  # CNY/kg
    amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    estimated: Mapped[bool] = mapped_column(Boolean, default=False)

    expense: Mapped[Expense] = relationship(back_populates="items")


class PriceRecord(Base):
    """Price memory: actual purchase prices recognised from receipts / labels."""

    __tablename__ = "price_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    ingredient: Mapped[str] = mapped_column(String(64), index=True)
    unit_price: Mapped[float] = mapped_column(Float)  # CNY/kg
    source: Mapped[str] = mapped_column(String(16), default="receipt")
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Upload(Base):
    __tablename__ = "uploads"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    group_id: Mapped[int | None] = mapped_column(ForeignKey("groups.id"), nullable=True)
    path: Mapped[str] = mapped_column(String(256))
    mime: Mapped[str] = mapped_column(String(64), default="image/jpeg")
    sensitive: Mapped[bool] = mapped_column(Boolean, default=False)  # receipts
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Recognition(Base):
    """An item-list card produced by image recognition, editable before confirmation."""

    __tablename__ = "recognitions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # ingredients / receipt / meal
    upload_id: Mapped[int | None] = mapped_column(ForeignKey("uploads.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending / confirmed / failed
    card: Mapped[dict] = mapped_column(JSON, default=dict)
    raw: Mapped[dict] = mapped_column(JSON, default=dict)
    message: Mapped[str] = mapped_column(String(256), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class MealPlan(Base):
    __tablename__ = "meal_plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"), index=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    instruction: Mapped[str] = mapped_column(Text, default="")
    options: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending / running / done / failed
    events: Mapped[list] = mapped_column(JSON, default=list)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    chosen_variant: Mapped[str] = mapped_column(String(16), default="")
    shopping_state: Mapped[dict] = mapped_column(JSON, default=dict)  # {variant: {item_name: checked}}
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class PlanCache(Base):
    __tablename__ = "plan_cache"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    result: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class MealRecord(Base):
    """Actual intake: from post-meal photo review or from marking a planned meal as eaten."""

    __tablename__ = "meal_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"), index=True)
    eaten_on: Mapped[date] = mapped_column(Date, default=date.today)
    meal: Mapped[str] = mapped_column(String(16), default="dinner")
    context: Mapped[str] = mapped_column(String(8), default="home")  # home / out
    dishes: Mapped[list] = mapped_column(JSON, default=list)
    nutrition: Mapped[dict] = mapped_column(JSON, default=dict)
    plan_id: Mapped[int | None] = mapped_column(ForeignKey("meal_plans.id"), nullable=True)
    upload_id: Mapped[int | None] = mapped_column(ForeignKey("uploads.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Twin(Base):
    """Dietary digital twin for a user (owner_type=user) or a group (owner_type=group)."""

    __tablename__ = "twins"
    __table_args__ = (UniqueConstraint("owner_type", "owner_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_type: Mapped[str] = mapped_column(String(8))
    owner_id: Mapped[int] = mapped_column(Integer, index=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    version: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class FeedbackEvent(Base):
    __tablename__ = "feedback_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    group_id: Mapped[int | None] = mapped_column(ForeignKey("groups.id"), nullable=True)
    kind: Mapped[str] = mapped_column(String(32))  # rating / favorite / delete / substitute / correction / choose_variant / meal / purchase
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    processed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(64))
    body: Mapped[str] = mapped_column(String(256), default="")
    link: Mapped[str] = mapped_column(String(128), default="")
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
