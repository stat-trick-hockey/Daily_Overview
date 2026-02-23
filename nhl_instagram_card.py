#!/usr/bin/env python3
"""
nhl_instagram_card.py  —  v2 REDESIGN
──────────────────────────────────────────────────────────────────────
Broadcast sports editorial aesthetic:
  • Deep charcoal base with ice-blue & electric-yellow accents
  • Bold condensed typography with tight tracking
  • Diagonal slash dividers & geometric corner marks
  • Hard-edged stat chips, no soft glow blobs
  • Each card feels like an ESPN/Sportsnet graphic

Cards generated:
  combined   — all-in-one daily post (recommended)
  matchups   — today's schedule
  results    — yesterday's scores
  leaders    — points + goals top 5
  form       — last-10 form for teams playing today

Output: docs/instagram/YYYY-MM-DD_{card}.png
        docs/instagram/latest_{card}.png

Deps: pip install pillow requests pandas
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import requests

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    raise SystemExit("Missing Pillow — run: pip install pillow")

# ─────────────────────────────────────────────────────────────────
# DESIGN SYSTEM
# ─────────────────────────────────────────────────────────────────
W = H = 1080

# Palette — charcoal ice editorial
C_BG      = (10,  12,  18)
C_BG2     = (16,  20,  30)
C_BG3     = (22,  28,  42)
C_ICE     = (0,  200, 255)
C_YELLOW  = (255, 210,   0)
C_WHITE   = (245, 248, 255)
C_MUTED   = (120, 140, 170)
C_DIM     = (55,   65,  85)
C_GREEN   = (0,  220, 120)
C_RED     = (255,  75,  75)
C_ORANGE  = (255, 140,   0)

PAD = 52
TZ  = ZoneInfo("America/Toronto")
API = "https://api-web.nhle.com"

# ─────────────────────────────────────────────────────────────────
# FONTS
# ─────────────────────────────────────────────────────────────────
_BOLD  = "/usr/share/fonts/truetype/google-fonts/Poppins-Bold.ttf"
_REG   = "/usr/share/fonts/truetype/google-fonts/Poppins-Regular.ttf"
_MED   = "/usr/share/fonts/truetype/google-fonts/Poppins-Medium.ttf"
_COND  = "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf"
_COND2 = "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed.ttf"

def _fp(p: str, fallback: str = "") -> str:
    return p if os.path.exists(p) else fallback

def F(size: int, style: str = "bold") -> ImageFont.FreeTypeFont:
    m = {
        "bold": _fp(_BOLD,  _fp(_COND,  "")),
        "reg":  _fp(_REG,   _fp(_COND2, "")),
        "med":  _fp(_MED,   _fp(_COND2, "")),
        "cond": _fp(_COND,  _fp(_BOLD,  "")),
    }
    p = m.get(style, "")
    return ImageFont.truetype(p, size) if p else ImageFont.load_default()

# ─────────────────────────────────────────────────────────────────
# HTTP
# ─────────────────────────────────────────────────────────────────
_S = requests.Session()
_S.headers["User-Agent"] = "nhl-ig-card/2.0"

def _get(url: str) -> Dict:
    r = _S.get(url, timeout=20); r.raise_for_status(); return r.json()

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
        return t.strftime("%-I:%M %p ET")
    except Exception: return s

def fetch_games(date: str) -> List[Dict]:
    return (_try(f"{API}/v1/score/{date}") or {}).get("games") or []

def fetch_leaders(cat: str, key: str, limit: int = 5) -> List[Dict]:
    js = _try(f"{API}/v1/skater-stats-leaders/current?categories={cat}&limit={limit}")
    return ((js or {}).get(key) or [])[:limit]

def is_final(g: Dict) -> bool:
    return (g.get("gameState") or "").upper() in {"FINAL","OFF"}

def is_live(g: Dict) -> bool:
    return (g.get("gameState") or "").upper() in {"LIVE","CRIT"}

def score_of(g: Dict) -> Tuple[Any, Any]:
    a = (g.get("awayTeam") or {}).get("score")
    h = (g.get("homeTeam") or {}).get("score")
    return a, h

def completed_games_for(tri: str) -> List[Dict]:
    js = _try(f"{API}/v1/club-schedule-season/{tri}/now")
    return [g for g in ((js or {}).get("games") or [])
            if (g.get("gameState") or "").upper() in {"FINAL","OFF"}]

def last10_results(tri: str, before: dt.date, n: int = 10) -> List[str]:
    rows = []
    for g in completed_games_for(tri):
        ds = str(g.get("gameDate",""))[:10]
        try: d = dt.date.fromisoformat(ds)
        except: continue
        if d < before: rows.append((d, g))
    rows.sort(key=lambda x: x[0])
    last = [g for _, g in rows][-n:]
    out = []
    for g in last:
        home = g.get("homeTeam") or {}; away = g.get("awayTeam") or {}
        hs = home.get("score"); as_ = away.get("score")
        if hs is None or as_ is None: out.append("?"); continue
        is_home = tricode(home) == tri
        ts = hs if is_home else as_; os_ = as_ if is_home else hs
        if ts > os_: out.append("W")
        else:
            lpt = ((g.get("gameOutcome") or {}).get("lastPeriodType") or "").upper()
            out.append("OTL" if lpt in {"OT","SO"} else "L")
    return out

# ─────────────────────────────────────────────────────────────────
# CANVAS
# ─────────────────────────────────────────────────────────────────

def make_canvas() -> Tuple[Image.Image, ImageDraw.ImageDraw]:
    img  = Image.new("RGB", (W, H), C_BG)
    draw = ImageDraw.Draw(img, "RGBA")

    # Vertical gradient
    for y in range(H):
        t = y / H
        r = int(C_BG[0] + (C_BG2[0]-C_BG[0])*t)
        g = int(C_BG[1] + (C_BG2[1]-C_BG[1])*t)
        b = int(C_BG[2] + (C_BG2[2]-C_BG[2])*t)
        draw.line([(0,y),(W,y)], fill=(r,g,b))

    # Subtle grid (ice rink)
    for x in range(0, W, 54):
        draw.line([(x,0),(x,H)], fill=(255,255,255,5))
    for y in range(0, H, 54):
        draw.line([(0,y),(W,y)], fill=(255,255,255,4))

    # Concentric circle watermark (top-right decorative)
    for i in range(4):
        r = 260 - i*40
        a = 10 - i*2
        cx, cy = W-80, 120
        draw.ellipse([cx-r, cy-r, cx+r, cy+r],
                     outline=(0,200,255,a), width=2)

    # Corner tick marks
    _corner_ticks(draw)
    return img, draw


def _corner_ticks(draw: ImageDraw.ImageDraw, s: int = 24, t: int = 3) -> None:
    col = (*C_ICE, 70); m = 20
    for pts in [
        [(m,m+s),(m,m),(m+s,m)],
        [(W-m-s,m),(W-m,m),(W-m,m+s)],
        [(m,H-m-s),(m,H-m),(m+s,H-m)],
        [(W-m-s,H-m),(W-m,H-m),(W-m,H-m-s)],
    ]:
        for i in range(len(pts)-1):
            draw.line([pts[i],pts[i+1]], fill=col, width=t)

# ─────────────────────────────────────────────────────────────────
# PRIMITIVES
# ─────────────────────────────────────────────────────────────────

def tw(draw: ImageDraw.ImageDraw, text: str, fnt) -> int:
    bb = draw.textbbox((0,0), text, font=fnt); return bb[2]-bb[0]

def th_px(draw: ImageDraw.ImageDraw, text: str, fnt) -> int:
    bb = draw.textbbox((0,0), text, font=fnt); return bb[3]-bb[1]

def ice_text(draw: ImageDraw.ImageDraw, x: int, y: int, text: str, fnt) -> None:
    """White → ice-blue gradient text."""
    bb = draw.textbbox((x,y), text, font=fnt)
    total_w = max(bb[2]-bb[0], 1); cx = x
    for ch in text:
        cb = draw.textbbox((cx,y), ch, font=fnt); cw = cb[2]-cb[0]
        t  = max(0., min(1., (cx-x)/total_w))
        col = tuple(int(C_WHITE[i]+(C_ICE[i]-C_WHITE[i])*t) for i in range(3))
        draw.text((cx,y), ch, font=fnt, fill=col)
        cx += cw

def yellow_text(draw: ImageDraw.ImageDraw, x: int, y: int, text: str, fnt) -> None:
    """Yellow → white gradient text."""
    bb = draw.textbbox((x,y), text, font=fnt)
    total_w = max(bb[2]-bb[0], 1); cx = x
    for ch in text:
        cb = draw.textbbox((cx,y), ch, font=fnt); cw = cb[2]-cb[0]
        t   = max(0., min(1., (cx-x)/total_w))
        col = tuple(int(C_YELLOW[i]+(C_WHITE[i]-C_YELLOW[i])*t) for i in range(3))
        draw.text((cx,y), ch, font=fnt, fill=col)
        cx += cw

def chip(draw: ImageDraw.ImageDraw, x: int, y: int, text: str, fnt,
         bg=(255,255,255,18), fg=C_WHITE,
         border=None, px: int=12, py: int=5) -> int:
    """Hard-edged chip. Returns right edge x."""
    bb = draw.textbbox((0,0), text, font=fnt)
    pw = bb[2]-bb[0]+px*2; ph = bb[3]-bb[1]+py*2
    draw.rectangle([x,y,x+pw,y+ph], fill=bg)
    if border:
        draw.rectangle([x,y,x+pw,y+ph], outline=border, width=1)
    draw.text((x+px, y+py), text, font=fnt, fill=fg)
    return x+pw

def slash_div(draw: ImageDraw.ImageDraw, y: int,
              x0: int=PAD, x1: int=W-PAD,
              color=C_DIM, width: int=1) -> None:
    draw.line([(x0+14,y),(x1-14,y)], fill=color, width=width)
    draw.line([(x0,y+7),(x0+12,y-7)], fill=color, width=width)
    draw.line([(x1-12,y+7),(x1,y-7)], fill=color, width=width)

def section_hdr(draw: ImageDraw.ImageDraw, y: int,
                label: str, sub: str="") -> int:
    """Yellow-bar section title. Returns new y."""
    draw.rectangle([PAD, y, PAD+4, y+34], fill=C_YELLOW)
    f = F(20, "bold")
    draw.text((PAD+16, y+6), label.upper(), font=f, fill=C_WHITE)
    if sub:
        fs = F(13,"reg")
        draw.text((PAD+16+tw(draw,label.upper(),f)+14, y+12),
                  sub, font=fs, fill=C_MUTED)
    return y+48

def draw_header(draw: ImageDraw.ImageDraw, date_str: str, title: str) -> int:
    """Top bar. Returns y after it."""
    draw.rectangle([0,0,W,92], fill=(*C_BG,255))
    draw.rectangle([0,88,W,92], fill=C_ICE)   # ice underline

    f_brand = F(38,"bold")
    draw.text((PAD,18), title, font=f_brand, fill=C_WHITE)
    bw = tw(draw, title, f_brand)
    draw.line([(PAD+bw+22,22),(PAD+bw+22,68)],
              fill=(*C_DIM,180), width=1)

    f_date = F(17,"bold"); f_tag = F(12,"reg")
    dw = tw(draw, date_str, f_date)
    draw.text((W-PAD-dw, 20), date_str, font=f_date, fill=C_YELLOW)
    tag = "NHL EDGE API"
    draw.text((W-PAD-tw(draw,tag,f_tag), 48), tag, font=f_tag, fill=C_MUTED)
    return 108

def _footer(draw: ImageDraw.ImageDraw) -> None:
    fy = H - PAD + 12
    draw.text((PAD, fy), "Data: api-web.nhle.com / NHL EDGE",
              font=F(12,"reg"), fill=(*C_MUTED,140))
    chip(draw, W-PAD-116, fy-4, "@nhl_edge", F(12,"bold"),
         bg=(*C_ICE,22), fg=C_ICE, border=(*C_ICE,50))

# ─────────────────────────────────────────────────────────────────
# ROW RENDERERS
# ─────────────────────────────────────────────────────────────────

def matchup_row(draw: ImageDraw.ImageDraw, y: int,
                away: str, home: str, label: str,
                is_fin: bool, is_lv: bool, row_h: int=66) -> int:

    draw.rectangle([PAD,y,W-PAD,y+row_h-5], fill=(*C_BG3,115))
    bar_col = C_GREEN if is_fin else (C_ICE if is_lv else C_DIM)
    draw.rectangle([PAD,y,PAD+3,y+row_h-5], fill=bar_col)

    f_team = F(26,"bold"); f_vs = F(14,"reg")
    draw.text((PAD+18, y+10), away, font=f_team, fill=C_WHITE)
    aw = tw(draw, away, f_team)
    draw.text((PAD+18+aw+12, y+18), "vs", font=f_vs, fill=C_MUTED)
    draw.text((PAD+18+aw+44, y+10), home, font=f_team, fill=C_WHITE)

    if is_fin or is_lv:
        f_score = F(28,"bold")
        lw = tw(draw,label,f_score)
        sx = W-PAD-lw-54
        if is_fin: yellow_text(draw, sx, y+8, label, f_score)
        else:      ice_text(draw, sx, y+8, label, f_score)
        f_ch = F(10,"bold")
        tag  = "FINAL" if is_fin else "LIVE"
        bg   = (*C_GREEN,28) if is_fin else (*C_ICE,28)
        fg   = C_GREEN if is_fin else C_ICE
        bd   = (*C_GREEN,65) if is_fin else (*C_ICE,65)
        chip(draw, W-PAD-50, y+16, tag, f_ch,
             bg=bg, fg=fg, border=bd, px=7, py=4)
    else:
        f_time = F(18,"med")
        ice_text(draw, W-PAD-tw(draw,label,f_time)-8, y+16, label, f_time)

    return y + row_h


def result_row(draw: ImageDraw.ImageDraw, y: int,
               away: str, home: str,
               a_score: Any, h_score: Any, row_h: int=78) -> int:

    draw.rectangle([PAD,y,W-PAD,y+row_h-5], fill=(*C_BG3,100))

    try: a_w = int(a_score) > int(h_score)
    except: a_w = True

    f_team  = F(21,"bold"); f_score = F(36,"bold"); f_sub = F(11,"reg")
    a_col   = C_WHITE if a_w  else C_MUTED
    h_col   = C_WHITE if not a_w else C_MUTED

    draw.text((PAD+18,  y+6),  away, font=f_team, fill=a_col)
    draw.text((PAD+18,  y+34), "AWAY", font=f_sub, fill=C_DIM)

    sc = f"{a_score}  –  {h_score}"
    sw = tw(draw, sc, f_score)
    yellow_text(draw, W//2-sw//2, y+14, sc, f_score)

    hw = tw(draw, home, f_team)
    draw.text((W-PAD-18-hw, y+6),  home, font=f_team, fill=h_col)
    draw.text((W-PAD-18-tw(draw,"HOME",f_sub), y+34),
              "HOME", font=f_sub, fill=C_DIM)

    # Winner badge
    winner = away if a_w else home
    chip(draw, PAD+18, y+54, f"W  {winner}", F(11,"bold"),
         bg=(*C_YELLOW,28), fg=C_YELLOW, border=(*C_YELLOW,60))

    return y + row_h


def leader_row(draw: ImageDraw.ImageDraw, y: int,
               rank: int, name: str, team: str,
               value: Any, row_h: int=54) -> int:

    f_rk  = F(44,"bold")
    rk_s  = str(rank)
    alpha = 170 if rank==1 else 75
    draw.text((PAD, y-6), rk_s, font=f_rk, fill=(*C_DIM,alpha))
    rk_w  = tw(draw, rk_s, f_rk) + 14

    if rank==1:
        draw.rectangle([PAD+rk_w-4, y+6, PAD+rk_w, y+row_h-10],
                       fill=C_YELLOW)

    f_name = F(20,"bold"); f_team = F(12,"reg")
    draw.text((PAD+rk_w+8, y+6),  name, font=f_name, fill=C_WHITE)
    draw.text((PAD+rk_w+8, y+30), team, font=f_team, fill=C_MUTED)

    f_val = F(32,"bold"); val_s = str(value)
    vw = tw(draw, val_s, f_val)
    if rank==1: yellow_text(draw, W-PAD-vw, y+8, val_s, f_val)
    else:       ice_text(draw,    W-PAD-vw, y+8, val_s, f_val)

    draw.line([(PAD+rk_w+8, y+row_h-2),(W-PAD, y+row_h-2)],
              fill=(*C_DIM,100), width=1)
    return y + row_h


def form_row(draw: ImageDraw.ImageDraw, y: int,
             tri: str, results: List[str], row_h: int=50) -> int:

    f_team = F(17,"bold"); f_dot = F(13,"bold"); f_pct = F(20,"bold")

    draw.text((PAD, y+14), tri, font=f_team, fill=C_WHITE)

    dot_x = PAD+72; dw=26; dh=20; gap=4
    for i, res in enumerate(results):
        col   = C_GREEN if res=="W" else (C_ORANGE if res=="OTL" else C_RED)
        rx    = dot_x + i*(dw+gap)
        draw.rectangle([rx, y+12, rx+dw, y+12+dh], fill=(*col,35))
        ltr   = res[0]
        lw    = tw(draw, ltr, f_dot)
        draw.text((rx+(dw-lw)//2, y+13), ltr, font=f_dot, fill=col)

    wins = sum(1 for r in results if r=="W")
    pct  = wins/len(results) if results else 0
    pct_s = f"{pct:.0%}"
    pct_col = C_GREEN if pct>=0.6 else (C_RED if pct<0.4 else C_MUTED)
    pw = tw(draw, pct_s, f_pct)
    draw.text((W-PAD-pw, y+10), pct_s, font=f_pct, fill=pct_col)

    draw.line([(PAD, y+row_h-2),(W-PAD, y+row_h-2)],
              fill=(*C_DIM,90), width=1)
    return y + row_h

# ─────────────────────────────────────────────────────────────────
# CARD BUILDERS
# ─────────────────────────────────────────────────────────────────

def build_matchups_card(today: dt.date) -> Image.Image:
    img, draw = make_canvas()
    y = draw_header(draw, today.strftime("%b %-d · %Y"), "TONIGHT'S GAMES")
    y += 8
    y = section_hdr(draw, y, "Schedule",
                    f"· {today.strftime('%A').upper()}")
    games = fetch_games(today.isoformat())
    if not games:
        draw.text((PAD+20,y+10), "No games scheduled.",
                  font=F(18,"reg"), fill=C_MUTED)
    else:
        for g in games[:7]:
            a = tricode(g.get("awayTeam") or {})
            h = tricode(g.get("homeTeam") or {})
            if not a or not h: continue
            fin=is_final(g); lv=is_live(g)
            if fin or lv:
                a_s,h_s = score_of(g)
                label = f"{a_s}  –  {h_s}" if a_s is not None else "—"
            else:
                label = parse_et(g.get("startTimeUTC",""))
            y = matchup_row(draw, y, a, h, label, fin, lv); y+=5
    _footer(draw); return img


def build_results_card(yday: dt.date) -> Image.Image:
    img, draw = make_canvas()
    y = draw_header(draw, yday.strftime("%b %-d · %Y"), "LAST NIGHT")
    y += 8
    y = section_hdr(draw, y, "Final Scores")
    games = [g for g in fetch_games(yday.isoformat()) if is_final(g)]
    if not games:
        draw.text((PAD+20,y+10),"No completed games.",
                  font=F(18,"reg"),fill=C_MUTED)
    else:
        for g in games[:6]:
            a=tricode(g.get("awayTeam") or {}); h=tricode(g.get("homeTeam") or {})
            a_s,h_s=score_of(g)
            y=result_row(draw,y,a,h,a_s,h_s); y+=5
    _footer(draw); return img


def build_leaders_card(today: dt.date) -> Image.Image:
    img, draw = make_canvas()
    y = draw_header(draw, today.strftime("%b %-d · %Y"), "LEAGUE LEADERS")
    y += 8

    def pname(x: Dict) -> str:
        pn = x.get("playerName") or {}
        if isinstance(pn,dict): return pn.get("default","—")
        if isinstance(pn,str):  return pn
        fn=(x.get("firstName") or {}).get("default","")
        ln=(x.get("lastName")  or {}).get("default","")
        return f"{fn} {ln}".strip() or "—"

    y = section_hdr(draw, y, "Points Leaders")
    for i,p in enumerate(fetch_leaders("points","points",5),1):
        if y > H-180: break
        y = leader_row(draw,y,i,pname(p),
                       str(p.get("teamAbbrev","")).upper(),p.get("value","—"))

    y += 10; slash_div(draw,y); y += 18
    y = section_hdr(draw, y, "Goals Leaders")
    for i,p in enumerate(fetch_leaders("goals","goals",3),1):
        if y > H-90: break
        y = leader_row(draw,y,i,pname(p),
                       str(p.get("teamAbbrev","")).upper(),
                       p.get("value","—"),row_h=46)
    _footer(draw); return img


def build_form_card(today: dt.date) -> Image.Image:
    img, draw = make_canvas()
    y = draw_header(draw, today.strftime("%b %-d · %Y"), "TEAM FORM")
    y += 8
    y = section_hdr(draw, y, "Last 10 Games",
                    "· teams playing today")
    games = fetch_games(today.isoformat())
    teams: List[str] = []
    for g in games:
        a=tricode(g.get("awayTeam") or {}); h=tricode(g.get("homeTeam") or {})
        if a: teams.append(a)
        if h: teams.append(h)
    teams = sorted(set(teams))
    if not teams:
        draw.text((PAD+20,y+10),"No games today.",font=F(18,"reg"),fill=C_MUTED)
    else:
        print(f"  [form] fetching {len(teams)} teams...")
        rows = []
        for tri in teams:
            res = last10_results(tri, today)
            fp  = sum(2 if r=="W" else(1 if r=="OTL" else 0) for r in res)/(2*len(res)) if res else 0
            rows.append((tri,fp,res))
        rows.sort(key=lambda x:-x[1])
        for tri,fp,res in rows:
            if y > H-80: break
            y = form_row(draw,y,tri,res); y+=4
    _footer(draw); return img


def build_combined_card(today: dt.date, yday: dt.date) -> Image.Image:
    img, draw = make_canvas()
    y = draw_header(draw, today.strftime("%b %-d · %Y"), "NHL DAILY")
    y += 6

    # ── TODAY ─────────────────────────────────────────────
    y = section_hdr(draw, y, "Today's Games",
                    f"· {today.strftime('%a %b %-d').upper()}")
    games_today = fetch_games(today.isoformat())
    if not games_today:
        draw.text((PAD+20,y),"No games scheduled.",
                  font=F(16,"reg"),fill=C_MUTED); y+=30
    else:
        for g in games_today[:5]:
            if y > 480: break
            a=tricode(g.get("awayTeam") or {}); h=tricode(g.get("homeTeam") or {})
            if not a or not h: continue
            fin=is_final(g); lv=is_live(g)
            if fin or lv:
                a_s,h_s=score_of(g)
                label=f"{a_s}  –  {h_s}" if a_s is not None else "—"
            else:
                label=parse_et(g.get("startTimeUTC",""))
            y=matchup_row(draw,y,a,h,label,fin,lv,row_h=60); y+=3

    y += 10
    slash_div(draw, y, color=(*C_ICE,40)); y += 18

    # ── YESTERDAY ─────────────────────────────────────────
    y = section_hdr(draw, y, "Yesterday",
                    f"· {yday.strftime('%a %b %-d').upper()}")
    games_yday = [g for g in fetch_games(yday.isoformat()) if is_final(g)]
    if not games_yday:
        draw.text((PAD+20,y),"No results.",font=F(16,"reg"),fill=C_MUTED); y+=28
    else:
        for g in games_yday[:3]:
            if y > 740: break
            a=tricode(g.get("awayTeam") or {}); h=tricode(g.get("homeTeam") or {})
            a_s,h_s=score_of(g)
            y=result_row(draw,y,a,h,a_s,h_s,row_h=66); y+=3

    y += 10
    slash_div(draw, y, color=(*C_YELLOW,35)); y += 18

    # ── LEADERS ───────────────────────────────────────────
    remaining = H - PAD - 36 - y
    if remaining > 80:
        y = section_hdr(draw, y, "Points Leaders")

        def pname(x: Dict) -> str:
            pn = x.get("playerName") or {}
            if isinstance(pn,dict): return pn.get("default","—")
            if isinstance(pn,str):  return pn
            fn=(x.get("firstName") or {}).get("default","")
            ln=(x.get("lastName")  or {}).get("default","")
            return f"{fn} {ln}".strip() or "—"

        max_l = max(1, min(3, remaining//54))
        for i,p in enumerate(fetch_leaders("points","points",max_l),1):
            if y > H-80: break
            rh = max(44, min(54,(H-PAD-36-y)//max(1,max_l-i+1)))
            y  = leader_row(draw,y,i,pname(p),
                            str(p.get("teamAbbrev","")).upper(),
                            p.get("value","—"),row_h=rh)

    _footer(draw); return img


# ─────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────

BUILDERS = {
    "matchups": lambda t,y: build_matchups_card(t),
    "results":  lambda t,y: build_results_card(y),
    "leaders":  lambda t,y: build_leaders_card(t),
    "form":     lambda t,y: build_form_card(t),
    "combined": build_combined_card,
}

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date",   default=None)
    ap.add_argument("--card",   default="all",
                    choices=["all","matchups","results","leaders","form","combined"])
    ap.add_argument("--outdir", default="docs/instagram")
    args = ap.parse_args()

    now   = dt.datetime.now(TZ)
    today = dt.date.fromisoformat(args.date) if args.date else now.date()
    yday  = today - dt.timedelta(days=1)
    out   = Path(args.outdir)
    out.mkdir(parents=True, exist_ok=True)

    def save(img: Image.Image, name: str) -> None:
        p1 = out / f"{today.isoformat()}_{name}.png"
        p2 = out / f"latest_{name}.png"
        img.save(p1, "PNG", optimize=True)
        img.save(p2, "PNG", optimize=True)
        print(f"  [OK] {p1}")

    to_build = list(BUILDERS.keys()) if args.card=="all" else [args.card]
    print(f"[IG Cards v2] {today}  cards: {to_build}")
    for name in to_build:
        print(f"  building {name}...")
        save(BUILDERS[name](today, yday), name)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
