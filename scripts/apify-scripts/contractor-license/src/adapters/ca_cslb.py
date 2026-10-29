"""California CSLB license check.

License numbers and business names use the official Check a License form
(https://www.cslb.ca.gov/OnlineServices/CheckLicenseII/CheckLicense.aspx).
That is one small HTML form and one result page. The statewide master file
is not downloaded for those lookups.

A trade with no license number and no business name has no targeted form
field. That path streams MasterLicenseData.csv and stops once maxResults
matches are in hand. The file is not loaded into memory.
"""

from __future__ import annotations

import csv
import logging
import re
from html import unescape
from urllib.parse import urlencode, urljoin

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


log = logging.getLogger("apify")

PORTAL_URL = "https://www.cslb.ca.gov/onlineservices/dataportal/ContractorList"
CHECK_URL = "https://www.cslb.ca.gov/OnlineServices/CheckLicenseII/CheckLicense.aspx"
DETAIL_BASE = "https://www.cslb.ca.gov/OnlineServices/CheckLicenseII/LicenseDetail.aspx?LicNum="
CSV_URL = (
    "https://www.cslb.ca.gov/OnlineServices/DataPortal/DownLoadFile.ashx"
    "?fName=MasterLicenseData&type=C"
)

_MESSAGES = {
    "captcha": "California CSLB returned a challenge page. This adapter does not bypass it.",
}
_TAG_RE = re.compile(r"<[^>]+>")
_BR_RE = re.compile(r"<br\s*/?>", re.I)
_SPACE_RE = re.compile(r"\s+")
_LICENSE_LINK_RE = re.compile(
    r'id="MainContent_dlMain_lblName_(\d+)"[^>]*>(.*?)</span>.*?'
    r'LicNum=(\d+)".*?'
    r'id="MainContent_dlMain_lblLicenseStatus_\1"[^>]*>(.*?)</span>',
    re.I | re.S,
)
_HIDDEN_RE = re.compile(r"<input\b[^>]*>", re.I)
_BOND_COMPANY_RE = re.compile(
    r"Contractor's Bond with\s*(?:<a\b[^>]*>)?\s*([^<.]{2,120})",
    re.I,
)
_BOND_AMOUNT_RE = re.compile(r"Bond Amount:\s*</strong>\s*\$?\s*([0-9][0-9,]*)", re.I)
_WC_COMPANY_RE = re.compile(
    r"workers compensation insurance with the\s*(?:<a\b[^>]*>)?\s*([^<]{2,160})",
    re.I,
)


def _plain(html):
    text = _BR_RE.sub("\n", html or "")
    text = _TAG_RE.sub(" ", text)
    text = unescape(text)
    lines = []
    for line in text.splitlines():
        cleaned = _SPACE_RE.sub(" ", line).strip()
        if cleaned:
            lines.append(cleaned)
    return lines


def _td_inner(html, element_id):
    match = re.search(rf'<td\b[^>]*\bid="{re.escape(element_id)}"[^>]*>', html or "", re.I)
    if not match:
        return ""
    depth = 1
    pos = match.end()
    for token in re.finditer(r"</?td\b", html[pos:], re.I):
        if token.group(0).lower().startswith("</"):
            depth -= 1
            if depth == 0:
                return html[pos:pos + token.start()]
        else:
            depth += 1
    return ""


def _span_text(html, element_id):
    match = re.search(
        rf'id="{re.escape(element_id)}"[^>]*>(.*?)</span>',
        html or "",
        re.I | re.S,
    )
    if not match:
        return ""
    return " ".join(_plain(match.group(1)))


def _hidden_fields(html):
    fields = {}
    for tag in _HIDDEN_RE.findall(html or ""):
        name_match = re.search(r'name="([^"]+)"', tag)
        if not name_match:
            continue
        name = name_match.group(1)
        if not (name.startswith("__") or re.search(r'type="hidden"', tag, re.I)):
            continue
        value_match = re.search(r'value="([^"]*)"', tag)
        fields[name] = unescape(value_match.group(1)) if value_match else ""
    return fields


def _post_body(html, extra):
    fields = _hidden_fields(html)
    fields.update(extra)
    return urlencode(fields).encode("utf-8")


def _failed(query, result):
    """Map a failed fetch to a status row.

    The license form loads recaptcha.js in the template and still returns the
    record without a solved challenge. A page that has the form or the detail
    fields is not treated as a captcha. A bare challenge page still is.
    """
    judged = result
    text = (result or {}).get("text") or ""
    if "the requested url was rejected" in text.lower():
        judged = dict(result)
        judged["text"] = ""
        judged["error"] = "CSLB rejected the request before returning a license page."
        return transport_row(query, judged, _MESSAGES, (result or {}).get("final_url") or CHECK_URL)
    if any(token in text for token in (
        "MainContent_LicNo",
        "MainContent_BusInfo",
        "MainContent_ErrMsg",
        "MainContent_dlMain_lblName_",
    )):
        judged = dict(result)
        judged["text"] = text.replace("recaptcha", "")
    return transport_row(query, judged, _MESSAGES, (result or {}).get("final_url") or CHECK_URL)


def _license_digits(value):
    return re.sub(r"\D", "", value or "")


def _address_from_lines(lines):
    kept = []
    for line in lines:
        if line.lower().startswith("business phone"):
            continue
        if line.lower().startswith("dba "):
            continue
        kept.append(line)
    if len(kept) <= 1:
        return kept[0] if kept else ""
    street = kept[0]
    rest = kept[1:]
    tail = rest[-1]
    city_match = re.match(r"^(.+),\s*([A-Z]{2})\s+(\d{5}(?:-\d{4})?)$", tail)
    if city_match and len(rest) == 1:
        city, state, zip_code = city_match.groups()
        return join_address(street, city, state, zip_code)
    return join_address(street, *rest)


def _bond(html):
    company_match = _BOND_COMPANY_RE.search(html or "")
    amount_match = _BOND_AMOUNT_RE.search(html or "")
    company = _SPACE_RE.sub(" ", unescape(company_match.group(1))).strip(" .") if company_match else ""
    amount = (amount_match.group(1).replace(",", "") if amount_match else "")
    if company or amount:
        return f"Contractor: {company} {amount}".strip()
    return ""


def _insurance(html):
    cell = _td_inner(html, "MainContent_WCStatus") or ""
    text = " ".join(_plain(cell))
    if re.search(r"\bexempt\b", text, re.I) and not _WC_COMPANY_RE.search(html or ""):
        return "Exempt"
    company_match = _WC_COMPANY_RE.search(html or "")
    if not company_match:
        return text[:300]
    company = _SPACE_RE.sub(" ", unescape(company_match.group(1))).strip(" .")
    return f"WC Insurance ({company})" if company else text[:300]


def _classes(html):
    cell = _td_inner(html, "MainContent_ClassCellTable")
    names = []
    for raw in re.findall(r"<a\b[^>]*>(.*?)</a>", cell or "", re.I | re.S):
        text = " ".join(_plain(raw))
        if text and text not in names:
            names.append(text)
    if names:
        return " ".join(names)
    return " ".join(_plain(cell))


def _business_lines(html):
    lines = _plain(_td_inner(html, "MainContent_BusInfo"))
    name = ""
    dba = ""
    address_lines = []
    for line in lines:
        lower = line.lower()
        if lower.startswith("business phone"):
            continue
        if lower.startswith("dba "):
            dba = line[4:].strip()
            continue
        if not name:
            name = line
            continue
        address_lines.append(line)
    if name and dba and dba.lower() not in name.lower():
        name = f"{name} DBA {dba}"
    return name, address_lines


def _detail_record(query, html, page_url):
    error = _span_text(html, "MainContent_ErrMsg")
    if error:
        return None, error
    name, lines = _business_lines(html)
    if not name and "License Detail" not in (html or ""):
        return None, ""
    header = " ".join(_plain(re.search(r"<h1\b[^>]*>.*?</h1>", html or "", re.I | re.S).group(0))) if re.search(r"<h1\b", html or "", re.I) else ""
    number_match = re.search(r"License\s*#\s*(\d+)", header) or re.search(r"LicNum=(\d+)", page_url or "")
    license_no = number_match.group(1) if number_match else _license_digits(query.license_no)
    class_text = _classes(html)
    status = " ".join(_plain(_td_inner(html, "MainContent_Status")))
    names = [name]
    if not record_matches(query, license_no, names, class_text):
        return None, ""
    record = found_row(
        query,
        license_no=license_no,
        name=name,
        status=status,
        issue_date=" ".join(_plain(_td_inner(html, "MainContent_IssDt"))),
        expiry_date=" ".join(_plain(_td_inner(html, "MainContent_ExpDt"))),
        bond=_bond(html),
        insurance=_insurance(html),
        address=_address_from_lines(lines),
        source_url=page_url or DETAIL_BASE + license_no,
    )
    record["class"] = class_text
    return record, ""


def _result_links(html):
    found = []
    seen = set()
    for match in _LICENSE_LINK_RE.finditer(html or ""):
        license_no = match.group(3)
        if license_no in seen:
            continue
        seen.add(license_no)
        name = " ".join(_plain(match.group(2)))
        status = " ".join(_plain(match.group(4)))
        href = urljoin(CHECK_URL, f"LicenseDetail.aspx?LicNum={license_no}")
        found.append({"license_no": license_no, "name": name, "status": status, "url": href})
    return found


def _fetch_form(query, fetch):
    result = fetch(CHECK_URL)
    failed = _failed(query, result)
    if failed is not None:
        return None, outcome([failed])
    return result, None


def _lookup_license(query, fetch):
    form, failed = _fetch_form(query, fetch)
    if failed is not None:
        return failed
    digits = _license_digits(query.license_no)
    body = _post_body(form.get("text") or "", {
        "ctl00$MainContent$LicNo": digits,
        "ctl00$MainContent$Contractor_License_Number_Search": " ",
    })
    result = fetch(CHECK_URL, body)
    failed = _failed(query, result)
    if failed is not None:
        return outcome([failed])
    page = result.get("text") or ""
    page_url = result.get("final_url") or (DETAIL_BASE + digits)
    record, error = _detail_record(query, page, page_url)
    log.info(
        "CSLB targeted license check finished. master_file_downloaded=false html_bytes=%s",
        len(form.get("text") or "") + len(page),
    )
    if error:
        return outcome([
            status_row(query, "not_found", error, page_url),
        ])
    if record is None:
        return outcome([
            status_row(
                query,
                "not_found",
                "No license matched this search on the CSLB license check.",
                page_url,
            ),
        ])
    return outcome([record])


def _lookup_name(query, fetch):
    form, failed = _fetch_form(query, fetch)
    if failed is not None:
        return failed
    body = _post_body(form.get("text") or "", {
        "ctl00$MainContent$NextName": (query.name or "")[:35],
        "ctl00$MainContent$Contractor_Business_Name_Button": " ",
    })
    result = fetch(CHECK_URL, body)
    failed = _failed(query, result)
    if failed is not None:
        return outcome([failed])
    page = result.get("text") or ""
    name_query = type(query)(query.state, query.license_no, query.name, "", query.max_results)
    links = [
        item for item in _result_links(page)
        if record_matches(name_query, item["license_no"], [item["name"]], "")
    ]
    if not links:
        log.info("CSLB targeted name check finished. master_file_downloaded=false matches=0")
        return outcome([
            status_row(
                query,
                "not_found",
                "No license matched this search on the CSLB license check.",
                result.get("final_url") or CHECK_URL,
            ),
        ])
    found = []
    seen = set()
    truncated = False
    for item in links:
        if len(found) >= query.max_results:
            truncated = True
            break
        detail = fetch(item["url"])
        failed = _failed(query, detail)
        if failed is not None:
            if found:
                break
            return outcome([failed])
        record, error = _detail_record(query, detail.get("text") or "", detail.get("final_url") or item["url"])
        if error or record is None:
            continue
        if take_match(found, seen, query, record):
            truncated = True
            break
    log.info(
        "CSLB targeted name check finished. master_file_downloaded=false matches=%s",
        len(found),
    )
    if not found:
        return outcome([
            status_row(
                query,
                "not_found",
                "No license matched this search on the CSLB license check.",
                CHECK_URL,
            ),
        ])
    return outcome(found, truncated)


def _iter_csv_rows(lines):
    header = None
    pending = ""
    for piece in lines:
        logical = piece if not pending else pending + "\n" + piece
        if logical.count('"') % 2:
            pending = logical
            continue
        pending = ""
        if header is None:
            if "licenseno" not in logical.lower():
                continue
            header = [(key or "").strip() for key in next(csv.reader([logical]))]
            continue
        values = next(csv.reader([logical]))
        if not any(values):
            continue
        yield {
            header[index]: (values[index] if index < len(values) else "").strip()
            for index in range(len(header))
            if header[index]
        }


def _record_from_csv(query, row):
    name = row.get("FullBusinessName") or row.get("BusinessName") or ""
    class_text = row.get("Classifications(s)") or ""
    names = [name, row.get("BusinessName") or ""]
    if not record_matches(query, row.get("LicenseNo"), names, class_text):
        return None
    primary = row.get("PrimaryStatus") or ""
    secondary = row.get("SecondaryStatus") or ""
    if primary and secondary:
        status = f"{primary} / {secondary}"
    else:
        status = primary or secondary
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
    coverage = row.get("WorkersCompCoverageType") or ""
    company = row.get("WCInsuranceCompany") or ""
    if coverage and company:
        insurance = f"{coverage} ({company})"
    else:
        insurance = coverage or company
    record = found_row(
        query,
        license_no=row.get("LicenseNo"),
        name=name,
        status=status,
        issue_date=row.get("IssueDate"),
        expiry_date=row.get("ExpirationDate"),
        bond="; ".join(parts),
        insurance=insurance,
        address=join_address(row.get("MailingAddress"), row.get("City"), row.get("State"), row.get("ZIPCode")),
        source_url=PORTAL_URL,
    )
    record["class"] = class_text
    return record


def _lookup_trade_file(query, fetch):
    """Stream the master file only when no license number or business name was given."""
    log.info("CSLB trade-only search is streaming the master file and will stop at the result cap.")
    streamer = getattr(fetch, "stream_lines", None)
    found = []
    seen = set()
    truncated = False
    header_seen = False
    if streamer is not None:
        streamed = streamer(CSV_URL)
        if isinstance(streamed, dict):
            failed = _failed(query, streamed)
            if failed is not None:
                return outcome([failed])
            lines = []
        else:
            lines = streamed
        for row in _iter_csv_rows(lines):
            header_seen = True
            record = _record_from_csv(query, row)
            if record is None:
                continue
            if take_match(found, seen, query, record):
                truncated = True
                break
    else:
        result = fetch(CSV_URL)
        failed = _failed(query, result)
        if failed is not None:
            return outcome([failed])
        for row in csv_dicts(result.get("text") or "", "LicenseNo"):
            header_seen = True
            record = _record_from_csv(query, row)
            if record is None:
                continue
            if take_match(found, seen, query, record):
                truncated = True
                break
        if not header_seen and "LicenseNo" not in (result.get("text") or ""):
            return outcome([
                status_row(query, "error", "CSLB master file had no license header.", PORTAL_URL),
            ])
    if streamer is not None and not header_seen and not found:
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


def lookup(query, fetch):
    if query.license_no:
        return _lookup_license(query, fetch)
    if query.name:
        return _lookup_name(query, fetch)
    return _lookup_trade_file(query, fetch)
