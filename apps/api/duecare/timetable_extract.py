"""Read an uploaded timetable into grid cells: weekday, time span, and the text printed in each cell.

Two sources are supported, both read without AI:
- The department's timetable PDF, read from its own text and ruling lines. This reconstructs merged
  multi-hour cells and side-by-side batch columns exactly.
- Screenshots of the Somaiya scheduler's Week view, read from pixel geometry with local OCR
  (`timetable_scheduler`).
The output is evidence for the student's review, never saved directly.
"""

import base64
import io
import re
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout

from PIL import Image, ImageOps, UnidentifiedImageError

from . import timetable_image_grid, timetable_scheduler
from .errors import ApiError

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_TOTAL_BYTES = 20 * 1024 * 1024
MAX_PDF_PAGES = 4
MAX_PICTURES = 4  # The scheduler scrolls; three screenshots cover 7am to 7pm.
MAX_PIXELS = 24_000_000
MAX_CELLS = 600
EXTRACT_SECONDS = 45

DAYS = {
    "monday": 1, "mon": 1, "tuesday": 2, "tue": 2, "tues": 2, "wednesday": 3, "wed": 3,
    "thursday": 4, "thu": 4, "thur": 4, "thurs": 4, "friday": 5, "fri": 5, "saturday": 6, "sat": 6,
    "sunday": 7, "sun": 7,
}  # fmt: skip
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
RANGE = re.compile(r"(\d{1,2})[:.](\d{2})(?:[ap]\.?m\.?)?-(\d{1,2})[:.](\d{2})(?:[ap]\.?m\.?)?")


class Unreadable(Exception):
    """A page without a recognizable timetable grid in its own text."""


def kind_of(data: bytes):
    if data.startswith(b"%PDF-"):
        return "pdf"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def validate(files):
    """files: [(name, bytes)]. Decoded type, sizes and counts; mixed submissions are rejected."""
    if not files:
        raise ApiError(422, "NO_FILE", "Choose a timetable PDF or picture")
    kinds = []
    for name, data in files:
        if len(data) > MAX_FILE_BYTES:
            raise ApiError(413, "FILE_TOO_LARGE", f"{name} is larger than 10 MB")
        kind = kind_of(data)
        if kind is None:
            raise ApiError(415, "UNSUPPORTED_FILE", f"{name} is not a PDF or a PNG, JPEG or WebP screenshot")
        kinds.append(kind)
    if sum(len(d) for _, d in files) > MAX_TOTAL_BYTES:
        raise ApiError(413, "FILE_TOO_LARGE", "Uploads are limited to 20 MB in total")
    if "pdf" in kinds and len(files) > 1:
        raise ApiError(422, "MIXED_UPLOAD", "Upload the timetable PDF, or scheduler screenshots, not both")
    if len(files) > MAX_PICTURES:
        raise ApiError(422, "TOO_MANY_FILES", "Upload at most four scheduler screenshots")
    return kinds


def clock(minutes):
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def time_rows(labels):
    """Printed row labels such as '12:00-1:00' to 24-hour spans.

    Rows run top to bottom in time order, so a clock value earlier than the previous one is read as
    afternoon. A first row before 7:00 is also read as afternoon and flagged for checking.
    """
    rows, previous, issues = [], None, []
    for label in labels:
        m = RANGE.search(re.sub(r"\s+", "", label.lower()))
        if not m:
            rows.append(None)
            continue
        h1, m1, h2, m2 = map(int, m.groups())
        if h1 > 23 or h2 > 23 or m1 > 59 or m2 > 59:
            rows.append(None)
            continue
        start = h1 * 60 + m1
        if previous is None and h1 < 7:
            start += 720
            issues.append("Afternoon was assumed for the first timetable row; check the times")
        while previous is not None and start < previous and start + 720 < 1440:
            start += 720
        end = h2 * 60 + m2
        while end <= start and end + 720 < 1440:
            end += 720
        if end <= start:
            rows.append(None)
            continue
        rows.append((start, end))
        previous = end
    return rows, issues


def day_of(text):
    return DAYS.get(re.sub(r"[^a-z]", "", text.lower()))


def header_info(lines):
    """'Class: SY B. Tech COMP B' and 'Year: 2026-2027 Semester: ODD' printed above the grid."""
    text = " ".join(lines)
    info = {}
    m = re.search(r"class\s*:\s*(.+?)(?=\s+year\s*:|$)", text, re.I)
    if m:
        info["classLabel"] = m.group(1).strip()[:120]
    m = re.search(r"year\s*:\s*([\d\s\-/]+\d)", text, re.I)
    if m:
        info["academicYear"] = re.sub(r"\s", "", m.group(1))[:20]
    m = re.search(r"semester\s*:\s*([A-Za-z0-9]+)", text, re.I)
    if m:
        info["semester"] = m.group(1)[:20]
    return info


# Native PDF text and geometry.


def runs(chars):
    """Text runs in content-stream order.

    Narrow batch columns can print text wider than their cell, overlapping the next column; such
    text still begins inside its own cell. Runs therefore follow drawing order and are placed by
    their first character, which keeps neighbouring cells' text apart.
    """
    explicit = any(c["text"] == " " for c in chars)
    out, cur, pending_space = [], None, False
    for c in chars:
        if c["text"].isspace():
            pending_space = True
            continue
        size = c.get("size") or 8
        same_line = cur is not None and abs(c["top"] - cur["top"]) < size * 0.3
        gap = c["x0"] - cur["x1"] if cur else 0
        if same_line and -size * 0.15 <= gap <= size * (1.2 if pending_space else 0.6):
            space = pending_space or (not explicit and gap > size * 0.25)
            cur["text"] += (" " if space else "") + c["text"]
            cur["x1"], cur["bottom"] = c["x1"], max(cur["bottom"], c["bottom"])
        else:
            cur = {"text": c["text"], "x0": c["x0"], "x1": c["x1"], "top": c["top"], "bottom": c["bottom"]}
            out.append(cur)
        pending_space = False
    return out


def cell_lines(items):
    lines = []
    for r in sorted(items, key=lambda r: (r["top"], r["x0"])):
        if lines and abs(lines[-1][0]["top"] - r["top"]) < 3:
            lines[-1].append(r)
        else:
            lines.append([r])
    return [" ".join(r["text"] for r in sorted(line, key=lambda r: r["x0"])).strip() for line in lines]


def overlap(a0, a1, b0, b1):
    return max(0.0, min(a1, b1) - max(a0, b0))


def grid_cells(boxes, texts, width, height, page_id, unsure=()):
    """Map cell boxes to weekday columns and time rows. texts: box index -> lines."""
    days = []
    for i, box in enumerate(boxes):
        lines = texts.get(i, [])
        d = day_of(" ".join(lines)) if lines else None
        if d:
            days.append((box, d, i))
    if len(days) < 3:
        raise Unreadable()
    header_bottom = max(b[3] for b, _, _ in days)
    first_day = min(b[0] for b, _, _ in days)
    time_boxes = []
    for i, box in enumerate(boxes):
        if (
            box[1] >= header_bottom - 1
            and box[2] <= first_day + 2
            and RANGE.search(re.sub(r"\s+", "", "".join(texts.get(i, [])).lower()))
        ):
            time_boxes.append((box, " ".join(texts.get(i, [])), i))
    time_boxes.sort(key=lambda t: t[0][1])
    spans, issues = time_rows([t[1] for t in time_boxes])
    rows = [(t[0][1], t[0][3], s) for t, s in zip(time_boxes, spans) if s]
    if len(rows) < 2:
        raise Unreadable()
    used = {i for *_, i in days} | {i for *_, i in time_boxes}
    cells = []
    for i, box in enumerate(boxes):
        lines = [line for line in texts.get(i, []) if line]
        if i in used or not lines or box[3] <= header_bottom + 1:
            continue
        x0, top, x1, bottom = box
        cover_days = [d for b, d, _ in days if overlap(x0, x1, b[0], b[2]) >= 0.5 * min(x1 - x0, b[2] - b[0])]
        cover_rows = [
            s for r0, r1, s in rows if overlap(top, bottom, r0, r1) >= 0.5 * min(bottom - top, r1 - r0)
        ]
        if not cover_days or not cover_rows:
            continue
        day_width = max(b[2] - b[0] for b, d, _ in days if d == cover_days[0])
        for d in cover_days:
            cells.append(
                {
                    "page": page_id,
                    "weekday": d,
                    "start": clock(min(s[0] for s in cover_rows)),
                    "end": clock(max(s[1] for s in cover_rows)),
                    "lines": lines[:12],
                    "text": " ".join(lines)[:400],
                    "bbox": [
                        round(x0 / width, 4),
                        round(top / height, 4),
                        round(x1 / width, 4),
                        round(bottom / height, 4),
                    ],  # fmt: skip
                    "spansDays": len(cover_days) > 1,
                    "narrow": len(cover_days) == 1 and (x1 - x0) < day_width * 0.9,
                    "unsure": i in unsure,
                }
            )
    return cells, issues


def pdf_page(page, page_id):
    tables = sorted(page.find_tables(), key=lambda t: (t.bbox[2] - t.bbox[0]) * (t.bbox[3] - t.bbox[1]))
    if not tables:
        raise Unreadable()
    table = tables[-1]
    boxes = [tuple(c) for c in table.cells]
    text_runs = runs(page.chars)
    texts = {}
    for r in text_runs:
        mid = (r["top"] + r["bottom"]) / 2
        # The run's first character decides its cell; the smallest containing box wins.
        holders = [
            (b[2] - b[0]) * (b[3] - b[1])
            for b in boxes
            if b[0] - 1 <= r["x0"] < b[2] - 0.5 and b[1] - 1 <= mid <= b[3] + 1
        ]
        if holders:
            smallest = min(holders)
            for i, b in enumerate(boxes):
                if (
                    (b[2] - b[0]) * (b[3] - b[1]) == smallest
                    and b[0] - 1 <= r["x0"] < b[2] - 0.5
                    and b[1] - 1 <= mid <= b[3] + 1
                ):
                    texts.setdefault(i, []).append(r)
                    break
    texts = {i: cell_lines(items) for i, items in texts.items()}
    cells, issues = grid_cells(boxes, texts, page.width, page.height, page_id)
    above = [r for r in text_runs if r["bottom"] <= table.bbox[1] + 1]
    return cells, issues, header_info(cell_lines(above))


def preview(image, edge=1400):
    image = image.convert("RGB")
    image.thumbnail((edge, edge))
    out = io.BytesIO()
    image.save(out, "JPEG", quality=72, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(out.getvalue()).decode()


SCANNED = (
    "is a scan without a readable weekday and time table. Upload the timetable PDF shared by the "
    "department, or screenshots of the Somaiya scheduler (My Scheduler, Week view)"
)


def sheet_picture(image, page_id):
    """A department timetable picture (scan or screenshot) -> cells, issues, header info."""
    if not timetable_scheduler.ocr_ready():
        raise ApiError(503, "OCR_UNAVAILABLE", "Reading pictures is not set up on this DueCare server")
    try:
        boxes, texts, unsure, header, width, height = timetable_image_grid.read(image)
    except timetable_image_grid.NoGrid:
        raise Unreadable()
    cells, issues = grid_cells(boxes, texts, width, height, page_id, unsure)
    timetable_image_grid.batch_columns(cells)
    issues.append("Read from a picture. Check course names, rooms and teachers against the original")
    return cells, issues, header_info(header)


def read_pdf(data, deadline):
    import pdfplumber
    from pdfminer.pdfdocument import PDFPasswordIncorrect
    from pdfminer.pdfparser import PDFSyntaxError

    try:
        pdf = pdfplumber.open(io.BytesIO(data))
    except (PDFSyntaxError, PDFPasswordIncorrect, ValueError):
        raise ApiError(422, "UNREADABLE_PDF", "This PDF is damaged or password-protected")
    except Exception:
        raise ApiError(422, "UNREADABLE_PDF", "This PDF could not be opened")
    with pdf:
        if len(pdf.pages) > MAX_PDF_PAGES:
            raise ApiError(
                422,
                "TOO_MANY_PAGES",
                f"This PDF has {len(pdf.pages)} pages. A timetable PDF has at most four; check that you chose "
                "the timetable",
            )
        pages = []
        for n, page in enumerate(pdf.pages, start=1):
            if time.monotonic() > deadline:
                raise ApiError(504, "EXTRACTION_TIMEOUT", "Reading took too long. Try a smaller file")
            if page.width * page.height * (150 / 72) ** 2 > MAX_PIXELS:
                raise ApiError(422, "PAGE_TOO_LARGE", "A PDF page is too large to read")
            page_id = f"p{n}"
            method = "pdf_text"
            image = page.to_image(resolution=200 if not page.chars else 150).original
            try:
                cells, issues, info = pdf_page(page, page_id)
            except Unreadable:
                if page.chars:
                    continue  # A text page without a weekday/time grid, such as a notes page.
                # A scanned page: read the department sheet from its picture.
                try:
                    cells, issues, info = sheet_picture(image, page_id)
                except Unreadable:
                    raise ApiError(422, "SCANNED_PDF", f"PDF page {n} {SCANNED}")
                method = "image_ocr"
            pages.append(
                {
                    "id": page_id,
                    "source": "PDF page " + str(n),
                    "preview": preview(image),
                    "layout": "grid",
                    "method": method,
                    "cells": cells,
                    "issues": issues,
                    "header": info,
                }
            )
        return pages


def picture(name, data):
    try:
        image = Image.open(io.BytesIO(data))
        if image.width * image.height > MAX_PIXELS:
            raise ApiError(422, "PICTURE_TOO_LARGE", f"{name} has too many pixels; use a normal screenshot")
        image.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise ApiError(422, "UNREADABLE_PICTURE", f"{name} could not be opened")
    return ImageOps.exif_transpose(image).convert("RGB")


def clock_range(a, b):
    return f"{clock(a)}–{clock(b)}"


def read_screenshots(files, deadline):
    """Scheduler Week-view screenshots, in any order and overlapping, combined into one week."""
    if not timetable_scheduler.ocr_ready():
        raise ApiError(503, "OCR_UNAVAILABLE", "Screenshot reading is not set up on this DueCare server")
    pages, observations, visible = [], [], []
    for n, (name, data) in enumerate(files, start=1):
        if time.monotonic() > deadline:
            raise ApiError(504, "EXTRACTION_TIMEOUT", "Reading took too long. Try fewer screenshots")
        page_id = f"p{n}"
        image = picture(name, data)
        try:
            seen, span = timetable_scheduler.read(image, page_id)
        except RuntimeError:  # Tesseract timed out or failed on this picture.
            raise ApiError(504, "EXTRACTION_TIMEOUT", f"Picture {n} took too long to read. Try again")
        except timetable_scheduler.NotScheduler:
            # Not the scheduler: perhaps a picture of the department timetable.
            try:
                cells, issues, info = sheet_picture(image, page_id)
            except (Unreadable, RuntimeError):
                raise ApiError(
                    422,
                    "NOT_A_TIMETABLE_PICTURE",
                    f"Picture {n} ({name}) is neither a Somaiya scheduler Week view nor a readable department "
                    "timetable. Capture the whole table, including the day names and times",
                )
            pages.append(
                {
                    "id": page_id,
                    "source": f"Picture {n}",
                    "preview": None,
                    "layout": "grid",
                    "method": "image_ocr",
                    "cells": cells,
                    "issues": issues,
                    "header": info,
                }
            )
            continue
        observations += seen
        visible.append(span)
        pages.append(
            {
                "id": page_id,
                "source": f"Screenshot {n}",
                "preview": None,
                "layout": "scheduler",
                "method": "scheduler_ocr",
                "cells": [],
                "issues": [],
                "header": {},
                "visible": clock_range(*span),
            }
        )
    events = timetable_scheduler.merge(observations)
    cells, unread = timetable_scheduler.to_cells(events)
    by_id = {p["id"]: p for p in pages}
    for c in cells:
        by_id[c["page"]]["cells"].append(c)
    for e in unread:
        by_id[e["page"]]["issues"].append(
            f"A class on {WEEKDAYS[e['weekday'] - 1]} near {clock(e['start'])} is cut off in "
            f"{by_id[e['page']]['source']}. Add a screenshot showing it fully"
        )
    # Gaps between screenshots mean classes could be missing.
    reach = None
    for start, end in sorted(visible):
        if reach is not None and start > reach + 5:
            pages[0]["issues"].append(
                f"No screenshot shows {clock_range(reach, start)}. Scroll the scheduler and add a screenshot "
                "of that time"
            )
        reach = end if reach is None else max(reach, end)
    return pages


def extract(files):
    """files: [(name, bytes)] in the student's chosen order. Returns the reading for review."""
    kinds = validate(files)
    deadline = time.monotonic() + EXTRACT_SECONDS
    pool = ThreadPoolExecutor(max_workers=1)
    if kinds[0] == "pdf":
        future = pool.submit(read_pdf, files[0][1], deadline)
    else:
        future = pool.submit(read_screenshots, files, deadline)
    try:
        pages = future.result(timeout=EXTRACT_SECONDS + 5)
    except FutureTimeout:
        raise ApiError(504, "EXTRACTION_TIMEOUT", "Reading took too long. Try a smaller file")
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    cells = [c for p in pages for c in p["cells"]]
    if len(cells) > MAX_CELLS:
        raise ApiError(422, "TOO_MANY_CELLS", "This timetable has more entries than one import supports")
    for n, c in enumerate(cells, start=1):
        c["id"] = f"c{n}"
    if not cells:
        raise ApiError(
            422,
            "NO_TIMETABLE_FOUND",
            "No classes were found. Upload the department timetable PDF, or scheduler Week-view screenshots "
            "showing the day names, hours and classes",
        )
    return {"method": pages[0]["method"], "pages": pages}
