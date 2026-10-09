"""Safe RFC 5322/MIME decoding for academic mail.

Message content is untrusted evidence. Nothing here follows links, loads remote resources,
executes markup, or keeps attachment bytes. Decoded text exists only for the current
processing step; callers persist identifiers, hashes, section structure, and metadata.
"""

import hashlib
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import getaddresses, parsedate_to_datetime
from html import unescape
from html.parser import HTMLParser

MAX_TEXT = 200_000
MAX_LINKS = 25
EMAIL = re.compile(r"^[^@\s<>\"',;]+@[^@\s<>\"',;]+\.[^@\s<>\"',;]+$")
URL = re.compile(r"https?://[^\s<>\"')\]]+", re.I)
QUOTE_HEADER = re.compile(
    r"^(on\s.{3,300}\swrote:|-{2,}\s*original message\s*-{2,}|-{2,}\s*forwarded message\s*-{2,}"
    r"|begin forwarded message:)\s*$",
    re.I,
)
OUTLOOK_HEADER = re.compile(r"^from:\s.+$", re.I)
FOOTER = re.compile(
    r"(unsubscribe|you are receiving this|manage (your )?(email|notification) preferences|"
    r"this e-?mail and any (files|attachments)|^disclaimer\b|confidentiality notice|"
    r"this is a copy of a message posted|digest preferences)",
    re.I,
)

NON_ACADEMIC = re.compile(
    r"\b(?:recruitment|recruiting|placements?|internships?|hiring|hackathons?|"
    r"councils?|student\s+clubs?|campus\s+ambassadors?|job\s+(?:openings?|opportunities)|"
    r"career\s+(?:opportunities|fair)|cultural\s+fest|webinars?|workshops?|competitions?|"
    r"exhibitions?|training\s+program(?:me)?s?|student\s+registrations?)\b",
    re.I,
)
PROMOTION = re.compile(
    r"\b(?:join|register|registration|sign\s+up|apply|applications?|invites?)\b.{0,160}"
    r"\b(?:community|clubs?|hackathons?|recruitment|placements?|internships?|competitions?|"
    r"webinars?|workshops?|councils?)\b",
    re.I | re.S,
)


def academic_exclusion(subject, sender_email=None, sender_name=None, text=None):
    """Exclude careers and extracurricular mail even when it mentions a test or deadline."""
    heading = " ".join(filter(None, [subject, sender_name, sender_email])).replace("_", " ")
    mailbox = (sender_email or "").split("@", 1)[0].lower()
    if re.search(
        r"recruit|placement|council|hackathon|internship|competitioncell|^(?:tpo|tnp)(?:\W|$)", mailbox
    ):
        return "non_academic_mail"
    if NON_ACADEMIC.search(heading) or PROMOTION.search(subject or ""):
        return "non_academic_mail"
    if text and PROMOTION.search(text[:12000]):
        return "non_academic_mail"
    return None


def normalize_email(value):
    """Exact mailbox comparison: trim and lower-case only; aliases are never guessed."""
    value = (value or "").strip().lower()
    return value if len(value) <= 320 and EMAIL.match(value) else None


@dataclass
class Section:
    kind: str  # authored, quoted, forwarded, signature, footer
    text: str
    attribution: str | None = None
    depth: int = 0


@dataclass
class Decoded:
    sender_email: str | None
    sender_name: str | None
    subject: str
    message_id: str | None
    in_reply_to: str | None
    references: list[str]
    sent_at: datetime | None
    sections: list[Section]
    attachments: list[dict]
    links: list[dict]
    authentication: dict | None
    recipients_include: set[str] = field(default_factory=set)
    truncated: bool = False

    @property
    def authored_text(self):
        return "\n\n".join(s.text for s in self.sections if s.kind == "authored")

    def content_hash(self):
        """Identity of the decoded content, independent of export filename or transport headers."""
        digest = hashlib.sha256()
        for part in (self.message_id or "", self.subject, self.sender_email or ""):
            digest.update(part.encode() + b"\0")
        for s in self.sections:
            digest.update(s.kind.encode() + b"\0" + s.text.encode() + b"\0")
        for a in self.attachments:
            digest.update(f"{a['title']}|{a['mediaType']}|{a['sizeBytes']}".encode() + b"\0")
        return digest.hexdigest()

    def summary(self):
        return {
            "sections": [
                {"kind": s.kind, "chars": len(s.text), "depth": s.depth, "attribution": bool(s.attribution)}
                for s in self.sections
            ],
            "truncated": self.truncated,
            "inReplyTo": self.in_reply_to,
            "references": self.references[-10:],
            # Observation only. Phase 3 validates authentication against trusted receiving infrastructure.
            "authenticationObserved": self.authentication,
        }


class _Text(HTMLParser):
    """HTML to bounded structured text; tables keep row/cell relationships."""

    BLOCK = {
        "p",
        "div",
        "br",
        "li",
        "ul",
        "ol",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "hr",
        "blockquote",
        "pre",
    }
    SKIP = {"script", "style", "head", "title", "noscript", "template", "svg", "object", "iframe"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.skip, self.links, self.quote = [], 0, [], 0
        self.cell, self.in_cell = False, 0

    def _break(self):
        # Block elements inside a table cell stay on the row's line.
        self.out.append(" " if self.in_cell else "\n")

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        elif tag == "a":
            href = dict(attrs).get("href") or ""
            if href.lower().startswith(("http://", "https://")):
                self.links.append(href)
        elif tag == "blockquote":
            self.quote += 1
            self.out.append("\n")
        elif tag == "tr":
            self.out.append("\n")
            self.cell = False
        elif tag in ("td", "th"):
            self.out.append(" | " if self.cell else "")
            self.cell = True
            self.in_cell += 1
        elif tag in self.BLOCK:
            self._break()

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
        elif tag == "blockquote":
            self.quote = max(0, self.quote - 1)
            self.out.append("\n")
        elif tag in ("td", "th"):
            self.in_cell = max(0, self.in_cell - 1)
        elif tag in ("table", "tr"):
            self.out.append("\n")
        elif tag in self.BLOCK:
            self._break()

    def handle_data(self, data):
        if self.skip:
            return
        text = re.sub(r"\s+", " ", data)
        if not text.strip():
            if self.out and not self.out[-1].endswith((" ", "\n")):
                self.out.append(" ")
            return
        if self.quote and (not self.out or self.out[-1].endswith("\n")):
            # Blockquote nesting becomes conventional quote markers for section splitting.
            text = "> " * self.quote + text.lstrip()
        self.out.append(text)

    def text(self):
        lines = [re.sub(r" {2,}", " ", line).strip() for line in "".join(self.out).split("\n")]
        return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def html_to_text(markup):
    parser = _Text()
    try:
        parser.feed(markup)
        parser.close()
    except Exception:  # Malformed markup degrades to tag-stripped text.
        return unescape(re.sub(r"<[^>]+>", " ", markup)), []
    return parser.text(), parser.links


def _part_text(part):
    try:
        return part.get_content()
    except (LookupError, UnicodeError, ValueError):
        payload = part.get_payload(decode=True) or b""
        return payload.decode("utf-8", errors="replace")


def _body(msg: EmailMessage):
    plain = msg.get_body(preferencelist=("plain",))
    html = msg.get_body(preferencelist=("html",))
    links, has_table = [], False
    if html is not None:
        markup = _part_text(html)
        html_text, links = html_to_text(markup)
        has_table = bool(re.search(r"<table\b", markup, re.I))
    # Plain text is preferred unless it would flatten a table's row/cell relationships.
    if plain is not None and _part_text(plain).strip() and not (has_table and html_text.strip()):
        text = _part_text(plain)
    elif html is not None:
        text = html_text
    else:
        text = ""
    return text.replace("\r\n", "\n").replace("\r", "\n"), links


def split_sections(text):
    """Separate authored content from quoted history, signatures and footers.

    Quoted history is retained as its own sections: it can hold the unchanged test date or
    original identity needed to interpret a later update.
    """
    sections: list[Section] = []
    lines = text.split("\n")
    current, kind, attribution, depth = [], "authored", None, 0
    marked = False  # Whether the current quote uses ">" markers (so unmarked text ends it).

    def flush():
        body = "\n".join(current).strip()
        if body:
            sections.append(Section(kind, body, attribution, depth))
        current.clear()

    for i, line in enumerate(lines):
        stripped = line.strip()
        quote_depth = len(re.match(r"^((>\s?)*)", line).group(1).replace(" ", ""))
        outlook = (
            OUTLOOK_HEADER.match(stripped)
            and i + 1 < len(lines)
            and re.match(r"^(sent|date|to|subject):", lines[i + 1].strip(), re.I)
        )
        if QUOTE_HEADER.match(re.sub(r"^(>\s?)+", "", stripped)) or (outlook and kind == "authored"):
            flush()
            kind = "forwarded" if "forward" in stripped.lower() else "quoted"
            attribution, depth, marked = stripped[:300], max(quote_depth, 1), False
            continue
        if line.rstrip() in ("--", "-- ") and (kind == "authored" or (kind == "quoted" and marked)):
            flush()
            kind, attribution = "signature", None
            continue
        if quote_depth:
            if kind not in ("quoted", "forwarded"):
                flush()
                kind, attribution, depth = "quoted", None, quote_depth
            marked = True
        elif kind == "quoted" and stripped and (attribution is None or marked):
            # Unmarked text after a marked quote is new authored text (an inline reply).
            flush()
            kind, attribution, depth, marked = "authored", None, 0, False
        if FOOTER.search(stripped) and kind in ("authored", "signature"):
            flush()
            kind = "footer"
        current.append(re.sub(r"^(>\s?)+", "", line) if quote_depth else line)
    flush()
    return sections


def _authentication(msg):
    # Only the topmost Authentication-Results header from Gmail's receiving server is an observation
    # worth keeping; lower headers can be forged or copied by any earlier hop or forwarder.
    for value in msg.get_all("Authentication-Results", []) or []:
        value = str(value)
        authserv = value.split(";", 1)[0].strip().lower()
        if authserv != "mx.google.com":
            return None
        result = {"authservId": authserv}
        for method in ("dkim", "spf", "dmarc"):
            match = re.search(rf"\b{method}=(\w+)", value, re.I)
            if match:
                result[method] = match.group(1).lower()
        domain = re.search(r"header\.from=([\w.-]+)", value, re.I)
        if domain:
            result["headerFrom"] = domain.group(1).lower()
        return result
    return None


def decode(raw: bytes) -> Decoded:
    msg = BytesParser(policy=policy.default).parsebytes(raw)
    senders = getaddresses([str(msg.get("From", ""))])
    name, address = senders[0] if senders else ("", "")
    try:
        sent_at = parsedate_to_datetime(str(msg["Date"])).astimezone(UTC) if msg["Date"] else None
    except (TypeError, ValueError):
        sent_at = None
    text, html_links = _body(msg)
    truncated = len(text) > MAX_TEXT
    sections = split_sections(text[:MAX_TEXT])
    attachments = []
    for index, part in enumerate(msg.walk()):
        if part.is_multipart():
            continue
        filename = part.get_filename()
        disposition = part.get_content_disposition()
        if not filename and disposition != "attachment":
            continue
        payload = part.get_payload(decode=True) or b""
        attachments.append(
            {
                "kind": "file",
                "title": (filename or "Untitled attachment")[:1000],
                "reference": f"mime-part:{index}",
                "mediaType": part.get_content_type(),
                "sizeBytes": len(payload),
            }
        )
    seen, links = set(), []
    linkable = "\n".join(s.text for s in sections if s.kind in ("authored", "quoted", "forwarded"))
    for url in [*html_links, *URL.findall(linkable)]:
        url = url.rstrip(".,;")
        if url in seen or len(url) > 2000 or FOOTER.search(url):
            continue
        seen.add(url)
        links.append({"kind": "link", "title": None, "reference": url, "mediaType": None, "sizeBytes": None})
        if len(links) >= MAX_LINKS:
            break
    recipients = {
        normalize_email(a)
        for _, a in getaddresses([str(v) for v in msg.get_all("To", []) + msg.get_all("Cc", [])])
    } - {None}
    return Decoded(
        sender_email=normalize_email(address),
        sender_name=(name or None) and name[:300],
        subject=str(msg.get("Subject", "") or "")[:1000],
        message_id=(str(msg["Message-ID"]).strip()[:1000] if msg["Message-ID"] else None),
        in_reply_to=(str(msg["In-Reply-To"]).strip()[:1000] if msg["In-Reply-To"] else None),
        references=str(msg.get("References", "") or "").split()[-50:],
        sent_at=sent_at,
        sections=sections,
        attachments=attachments,
        links=links,
        authentication=_authentication(msg),
        recipients_include=recipients,
        truncated=truncated,
    )


def header_sender(headers):
    """Sender mailbox from Gmail metadata headers, used before any body is fetched."""
    for h in headers or []:
        if h.get("name", "").lower() == "from":
            found = getaddresses([h.get("value", "")])
            return normalize_email(found[0][1]) if found else None
    return None
