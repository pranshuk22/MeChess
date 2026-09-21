#!/usr/bin/env python3
"""Generates docs/assets/banner.svg (the repository image) and docs/assets/logo.svg: an angular, faceted knight in the Catppuccin Mocha
palette (green accent on dark), built from an outline that is triangulated and subdivided, so every shape is deterministic.
Usage: python tools/make_banner.py"""
import math
import random
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "docs" / "assets"
# Catppuccin Mocha
BASE, MANTLE, CRUST, SURFACE0, SURFACE1, TEXT, SUB = "#1e1e2e", "#181825", "#11111b", "#313244", "#45475a", "#cdd6f4", "#a6adc8"
GREEN, TEAL, SKY, MAUVE = "#a6e3a1", "#94e2d5", "#89dceb", "#cba6f7"
FONT = "'JetBrains Mono','SF Mono',Menlo,Consolas,'DejaVu Sans Mono',monospace"

# the knight, facing left, in a 400 x 500 box (clockwise from the bottom left of the neck); the back of the neck is a jagged mane
OUTLINE = [(100, 440), (300, 440), (314, 392), (332, 338), (312, 318), (338, 280), (306, 262), (330, 226), (298, 212), (318, 176), (284, 166),
           (296, 128), (266, 132), (262, 84), (246, 40), (222, 84), (196, 96), (168, 112), (128, 148), (86, 196), (46, 236), (52, 268),
           (90, 278), (124, 256), (152, 272), (134, 326), (114, 384)]
BASE_PLATE = [(70, 440), (330, 440), (344, 480), (56, 480)]


def area(p):
    return sum(p[i][0] * p[(i + 1) % len(p)][1] - p[(i + 1) % len(p)][0] * p[i][1] for i in range(len(p))) / 2


def inside(pt, tri):
    (x, y), (a, b, c) = pt, tri
    d = lambda p1, p2, p3: (p1[0] - p3[0]) * (p2[1] - p3[1]) - (p2[0] - p3[0]) * (p1[1] - p3[1])
    d1, d2, d3 = d(pt, a, b), d(pt, b, c), d(pt, c, a)
    return not ((d1 < 0 or d2 < 0 or d3 < 0) and (d1 > 0 or d2 > 0 or d3 > 0))


def ear_clip(poly):
    """Triangulate a simple polygon."""
    pts = list(poly) if area(poly) > 0 else list(reversed(poly))
    tris = []
    while len(pts) > 3:
        for i in range(len(pts)):
            a, b, c = pts[i - 1], pts[i], pts[(i + 1) % len(pts)]
            if (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0]) <= 0:      # reflex vertex: not an ear
                continue
            if any(inside(p, (a, b, c)) for p in pts if p not in (a, b, c)):
                continue
            tris.append((a, b, c))
            pts.pop(i)
            break
        else:
            raise ValueError("cannot triangulate")
    tris.append(tuple(pts))
    return tris


def split4(t):
    a, b, c = t
    ab, bc, ca = [((p[0] + q[0]) / 2, (p[1] + q[1]) / 2) for p, q in ((a, b), (b, c), (c, a))]
    return [(a, ab, ca), (ab, b, bc), (ca, bc, c), (ab, bc, ca)]


def mix(c1, c2, t):
    a, b = [tuple(int(c[i:i + 2], 16) for i in (1, 3, 5)) for c in (c1, c2)]
    return "#%02x%02x%02x" % tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def facets():
    rnd = random.Random(7)
    tris = [s for t in ear_clip(OUTLINE) for s in (split4(t) if abs(area(list(t))) > 900 else [t])]
    xs, ys = [p[0] for p in OUTLINE], [p[1] for p in OUTLINE]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    out = []
    for t in tris:
        cx, cy = sum(p[0] for p in t) / 3, sum(p[1] for p in t) / 3
        light = 0.9 * (1 - (cx - x0) / (x1 - x0)) * 0.62 + 0.9 * (1 - (cy - y0) / (y1 - y0)) * 0.42 + 0.06 + rnd.uniform(-0.2, 0.2)
        light = max(0.0, min(1.0, light)) ** 1.35                 # more contrast: bright on the face and top, deep in the shadow of the mane
        col = mix("#0d221e", GREEN, light)
        if rnd.random() < 0.16:
            col = mix(col, TEAL, 0.55)
        out.append((t, col))
    return out


def pts(t):
    return " ".join(f"{x:.1f},{y:.1f}" for x, y in t)


def knight_group(gid="k"):
    f = facets()
    body = "".join(f'<polygon points="{pts(t)}" fill="{c}" stroke="{GREEN}" stroke-opacity="0.30" stroke-width="0.8" stroke-linejoin="round"/>' for t, c in f)
    plate = ear_clip(BASE_PLATE)
    plate_svg = "".join(f'<polygon points="{pts(t)}" fill="{mix("#16302b", GREEN, 0.28 + 0.12 * i)}" stroke="{GREEN}" stroke-opacity="0.35" stroke-width="0.8"/>'
                        for i, t in enumerate(plate))
    eye = f'<polygon points="150,150 178,144 168,160" fill="{CRUST}" stroke="{GREEN}" stroke-width="1.6" filter="url(#glow)"/>'
    nostril = f'<polygon points="62,236 76,232 70,244" fill="{CRUST}" opacity="0.9"/>'
    edge = f'<polygon points="{pts(OUTLINE)}" fill="none" stroke="{GREEN}" stroke-width="2.2" stroke-linejoin="miter" filter="url(#glow)"/>'
    bevel = f'<polyline points="70,440 330,440" stroke="{GREEN}" stroke-width="2" filter="url(#glow)"/>'
    return f'<g id="{gid}">{plate_svg}{body}{eye}{nostril}{edge}{bevel}</g>'


def defs():
    return f"""<defs>
  <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{CRUST}"/><stop offset="0.55" stop-color="{MANTLE}"/><stop offset="1" stop-color="{BASE}"/></linearGradient>
  <radialGradient id="halo" cx="0.5" cy="0.5" r="0.5"><stop offset="0" stop-color="{GREEN}" stop-opacity="0.22"/><stop offset="0.6" stop-color="{GREEN}" stop-opacity="0.05"/><stop offset="1" stop-color="{GREEN}" stop-opacity="0"/></radialGradient>
  <linearGradient id="fade" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff" stop-opacity="0"/><stop offset="1" stop-color="#fff" stop-opacity="0.9"/></linearGradient>
  <mask id="fadeMask"><rect x="0" y="0" width="1280" height="640" fill="url(#fade)"/></mask>
  <pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse"><path d="M40 0H0V40" fill="none" stroke="{SURFACE0}" stroke-opacity="0.55" stroke-width="1"/></pattern>
  <filter id="glow" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="3.2" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
  <filter id="soft" x="-30%" y="-30%" width="160%" height="160%"><feGaussianBlur stdDeviation="14"/></filter>
</defs>"""


def traces():
    """Circuit-style traces at 45 degree corners, faint, with nodes."""
    paths = [("M40 96 H150 L190 56 H300", 0.5), ("M40 150 H96 L124 178 H210", 0.35), ("M1240 70 H1110 L1076 104 H960", 0.45), ("M1240 124 H1170 L1146 148 H1040", 0.3),
             ("M40 560 H120 L160 520 H262", 0.4), ("M1240 560 H1120 L1080 600 H940", 0.4), ("M1240 512 H1190 L1166 536 H1100", 0.28)]
    svg = ""
    for d, o in paths:
        svg += f'<path d="{d}" fill="none" stroke="{GREEN}" stroke-opacity="{o}" stroke-width="1.6" stroke-linejoin="round"/>'
        end = d.split()[-1]
        x = float(end.lstrip("HV")) if end[0] == "H" else None
        # node at both ends
        first = d.split()[0][1:], d.split()[1]
        svg += f'<circle cx="{first[0]}" cy="{first[1]}" r="3.4" fill="{BASE}" stroke="{GREEN}" stroke-opacity="{min(1, o + 0.3)}" stroke-width="1.6"/>'
    return svg


def board_strip():
    sq, x0, y0 = 40, 560, 600
    s = ""
    for i in range(18):
        for j in range(2):
            if (i + j) % 2 == 0:
                s += f'<rect x="{x0 + i * sq}" y="{y0 + j * sq}" width="{sq}" height="{sq}" fill="{GREEN}" fill-opacity="0.05"/>'
    return f'<g mask="url(#fadeMask)" opacity="0.9">{s}</g>'


def knight_move():
    """An L-shaped knight move (two forward, one across) with square labels."""
    return (f'<g font-family="{FONT}" font-size="15" fill="{SUB}"><path d="M1082 232 V292 H1122" fill="none" stroke="{GREEN}" stroke-width="2.4" stroke-dasharray="7 6" stroke-linecap="round"/>'
            f'<circle cx="1082" cy="232" r="5" fill="{GREEN}"/><path d="M1122 292 l-11 -7 v14 z" fill="{GREEN}"/>'
            f'<text x="1094" y="228">g1</text><text x="1134" y="298">f3</text></g>')


def pills(items, x=570, y=452):
    """Small labelled boxes sized to their text (a monospace character is about 9.7 px wide at 16 px)."""
    out, cx = "", 0
    for label, col in items:
        w = round(len(label) * 9.7 + 26)
        out += (f'<rect x="{cx}" y="0" width="{w}" height="34" rx="3" fill="{SURFACE0}" stroke="{col}" stroke-opacity="0.55"/>'
                f'<text x="{cx + w / 2:.0f}" y="22" text-anchor="middle" fill="{col}">{label}</text>')
        cx += w + 12
    return f'<g transform="translate({x},{y})" font-size="16">{out}</g>'


def banner():
    k = knight_group()
    title = "MeChess"
    return f"""<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="1280" height="640" viewBox="0 0 1280 640" role="img" aria-labelledby="t d">
<title id="t">MeChess</title><desc id="d">A faceted green knight on a dark background, with the words MeChess: a chess engine that plays like you.</desc>
{defs()}
<rect width="1280" height="640" fill="url(#bg)"/>
<rect width="1280" height="640" fill="url(#grid)"/>
<ellipse cx="300" cy="330" rx="330" ry="300" fill="url(#halo)"/>
{traces()}
{board_strip()}
<g transform="translate(112,64) scale(1.0)">
  <g opacity="0.55" filter="url(#soft)"><use xlink:href="#k" href="#k" transform="translate(0,0)"/></g>
  {k}
  <clipPath id="s1"><rect x="-10" y="196" width="420" height="13"/></clipPath>
  <clipPath id="s2"><rect x="-10" y="312" width="420" height="8"/></clipPath>
  <g clip-path="url(#s1)" transform="translate(20,0)" opacity="0.9"><use xlink:href="#k" href="#k"/></g>
  <g clip-path="url(#s2)" transform="translate(-16,0)" opacity="0.85"><use xlink:href="#k" href="#k"/></g>
  <rect x="-10" y="196" width="420" height="1.4" fill="{TEAL}" opacity="0.8"/><rect x="-10" y="312" width="420" height="1.2" fill="{TEAL}" opacity="0.6"/>
</g>
<g font-family="{FONT}">
  <text x="570" y="196" font-size="19" fill="{GREEN}" opacity="0.9">$ chessme mechess --elo 1600</text>
  <text x="566" y="308" font-size="104" font-weight="800" fill="{TEXT}" letter-spacing="-3">{title}</text>
  <text x="566" y="308" font-size="104" font-weight="800" fill="{GREEN}" letter-spacing="-3" opacity="0.28" filter="url(#glow)">{title}</text>
  <rect x="1000" y="238" width="30" height="66" fill="{GREEN}" filter="url(#glow)"/>
  <text x="570" y="368" font-size="34" fill="{TEXT}">An engine that plays like <tspan fill="{GREEN}" font-weight="700">you</tspan>.</text>
  <text x="570" y="416" font-size="20" fill="{SUB}">C++ engine  ·  learns from your games  ·  Elo dial</text>
  {pills([("open research", GREEN), ("UCI engine", TEAL), ("human-like play", SKY)])}
</g>
{knight_move()}
<rect x="0.5" y="0.5" width="1279" height="639" fill="none" stroke="{GREEN}" stroke-opacity="0.22"/>
</svg>
"""


def logo():
    k = knight_group("kl")
    return f"""<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="512" height="512" viewBox="0 0 512 512" role="img" aria-label="MeChess knight">
{defs().replace('width="1280" height="640"', 'width="512" height="512"')}
<rect width="512" height="512" rx="72" fill="url(#bg)"/>
<rect width="512" height="512" rx="72" fill="url(#grid)" opacity="0.6"/>
<ellipse cx="256" cy="270" rx="230" ry="220" fill="url(#halo)"/>
<g transform="translate(60,22) scale(0.9)">{k}</g>
<rect x="0.5" y="0.5" width="511" height="511" rx="72" fill="none" stroke="{GREEN}" stroke-opacity="0.35"/>
</svg>
"""


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "banner.svg").write_text(banner(), encoding="utf-8")
    (OUT / "logo.svg").write_text(logo(), encoding="utf-8")
    print("wrote", OUT / "banner.svg", OUT / "logo.svg")
