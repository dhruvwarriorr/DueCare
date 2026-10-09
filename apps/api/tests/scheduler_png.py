"""Draw synthetic Somaiya scheduler Week-view screenshots: ruled grid, day headers, hour labels and
coloured class blocks with white text. Used instead of real screenshots, which carry student names."""

from PIL import Image, ImageDraw, ImageFont

DAYS = ["Sun 10/4", "Mon 10/5", "Tue 10/6", "Wed 10/7", "Thu 10/8", "Fri 10/9", "Sat 10/10"]
LINE = (92, 92, 92)


def font(size):
    return ImageFont.load_default(size=size)


def hour_label(minutes):
    h = minutes // 60
    return f"{h % 12 or 12}{'am' if h < 12 else 'pm'}"


def screenshot(first_minute, last_minute, events, slot=52):
    """events: [(day_index 0=Sun, start_min, end_min, rgb, [lines])]; the view shows
    first_minute..last_minute, which may begin or end part-way through a 30-minute row."""
    left, time_w, col_w, top, head_h = 148, 66, 170, 395, 39
    body_top = top + head_h
    px = slot / 30
    height = int((last_minute - first_minute) * px)
    img = Image.new("RGB", (left + time_w + 7 * col_w + 120, body_top + height + 160), (246, 246, 246))
    d = ImageDraw.Draw(img)
    right = left + time_w + 7 * col_w
    d.rectangle((left, top, right, body_top + height), fill=(255, 255, 255))
    y_of = lambda m: body_top + (m - first_minute) * px  # noqa: E731
    first_line = -(-first_minute // 30) * 30
    for m in range(first_line, last_minute + 1, 30):
        d.line((left, y_of(m), right, y_of(m)), fill=LINE, width=1)
        if m % 60 == 0 and y_of(m) + slot <= body_top + height + 1:
            d.text((left + 14, y_of(m) + 18), hour_label(m), fill=(20, 20, 20), font=font(15))
    for x in [left, left + time_w] + [left + time_w + i * col_w for i in range(1, 8)]:
        d.line((x, top, x, body_top + height), fill=LINE, width=1)
    for y in (top, body_top, body_top + height):
        d.line((left, y, right, y), fill=LINE, width=1)
    for i, name in enumerate(DAYS):
        d.text((left + time_w + i * col_w + 50, top + 12), name, fill=(20, 20, 20), font=font(15))
    for day, start, end, rgb, lines in events:
        x0 = left + time_w + day * col_w + 3
        y0, y1 = max(y_of(start) + 1, body_top + 1), min(y_of(end) - 1, body_top + height - 1)
        if y1 <= y0:
            continue
        d.rounded_rectangle((x0, y0, x0 + col_w - 7, y1), radius=3, fill=rgb)
        for n, line in enumerate(lines):
            ty = y_of(start) + 12 + n * 22
            if body_top < ty and ty + 18 < y1:
                d.text((x0 + 12, ty), line, fill=(255, 255, 255), font=font(15))
    return img
