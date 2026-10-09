"""Read screenshots of the Somaiya scheduler ("My Scheduler Overview", Week view) without AI.

The week view is a fixed grid: grey ruling lines mark seven day columns and 30-minute rows, and each
class is a solid coloured block with white text. Geometry comes from the pixels; local Tesseract
OCR reads only small crops (day headers, hour labels, block text). The page scrolls, so a student
uploads several screenshots; blocks cut off at a screenshot edge are joined across screenshots by
weekday, colour and overlapping time.
"""

import re
import shutil
from statistics import median

import numpy as np
from PIL import Image, ImageOps

DAY_NAMES = {"sun": 7, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6}
CODE = re.compile(r"\b(\d{2}[A-Z]{1,2}\d{3,4})\b")
HOUR = re.compile(r"(\d{1,2})\s*([ap])m", re.I)


class NotScheduler(Exception):
    """The picture is not a readable scheduler Week view."""


def ocr_ready():
    return shutil.which("tesseract") is not None


def ocr(image, psm=6, whitelist=None):
    import pytesseract

    config = f"--psm {psm}" + (f" -c tessedit_char_whitelist={whitelist}" if whitelist else "")
    return pytesseract.image_to_data(image, config=config, output_type=pytesseract.Output.DICT, timeout=10)


def text_lines(data, min_conf=45):
    """Words grouped into lines, dropping low-confidence fragments such as half-hidden text."""
    lines = {}
    for i, word in enumerate(data["text"]):
        word = word.strip()
        if word and float(data["conf"][i]) >= min_conf:
            key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
            lines.setdefault(key, []).append((data["left"][i], word))
    return [" ".join(w for _, w in sorted(ws)) for _, ws in sorted(lines.items())]


def runs(mask, min_len=1):
    """Start/end index pairs of consecutive True values."""
    out, start = [], None
    for i, v in enumerate(list(mask) + [False]):
        if v and start is None:
            start = i
        elif not v and start is not None:
            if i - start >= min_len:
                out.append((start, i - 1))
            start = None
    return out


def centers(pairs):
    return [(a + b) / 2 for a, b in pairs]


def grid(rgb):
    """Ruling lines: grey, unsaturated, dark pixels spanning the table."""
    spread = rgb.max(axis=2) - rgb.min(axis=2)
    # Downscaled or recompressed screenshots (e.g. sent through WhatsApp) blend 1px lines into the
    # white background, so any clearly darker-than-white grey counts.
    grey = (rgb.mean(axis=2) < 205) & (spread < 30)
    h, w = grey.shape
    # Vertical lines run through most of the image height inside the table.
    col_score = grey.mean(axis=0)
    verticals = centers(runs(col_score > 0.25))
    if len(verticals) < 9:
        raise NotScheduler()
    # Nine consecutive, roughly evenly spaced day lines after the time column.
    xs = verticals
    best = None
    for i in range(len(xs) - 8):
        cand = xs[i : i + 9]
        widths = np.diff(cand[1:])
        if widths.min() > 60 and widths.max() - widths.min() < max(8, widths.mean() * 0.06):
            best = cand
    if best is None:
        raise NotScheduler()
    left, time_right, day_lines = best[0], best[1], best[1:]
    # The table spans the rows where its left border is drawn.
    border = grey[:, max(0, int(left) - 1) : int(left) + 2].any(axis=1)
    top, bottom = max(runs(border), key=lambda r: r[1] - r[0])
    # Horizontal lines read in the time column, which events never cover.
    band = grey[top : bottom + 1, int(left) + 3 : int(time_right) - 2]
    rows = [y + top for y in centers(runs(band.mean(axis=1) > 0.85))]
    if len(rows) < 5:
        raise NotScheduler()
    return left, time_right, day_lines, rows


def header_days(img, day_lines, header_top, header_bottom):
    days = []
    for x0, x1 in zip(day_lines, day_lines[1:]):
        crop = img.crop((int(x0) + 2, int(header_top) + 2, int(x1) - 2, int(header_bottom) - 2))
        crop = ImageOps.grayscale(crop).resize((crop.width * 3, crop.height * 3))
        words = " ".join(text_lines(ocr(crop, psm=7), min_conf=0)).lower()
        m = re.search(r"(sun|mon|tue|wed|thu|fri|sat)", words)
        days.append(DAY_NAMES[m.group(1)] if m else None)
    known = [(i, d) for i, d in enumerate(days) if d]
    if len(known) < 3:
        raise NotScheduler()
    # The week view lists consecutive days; fill any unread header from its neighbours.
    i0, d0 = known[0]
    start = (d0 - 1 - i0) % 7  # weekday index (0 = Monday) of the first column
    return [(start + i) % 7 + 1 for i in range(len(days))]


def regular(rows):
    """Ruling lines on the 30-minute grid. The header's bottom edge and the scrolled view's bottom
    border usually fall between grid lines and are left out."""
    gaps = [b - a for a, b in zip(rows, rows[1:]) if b - a > 20]
    if not gaps:
        raise NotScheduler()
    spacing = median(gaps)
    tolerance = max(3, spacing * 0.06)
    lines = [y for y in rows if any(abs(abs(y - o) - spacing) <= tolerance for o in rows if o != y)]
    if len(lines) < 3:
        raise NotScheduler()
    return lines, spacing


def hour_rows(img, left, time_right, lines, spacing):
    """Minutes = offset + y / spacing * 30, anchored by hour labels ("11am") in the time column."""
    votes = {}
    for a, b in zip(lines, lines[1:]):
        if abs(b - a - spacing) > max(3, spacing * 0.06):
            continue
        crop = img.crop((int(left) + 3, int(a) + 2, int(time_right) - 2, int(b) - 1))
        crop = ImageOps.grayscale(crop).resize((crop.width * 4, crop.height * 4))
        text = " ".join(text_lines(ocr(crop, psm=7, whitelist="0123456789apm"), min_conf=0))
        m = HOUR.search(text)
        if not m or not 1 <= int(m.group(1)) <= 12:
            continue
        hour = int(m.group(1)) % 12 + (12 if m.group(2).lower() == "p" else 0)
        # Each label sits in the first half-hour row of its hour; count rows from the top line.
        k = round((a - lines[0]) / spacing)
        offset = hour * 60 - k * 30
        votes[offset] = votes.get(offset, 0) + 1
    if not votes:
        raise NotScheduler()
    offset = max(votes, key=votes.get)
    return lambda y: offset + (y - lines[0]) / spacing * 30


def snap(minutes):
    return int(round(minutes / 5) * 5)


def blocks(rgb, x0, x1, top, bottom):
    """Coloured event blocks in one day column, read from a narrow strip inside the block padding.

    Blocks are separated by uncoloured rows; touching blocks of different courses differ clearly in
    colour. Antialiased rounded edges and compression noise only shift the colour briefly.
    """
    strip = rgb[int(top) + 1 : int(bottom), int(x0) + 5 : int(x0) + 11]
    colors = np.median(strip, axis=1)
    colored = (colors.max(axis=1) - colors.min(axis=1)) > 60
    out = []
    for a, b in runs(colored, min_len=3):
        cuts = [a]
        for y in range(a + 4, b - 3):
            before, after = colors[y - 4 : y].mean(axis=0), colors[y : y + 4].mean(axis=0)
            if np.abs(after - before).sum() > 120 and y - cuts[-1] > 6:
                cuts.append(y)
        for c0, c1 in zip(cuts, cuts[1:] + [b + 1]):
            if c1 - c0 >= 3:
                color = tuple(int(v) for v in np.median(colors[c0:c1], axis=0))
                out.append((c0 + int(top) + 1, c1 - 1 + int(top) + 1, color))
    return out


CODE_LIKE = re.compile(r"\b(\d{2})([A-Z$5]{1,2})([0-9SOIlBZ]{3,4})\b")
DIGIT = str.maketrans({"S": "5", "O": "0", "I": "1", "l": "1", "B": "8", "Z": "2"})


def fix_code(line):
    """OCR of small text confuses look-alike characters inside course codes ('32$B002', '16U2S38')."""
    return CODE_LIKE.sub(
        lambda m: m.group(1) + m.group(2).replace("$", "S").replace("5", "S") + m.group(3).translate(DIGIT),
        line,
    )


def block_text(rgb, x0, x1, y0, y1):
    """White text on a coloured block -> (lines, confidence score).

    The colour crop is enlarged before thresholding, which keeps letter shapes intact; two
    thresholds suit light and dark block colours, and the more confident reading wins.
    """
    crop = rgb[y0 : y1 + 1, int(x0) + 5 : int(x1) - 9]
    if crop.shape[0] < 8 or crop.shape[1] < 20:
        return [], 0
    big = Image.fromarray(crop.astype("uint8")).resize((crop.shape[1] * 3, crop.shape[0] * 3), Image.LANCZOS)
    big = np.asarray(big).astype(int)
    lum = big.mean(axis=2)
    best = ([], 0)
    for mask in (big.min(axis=2) > 150, lum > np.median(lum) + 60):
        if mask.sum() < 50:
            continue
        # The scheduler hides overflowing text mid-line; a cut last line is shorter than full ones.
        # Thin runs are the block's antialiased rounded edge, not text.
        text_rows = [r for r in runs(mask.any(axis=1)) if r[1] - r[0] >= 9]
        heights = [b - a for a, b in text_rows[:-1]]
        if heights and text_rows[-1][1] - text_rows[-1][0] < 0.75 * median(heights):
            mask = mask.copy()
            mask[text_rows[-1][0] :] = False
        page = ImageOps.expand(Image.fromarray(np.where(mask, 0, 255).astype("uint8")), border=20, fill=255)
        data = ocr(page, psm=6)
        score = sum(float(c) for w, c in zip(data["text"], data["conf"]) if w.strip() and float(c) >= 55)
        if score > best[1]:
            lines = [re.sub(r"\.{2,}$|[|]", "", line).strip() for line in text_lines(data, min_conf=55)]
            best = ([fix_code(re.sub(r"\s+", " ", line)) for line in lines if len(line) > 1], score)
    return best


def read(image, page_id):
    """One screenshot -> (observations, visible minutes). Observations hold weekday, minutes,
    colour, text lines, whether the block is cut off by the scrolled view, and its region."""
    img = image.convert("RGB")
    if img.width < 1800:
        # Shrunk screenshots are enlarged to desktop size: lines stay continuous and OCR sees
        # normal-sized text. Positions are reported as fractions, so scale does not matter.
        factor = 2000 / img.width
        img = img.resize((2000, round(img.height * factor)), Image.LANCZOS)
    rgb = np.asarray(img).astype(int)
    left, time_right, day_lines, rows = grid(rgb)
    header_top, header_bottom = rows[0], rows[1]
    if header_bottom - header_top < 15:
        raise NotScheduler()
    weekdays = header_days(img, day_lines, header_top, header_bottom)
    body = rows[1:]
    lines, spacing = regular(body)
    minutes = hour_rows(img, left, time_right, lines, spacing)
    top, bottom = body[0], body[-1]
    width, height = img.size
    out = []
    for weekday, x0, x1 in zip(weekdays, day_lines, day_lines[1:]):
        for y0, y1, color in blocks(rgb, x0, x1, top, bottom):
            clipped_top = y0 <= top + 3
            clipped_bottom = y1 >= bottom - 3
            out.append(
                {
                    "page": page_id,
                    "weekday": weekday,
                    "start": snap(minutes(y0 - 1)),
                    "end": snap(minutes(y1 + 1)),
                    "color": color,
                    **dict(zip(("lines", "score"), block_text(rgb, x0, x1, y0, y1))),
                    "clippedTop": clipped_top,
                    "clippedBottom": clipped_bottom,
                    "bbox": [
                        round(x0 / width, 4),
                        round(y0 / height, 4),
                        round(x1 / width, 4),
                        round(y1 / height, 4),
                    ],  # fmt: skip
                }
            )
    return out, (snap(minutes(top)), snap(minutes(bottom)))


def same_color(a, b):
    return sum(abs(x - y) for x, y in zip(a, b)) <= 90


def code_of(lines):
    m = CODE.search(" ".join(lines))
    return m.group(1) if m else None


def merge(observations):
    """Join pieces of one class seen in different screenshots (scrolled views overlap)."""
    events = []
    for o in sorted(observations, key=lambda o: (o["weekday"], o["start"])):
        for e in events:
            if (
                e["weekday"] == o["weekday"]
                and o["page"] not in e["pages"]
                and same_color(e["color"], o["color"])
                and o["start"] <= e["end"]
                and e["start"] <= o["end"]
                and (
                    not code_of(e["lines"])
                    or not code_of(o["lines"])
                    or code_of(e["lines"]) == code_of(o["lines"])
                )
            ):
                if o["start"] < e["start"] or (o["start"] == e["start"] and not o["clippedTop"]):
                    e["start"], e["clippedTop"] = o["start"], o["clippedTop"]
                if o["end"] > e["end"] or (o["end"] == e["end"] and not o["clippedBottom"]):
                    e["end"], e["clippedBottom"] = o["end"], o["clippedBottom"]
                if o["score"] > e["score"]:
                    e["lines"], e["score"], e["page"], e["bbox"] = (
                        o["lines"],
                        o["score"],
                        o["page"],
                        o["bbox"],
                    )
                e["pages"].add(o["page"])
                break
        else:
            events.append({**o, "pages": {o["page"]}})
    consolidate(events)
    return events


def name_key(lines):
    """Course name without its code: the first characters, plus whether it is a lab or tutorial."""
    name = re.sub(r"[^a-z]", "", CODE.sub(" ", " ".join(lines)).lower())
    return name[:18], "laborator" in name or "tutorial" in name


def consolidate(events):
    """Every session of one course shows one reading: the code most sessions agree on and the most
    confident name. Sessions belong together when they share a course code, or a name and block
    colour, since OCR can misread either one."""
    parent = list(range(len(events)))

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    keys = [name_key(e["lines"]) for e in events]
    codes = [code_of(e["lines"]) for e in events]
    for i in range(len(events)):
        for j in range(i):
            same_code = codes[i] and codes[i] == codes[j]
            same_name = (
                len(keys[i][0]) >= 6
                and keys[i] == keys[j]
                and same_color(events[i]["color"], events[j]["color"])
            )
            if same_code or same_name:
                parent[root(i)] = root(j)
    groups = {}
    for i, e in enumerate(events):
        groups.setdefault(root(i), []).append(e)
    for members in groups.values():
        found = [code_of(e["lines"]) for e in members if code_of(e["lines"])]
        code = max(set(found), key=found.count) if found else None
        best = max(members, key=lambda e: e["score"])
        lines = [line for line in (CODE.sub("", line).strip() for line in best["lines"]) if line]
        for e in members:
            e["lines"] = ([code] if code else []) + lines


def to_cells(events):
    cells, unread = [], []
    for e in events:
        text = " ".join(e["lines"])
        if not text:
            unread.append(e)
            continue
        cells.append(
            {
                "page": e["page"],
                "weekday": e["weekday"],
                "start": f"{e['start'] // 60:02d}:{e['start'] % 60:02d}",
                "end": f"{e['end'] // 60:02d}:{e['end'] % 60:02d}",
                "lines": e["lines"][:12],
                "text": text[:400],
                "bbox": e["bbox"],
                "spansDays": False,
                "narrow": False,
                "clippedTop": e["clippedTop"],
                "clippedBottom": e["clippedBottom"],
            }
        )
    return cells, unread
