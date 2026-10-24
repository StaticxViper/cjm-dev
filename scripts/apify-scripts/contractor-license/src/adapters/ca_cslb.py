"""California CSLB license master file.

Verified 2026-10-24: the public data portal serves MasterLicenseData.csv
without a CAPTCHA at the ashx URL below. The file is renewed and renewable
licenses only. Cancelled, revoked, and expired-nonrenewable licenses are
omitted, so a miss is not proof that a license never existed. The Instant
License Check form is not used.
"""

from __future__ import annotations

try:
    from .base import (
        csv_dicts,
        found_row,
        join_address,
        outcome,
        record_matches,
        status_row,
        take_match,
        transport_row,
    )
except ImportError:
    from adapters.base import (
        csv_dicts,
        found_row,
        join_address,
        outcome,
        record_matches,
        status_row,
        take_match,
        transport_row,
    )


PORTAL_URL = "https://www.cslb.ca.gov/onlineservices/dataportal/ContractorList"
CSV_URL = (
    "https://www.cslb.ca.gov/OnlineServices/DataPortal/DownLoadFile.ashx"
    "?fName=MasterLicenseData&type=C"
)

_MESSAGES = {
    "captcha": "California CSLB returned a challenge page. This adapter does not bypass it.",
}


def _bond(row):
    parts = []
    for label, company_key, amount_key in (
        ("Contractor", "CBSuretyCompany", "CBAmount"),
        ("Worker", "WBSuretyCompany", "WBAmount"),
        ("Disciplinary", "DBSuretyCompany", "DBAmount"),
    ):
        company = row.get(company_key) or ""
        amount = row.get(amount_key) or ""
        if company or amount:
            parts.append(f"{label}: {company} {amount}".strip())
    return "; ".join(parts)


def _insurance(row):
    coverage = row.get("WorkersCompCoverageType") or ""
    company = row.get("WCInsuranceCompany") or ""
    if coverage and company:
        return f"{coverage} ({company})"
    return coverage or company


def _status(row):
    primary = row.get("PrimaryStatus") or ""
    secondary = row.get("SecondaryStatus") or ""
    if primary and secondary:
        return f"{primary} / {secondary}"
    return primary or secondary


def _record(query, row):
    name = row.get("FullBusinessName") or row.get("BusinessName") or ""
    class_text = row.get("Classifications(s)") or ""
    names = [name, row.get("BusinessName") or ""]
    if not record_matches(query, row.get("LicenseNo"), names, class_text):
        return None
    record = found_row(
        query,
        license_no=row.get("LicenseNo"),
        name=name,
        status=_status(row),
        issue_date=row.get("IssueDate"),
        expiry_date=row.get("ExpirationDate"),
        bond=_bond(row),
        insurance=_insurance(row),
        address=join_address(row.get("MailingAddress"), row.get("City"), row.get("State"), row.get("ZIPCode")),
        source_url=PORTAL_URL,
    )
    record["class"] = class_text
    return record


def lookup(query, fetch):
    result = fetch(CSV_URL)
    failed = transport_row(query, result, _MESSAGES, PORTAL_URL)
    if failed is not None:
        return outcome([failed])
    found = []
    seen = set()
    truncated = False
    header_seen = False
    for row in csv_dicts(result.get("text") or "", "LicenseNo"):
        header_seen = True
        record = _record(query, row)
        if record is None:
            continue
        if take_match(found, seen, query, record):
            truncated = True
            break
    if not header_seen and "LicenseNo" not in (result.get("text") or ""):
        return outcome([
            status_row(query, "error", "CSLB master file had no license header.", PORTAL_URL),
        ])
    if not found:
        return outcome([
            status_row(
                query,
                "not_found",
                "No license matched this search in the CSLB master file.",
                PORTAL_URL,
            ),
        ])
    return outcome(found, truncated)
