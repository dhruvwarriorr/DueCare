"""Build small synthetic timetable PDFs: ruled cells and text, like the college's generated sheets."""


def _escape(text):
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def build(header, days, times, cells, width=842, height=595):
    """cells: [(day_index, row_from, row_to, column, columns, [lines])]; rows/columns are 0-based."""
    left, top, time_w, row_h, head_h = 40, 120, 60, 30, 20
    day_w = (width - 2 * left - time_w) / len(days)
    ops = []

    def rect(x0, y0, x1, y1):
        # Thin filled rectangles form the ruling, as in the college's exported PDFs.
        for a, b, c, d in ((x0, y0, x1, y0), (x0, y1, x1, y1), (x0, y0, x0, y1), (x1, y0, x1, y1)):
            ops.append(
                f"{a:.1f} {height - max(b, d) - 0.3:.1f} {max(c - a, 0.6):.1f} {max(d - b, 0.6):.1f} re f"
            )

    def text(x, y, lines):
        for n, line in enumerate(lines):
            ops.append(f"BT /F1 7 Tf {x + 2:.1f} {height - y - 9 - n * 8:.1f} Td ({_escape(line)}) Tj ET")

    text(left, top - 30, [header])
    rect(left, top, left + time_w, top + head_h)
    text(left, top + 2, ["Time/Day"])
    for i, day in enumerate(days):
        x = left + time_w + i * day_w
        rect(x, top, x + day_w, top + head_h)
        text(x, top + 2, [day])
    filled = set()
    for d, r0, r1, col, cols, lines in cells:
        x0 = left + time_w + d * day_w + col * day_w / cols
        y0 = top + head_h + r0 * row_h
        rect(x0, y0, x0 + day_w / cols, y0 + (r1 - r0 + 1) * row_h)
        text(x0, y0 + 2, lines)
        filled |= {(d, r) for r in range(r0, r1 + 1)}
    for r, label in enumerate(times):
        y = top + head_h + r * row_h
        rect(left, y, left + time_w, y + row_h)
        text(left, y + 2, [label])
        for d in range(len(days)):
            if (d, r) not in filled:
                x = left + time_w + d * day_w
                rect(x, y, x + day_w, y + row_h)
    stream = "\n".join(ops).encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {width} {height}] /Contents 4 0 R "
        "/Resources << /Font << /F1 5 0 R >> >> >>".encode(),
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for n, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{n} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


TIMES = ["9:00-10:00", "10:00-11:00", "11:00-12:00", "12:00-1:00", "1:00-2:00", "2:00-3:00", "3:00-4:00"]
DAYS = ["Monday", "Tuesday", "Wednesday"]


def sample():
    """A division B timetable: theory, a two-hour batch lab block, numbered groups and lunch."""
    return build(
        "Class: SY B. Tech COMP B          Year: 2026-2027 Semester: ODD",
        DAYS,
        TIMES,
        [
            (0, 0, 0, 0, 1, ["DS B204 JMR"]),
            (0, 1, 1, 0, 1, ["DBMS B202 ASH"]),
            (0, 4, 4, 0, 1, ["LUNCH BREAK"]),
            (0, 5, 6, 0, 3, ["B1", "WDL", "B115B SIP"]),
            (0, 5, 6, 1, 3, ["B2", "DBMS", "B116A JMR"]),
            (0, 5, 6, 2, 3, ["B3", "DS B109", "PVK"]),
            (1, 2, 3, 0, 2, ["DA_1", "B201 MMK"]),
            (1, 2, 3, 1, 2, ["DA_2", "B202 SNJ"]),
            (1, 4, 4, 0, 1, ["LUNCH BREAK"]),
            (2, 3, 3, 0, 1, ["COA B205 KMK"]),
            (2, 4, 4, 0, 1, ["LUNCH BREAK"]),
        ],
    )
