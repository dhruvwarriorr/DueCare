"""The DueCare mark: an answer bubble with a printed D, half-marked in pencil-rose.
One geometry (a 100-unit box) drives every rendering."""
import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageChops

GRAPHITE, ROSE, WHITE, PAPER = "#18171B", "#C21C58", "#FFFFFF", "#F4F5F8"
S = 8  # supersampling
PENCIL_POINTS = [(-10, -10), (64.2, -10), (39.8, 110), (-10, 110)]

def stadium(d, box, fill=None, outline=None, width=0, scale=1):
    x0, y0, x1, y1 = [v * scale for v in box]
    d.rounded_rectangle([x0, y0, x1, y1], radius=(y1 - y0) / 2, fill=fill, outline=outline, width=int(width * scale))

def d_glyph(size, scale, off=(0, 0)):
    m = Image.new("L", (size, size), 0); g = ImageDraw.Draw(m)
    ox, oy = off
    def p(x, y): return (ox + x * scale, oy + y * scale)
    # Outer D: stem rect + bowl (half disc radius 13 at (53,50)).
    g.rectangle([p(34, 37), p(53, 63)], fill=255)
    g.pieslice([p(40, 37), p(66, 63)], -90, 90, fill=255)
    # Counter.
    g.rectangle([p(44, 45), p(53, 55)], fill=0)
    g.pieslice([p(48, 45), p(58, 55)], -90, 90, fill=0)
    return m

def mark(size, bg=None, ring=WHITE, fill=ROSE, d_out=WHITE, d_in=WHITE, extent=1.0, rounded=False):
    """Render at `size` px; the 100-unit box spans `extent` of the canvas, centred."""
    big = size * S
    scale = big * extent / 100
    off = ((big - 100 * scale) / 2,) * 2
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if bg:
        if rounded: d.rounded_rectangle([0, 0, big - 1, big - 1], radius=big * 0.23, fill=bg)
        else: d.rectangle([0, 0, big, big], fill=bg)
    def box(b): return [off[0] + b[0] * scale, off[1] + b[1] * scale, off[0] + b[2] * scale, off[1] + b[3] * scale]
    # Pencil fill, clipped to the bubble's inside.
    inner = Image.new("L", (big, big), 0)
    ImageDraw.Draw(inner).rounded_rectangle(box((11.5, 27.5, 88.5, 72.5)), radius=22.5 * scale, fill=255)
    poly = Image.new("L", (big, big), 0)
    ImageDraw.Draw(poly).polygon([(off[0] + x * scale, off[1] + y * scale) for x, y in PENCIL_POINTS], fill=255)
    marked = ImageChops.multiply(inner, poly)
    img.paste(Image.new("RGBA", (big, big), fill), (0, 0), marked)
    # The printed D: one tone outside the mark, another inside it.
    D = d_glyph(big, scale, off)
    img.paste(Image.new("RGBA", (big, big), d_out), (0, 0), ImageChops.subtract(D, marked))
    img.paste(Image.new("RGBA", (big, big), d_in), (0, 0), ImageChops.multiply(D, marked))
    # The bubble's printed outline.
    # SVG centres its 7-unit stroke on the path; Pillow draws it inside the box.
    d.rounded_rectangle(box((4.5, 20.5, 95.5, 79.5)), radius=29.5 * scale, outline=ring, width=int(7 * scale))
    return img.resize((size, size), Image.LANCZOS)

if __name__ == "__main__" and len(sys.argv) == 2:
    out = Path(sys.argv[1])
    sheet = Image.new("RGB", (1500, 560), PAPER)
    sheet.paste(mark(420, bg=GRAPHITE, extent=0.74, rounded=True), (40, 70), mark(420, bg=GRAPHITE, extent=0.74, rounded=True))
    light = mark(420, ring=ROSE, fill=ROSE, d_out=GRAPHITE, d_in=WHITE, extent=0.9)
    sheet.paste(light, (500, 70), light)
    for i, s in enumerate([144, 96, 48]):
        m = mark(s, bg=GRAPHITE, extent=0.74, rounded=True)
        sheet.paste(m, (960 + i * 170, 220), m)
    sheet.save(out)


RING = "M34,24 H66 A26,26 0 0 1 66,76 H34 A26,26 0 0 1 34,24 Z"
INNER = "M34,27.5 H66 A22.5,22.5 0 0 1 66,72.5 H34 A22.5,22.5 0 0 1 34,27.5 Z"
PENCIL = "M" + " L".join(f"{x},{y}" for x, y in PENCIL_POINTS) + " Z"
D = "M34,37 H53 A13,13 0 0 1 53,63 H34 Z M44,45 V55 H53 A5,5 0 0 0 53,45 Z"


def vector(size_dp, viewport, scale, shift, body, comment):
    return f'''<?xml version="1.0" encoding="utf-8"?>
<!-- {comment} -->
<vector xmlns:android="http://schemas.android.com/apk/res/android"
    android:width="{size_dp}dp"
    android:height="{size_dp}dp"
    android:viewportWidth="{viewport}"
    android:viewportHeight="{viewport}">
    <group android:scaleX="{scale}" android:scaleY="{scale}" android:translateX="{shift}" android:translateY="{shift}">
{body}
    </group>
</vector>
'''


def android(res):
    res = Path(res)
    (res / "drawable").mkdir(exist_ok=True)
    (res / "mipmap-anydpi-v26").mkdir(exist_ok=True)
    colour = f'''        <group>
            <clip-path android:pathData="{INNER}" />
            <path android:fillColor="{ROSE}" android:pathData="{PENCIL}" />
        </group>
        <path android:fillColor="#FFFFFFFF" android:fillType="evenOdd" android:pathData="{D}" />
        <path android:strokeColor="#FFFFFFFF" android:strokeWidth="7" android:pathData="{RING}" />'''
    # One colour: the marked part is solid and the D shows through it.
    silhouette = f'''        <group>
            <clip-path android:pathData="{INNER}" />
            <path android:fillColor="#FFFFFFFF" android:fillType="evenOdd" android:pathData="{PENCIL} {D}" />
        </group>
        <path android:strokeColor="#FFFFFFFF" android:strokeWidth="7" android:pathData="{RING}" />'''
    # Adaptive icons: a 108dp canvas whose central 66dp always shows.
    (res / "drawable/ic_launcher_foreground.xml").write_text(
        vector(108, 108, 0.62, 23, colour, "The DueCare mark: an answer bubble with a printed D, half marked in rose."))
    (res / "drawable/ic_launcher_monochrome.xml").write_text(
        vector(108, 108, 0.62, 23, silhouette, "The mark in one colour, for Android's themed icons."))
    (res / "drawable/ic_stat_duecare.xml").write_text(
        vector(24, 100, 1.0, 0, silhouette, "The mark as a one-colour status bar icon."))
    adaptive = '''<?xml version="1.0" encoding="utf-8"?>
<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">
    <background android:drawable="@color/ic_launcher_background" />
    <foreground android:drawable="@drawable/ic_launcher_foreground" />
    <monochrome android:drawable="@drawable/ic_launcher_monochrome" />
</adaptive-icon>
'''
    (res / "mipmap-anydpi-v26/ic_launcher.xml").write_text(adaptive)
    (res / "values").mkdir(exist_ok=True)
    (res / "values/colors.xml").write_text(f'''<?xml version="1.0" encoding="utf-8"?>
<resources>
    <color name="ic_launcher_background">{GRAPHITE}</color>
    <color name="splash_background">{PAPER}</color>
</resources>
''')
    (res / "values-night").mkdir(exist_ok=True)
    (res / "values-night/colors.xml").write_text('''<?xml version="1.0" encoding="utf-8"?>
<resources>
    <color name="splash_background">#121014</color>
</resources>
''')
    # Pre-Oreo launchers get a rounded-square bitmap.
    for name, px in {"mdpi": 48, "hdpi": 72, "xhdpi": 96, "xxhdpi": 144, "xxxhdpi": 192}.items():
        mark(px, bg=GRAPHITE, extent=0.74, rounded=True).save(res / f"mipmap-{name}/ic_launcher.png")
    # The splash on older Android: the icon centred on the paper ground.
    mark(288, bg=GRAPHITE, extent=0.74, rounded=True).save(res / "drawable/splash_mark.png")


def web(app):
    """Generate Next.js metadata icons: python tool/mark.py <app-dir> web."""
    app = Path(app)
    app.mkdir(parents=True, exist_ok=True)
    (app / "icon.svg").write_text(f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
  <defs>
    <clipPath id="in"><path d="{INNER}"/></clipPath>
  </defs>
  <rect width="100" height="100" rx="23" fill="{GRAPHITE}"/>
  <g transform="translate(13 13) scale(0.74)">
    <path clip-path="url(#in)" d="{PENCIL}" fill="{ROSE}"/>
    <path fill-rule="evenodd" fill="{WHITE}" d="{D}"/>
    <path d="{RING}" fill="none" stroke="{WHITE}" stroke-width="7"/>
  </g>
</svg>
''')
    # iOS applies its own corner mask; supply an opaque, square image.
    mark(180, bg=GRAPHITE, extent=0.74).convert("RGB").save(app / "apple-icon.png")


if __name__ == "__main__" and len(sys.argv) > 2:
    if sys.argv[2] == "android":
        android(sys.argv[1])
    elif sys.argv[2] == "web":
        web(sys.argv[1])
