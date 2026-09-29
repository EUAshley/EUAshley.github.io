"""Data model.

Idea is the "content item": it carries one piece of content from idea to
performance. Everything platform-specific lives on Publication, and metrics are
time-series snapshots, so one idea can be published to several platforms and
measured repeatedly.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import JSON, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class Timestamped:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# --- Brands & categories -----------------------------------------------------

class Brand(Timestamped, Base):
    __tablename__ = "brands"
    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    categories: Mapped[list["Category"]] = relationship(back_populates="brand")


class Category(Timestamped, Base):
    __tablename__ = "categories"
    __table_args__ = (UniqueConstraint("brand_id", "name"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    brand_id: Mapped[int] = mapped_column(ForeignKey("brands.id"))
    name: Mapped[str] = mapped_column(String(120))
    parent_id: Mapped[Optional[int]] = mapped_column(ForeignKey("categories.id"))
    brand: Mapped[Brand] = relationship(back_populates="categories")


# --- Ideas (content items) ---------------------------------------------------

class Idea(Timestamped, Base):
    __tablename__ = "ideas"
    id: Mapped[int] = mapped_column(primary_key=True)
    brand_id: Mapped[int] = mapped_column(ForeignKey("brands.id"))
    category_id: Mapped[Optional[int]] = mapped_column(ForeignKey("categories.id"))
    title: Mapped[str] = mapped_column(String(200))
    problem_solved: Mapped[str] = mapped_column(Text, default="")
    benefit: Mapped[str] = mapped_column(Text, default="")  # the outcome the viewer gets
    target_audience: Mapped[str] = mapped_column(Text, default="")
    hook: Mapped[str] = mapped_column(Text, default="")
    solution_steps: Mapped[str] = mapped_column(Text, default="")  # one step per line
    tools: Mapped[str] = mapped_column(Text, default="")  # apps/products involved, comma-separated
    source: Mapped[str] = mapped_column(Text, default="")  # where the idea came from
    research_notes: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(40), default="idea", index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    brand: Mapped[Brand] = relationship()
    category: Mapped[Optional[Category]] = relationship()
    scores: Mapped[list["IdeaScore"]] = relationship(back_populates="idea", cascade="all, delete-orphan")
    history: Mapped[list["StatusChange"]] = relationship(
        back_populates="idea", cascade="all, delete-orphan", order_by="StatusChange.id"
    )
    scripts: Mapped[list["Script"]] = relationship(
        back_populates="idea", cascade="all, delete-orphan", order_by="Script.version"
    )
    learnings: Mapped[list["Learning"]] = relationship(back_populates="idea")
    offer_links: Mapped[list["OfferLink"]] = relationship(back_populates="idea", cascade="all, delete-orphan")

    @property
    def steps(self) -> list[str]:
        return [s.strip(" -•\t") for s in self.solution_steps.splitlines() if s.strip(" -•\t")]

    @property
    def tool_list(self) -> list[str]:
        return [t.strip() for t in self.tools.split(",") if t.strip()]

    @property
    def current_script(self) -> Optional["Script"]:
        current = [s for s in self.scripts if s.is_current]
        return current[-1] if current else None


class IdeaScore(Base):
    __tablename__ = "idea_scores"
    __table_args__ = (UniqueConstraint("idea_id", "criterion"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    idea_id: Mapped[int] = mapped_column(ForeignKey("ideas.id"))
    criterion: Mapped[str] = mapped_column(String(60))
    value: Mapped[int] = mapped_column(Integer)
    rationale: Mapped[str] = mapped_column(Text, default="")
    scored_by: Mapped[str] = mapped_column(String(40), default="human")  # human | ai | model
    scored_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    idea: Mapped[Idea] = relationship(back_populates="scores")


class StatusChange(Base):
    __tablename__ = "status_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    idea_id: Mapped[int] = mapped_column(ForeignKey("ideas.id"))
    from_status: Mapped[Optional[str]] = mapped_column(String(40))
    to_status: Mapped[str] = mapped_column(String(40))
    note: Mapped[str] = mapped_column(Text, default="")
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    idea: Mapped[Idea] = relationship(back_populates="history")


# --- Scripts & production packages ------------------------------------------

class Script(Timestamped, Base):
    __tablename__ = "scripts"
    id: Mapped[int] = mapped_column(primary_key=True)
    idea_id: Mapped[int] = mapped_column(ForeignKey("ideas.id"))
    version: Mapped[int] = mapped_column(Integer, default=1)
    is_current: Mapped[bool] = mapped_column(default=True)
    hook_type: Mapped[str] = mapped_column(String(60), default="")
    # [{key, label, start, end, voiceover, on_screen_text, visual}]
    sections: Mapped[list] = mapped_column(JSON, default=list)
    cta: Mapped[str] = mapped_column(Text, default="")
    target_seconds: Mapped[int] = mapped_column(Integer, default=0)
    generator: Mapped[str] = mapped_column(String(60), default="template")
    idea: Mapped[Idea] = relationship(back_populates="scripts")
    packages: Mapped[list["ProductionPackage"]] = relationship(
        back_populates="script", cascade="all, delete-orphan", order_by="ProductionPackage.id"
    )

    @property
    def voiceover(self) -> str:
        return "\n".join(s["voiceover"] for s in self.sections if s.get("voiceover"))

    @property
    def current_package(self) -> Optional["ProductionPackage"]:
        return self.packages[-1] if self.packages else None


class ProductionPackage(Timestamped, Base):
    __tablename__ = "production_packages"
    id: Mapped[int] = mapped_column(primary_key=True)
    script_id: Mapped[int] = mapped_column(ForeignKey("scripts.id"))
    title: Mapped[str] = mapped_column(String(200))
    opening_hook: Mapped[str] = mapped_column(Text, default="")
    voiceover: Mapped[str] = mapped_column(Text, default="")
    shot_list: Mapped[list] = mapped_column(JSON, default=list)  # [{shot, time, visual, on_screen_text}]
    recording_steps: Mapped[list] = mapped_column(JSON, default=list)
    on_screen_text: Mapped[list] = mapped_column(JSON, default=list)
    caption: Mapped[str] = mapped_column(Text, default="")
    cta: Mapped[str] = mapped_column(Text, default="")
    hashtags: Mapped[list] = mapped_column(JSON, default=list)
    keywords: Mapped[list] = mapped_column(JSON, default=list)
    cover_text: Mapped[str] = mapped_column(Text, default="")
    required_assets: Mapped[list] = mapped_column(JSON, default=list)
    monetization_notes: Mapped[list] = mapped_column(JSON, default=list)
    est_minutes: Mapped[int] = mapped_column(Integer, default=0)
    script: Mapped[Script] = relationship(back_populates="packages")
    approvals: Mapped[list["Approval"]] = relationship(
        back_populates="package", cascade="all, delete-orphan", order_by="Approval.id"
    )
    publications: Mapped[list["Publication"]] = relationship(back_populates="package")
    renders: Mapped[list["Render"]] = relationship(
        back_populates="package", cascade="all, delete-orphan", order_by="Render.id"
    )

    @property
    def latest_approval(self) -> Optional["Approval"]:
        return self.approvals[-1] if self.approvals else None

    @property
    def latest_render(self) -> Optional["Render"]:
        return self.renders[-1] if self.renders else None


class Render(Timestamped, Base):
    """A finished video produced by the auto-editor for a package."""
    __tablename__ = "renders"
    id: Mapped[int] = mapped_column(primary_key=True)
    package_id: Mapped[int] = mapped_column(ForeignKey("production_packages.id"))
    path: Mapped[str] = mapped_column(Text)  # relative to the project root
    cover_path: Mapped[str] = mapped_column(Text, default="")
    seconds: Mapped[float] = mapped_column(Float, default=0)
    clip_count: Mapped[int] = mapped_column(Integer, default=0)
    music: Mapped[str] = mapped_column(Text, default="")  # track file name, or "" for none
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    package: Mapped["ProductionPackage"] = relationship(back_populates="renders")


class Approval(Base):
    __tablename__ = "approvals"
    id: Mapped[int] = mapped_column(primary_key=True)
    package_id: Mapped[int] = mapped_column(ForeignKey("production_packages.id"))
    decision: Mapped[str] = mapped_column(String(40))  # approved | changes_requested | rejected
    notes: Mapped[str] = mapped_column(Text, default="")
    reviewer: Mapped[str] = mapped_column(String(80), default="owner")
    decided_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    package: Mapped[ProductionPackage] = relationship(back_populates="approvals")


# --- Publishing & performance -------------------------------------------------

class Publication(Timestamped, Base):
    __tablename__ = "publications"
    id: Mapped[int] = mapped_column(primary_key=True)
    package_id: Mapped[int] = mapped_column(ForeignKey("production_packages.id"))
    platform: Mapped[str] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(40), default="queued")  # queued | published | cancelled
    scheduled_for: Mapped[Optional[date]] = mapped_column(Date)
    published_at: Mapped[Optional[date]] = mapped_column(Date)
    url: Mapped[str] = mapped_column(Text, default="")
    tracking_link: Mapped[str] = mapped_column(Text, default="")  # manual link (e.g. link-in-bio page)
    # Short unique code per post, embedded in every offer link so revenue can be attributed.
    tracking_code: Mapped[Optional[str]] = mapped_column(String(40), unique=True)
    tracking_links: Mapped[Optional[list]] = mapped_column(JSON)  # [{offer_id, offer, url}]
    package: Mapped[ProductionPackage] = relationship(back_populates="publications")
    snapshots: Mapped[list["PerformanceSnapshot"]] = relationship(
        back_populates="publication", cascade="all, delete-orphan", order_by="PerformanceSnapshot.captured_at"
    )

    @property
    def idea(self) -> Idea:
        return self.package.script.idea

    @property
    def latest_snapshot(self) -> Optional["PerformanceSnapshot"]:
        return self.snapshots[-1] if self.snapshots else None


class PerformanceSnapshot(Base):
    __tablename__ = "performance_snapshots"
    id: Mapped[int] = mapped_column(primary_key=True)
    publication_id: Mapped[int] = mapped_column(ForeignKey("publications.id"))
    captured_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    views: Mapped[int] = mapped_column(Integer, default=0)
    avg_watch_seconds: Mapped[Optional[float]] = mapped_column(Float)
    retention_pct: Mapped[Optional[float]] = mapped_column(Float)
    likes: Mapped[int] = mapped_column(Integer, default=0)
    comments: Mapped[int] = mapped_column(Integer, default=0)
    shares: Mapped[int] = mapped_column(Integer, default=0)
    saves: Mapped[int] = mapped_column(Integer, default=0)
    follows: Mapped[int] = mapped_column(Integer, default=0)
    link_clicks: Mapped[int] = mapped_column(Integer, default=0)
    source: Mapped[str] = mapped_column(String(40), default="manual")  # manual | csv | api
    publication: Mapped[Publication] = relationship(back_populates="snapshots")


# --- Monetization --------------------------------------------------------------

OFFER_TYPES = [
    "affiliate", "referral", "ad_revenue", "sponsorship", "digital_product",
    "shortcut_pack", "template", "newsletter", "paid_guide", "membership",
    "lead_gen", "own_product",
]


class Offer(Timestamped, Base):
    __tablename__ = "offers"
    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(200))
    url: Mapped[str] = mapped_column(Text, default="")
    program: Mapped[str] = mapped_column(String(200), default="")  # e.g. "Amazon Associates"
    terms: Mapped[str] = mapped_column(Text, default="")  # commission, cookie window...
    # Optional per-video link pattern, e.g. "https://amzn.to/x?tag=me-20&ascsubtag={code}".
    # Placeholders: {code} {platform} {idea_id}. Blank = offer url + UTM parameters.
    link_template: Mapped[Optional[str]] = mapped_column(Text, default="")
    active: Mapped[bool] = mapped_column(default=True)
    links: Mapped[list["OfferLink"]] = relationship(back_populates="offer", cascade="all, delete-orphan")
    revenue_events: Mapped[list["RevenueEvent"]] = relationship(back_populates="offer")


class OfferLink(Base):
    """Associates an offer with an idea or a whole category."""
    __tablename__ = "offer_links"
    id: Mapped[int] = mapped_column(primary_key=True)
    offer_id: Mapped[int] = mapped_column(ForeignKey("offers.id"))
    idea_id: Mapped[Optional[int]] = mapped_column(ForeignKey("ideas.id"))
    category_id: Mapped[Optional[int]] = mapped_column(ForeignKey("categories.id"))
    role: Mapped[str] = mapped_column(String(40), default="primary")  # primary | secondary
    offer: Mapped[Offer] = relationship(back_populates="links")
    idea: Mapped[Optional[Idea]] = relationship(back_populates="offer_links")
    category: Mapped[Optional[Category]] = relationship()


class RevenueEvent(Timestamped, Base):
    __tablename__ = "revenue_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    offer_id: Mapped[int] = mapped_column(ForeignKey("offers.id"))
    publication_id: Mapped[Optional[int]] = mapped_column(ForeignKey("publications.id"))
    date: Mapped[date] = mapped_column(Date)
    clicks: Mapped[int] = mapped_column(Integer, default=0)
    conversions: Mapped[int] = mapped_column(Integer, default=0)
    revenue_cents: Mapped[int] = mapped_column(Integer, default=0)
    source: Mapped[str] = mapped_column(String(40), default="manual")
    tracking_code: Mapped[Optional[str]] = mapped_column(String(40))
    notes: Mapped[str] = mapped_column(Text, default="")
    offer: Mapped[Offer] = relationship(back_populates="revenue_events")
    publication: Mapped[Optional[Publication]] = relationship()


# --- Learnings -----------------------------------------------------------------

class Learning(Timestamped, Base):
    __tablename__ = "learnings"
    id: Mapped[int] = mapped_column(primary_key=True)
    idea_id: Mapped[Optional[int]] = mapped_column(ForeignKey("ideas.id"))
    publication_id: Mapped[Optional[int]] = mapped_column(ForeignKey("publications.id"))
    category_id: Mapped[Optional[int]] = mapped_column(ForeignKey("categories.id"))
    text: Mapped[str] = mapped_column(Text)
    tags: Mapped[str] = mapped_column(Text, default="")
    idea: Mapped[Optional[Idea]] = relationship(back_populates="learnings")
