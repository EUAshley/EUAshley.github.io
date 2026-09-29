"""Per-video tracking links and revenue attribution.

Each publication gets a short code (e.g. `dbs12tt3`). Every offer linked to the
idea gets a link that carries that code, either through the offer's
`link_template` (most affiliate programs have a sub-ID parameter) or, by
default, as UTM parameters. Affiliate/revenue reports that include the code
can then be imported and attributed to the exact video.
"""
from __future__ import annotations

import csv
import re
from datetime import date, datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Offer, Publication
from . import offers as offer_service

PLATFORM_ABBR = {"tiktok": "tt", "instagram_reels": "ig", "youtube_shorts": "yt", "facebook_reels": "fb"}


def make_code(pub: Publication) -> str:
    brand = pub.idea.brand.slug
    prefix = "".join(w[0] for w in re.split(r"[-_\s]+", brand) if w)[:4]
    abbr = PLATFORM_ABBR.get(pub.platform, re.sub(r"[^a-z]", "", pub.platform.lower())[:2])
    return f"{prefix}{pub.idea.id}{abbr}{pub.id}"


def build_link(offer: Offer, code: str, pub: Publication) -> str:
    if offer.link_template:
        return offer.link_template.format(code=code, platform=pub.platform, idea_id=pub.idea.id)
    if not offer.url:
        return ""
    parts = urlsplit(offer.url)
    query = dict(parse_qsl(parts.query))
    query.update({"utm_source": pub.platform, "utm_medium": "shortform", "utm_campaign": code})
    return urlunsplit(parts._replace(query=urlencode(query)))


def assign(session: Session, pub: Publication) -> Publication:
    """Give a publication its code and (re)build its per-offer links."""
    if not pub.tracking_code:
        pub.tracking_code = make_code(pub)
    pub.tracking_links = [
        {"offer_id": o.id, "offer": o.name, "type": o.type, "url": build_link(o, pub.tracking_code, pub)}
        for o in offer_service.offers_for_idea(session, pub.idea)
    ]
    session.flush()
    return pub


def refresh_for_idea(session: Session, idea) -> None:
    """Rebuild links for an idea's live publications (e.g. after linking a new offer)."""
    for script in idea.scripts:
        for package in script.packages:
            for pub in package.publications:
                if pub.status != "cancelled":
                    assign(session, pub)


# --- Revenue report import -----------------------------------------------------

CODE_COLUMNS = ["tracking_code", "code", "subid", "sub_id", "sub id", "ascsubtag", "tracking id",
                "utm_campaign", "campaign"]
DATE_COLUMNS = ["date", "day", "order date", "event date"]
CLICK_COLUMNS = ["clicks", "click"]
CONVERSION_COLUMNS = ["conversions", "orders", "items ordered", "sales", "ordered items"]
REVENUE_COLUMNS = ["revenue", "earnings", "commission", "amount", "payout", "total earnings", "ad fees"]
OFFER_COLUMNS = ["offer", "offer_id", "program"]


def _pick(row: dict, names: list[str]) -> str:
    for n in names:
        if row.get(n):
            return row[n]
    return ""


def _money_cents(v: str) -> int:
    v = v.replace("$", "").replace(",", "").strip()
    return round(float(v) * 100) if v else 0


def _parse_date(v: str) -> date:
    v = v.strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%b %d, %Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(v, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unrecognized date '{v}'")


def find_offer(session: Session, value: str) -> Offer | None:
    if not value:
        return None
    if value.isdigit():
        return session.get(Offer, int(value))
    return session.scalar(select(Offer).where(func.lower(Offer.name) == value.lower()))


def import_revenue_csv(session: Session, path: str | Path, default_offer: Offer | None = None) -> tuple[int, list[str]]:
    """Import an affiliate/revenue report. Each row needs a tracking code (or an
    offer for unattributed revenue). Column names are matched case-insensitively
    against common report headers."""
    imported, errors = 0, []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for n, raw in enumerate(csv.DictReader(f), start=2):
            row = {k.strip().lower(): (v or "").strip() for k, v in raw.items() if k}
            code = _pick(row, CODE_COLUMNS)
            pub = session.scalar(select(Publication).where(Publication.tracking_code == code)) if code else None
            offer = find_offer(session, _pick(row, OFFER_COLUMNS)) or default_offer
            if offer is None and pub is not None and pub.tracking_links and len(pub.tracking_links) == 1:
                offer = session.get(Offer, pub.tracking_links[0]["offer_id"])
            if offer is None:
                errors.append(f"line {n}: can't tell which offer (add an 'offer' column or use --offer)")
                continue
            if code and pub is None:
                errors.append(f"line {n}: unknown tracking code '{code}' (recorded without a video)")
            try:
                offer_service.record_revenue(
                    session, offer,
                    on=_parse_date(_pick(row, DATE_COLUMNS)) if _pick(row, DATE_COLUMNS) else date.today(),
                    clicks=int(float(_pick(row, CLICK_COLUMNS) or 0)),
                    conversions=int(float(_pick(row, CONVERSION_COLUMNS) or 0)),
                    revenue_cents=_money_cents(_pick(row, REVENUE_COLUMNS)),
                    publication_id=pub.id if pub else None, source="csv", tracking_code=code or None,
                )
                imported += 1
            except ValueError as e:
                errors.append(f"line {n}: {e}")
    return imported, errors
