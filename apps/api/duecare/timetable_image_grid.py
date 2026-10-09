"""Read a department timetable that is only available as a picture or a scanned PDF, without AI.

The department sheet is a ruled table. Its ruling lines are found in the pixels, the table is cut
into the smallest cells between lines, and neighbouring cells are joined wherever the line between
them is missing, which recovers merged multi-hour labs and side-by-side batch columns. Each joined
cell is read separately with local Tesseract OCR. The resulting boxes and text then go through the
same weekday/time mapping as a generated PDF.
"""

import re

import numpy as np
from PIL import Image, ImageOps

from .timetable_scheduler import ocr, text_lines


class NoGrid(Exception):
    """No ruled weekday/time table was found."""


def dark_mask(rgb):
    # Scanned ruling lines can be light grey. Only long straight runs count as lines, so a light
    # threshold does not turn text into lines.
    return rgb.mean(axis=2) < 205


def long_runs(mask, min_len):
    """Total length of straight runs at least min_len long, per row of the mask."""
    h = mask.shape[0]
    pad = np.zeros((h, 1), dtype=np.int8)
    d = np.diff(np.concatenate([pad, mask.astype(np.int8), pad], axis=1), axis=1)
    starts, ends = np.argwhere(d == 1), np.argwhere(d == -1)
    lengths = ends[:, 1] - starts[:, 1]
    keep = lengths >= min_len
    return np.bincount(starts[keep, 0], weights=lengths[keep], minlength=h)


def cluster(values, gap=3):
    groups = []
    for v in sorted(values):
        if groups and v - groups[-1][-1] <= gap:
            groups[-1].append(v)
        else:
            groups.append([v])
    return [(g[0] + g[-1]) / 2 for g in groups]


def lines(mask, scale):
    """Positions of horizontal and vertical ruling lines. A ruling line is long in total, even when
    merged cells interrupt it; text never forms long straight runs."""
    height, width = mask.shape
    rows = long_runs(mask, int(40 * scale))
    cols = long_runs(mask.T, int(22 * scale))
    # Sub-column lines of one batch block can be as short as a single time row.
    ys = cluster([int(y) for y in np.nonzero(rows >= width * 0.12)[0]])
    xs = cluster([int(x) for x in np.nonzero(cols >= height * 0.03)[0]])
    return xs, ys


def present(mask, x0, x1, y0, y1, vertical):
    """Whether a ruling line runs along this cell edge: its best single pixel column (or row) is
    nearly solid. Text crossing an edge leaves gaps between letters."""
    region = mask[int(y0) : int(y1) + 1, int(x0) : int(x1) + 1]
    if not region.size:
        return False
    return region.mean(axis=0 if vertical else 1).max() >= 0.75


def cells(mask, xs, ys):
    """Join the smallest cells across missing line segments; returns boxes (x0, top, x1, bottom)."""
    nx, ny = len(xs) - 1, len(ys) - 1
    if nx < 3 or ny < 3:
        raise NoGrid()
    parent = list(range(nx * ny))

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for j in range(ny):
        for i in range(nx):
            y0, y1 = ys[j] + 3, ys[j + 1] - 3
            x0, x1 = xs[i] + 3, xs[i + 1] - 3
            if i + 1 < nx:
                x = xs[i + 1]
                if not present(mask, x - 2, x + 2, y0, y1, vertical=True):
                    parent[root(j * nx + i + 1)] = root(j * nx + i)
            if j + 1 < ny:
                y = ys[j + 1]
                if not present(mask, x0, x1, y - 2, y + 2, vertical=False):
                    parent[root((j + 1) * nx + i)] = root(j * nx + i)
    boxes = {}
    for j in range(ny):
        for i in range(nx):
            r = root(j * nx + i)
            x0, y0, x1, y1 = xs[i], ys[j], xs[i + 1], ys[j + 1]
            b = boxes.get(r)
            boxes[r] = (
                (x0, y0, x1, y1)
                if b is None
                else (min(b[0], x0), min(b[1], y0), max(b[2], x1), max(b[3], y1))
            )
    return list(boxes.values())


def otsu(a):
    """Threshold that best separates ink from paper in this cell."""
    hist = np.bincount(a.ravel(), minlength=256).astype(float)
    levels = np.arange(256)
    w0 = np.cumsum(hist)
    w1 = w0[-1] - w0
    m0 = np.cumsum(hist * levels)
    with np.errstate(divide="ignore", invalid="ignore"):
        between = (m0[-1] * w0 / w0[-1] - m0) ** 2 / (w0 * w1)
    return int(np.nanargmax(between))


def cell_text(gray, box):
    """OCR one cell; two preprocessings, keeping the more confident reading. Returns (lines, mean
    confidence)."""
    x0, y0, x1, y1 = (int(v) for v in box)
    crop = gray.crop((x0 + 3, y0 + 3, max(x0 + 4, x1 - 3), max(y0 + 4, y1 - 3)))
    if crop.width < 6 or crop.height < 6 or (np.asarray(crop) < 140).sum() < 15:
        return [], 0.0
    big = ImageOps.autocontrast(crop.resize((crop.width * 3, crop.height * 3), Image.LANCZOS))
    a = np.asarray(big)
    best = ([], 0.0, 0.0)
    for page in (big, Image.fromarray(np.where(a > otsu(a), 255, 0).astype("uint8"))):
        data = ocr(ImageOps.expand(page, border=20, fill=255), psm=6)
        confs = [float(c) for w, c in zip(data["text"], data["conf"]) if w.strip()]
        kept = [c for c in confs if c >= 30]
        score = sum(kept)
        if score > best[2]:
            best = (text_lines(data, min_conf=30), sum(confs) / len(confs) if confs else 0.0, score)
    return [line for line in best[0] if line.strip(" |")], best[1]


def read(image):
    """A picture -> (boxes, texts by box index, low-confidence box indexes, header lines, width,
    height)."""
    img = image.convert("RGB")
    # A fixed working width keeps text at a size Tesseract reads well after the 3x cell enlargement.
    img = img.resize((2400, round(img.height * 2400 / img.width)), Image.LANCZOS)
    rgb = np.asarray(img).astype(int)
    mask = dark_mask(rgb)
    scale = img.width / 2400
    xs, ys = lines(mask, scale)
    if len(xs) < 4 or len(ys) < 4:
        raise NoGrid()
    boxes = cells(mask, xs, ys)
    gray = ImageOps.grayscale(img)
    texts, unsure = {}, set()
    for n, box in enumerate(boxes):
        found, confidence = cell_text(gray, box)
        if found:
            texts[n] = [clean_line(re.sub(r"\s+", " ", t).strip(" |")) for t in found]
            if confidence < 70:
                unsure.add(n)
    top = min(ys)
    header = []
    if top > 20:
        crop = gray.crop((0, 0, img.width, int(top) - 2))
        header = text_lines(ocr(crop, psm=6), min_conf=30)
    return boxes, repair(boxes, texts), unsure, header, img.width, img.height


DAY_PREFIX = {"mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6, "sun": 7}
DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
LOOKALIKE = str.maketrans({"l": "1", "I": "1", "|": "1", "L": "1", "O": "0", "o": "0", "S": "5"})


def fuzzy_day(lines):
    letters = re.sub(r"[^a-z]", "", " ".join(lines).lower())
    for prefix, day in DAY_PREFIX.items():
        if letters.startswith(prefix):
            return day
    return None


def repair(boxes, texts):
    """Fill what OCR missed using the sheet's fixed structure: consecutive weekday columns and
    one-hour rows. Returns texts with day names and hour labels the PDF reader understands."""
    texts = dict(texts)
    left = min(b[0] for b in boxes)
    top = min(b[1] for b in boxes)
    header = sorted(
        (i for i, b in enumerate(boxes) if b[1] <= top + 5 and b[0] > left + 5), key=lambda i: boxes[i][0]
    )
    days = [fuzzy_day(texts.get(i, [])) for i in header]
    known = [(n, d) for n, d in enumerate(days) if d]
    if not known:
        return texts
    n0, d0 = known[0]
    for n, i in enumerate(header):
        texts[i] = [DAY_NAMES[(d0 - 1 + n - n0) % 7]]
    header_bottom = max(boxes[i][3] for i in header)
    rows = sorted(
        (i for i, b in enumerate(boxes) if b[0] <= left + 5 and b[1] >= header_bottom - 3),
        key=lambda i: boxes[i][1],
    )
    votes = {}
    for n, i in enumerate(rows):
        parts = re.split(r"[-–]", " ".join(texts.get(i, [])).translate(LOOKALIKE), maxsplit=1)
        for k, part in enumerate(parts[:2]):
            m = re.match(r"\s*(\d{1,2})[:.]\d{2}", part)
            if m and 1 <= int(m.group(1)) <= 12:
                base = (int(m.group(1)) - k - n - 1) % 12  # hour of row 0, minus one
                votes[base] = votes.get(base, 0) + 1
    if votes and max(votes.values()) >= 2:
        base = max(votes, key=votes.get)
        for n, i in enumerate(rows):
            start = (base + n) % 12 + 1
            texts[i] = [f"{start}:00-{start % 12 + 1}:00"]
    return texts


ROOMISH = re.compile(r"^[AB86][0-9lIOS|]{3}[A-Z84]?$")
ROOM_HEAD = {"8": "B", "6": "B"}
ROOM_TAIL = {"8": "B", "4": "A"}


def clean_line(line):
    """Common OCR look-alikes in room codes and batch labels ('B1l03' -> 'B103', 'Bl' -> 'B1')."""
    words = []
    # Department sheets print in capitals; OCR's lowercase look-alikes ('co2', 'Bi07A') are noise.
    for w in line.upper().split():
        if ROOMISH.match(w) and (not w.isdigit() or w[0] in ROOM_HEAD):
            # Rooms are a block letter, three digits and an optional wing letter: 82078 -> B207B.
            tail = w[4:]
            w = ROOM_HEAD.get(w[0], w[0]) + w[1:4].translate(LOOKALIKE) + ROOM_TAIL.get(tail, tail)
        elif re.fullmatch(r"[A-D][lI|]", w):
            w = w[0] + "1"
        words.append(w)
    return " ".join(words)


def batch_columns(cells):
    """Side-by-side batch cells are labelled in order (B1, B2, B3). A label OCR missed is
    restored from its position when its neighbours agree on the pattern."""
    blocks = {}
    for c in cells:
        if c["narrow"] and c["bbox"]:
            blocks.setdefault((c["weekday"], c["start"], c["end"]), []).append(c)
    for block in blocks.values():
        block.sort(key=lambda c: c["bbox"][0])
        labels = [re.fullmatch(r"([A-Z])(\d)", c["lines"][0]) for c in block]
        found = [(n, m) for n, m in enumerate(labels) if m]
        letters = {m.group(1) for _, m in found}
        if (
            len(block) < 2
            or not found
            or len(letters) != 1
            or any(int(m.group(2)) != n + 1 for n, m in found)
        ):
            continue
        letter = letters.pop()
        for n, c in enumerate(block):
            if not labels[n]:
                first = c["lines"][0]
                rest = c["lines"][1:] if len(first) <= 3 else c["lines"]
                c["lines"] = [f"{letter}{n + 1}", *rest]
                c["text"] = " ".join(c["lines"])
