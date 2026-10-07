"""Split We Work Remotely titles of the form 'Company: Role'."""

from __future__ import annotations

from opp_finder_v2.models import RawListing


def postprocess(listing: RawListing) -> RawListing:
    title = (listing.title or "").strip()
    if ":" not in title:
        return listing
    company, role = title.split(":", 1)
    company = company.strip().rstrip(".")
    role = role.strip()
    if company and role:
        listing.company = company
        listing.title = role
    return listing
