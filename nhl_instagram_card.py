#!/usr/bin/env python3
"""
nhl_instagram_card.py
─────────────────────────────────────────────────────────────────
Generates a 1080x1080 Instagram-ready PNG from today's NHL data.

Pulls directly from the NHL API (same endpoints as nhl_daily_dashboard.py)
and renders a broadcast-style dark card with:

  CARD 1 — Today's matchups (up to 5 games, score if final / time if upcoming)
  CARD 2 — Yesterday's results with score + shot summary
  CARD 3 — League leaders (points + goals top 3)
  CARD 4 — Team form for teams playing today

Output: docs/instagram/YYYY-MM-DD.png  +  docs/instagram/latest.png

Usage:
    python nhl_instagram_card.py                  # today
    python nhl_instagram_card.py --date 2025-04-10
    python nhl_instagram_card.py --card results   # yesterday only
    python nhl_instagram_card.py --card matchups  # today's games only

Deps:  pip install pillow requests pandas
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import textwrap
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import requests

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    raise SystemExit("Missing Pillow — run: pip install pillow")

# ─────────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────────
W = H = 1080
PAD  = 56          # outer padding
TZ   = ZoneInfo("America/Toronto")
API  = "https://api-web.nhle.com"

# Dark broadcast palette
BG_TOP    = (4,   6,  22)
BG_BOT    = (8,  14,  36)
ACCENT    = (168, 85, 247)   # purple
ACCENT2   = (34, 211, 238)   # cyan
GOLD      = (255, 200,  50)
GREEN     = (52, 211, 153)
RED       = (248, 113, 113)
WHITE     = (255, 255, 255)
MUTED     = (140, 160, 200)
CARD_BG   = (14,  22,  54)
CARD_BRD  = (255, 255, 255, 30)   # RGBA

# Font paths (Poppins is available on ubuntu-latest GitHub runners)
_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/google-fonts/Poppins-Bold.ttf",
    "/usr/share/fonts/truetype/google-fonts/Poppins-Regular.ttf",
    "/usr/share/fonts/truetype/google-fonts/Poppins-Medium.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
]

def _find_font(bold: bool = False) -> str:
    prefs = (
        ["/usr/share/fonts/truetype/google-fonts/Poppins-Bold.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
         "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"]
        if bold else
        ["/usr/share/fonts/truetype/google-fonts/Poppins-Regular.ttf",
         "/usr/share/fonts/truetype/google-fonts/Poppins-Medium.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
         "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"]
    )
    for p in prefs:
        if os.path.exists(p): return p
    # last resort: any .ttf
    for p in _FONT_CANDIDATES:
        if os.path.exists(p): return p
    return ""   # Pillow default bitmap font fallback


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    path = _find_font(bold)
    if path:
        return ImageFont.truetype(path, size)
    return ImageFont.load_default()


# ─────────────────────────────────────────────────────────────────
# HTTP helpers (reuse from dashboard)
# ─────────────────────────────────────────────────────────────────
_S = requests.Session()
_S.headers["User-Agent"] = "nhl-ig-card/1.0"

def _get(url: str) -> Dict:
    r = _S.get(url, timeout=20)
    r.raise_for_status()
    return r.json()

def _try(url: str) -> Optional[Dict]:
    try: return _get(url)
    except Exception: return None

def tricode(side: Dict) -> str:
    ta = side.get("teamAbbrev")
    if isinstance(ta, dict): return (ta.get("default") or "").upper()
    if isinstance(ta, str):  return ta.upper()
    return (side.get("abbrev") or side.get("triCode") or "").upper()

def parse_et(s: str) -> str:
    if not s: return ""
    try:
        t = dt.datetime.fromisoformat(s.replace("Z","+00:00")).astimezone(TZ)
        return t.strftime("%I:%M %p").lstrip("0")
    except Exception: return s


# ─────────────────────────────────────────────────────────────────
# DRAWING PRIMITIVES
# ─────────────────────────────────────────────────────────────────

def make_canvas() -> Tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (W, H), BG_TOP)
    draw = ImageDraw.Draw(img, "RGBA")

    # Gradient background (vertical bands)
    for y in range(H):
        t = y / H
        r = int(BG_TOP[0] + (BG_BOT[0] - BG_TOP[0]) * t)
        g = int(BG_TOP[1] + (BG_BOT[1] - BG_TOP[1]) * t)
        b = int(BG_TOP[2] + (BG_BOT[2] - BG_TOP[2]) * t)
        draw.line([(0, y), (W, y)], fill=(r, g, b))

    # Subtle radial glow top-left (purple)
    for i in range(180, 0, -1):
        alpha = max(0, int(60 * (1 - i / 180)))
        draw.ellipse(
            [PAD - i, PAD - i, PAD + i * 3, PAD + i * 3],
            fill=(*ACCENT, alpha)
        )

    # Subtle radial glow bottom-right (cyan)
    for i in range(200, 0, -1):
        alpha = max(0, int(40 * (1 - i / 200)))
        draw.ellipse(
            [W - PAD - i * 3, H - PAD - i * 3, W - PAD + i, H - PAD + i],
            fill=(*ACCENT2, alpha)
        )

    return img, draw


def rounded_rect(
    draw: ImageDraw.ImageDraw,
    xy: Tuple[int, int, int, int],
    radius: int = 16,
    fill=None,
    outline=None,
    outline_width: int = 1,
) -> None:
    x0, y0, x1, y1 = xy
    if fill:
        draw.rounded_rectangle(xy, radius=radius, fill=fill)
    if outline:
        draw.rounded_rectangle(xy, radius=radius, outline=outline, width=outline_width)


def pill(
    draw: ImageDraw.ImageDraw,
    cx: int, cy: int,
    text: str,
    fnt: ImageFont.FreeTypeFont,
    bg=(255, 255, 255, 22),
    fg=WHITE,
    pad_x: int = 14,
    pad_y: int = 6,
) -> Tuple[int, int]:
    """Draw a pill-shaped label centered at (cx, cy). Returns (width, height)."""
    bbox = draw.textbbox((0, 0), text, font=fnt)
    tw = bbox[2] - bbox[0]; th = bbox[3] - bbox[1]
    pw = tw + pad_x * 2; ph = th + pad_y * 2
    x0 = cx - pw // 2; y0 = cy - ph // 2
    draw.rounded_rectangle([x0, y0, x0 + pw, y0 + ph], radius=ph // 2, fill=bg)
    draw.text((x0 + pad_x, y0 + pad_y), text, font=fnt, fill=fg)
    return pw, ph


def accent_bar(draw: ImageDraw.ImageDraw, x: int, y: int, w: int = 40, h: int = 4) -> None:
    """Tiny gradient accent underbar."""
    for i in range(w):
        t = i / w
        r = int(ACCENT[0] + (ACCENT2[0] - ACCENT[0]) * t)
        g = int(ACCENT[1] + (ACCENT2[1] - ACCENT[1]) * t)
        b = int(ACCENT[2] + (ACCENT2[2] - ACCENT[2]) * t)
        draw.line([(x + i, y), (x + i, y + h)], fill=(r, g, b))


def divider(draw: ImageDraw.ImageDraw, y: int, x0: int = PAD, x1: int = W - PAD) -> None:
    for x in range(x0, x1):
        t = (x - x0) / (x1 - x0)
        alpha = int(60 * (1 - abs(t * 2 - 1)))
        draw.line([(x, y), (x, y)], fill=(255, 255, 255, alpha))


def score_gradient_text(
    draw: ImageDraw.ImageDraw,
    xy: Tuple[int, int],
    text: str,
    fnt: ImageFont.FreeTypeFont,
) -> None:
    """Render text with purple→cyan gradient fill."""
    bbox = draw.textbbox(xy, text, font=fnt)
    tw = max(bbox[2] - bbox[0], 1)
    # Draw each character with interpolated color
    x, y = xy
    for ch in text:
        cb = draw.textbbox((x, y), ch, font=fnt)
        cw = cb[2] - cb[0]
        cx = x + cw // 2
        t  = max(0.0, min(1.0, (cx - bbox[0]) / tw))
        r  = int(ACCENT[0] + (ACCENT2[0] - ACCENT[0]) * t)
        g  = int(ACCENT[1] + (ACCENT2[1] - ACCENT[1]) * t)
        b  = int(ACCENT[2] + (ACCENT2[2] - ACCENT[2]) * t)
        draw.text((x, y), ch, font=fnt, fill=(r, g, b))
        x += cw


# ─────────────────────────────────────────────────────────────────
# SECTION RENDERERS
# ─────────────────────────────────────────────────────────────────

def draw_header(draw: ImageDraw.ImageDraw, date_str: str) -> int:
    """Returns y position after header."""
    y = PAD

    # Brand
    f_brand = font(28, bold=True)
    draw.text((PAD, y), "NHL DAILY", font=f_brand, fill=WHITE)
    bx = draw.textbbox((PAD, y), "NHL DAILY", font=f_brand)
    bw = bx[2] - bx[0]
    accent_bar(draw, PAD, y + bx[3] - bx[1] + 4, w=bw, h=3)

    # Date pill top-right
    f_date = font(18)
    pill(draw, W - PAD - 90, y + 16, date_str, f_date,
         bg=(*ACCENT2, 28), fg=ACCENT2)

    y += 56
    divider(draw, y)
    return y + 14


def draw_section_title(
    draw: ImageDraw.ImageDraw,
    y: int,
    title: str,
    emoji: str = "",
) -> int:
    f = font(20, bold=True)
    text = f"{emoji}  {title}" if emoji else title
    draw.text((PAD, y), text, font=f, fill=WHITE)
    bb = draw.textbbox((PAD, y), text, font=f)
    accent_bar(draw, PAD, bb[3] + 4, w=min(bb[2] - bb[0], 120), h=2)
    return bb[3] + 18


def draw_matchup_row(
    draw: ImageDraw.ImageDraw,
    y: int,
    away: str,
    home: str,
    time_or_score: str,
    is_final: bool,
    row_h: int = 64,
) -> int:
    """Draw one game row. Returns new y."""
    x0 = PAD; x1 = W - PAD

    # Card background
    rounded_rect(draw, (x0, y, x1, y + row_h - 6),
                 radius=14, fill=(*CARD_BG, 180), outline=(*ACCENT, 25), outline_width=1)

    # Away team
    f_team = font(22, bold=True)
    draw.text((x0 + 20, y + row_h // 2 - 12), away, font=f_team, fill=WHITE)

    # "@ " separator
    f_at = font(16)
    draw.text((x0 + 100, y + row_h // 2 - 8), "@", font=f_at, fill=MUTED)

    # Home team
    draw.text((x0 + 126, y + row_h // 2 - 12), home, font=f_team, fill=WHITE)

    # Score or time — right aligned
    f_score = font(22, bold=True)
    bb = draw.textbbox((0, 0), time_or_score, font=f_score)
    sw = bb[2] - bb[0]
    sx = x1 - 20 - sw

    if is_final:
        score_gradient_text(draw, (sx, y + row_h // 2 - 12), time_or_score, f_score)
        # FINAL badge
        f_fin = font(11)
        pill(draw, sx + sw // 2, y + row_h - 14, "FINAL", f_fin,
             bg=(52, 211, 153, 30), fg=GREEN, pad_x=8, pad_y=3)
    else:
        draw.text((sx, y + row_h // 2 - 12), time_or_score, font=f_score, fill=ACCENT2)

    return y + row_h


def draw_result_row(
    draw: ImageDraw.ImageDraw,
    y: int,
    away: str,
    home: str,
    a_score: Any,
    h_score: Any,
    a_shots: Any,
    h_shots: Any,
    row_h: int = 72,
) -> int:
    x0 = PAD; x1 = W - PAD

    rounded_rect(draw, (x0, y, x1, y + row_h - 6),
                 radius=14, fill=(*CARD_BG, 180), outline=(*ACCENT2, 20), outline_width=1)

    f_team  = font(20, bold=True)
    f_score = font(26, bold=True)
    f_sub   = font(12)

    # Winner highlight
    try:
        a_w = int(a_score) > int(h_score)
    except Exception:
        a_w = False

    a_col = WHITE if a_w else MUTED
    h_col = WHITE if not a_w else MUTED

    draw.text((x0 + 20, y + 14), away, font=f_team, fill=a_col)
    draw.text((x0 + 20, y + row_h - 28), home, font=f_team, fill=h_col)

    # Score center
    score_str = f"{a_score}  -  {h_score}"
    bb = draw.textbbox((0, 0), score_str, font=f_score)
    sx = W // 2 - (bb[2] - bb[0]) // 2
    score_gradient_text(draw, (sx, y + row_h // 2 - 16), score_str, f_score)

    # Shots right
    if a_shots is not None and h_shots is not None:
        shots_str = f"{a_shots} SOG {h_shots}"
        bb2 = draw.textbbox((0, 0), shots_str, font=f_sub)
        draw.text((x1 - 20 - (bb2[2] - bb2[0]), y + row_h // 2 - 8),
                  shots_str, font=f_sub, fill=MUTED)

    return y + row_h


def draw_leader_row(
    draw: ImageDraw.ImageDraw,
    y: int,
    rank: int,
    name: str,
    team: str,
    value: Any,
    stat: str,
    row_h: int = 52,
) -> int:
    x0 = PAD; x1 = W - PAD

    # Rank circle
    rank_colors = {1: (GOLD, (80, 60, 0)), 2: (MUTED, (40, 40, 40)), 3: ((205,127,50), (60,40,10))}
    rc, rbg = rank_colors.get(rank, (MUTED, (30, 30, 50)))
    draw.ellipse([x0, y + 10, x0 + 30, y + 40], fill=(*rbg, 220))
    f_rk = font(14, bold=True)
    draw.text((x0 + 7, y + 13), str(rank), font=f_rk, fill=rc)

    # Name
    f_name = font(18, bold=True)
    f_team = font(13)
    name_short = name[:20] if len(name) > 20 else name
    draw.text((x0 + 44, y + 10), name_short, font=f_name, fill=WHITE)
    draw.text((x0 + 44, y + 30), team, font=f_team, fill=MUTED)

    # Value
    f_val = font(22, bold=True)
    val_str = str(value)
    bb = draw.textbbox((0, 0), val_str, font=f_val)
    vw = bb[2] - bb[0]
    draw.text((x1 - 20 - vw, y + 12), val_str, font=f_val, fill=ACCENT2)

    f_stat = font(11)
    draw.text((x1 - 20 - vw, y + 36), stat, font=f_stat, fill=MUTED)

    return y + row_h


def draw_form_row(
    draw: ImageDraw.ImageDraw,
    y: int,
    tri: str,
    form_pct: Optional[float],
    spark: str,
    row_h: int = 46,
) -> int:
    x0 = PAD; x1 = W - PAD
    f_team = font(16, bold=True)
    f_pct  = font(15)
    f_dot  = font(14)

    # Team abbrev
    draw.text((x0, y + 12), tri, font=f_team, fill=WHITE)

    # Form bar (10 segments)
    if form_pct is not None:
        filled = round(form_pct * 10)
        seg_w = 14; gap = 3
        bx = x0 + 72
        for i in range(10):
            col = GREEN if i < filled else (60, 80, 120)
            draw.rounded_rectangle(
                [bx + i * (seg_w + gap), y + 14,
                 bx + i * (seg_w + gap) + seg_w, y + 30],
                radius=3, fill=col
            )
        # Percent label
        pct_str = f"{form_pct:.0%}"
        draw.text((bx + 10 * (seg_w + gap) + 8, y + 14), pct_str, font=f_pct, fill=GREEN if form_pct >= 0.55 else RED if form_pct < 0.4 else MUTED)
    else:
        draw.text((x0 + 72, y + 12), "—", font=f_pct, fill=MUTED)

    # Light divider
    divider(draw, y + row_h - 2, x0=x0, x1=x0 + 500)

    return y + row_h


def draw_footer(draw: ImageDraw.ImageDraw, y: int) -> None:
    f = font(13)
    draw.text((PAD, y), "Data: api-web.nhle.com  •  NHL EDGE API", font=f, fill=MUTED)
    f2 = font(13, bold=True)
    pill(draw, W - PAD - 70, y + 10, "@nhl_edge", f2,
         bg=(*ACCENT, 30), fg=ACCENT, pad_x=10, pad_y=5)


# ─────────────────────────────────────────────────────────────────
# DATA FETCHERS (thin wrappers, same as dashboard)
# ─────────────────────────────────────────────────────────────────

def fetch_games(date: str) -> List[Dict]:
    js = _try(f"{API}/v1/score/{date}")
    return (js or {}).get("games") or []

def fetch_leaders(cat: str, key: str, limit: int = 3) -> List[Dict]:
    js = _try(f"{API}/v1/skater-stats-leaders/current?categories={cat}&limit={limit}")
    return ((js or {}).get(key) or [])[:limit]

def game_state(g: Dict) -> str:
    return (g.get("gameState") or "").upper()

def is_final(g: Dict) -> bool:
    return game_state(g) in {"FINAL", "OFF"}

def is_live(g: Dict) -> bool:
    return game_state(g) in {"LIVE", "CRIT"}

def score_of(g: Dict) -> Tuple[Any, Any]:
    a = (g.get("awayTeam") or {}).get("score")
    h = (g.get("homeTeam") or {}).get("score")
    return a, h

def completed_games_for(tri: str) -> List[Dict]:
    js = _try(f"{API}/v1/club-schedule-season/{tri}/now")
    return [g for g in ((js or {}).get("games") or [])
            if game_state(g) in {"FINAL","OFF"}]

def last10_pct(tri: str, before: dt.date) -> Optional[float]:
    rows = [(dt.date.fromisoformat(str(g.get("gameDate",""))[:10]), g)
            for g in completed_games_for(tri)
            if g.get("gameDate")]
    rows = [(d, g) for d, g in rows if d < before]
    rows.sort(key=lambda x: x[0])
    last = [g for _, g in rows][-10:]
    pts = gp = 0
    for g in last:
        home = g.get("homeTeam") or {}; away = g.get("awayTeam") or {}
        h_tri = tricode(home)
        hs = home.get("score"); as_ = away.get("score")
        if hs is None or as_ is None: continue
        gp += 1
        is_home = h_tri == tri
        ts = hs if is_home else as_; os_ = as_ if is_home else hs
        if ts > os_: pts += 2
        else:
            lpt = ((g.get("gameOutcome") or {}).get("lastPeriodType") or "").upper()
            if lpt in {"OT","SO"}: pts += 1
    return pts / (2 * gp) if gp else None

# ─────────────────────────────────────────────────────────────────
# PBP shot totals (fast single pass)
# ─────────────────────────────────────────────────────────────────

def pbp_shots(game_id: int, a_tri: str, h_tri: str) -> Tuple[Optional[int], Optional[int]]:
    js = _try(f"{API}/v1/gamecenter/{game_id}/play-by-play")
    if not js: return None, None
    shots: Dict[str, int] = {a_tri: 0, h_tri: 0}
    id_map: Dict[int, str] = {}
    for k in ("awayTeam","homeTeam"):
        t = js.get(k) or {}
        tri = tricode(t); tid = t.get("id") or t.get("teamId")
        try:
            if tri and tid: id_map[int(tid)] = tri
        except Exception: pass
    for ev in (js.get("plays") or []):
        etype = str(ev.get("typeDescKey") or ev.get("typeCode") or "").lower()
        if etype not in {"shot-on-goal","sog","shot_on_goal"}: continue
        # resolve team
        raw = ((ev.get("details") or {}).get("teamAbbrev") or {})
        tri = (raw.get("default") if isinstance(raw, dict) else raw) or ""
        tri = str(tri).upper()
        if not tri:
            tid = (ev.get("details") or {}).get("eventOwnerTeamId")
            try: tri = id_map.get(int(tid), "")
            except Exception: tri = ""
        if tri in shots: shots[tri] += 1
    return shots.get(a_tri), shots.get(h_tri)


# ─────────────────────────────────────────────────────────────────
# CARD BUILDERS
# ─────────────────────────────────────────────────────────────────

def build_matchups_card(today: dt.date) -> Image.Image:
    img, draw = make_canvas()
    date_str = today.strftime("%b %-d, %Y")
    y = draw_header(draw, date_str)
    y = draw_section_title(draw, y, "TODAY'S GAMES", "🏒")

    games = fetch_games(today.isoformat())
    if not games:
        f = font(18)
        draw.text((PAD, y + 10), "No games scheduled today.", font=f, fill=MUTED)
    else:
        for g in games[:7]:  # max 7 rows in 1080px
            a = tricode(g.get("awayTeam") or {})
            h = tricode(g.get("homeTeam") or {})
            if not a or not h: continue
            if is_final(g) or is_live(g):
                a_s, h_s = score_of(g)
                label = f"{a_s}  –  {h_s}" if a_s is not None else "—"
                fin = is_final(g)
            else:
                label = parse_et(g.get("startTimeUTC",""))
                fin = False
            y = draw_matchup_row(draw, y, a, h, label, fin)
            y += 4

    draw_footer(draw, H - PAD - 20)
    return img


def build_results_card(yday: dt.date) -> Image.Image:
    img, draw = make_canvas()
    date_str = yday.strftime("%b %-d, %Y")
    y = draw_header(draw, date_str)
    y = draw_section_title(draw, y, "YESTERDAY'S RESULTS", "📊")

    games = [g for g in fetch_games(yday.isoformat()) if is_final(g)]
    if not games:
        f = font(18)
        draw.text((PAD, y + 10), "No completed games.", font=f, fill=MUTED)
    else:
        for g in games[:6]:
            a = tricode(g.get("awayTeam") or {})
            h = tricode(g.get("homeTeam") or {})
            a_s, h_s = score_of(g)
            gid = g.get("id") or g.get("gameId")
            a_shots = h_shots = None
            if gid:
                try: a_shots, h_shots = pbp_shots(int(gid), a, h)
                except Exception: pass
            y = draw_result_row(draw, y, a, h, a_s, h_s, a_shots, h_shots)
            y += 4

    draw_footer(draw, H - PAD - 20)
    return img


def build_leaders_card(today: dt.date) -> Image.Image:
    img, draw = make_canvas()
    date_str = today.strftime("%b %-d, %Y")
    y = draw_header(draw, date_str)
    y = draw_section_title(draw, y, "LEAGUE LEADERS", "⭐")

    def player_name(x: Dict) -> str:
        pn = (x.get("playerName") or {})
        if isinstance(pn, dict): return pn.get("default","—")
        if isinstance(pn, str): return pn
        fn = (x.get("firstName") or {}).get("default","")
        ln = (x.get("lastName") or {}).get("default","")
        return f"{fn} {ln}".strip() or "—"

    # Points
    f_sub = font(15, bold=True)
    draw.text((PAD, y), "Points", font=f_sub, fill=ACCENT2)
    y += 28
    pts = fetch_leaders("points", "points", 3)
    for i, p in enumerate(pts, 1):
        name = player_name(p)
        team = str(p.get("teamAbbrev") or "").upper() or "—"
        val  = p.get("value","—")
        y = draw_leader_row(draw, y, i, name, team, val, "PTS")
    y += 10

    divider(draw, y)
    y += 14

    # Goals
    draw.text((PAD, y), "Goals", font=f_sub, fill=ACCENT)
    y += 28
    goals = fetch_leaders("goals", "goals", 3)
    for i, p in enumerate(goals, 1):
        name = player_name(p)
        team = str(p.get("teamAbbrev") or "").upper() or "—"
        val  = p.get("value","—")
        y = draw_leader_row(draw, y, i, name, team, val, "G")

    draw_footer(draw, H - PAD - 20)
    return img


def build_form_card(today: dt.date) -> Image.Image:
    img, draw = make_canvas()
    date_str = today.strftime("%b %-d, %Y")
    y = draw_header(draw, date_str)
    y = draw_section_title(draw, y, "TEAM FORM — LAST 10", "📈")

    # Teams playing today
    games = fetch_games(today.isoformat())
    teams: List[str] = []
    for g in games:
        a = tricode(g.get("awayTeam") or {}); h = tricode(g.get("homeTeam") or {})
        if a: teams.append(a)
        if h: teams.append(h)
    teams = sorted(set(teams))

    if not teams:
        f = font(18)
        draw.text((PAD, y + 10), "No games today.", font=f, fill=MUTED)
    else:
        print(f"  [form] fetching last-10 for {len(teams)} teams...")
        form_data: List[Tuple[str, Optional[float]]] = []
        for tri in teams:
            fp = last10_pct(tri, today)
            form_data.append((tri, fp))
        form_data.sort(key=lambda x: (x[1] or 0), reverse=True)

        for tri, fp in form_data:
            if y > H - 140: break
            y = draw_form_row(draw, y, tri, fp, "")
            y += 2

    draw_footer(draw, H - PAD - 20)
    return img


def build_full_card(today: dt.date, yday: dt.date) -> Image.Image:
    """
    Combined 1080x1080 with all 4 sections squeezed in:
    header / matchups (top half) / results + leaders (bottom half)
    """
    img, draw = make_canvas()
    date_str = today.strftime("%b %-d, %Y")
    y = draw_header(draw, date_str)

    # TODAY section
    y = draw_section_title(draw, y, "TODAY", "🏒")
    games_today = fetch_games(today.isoformat())
    if not games_today:
        draw.text((PAD, y), "No games.", font=font(15), fill=MUTED)
        y += 30
    else:
        for g in games_today[:4]:
            a = tricode(g.get("awayTeam") or {}); h = tricode(g.get("homeTeam") or {})
            if not a or not h: continue
            if is_final(g) or is_live(g):
                a_s, h_s = score_of(g)
                label = f"{a_s}  –  {h_s}" if a_s is not None else "—"
                fin = is_final(g)
            else:
                label = parse_et(g.get("startTimeUTC",""))
                fin = False
            y = draw_matchup_row(draw, y, a, h, label, fin, row_h=56)
            y += 2

    y += 8
    divider(draw, y)
    y += 14

    # YESTERDAY section
    y = draw_section_title(draw, y, "YESTERDAY", "📊")
    games_yday = [g for g in fetch_games(yday.isoformat()) if is_final(g)]
    if not games_yday:
        draw.text((PAD, y), "No results.", font=font(15), fill=MUTED)
        y += 30
    else:
        for g in games_yday[:3]:
            a = tricode(g.get("awayTeam") or {}); h = tricode(g.get("homeTeam") or {})
            a_s, h_s = score_of(g)
            y = draw_result_row(draw, y, a, h, a_s, h_s, None, None, row_h=58)
            y += 2

    y += 8
    divider(draw, y)
    y += 14

    # LEADERS section (compact)
    y = draw_section_title(draw, y, "POINTS LEADERS", "⭐")

    def player_name(x: Dict) -> str:
        pn = (x.get("playerName") or {})
        if isinstance(pn, dict): return pn.get("default","—")
        if isinstance(pn, str): return pn
        fn = (x.get("firstName") or {}).get("default","")
        ln = (x.get("lastName") or {}).get("default","")
        return f"{fn} {ln}".strip() or "—"

    pts = fetch_leaders("points", "points", 3)
    for i, p in enumerate(pts, 1):
        if y > H - 100: break
        name = player_name(p); team = str(p.get("teamAbbrev") or "").upper()
        y = draw_leader_row(draw, y, i, name, team, p.get("value","—"), "PTS", row_h=46)

    draw_footer(draw, H - PAD - 20)
    return img


# ─────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────

CARDS = {
    "matchups": build_matchups_card,
    "results":  build_results_card,
    "leaders":  build_leaders_card,
    "form":     build_form_card,
}


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate NHL Instagram PNG card(s)")
    ap.add_argument("--date", default=None, help="YYYY-MM-DD (default: today ET)")
    ap.add_argument(
        "--card",
        default="all",
        choices=["all", "matchups", "results", "leaders", "form", "combined"],
        help="Which card(s) to generate (default: all)",
    )
    ap.add_argument("--outdir", default="docs/instagram")
    args = ap.parse_args()

    now   = dt.datetime.now(TZ)
    today = dt.date.fromisoformat(args.date) if args.date else now.date()
    yday  = today - dt.timedelta(days=1)

    out = Path(args.outdir)
    out.mkdir(parents=True, exist_ok=True)

    def save(img: Image.Image, name: str) -> None:
        path = out / f"{today.isoformat()}_{name}.png"
        latest = out / f"latest_{name}.png"
        img.save(path, "PNG", optimize=True)
        img.save(latest, "PNG", optimize=True)
        print(f"  [OK] {path}")

    if args.card == "all":
        print(f"[IG Cards] Generating all cards for {today}")
        print("  matchups...")
        save(build_matchups_card(today), "matchups")
        print("  results...")
        save(build_results_card(yday), "results")
        print("  leaders...")
        save(build_leaders_card(today), "leaders")
        print("  form...")
        save(build_form_card(today), "form")
        print("  combined...")
        save(build_full_card(today, yday), "combined")

    elif args.card == "combined":
        print(f"[IG Cards] Combined card for {today}")
        save(build_full_card(today, yday), "combined")

    else:
        print(f"[IG Cards] {args.card} card for {today}")
        if args.card == "results":
            save(CARDS[args.card](yday), args.card)   # type: ignore
        else:
            save(CARDS[args.card](today), args.card)  # type: ignore

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
