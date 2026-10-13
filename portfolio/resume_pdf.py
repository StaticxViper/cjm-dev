"""Build a text resume PDF from portfolio content. Uses only the Python standard library."""

from __future__ import annotations

PAGE_W = 612
PAGE_H = 792
MARGIN_X = 54
MARGIN_TOP = 48
MARGIN_BOTTOM = 46

INK = (0.102, 0.094, 0.078)
MUTED = (0.29, 0.271, 0.235)
TEAL = (0.071, 0.196, 0.184)

# Helvetica AFM widths in 1000-unit em. Unknown glyphs fall back to 520.
_WIDTHS = {
    " ": 278,
    "!": 278,
    '"': 355,
    "#": 556,
    "$": 556,
    "%": 889,
    "&": 667,
    "'": 191,
    "(": 333,
    ")": 333,
    "*": 389,
    "+": 584,
    ",": 278,
    "-": 333,
    ".": 278,
    "/": 278,
    "0": 556,
    "1": 556,
    "2": 556,
    "3": 556,
    "4": 556,
    "5": 556,
    "6": 556,
    "7": 556,
    "8": 556,
    "9": 556,
    ":": 278,
    ";": 278,
    "<": 584,
    "=": 584,
    ">": 584,
    "?": 556,
    "@": 1015,
    "A": 667,
    "B": 667,
    "C": 722,
    "D": 722,
    "E": 667,
    "F": 611,
    "G": 778,
    "H": 722,
    "I": 278,
    "J": 500,
    "K": 667,
    "L": 556,
    "M": 833,
    "N": 722,
    "O": 778,
    "P": 667,
    "Q": 778,
    "R": 722,
    "S": 667,
    "T": 611,
    "U": 722,
    "V": 667,
    "W": 944,
    "X": 667,
    "Y": 667,
    "Z": 611,
    "a": 556,
    "b": 556,
    "c": 500,
    "d": 556,
    "e": 556,
    "f": 278,
    "g": 556,
    "h": 556,
    "i": 222,
    "j": 222,
    "k": 500,
    "l": 222,
    "m": 833,
    "n": 556,
    "o": 556,
    "p": 556,
    "q": 556,
    "r": 333,
    "s": 500,
    "t": 278,
    "u": 556,
    "v": 500,
    "w": 722,
    "x": 500,
    "y": 500,
    "z": 500,
}


def _translate(text: str) -> str:
    return (
        text.replace("–", "\x96")
        .replace("—", "\x97")
        .replace("’", "'")
        .replace("“", '"')
        .replace("”", '"')
        .replace("•", "\x95")
    )


def _escape(text: str) -> str:
    encoded = _translate(text).encode("latin-1", "replace").decode("latin-1")
    return encoded.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _text_width(text: str, size: float, bold: bool) -> float:
    scale = 1.07 if bold else 1.0
    units = 0
    for ch in _translate(text):
        units += _WIDTHS.get(ch, 520)
    return units * size / 1000 * scale


def _chunks(word: str, size: float, bold: bool, max_width: float) -> list[str]:
    if _text_width(word, size, bold) <= max_width:
        return [word]
    pieces: list[str] = []
    buf = ""
    for ch in word:
        trial = buf + ch
        if buf and _text_width(trial, size, bold) > max_width:
            pieces.append(buf)
            buf = ch
        else:
            buf = trial
    if buf:
        pieces.append(buf)
    return pieces


def _wrap(text: str, size: float, bold: bool, max_width: float) -> list[str]:
    words: list[str] = []
    for word in text.split():
        words.extend(_chunks(word, size, bold, max_width))
    if not words:
        return [""]
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        trial = f"{current} {word}"
        if _text_width(trial, size, bold) <= max_width:
            current = trial
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


class ResumeDoc:
    def __init__(self) -> None:
        self.pages: list[list[str]] = []
        self.ops: list[str] = []
        self.y = 0.0
        self._start_page()

    def _start_page(self) -> None:
        self.ops = [f"{TEAL[0]:.3f} {TEAL[1]:.3f} {TEAL[2]:.3f} rg 0 0 8 {PAGE_H} re f"]
        self.pages.append(self.ops)
        self.y = PAGE_H - MARGIN_TOP

    def _ensure(self, height: float) -> None:
        if self.y - height < MARGIN_BOTTOM:
            self._start_page()
            self._text("Christopher J. Moulton  ·  Resume", 9, bold=False, color=MUTED, gap=16)

    def _text(
        self,
        text: str,
        size: float,
        *,
        bold: bool = False,
        color: tuple[float, float, float] = INK,
        indent: float = 0,
        gap: float = 0,
        leading: float | None = None,
    ) -> None:
        font = "F2" if bold else "F1"
        lead = leading if leading is not None else size * 1.32
        max_width = PAGE_W - MARGIN_X - 36 - indent
        lines = _wrap(text, size, bold, max_width)
        self._ensure(lead * len(lines) + gap)
        r, g, b = color
        for line in lines:
            baseline = self.y - size
            self.ops.append(
                f"{r:.3f} {g:.3f} {b:.3f} rg BT /{font} {size:.2f} Tf "
                f"1 0 0 1 {MARGIN_X + indent:.2f} {baseline:.2f} Tm ({_escape(line)}) Tj ET"
            )
            self.y -= lead
        self.y -= gap

    def _rule(self) -> None:
        self._ensure(8)
        y = self.y - 2
        self.ops.append(
            f"{TEAL[0]:.3f} {TEAL[1]:.3f} {TEAL[2]:.3f} RG 0.8 w "
            f"{MARGIN_X:.2f} {y:.2f} m {PAGE_W - 36:.2f} {y:.2f} l S"
        )
        self.y -= 10

    def _bullets(self, items: list[str]) -> None:
        for item in items:
            self._text(f"- {item}", 10, indent=8, leading=13, gap=2)

    def _heading(self, label: str) -> None:
        self.y -= 8
        self._text(label.upper(), 11, bold=True, color=TEAL, gap=2)
        self._rule()

    def render(self, content: dict) -> bytes:
        contact = content["contact"]
        self._text(content["name"], 22, bold=True, leading=26, gap=2)
        self._text(content["headline"], 12, bold=True, color=TEAL, gap=2)
        self._text(content["location"], 10, color=MUTED, gap=3)
        contact_line = (
            f"{contact['phone']}   {contact['email']}   "
            f"{contact['linkedinLabel']}   {contact['githubLabel']}"
        )
        self._text(contact_line, 9, color=MUTED, gap=2)
        creds = "  ·  ".join(content["credentials"])
        self._text(creds, 9, color=MUTED, gap=4)

        self._heading("Summary")
        for paragraph in content["bio"]:
            self._text(paragraph, 10, leading=13.2, gap=4)

        self._heading("Experience")
        for job in content["experience"]:
            title = job["roles"][0]["title"]
            dates = job["roles"][0]["dates"]
            self._text(f"{title}  ·  {dates}", 11, bold=True, gap=1)
            if len(job["roles"]) > 1:
                prior = job["roles"][1]
                self._text(f"Previously {prior['title']}, {prior['dates']}", 10, color=MUTED, gap=1)
            place = job["location"]
            self._text(f"{job['company']}  ·  {place}", 10, color=MUTED, gap=2)
            if job.get("summary"):
                self._text(job["summary"], 10, leading=13.2, gap=2)
            self._bullets(job["highlights"])
            self.y -= 6

        self._heading("Projects")
        for project in content["projects"]:
            self._text(project["name"], 11, bold=True, gap=1)
            self._text(project["description"], 10, leading=13.2, gap=1)
            if project.get("url"):
                self._text(project["url"], 8, color=MUTED, gap=4)
            else:
                self.y -= 3

        self._heading("Skills")
        for group in content["skills"]:
            self._text(f"{group['group']}: {', '.join(group['items'])}", 10, leading=13.2, gap=3)

        self._heading("Education")
        for school in content["education"]:
            self._text(f"{school['credential']}  ·  {school['dates']}", 11, bold=True, gap=1)
            place = f"  ·  {school['location']}" if school.get("location") else ""
            self._text(f"{school['school']}{place}", 10, color=MUTED, gap=1)
            if school.get("details"):
                self._text(school["details"], 10, leading=13.2, gap=4)
            else:
                self.y -= 4

        self._heading("Certifications")
        self._bullets(content["certifications"])
        self._heading("Honors")
        self._bullets(content["honors"])
        return _assemble(self.pages)


def _assemble(pages: list[list[str]]) -> bytes:
    font_regular = (
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"
    )
    font_bold = (
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>"
    )
    page_objects: list[bytes] = []
    content_objects: list[bytes] = []
    for ops in pages:
        stream = "\n".join(ops).encode("latin-1", "replace")
        content_objects.append(
            b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream"
        )
    # Object numbers: 1 catalog, 2 pages, 3 font, 4 font bold, then pairs of page/content.
    # Assign after we know counts.
    objects: list[bytes] = [b"", b""]  # placeholders for catalog and pages
    objects.append(font_regular)
    objects.append(font_bold)
    kids = []
    for index, content in enumerate(content_objects):
        page_num = 5 + index * 2
        content_num = page_num + 1
        kids.append(f"{page_num} 0 R".encode("ascii"))
        page_objects.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_W} {PAGE_H}] "
                f"/Contents {content_num} 0 R /Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> >>"
            ).encode("ascii")
        )
        objects.append(page_objects[-1])
        objects.append(content)
    kids_joined = b" ".join(kids)
    objects[1] = (
        b"<< /Type /Pages /Count "
        + str(len(pages)).encode("ascii")
        + b" /Kids ["
        + kids_joined
        + b"] >>"
    )
    objects[0] = b"<< /Type /Catalog /Pages 2 0 R >>"
    info = (
        b"<< /Title (Christopher J. Moulton Resume) /Author (Christopher J. Moulton) "
        b"/Creator (cjm-dev portfolio build) >>"
    )
    objects.append(info)

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for number, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out.extend(f"{number} 0 obj\n".encode("ascii"))
        out.extend(obj)
        out.extend(b"\nendobj\n")
    xref_at = len(out)
    out.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    out.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        out.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    out.extend(
        (
            f"trailer << /Size {len(objects) + 1} /Root 1 0 R /Info {len(objects)} 0 R >>\n"
            f"startxref\n{xref_at}\n%%EOF\n"
        ).encode("ascii")
    )
    return bytes(out)


def build_resume(content: dict) -> bytes:
    return ResumeDoc().render(content)
