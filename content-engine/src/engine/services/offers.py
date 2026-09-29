from __future__ import annotations

from datetime import date

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..models import OFFER_TYPES, Idea, Offer, OfferLink, RevenueEvent


def create_offer(session: Session, *, type: str, name: str, url: str = "", program: str = "",
                 terms: str = "") -> Offer:
    if type not in OFFER_TYPES:
        raise ValueError(f"Unknown offer type '{type}'. Use one of: {', '.join(OFFER_TYPES)}")
    offer = Offer(type=type, name=name, url=url, program=program, terms=terms)
    session.add(offer)
    session.flush()
    return offer


def link_offer(session: Session, offer: Offer, *, idea: Idea | None = None, category_id: int | None = None,
               role: str = "primary") -> OfferLink:
    if idea is None and category_id is None:
        raise ValueError("Link an offer to an idea or a category")
    link = OfferLink(offer=offer, idea=idea, category_id=category_id, role=role)
    session.add(link)
    session.flush()
    return link


def offers_for_idea(session: Session, idea: Idea) -> list[Offer]:
    """Offers linked directly to the idea, plus offers linked to its category."""
    conds = [OfferLink.idea_id == idea.id]
    if idea.category_id:
        conds.append(OfferLink.category_id == idea.category_id)
    stmt = (select(Offer).join(OfferLink).where(or_(*conds), Offer.active.is_(True))
            .order_by(OfferLink.role, Offer.id).distinct())
    return list(session.scalars(stmt))


def record_revenue(session: Session, offer: Offer, *, on: date, clicks: int = 0, conversions: int = 0,
                   revenue_cents: int = 0, publication_id: int | None = None, source: str = "manual",
                   notes: str = "") -> RevenueEvent:
    event = RevenueEvent(offer=offer, date=on, clicks=clicks, conversions=conversions,
                         revenue_cents=revenue_cents, publication_id=publication_id, source=source, notes=notes)
    session.add(event)
    session.flush()
    return event
