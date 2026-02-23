#!/usr/bin/env python3
"""
NHL Daily Dashboard — ENHANCED REWRITE
────────────────────────────────────────
Improvements over previous version:
  VISUAL   — full neon broadcast redesign: gradient glow cards, stat comparison
             bars, color-coded rank badges, expandable game cards with live feel
  DATA     — richer EDGE fields, head-to-head comparison rows, form sparklines,
             TOI-share context, shooting% vs avg, zone-time bars
  NARRATIVE — smarter commentary: rest impact sentences, form narrative,
              stat-driven "keys to win", contextual edge phrases
  RELIABILITY — per-endpoint try/except with typed fallbacks, graceful "—"
               everywhere, no uncaught AttributeError on None paths

Outputs:  docs/latest.html  •  docs/archive/YYYY-MM-DD.html
Deps:     pip install pandas requests
"""

from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path
from string import Template
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import requests
from zoneinfo import ZoneInfo

API = "https://api-web.nhle.com"
TZ  = ZoneInfo("America/Toronto")

# ═══════════════════════════════════════════════════════
# UTILITY BELT
# ═══════════════════════════════════════════════════════

def _safe(x: Any) -> str:
    """Escape HTML."""
    if x is None: return ""
    return (str(x)
            .replace("&","&amp;").replace("<","&lt;")
            .replace(">","&gt;").replace('"',"&quot;"))

def _f(x: Any, nd: int = 1, suffix: str = "") -> str:
    if x is None: return "—"
    try:
        v = float(str(x).replace("%","").strip())
        return f"{v:.{nd}f}{suffix}"
    except Exception: return "—"

def _fi(x: Any) -> str:
    if x is None: return "—"
    try: return str(int(float(str(x).strip())))
    except Exception: return "—"

def _to_f(x: Any) -> Optional[float]:
    if x is None: return None
    try: return float(str(x).replace("%","").strip())
    except Exception: return None

def _to_i(x: Any) -> Optional[int]:
    v = _to_f(x)
    return None if v is None else int(v)

def _pct(x: Any) -> Optional[float]:
    """Parse '54.2%' or 54.2 → float."""
    if x is None: return None
    s = str(x).strip()
    if s in ("","—"): return None
    s = s.rstrip("%")
    try: return float(s)
    except Exception: return None

def fmt_signed(v: Optional[float], nd: int = 1) -> str:
    if v is None: return "—"
    sign = "+" if v >= 0 else ""
    return f"{sign}{v:.{nd}f}"

def safe_get(d: Any, path: List[Any], default=None) -> Any:
    cur = d
    for k in path:
        try: cur = cur[k] if isinstance(k, int) else cur.get(k)
        except Exception: return default
        if cur is None: return default
    return cur

def pick(d: Any, keys: List[str]) -> Any:
    if not isinstance(d, dict): return None
    for k in keys:
        if k in d and d[k] is not None: return d[k]
    return None

def parse_et(s: str) -> str:
    if not s: return ""
    try:
        t = dt.datetime.fromisoformat(s.replace("Z","+00:00")).astimezone(TZ)
        return t.strftime("%I:%M %p").lstrip("0")
    except Exception: return s

def season_str(d: dt.date) -> str:
    y = d.year if d.month >= 7 else d.year - 1
    return f"{y}{y+1}"

def tricode(side: Dict[str, Any]) -> str:
    ta = side.get("teamAbbrev")
    if isinstance(ta, dict): return (ta.get("default") or "").upper()
    if isinstance(ta, str):  return ta.upper()
    return (side.get("abbrev") or side.get("triCode") or "").upper()

# ───────────────────────────────────────
# Rank badge HTML helper
# ───────────────────────────────────────
def rank_badge(rk: Any, total: int = 32) -> str:
    """Color-coded rank badge: top10=green, top20=yellow, bottom=red."""
    v = _to_i(rk)
    if v is None: return "<span class='rk rk-na'>—</span>"
    if v <= 10:   cls = "rk-top"
    elif v <= 22: cls = "rk-mid"
    else:         cls = "rk-bot"
    return f"<span class='rk {cls}'>#{v}</span>"

def delta_badge(val: Any, avg: Any, nd: int = 1, pct_mode: bool = False) -> str:
    """Show value with colored Δ vs avg."""
    v = _to_f(val);  a = _to_f(avg)
    if v is None: return "—"
    if a is None: return _f(val, nd)
    d = v - a
    sign = "+" if d >= 0 else ""
    cls  = "pos" if d > 0 else ("neg" if d < 0 else "neu")
    suf  = "%" if pct_mode else ""
    return (f"{v:.{nd}f}{suf} "
            f"<span class='{cls} small-delta'>({sign}{d:.{nd}f}{suf})</span>")

def mini_bar(val: Any, avg: Any, lo: float = 0, hi: float = 100,
             width: int = 80, label: str = "") -> str:
    """Tiny SVG progress bar showing val vs avg on lo-hi scale."""
    v = _to_f(val); a = _to_f(avg)
    if v is None: return ""
    span = hi - lo or 1
    pv = max(0.0, min(1.0, (v - lo) / span))
    pa = max(0.0, min(1.0, (a - lo) / span)) if a is not None else None
    col = "#22d3ee" if (a is None or v >= a) else "#f87171"
    avg_line = (f"<line x1='{pa*width:.1f}' y1='0' x2='{pa*width:.1f}' y2='8' "
                f"stroke='rgba(255,255,255,.5)' stroke-width='1.5' stroke-dasharray='2,2'/>") if pa is not None else ""
    tip = f" title='{_safe(label)}'" if label else ""
    return (
        f"<svg width='{width}' height='8' style='vertical-align:middle;display:inline-block;margin-left:4px;overflow:visible'{tip}>"
        f"<rect x='0' y='2' width='{width}' height='4' rx='2' fill='rgba(255,255,255,.10)'/>"
        f"<rect x='0' y='2' width='{pv*width:.1f}' height='4' rx='2' fill='{col}' opacity='.85'/>"
        f"{avg_line}"
        f"<circle cx='{pv*width:.1f}' cy='4' r='3' fill='{col}' stroke='#04040a' stroke-width='1.2'/>"
        f"</svg>"
    )

# ═══════════════════════════════════════════════════════
# HTTP
# ═══════════════════════════════════════════════════════

_SESSION = requests.Session()
_SESSION.headers["User-Agent"] = "nhl-daily-dashboard/17.0"

def get_json(url: str, timeout: int = 28) -> Dict[str, Any]:
    try:
        r = _SESSION.get(url, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except requests.HTTPError as e:
        raise RuntimeError(f"HTTP {e.response.status_code}: {url}") from e
    except Exception as e:
        raise RuntimeError(f"Fetch failed: {url} — {e}") from e

def try_json(url: str, tag: str = "") -> Tuple[Optional[Dict[str,Any]], Optional[str]]:
    """Returns (data, None) on success or (None, error_string)."""
    try:
        return get_json(url), None
    except Exception as e:
        return None, f"{tag}: {e}"

# ═══════════════════════════════════════════════════════
# ENDPOINTS
# ═══════════════════════════════════════════════════════

def fetch_score(date: str):            return get_json(f"{API}/v1/score/{date}")
def fetch_standings():                 return get_json(f"{API}/v1/standings/now")
def fetch_pbp(gid: int):               return get_json(f"{API}/v1/gamecenter/{gid}/play-by-play")
def fetch_sched(tri: str):             return get_json(f"{API}/v1/club-schedule-season/{tri}/now")
def fetch_skater_leaders(cat, n=10):   return get_json(f"{API}/v1/skater-stats-leaders/current?categories={cat}&limit={n}")
def fetch_goalie_leaders(cat, n=10):   return get_json(f"{API}/v1/goalie-stats-leaders/current?categories={cat}&limit={n}")
def fetch_edge_compare(tid: int):      return get_json(f"{API}/v1/edge/team-comparison/{tid}/now")
def fetch_edge_detail(tid, season, gt=2): return get_json(f"{API}/v1/edge/team-detail/{tid}/{season}/{gt}")

# ═══════════════════════════════════════════════════════
# SCORE / SCHEDULE PARSING
# ═══════════════════════════════════════════════════════

def parse_games(js: Dict) -> List[Dict]:
    g = js.get("games") or []
    return g if isinstance(g, list) else []

def matchup(game: Dict) -> Tuple[str, str]:
    a = tricode(game.get("awayTeam") or {})
    h = tricode(game.get("homeTeam") or {})
    return a, h

def is_final(game: Dict) -> bool:
    return (game.get("gameState") or "").upper() in {"FINAL","OFF"}

def score_str(game: Dict) -> str:
    a = (game.get("awayTeam") or {}).get("score")
    h = (game.get("homeTeam") or {}).get("score")
    return f"{a}–{h}" if a is not None and h is not None else "—"

def game_id(game: Dict) -> Optional[int]:
    gid = game.get("id") or game.get("gameId")
    try: return int(gid)
    except Exception: return None

def tri_to_id_map(standings_js: Dict) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for s in (standings_js.get("standings") or []):
        ta = s.get("teamAbbrev")
        tri = ((ta.get("default") if isinstance(ta, dict) else ta) or "").upper()
        try:
            if tri: out[tri] = int(s["teamId"])
        except Exception: pass
    return out

def tri_to_id_from_games(games: List[Dict]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for g in games:
        for k in ("awayTeam","homeTeam"):
            side = g.get(k) or {}
            tri = tricode(side)
            tid = side.get("id") or side.get("teamId")
            try:
                if tri and tid: out[tri] = int(tid)
            except Exception: pass
    return out

# ═══════════════════════════════════════════════════════
# REST + FORM
# ═══════════════════════════════════════════════════════

def completed_games(tri: str) -> List[Dict]:
    try:
        js = fetch_sched(tri)
        return [g for g in (js.get("games") or [])
                if (g.get("gameState") or "").upper() in {"FINAL","OFF"}]
    except Exception:
        return []

def game_date(g: Dict) -> Optional[dt.date]:
    s = g.get("gameDate") or g.get("startTimeUTC") or ""
    try: return dt.date.fromisoformat(str(s)[:10])
    except Exception: return None

def rest_days(tri: str, today: dt.date) -> Optional[int]:
    last = None
    for g in completed_games(tri):
        d = game_date(g)
        if d and d < today and (last is None or d > last):
            last = d
    return (today - last).days if last else None

def last10_form(tri: str, before: dt.date) -> Tuple[Optional[float], int]:
    """Returns (pts_pct 0-1, games_used)."""
    rows = []
    for g in completed_games(tri):
        d = game_date(g)
        if d and d < before:
            rows.append((d, g))
    rows.sort(key=lambda x: x[0])
    last = [g for _, g in rows][-10:]
    pts = gp = 0
    for g in last:
        home = g.get("homeTeam") or {}; away = g.get("awayTeam") or {}
        h_tri = tricode(home); a_tri = tricode(away)
        hs = home.get("score"); as_ = away.get("score")
        if hs is None or as_ is None: continue
        gp += 1
        is_home = h_tri == tri
        ts = hs if is_home else as_; os_ = as_ if is_home else hs
        if ts > os_: pts += 2
        else:
            lpt = ((g.get("gameOutcome") or {}).get("lastPeriodType") or "").upper()
            if lpt in {"OT","SO"}: pts += 1
    return (pts / (2 * gp), gp) if gp else (None, 0)

def form_bar(pct: Optional[float]) -> str:
    """Visual form bar 0-1 scale."""
    if pct is None: return "—"
    filled = round(pct * 10)
    bar = "█" * filled + "░" * (10 - filled)
    cls = "pos" if pct >= 0.6 else ("neg" if pct < 0.4 else "neu")
    return f"<span class='{cls}' style='font-size:11px;letter-spacing:1px'>{bar}</span> <span class='small-delta'>{pct:.0%}</span>"

def sparkline_form(tri: str, before: dt.date, n: int = 10) -> str:
    """W/OTL/L dots for last n games."""
    rows = []
    for g in completed_games(tri):
        d = game_date(g)
        if d and d < before: rows.append((d, g))
    rows.sort(key=lambda x: x[0])
    last = [g for _, g in rows][-n:]
    dots = []
    for g in last:
        home = g.get("homeTeam") or {}; away = g.get("awayTeam") or {}
        h_tri = tricode(home)
        hs = home.get("score"); as_ = away.get("score")
        if hs is None or as_ is None: dots.append("<span style='color:#666'>?</span>"); continue
        is_home = h_tri == tri
        ts = hs if is_home else as_; os_ = as_ if is_home else hs
        lpt = ((g.get("gameOutcome") or {}).get("lastPeriodType") or "").upper()
        if ts > os_:        dots.append("<span class='pos'>●</span>")
        elif lpt in {"OT","SO"}: dots.append("<span class='neu'>◑</span>")
        else:                    dots.append("<span class='neg'>●</span>")
    return "".join(dots) if dots else "—"

# ═══════════════════════════════════════════════════════
# EDGE TEAM DETAIL
# ═══════════════════════════════════════════════════════

def _imp(x: Any) -> Any:
    return x.get("imperial") if isinstance(x, dict) else x

def _lag(x: Any) -> Any:
    if not isinstance(x, dict): return None
    la = x.get("leagueAvg")
    return la.get("imperial") if isinstance(la, dict) else la

def _sog(edge_js: Dict, code: str) -> Dict:
    for r in (edge_js.get("sogSummary") or []):
        if isinstance(r, dict) and r.get("locationCode") == code:
            return r
    return {}

def parse_edge_detail(js: Dict, tri: str, tid: int) -> Dict[str, Any]:
    team = js.get("team") or {}
    alls = _sog(js, "all"); high = _sog(js, "high")
    mid  = _sog(js, "mid"); lng  = _sog(js, "long")
    spd  = js.get("shotSpeed") or {}
    sk   = js.get("skatingSpeed") or {}
    dist = safe_get(js, ["distanceSkated","total"]) or {}
    zt   = js.get("zoneTimeDetails") or {}
    top_shot = spd.get("topShotSpeed") or {}
    smax     = sk.get("speedMax") or {}

    def sog_block(s: Dict, pfx: str) -> Dict:
        return {
            f"{pfx} Shots":     pick(s, ["shots","shotCount","shotsFor"]),
            f"{pfx} Sh%":       pick(s, ["shootingPctg","shootingPct","shPct"]),
            f"{pfx} Shots rk":  pick(s, ["shotsRank","shotsRk","rankShots","rank"]),
            f"{pfx} Sh% rk":    pick(s, ["shootingPctgRank","shootingPctRank","shPctRank"]),
            f"{pfx} Shots avg": pick(s, ["shotsLeagueAvg","shotsAvg"]),
            f"{pfx} Sh% avg":   pick(s, ["shootingPctgLeagueAvg","shootingPctLeagueAvg"]),
        }

    row: Dict[str, Any] = {
        "Team": tri, "TeamId": tid,
        "Record": f"{team.get('wins','—')}-{team.get('losses','—')}-{team.get('otLosses','—')}",
        "GP":  team.get("gamesPlayed"), "PTS": team.get("points"),
        "Status": "OK",
        **sog_block(alls, "ALL"),
        **sog_block(high, "HIGH"),
        **sog_block(mid,  "MID"),
        **sog_block(lng,  "LONG"),
        "OZ EV%":     pick(zt, ["offensiveZoneEvPctg","ozEvPctg","ozEvPct"]),
        "OZ EV% avg": pick(zt, ["offensiveZoneEvPctgLeagueAvg","ozEvLeagueAvg"]),
        "OZ EV% rk":  pick(zt, ["offensiveZoneEvRank","ozEvRank"]),
        "NZ%":        pick(zt, ["neutralZonePctg","nzPctg"]),
        "NZ% avg":    pick(zt, ["neutralZonePctgLeagueAvg","nzLeagueAvg"]),
        "NZ% rk":     pick(zt, ["neutralZoneRank","nzRank"]),
        "DZ%":        pick(zt, ["defensiveZonePctg","dzPctg"]),
        "DZ% avg":    pick(zt, ["defensiveZonePctgLeagueAvg","dzLeagueAvg"]),
        "DZ% rk":     pick(zt, ["defensiveZoneRank","dzRank"]),
        "SpeedMax mph":     _imp(smax),
        "SpeedMax mph avg": _lag(smax),
        "SpeedMax rk":      pick(smax, ["rank","rk","leagueRank"]),
        "TopShot mph":     _imp(top_shot),
        "TopShot mph avg": _lag(top_shot),
        "TopShot rk":      pick(top_shot, ["rank","rk","leagueRank"]),
        "Dist mi":     _imp(dist) if isinstance(dist, dict) else None,
        "Dist mi avg": safe_get(dist, ["leagueAvg","imperial"]),
        "Dist rk":     pick(dist, ["rank","rk","leagueRank"]) if isinstance(dist, dict) else None,
        "SA>90":    safe_get(spd, ["shotAttemptsOver90","value"]),
        "SA>90 rk": safe_get(spd, ["shotAttemptsOver90","rank"]),
        "B>22":    safe_get(sk, ["burstsOver22","value"]),
        "B>22 rk": safe_get(sk, ["burstsOver22","rank"]),
    }
    return row

EDGE_DETAIL_CACHE: Dict[int, Dict] = {}

def get_edge_detail(tri: str, tid: Optional[int], season: str, gt: int = 2) -> Dict[str, Any]:
    if tid is None:
        return {"Team": tri, "Status": "NO_ID"}
    if tid not in EDGE_DETAIL_CACHE:
        try:
            js = fetch_edge_detail(tid, season, gt)
            EDGE_DETAIL_CACHE[tid] = parse_edge_detail(js, tri, tid)
        except Exception as e:
            EDGE_DETAIL_CACHE[tid] = {"Team": tri, "TeamId": tid,
                                       "Status": f"ERR:{type(e).__name__}:{e}"}
    return EDGE_DETAIL_CACHE[tid]

EDGE_NOW_CACHE: Dict[int, Dict] = {}

def get_edge_now(tri: str, tid: Optional[int]) -> Dict[str, Any]:
    if tid is None: return {"_status": "NO_ID"}
    if tid not in EDGE_NOW_CACHE:
        try:
            js = fetch_edge_compare(tid)
            EDGE_NOW_CACHE[tid] = js
        except Exception as e:
            EDGE_NOW_CACHE[tid] = {"_status": f"ERR:{e}"}
    return EDGE_NOW_CACHE[tid]

def edge_now_summary(tri: str, tid: Optional[int]) -> str:
    js = get_edge_now(tri, tid)
    if not js or js.get("_status"): return f"{tri}: EDGE-now unavailable"

    def fv(keys: List[str], nd: int = 1) -> str:
        for k in keys:
            v = js.get(k)
            if v is not None:
                try: return f"{float(v):.{nd}f}"
                except Exception: pass
        return "—"

    sd  = js.get("shotDifferential")
    top = fv(["topShotSpeed","topShot"], 1)
    avg = fv(["avgShotSpeed","avgShot"], 1)
    sa100 = js.get("shotAttemptsOver100")
    sa90  = js.get("shotAttempts90To100")

    bits = []
    if sd is not None:
        try: bits.append(f"ShotDiff <b>{int(float(sd)):+d}</b>")
        except Exception: pass
    if top != "—": bits.append(f"TopShot <b>{top} mph</b>")
    if avg != "—": bits.append(f"AvgShot <b>{avg} mph</b>")
    if sa100 is not None:
        try: bits.append(f"SA>100 <b>{int(float(sa100))}</b>")
        except Exception: pass
    if sa90 is not None:
        try: bits.append(f"SA 90-100 <b>{int(float(sa90))}</b>")
        except Exception: pass
    return f"{tri}: " + (" · ".join(bits) if bits else "EDGE-now: no fields")

# ═══════════════════════════════════════════════════════
# NARRATIVE ENGINE
# ═══════════════════════════════════════════════════════

def _rest_sentence(tri: str, rd: Optional[int]) -> str:
    if rd is None: return ""
    if rd == 1:    return f"{tri} is on a back-to-back — expect conservative deployment, shortened shifts."
    if rd == 2:    return f"{tri} had one day of rest — normal prep."
    if rd >= 3:    return f"{tri} is well-rested ({rd}d) — they can push tempo early."
    return ""

def _form_sentence(tri: str, pct: Optional[float], gp: int) -> str:
    if pct is None or gp == 0: return ""
    if pct >= 0.70:   tone = "red-hot"
    elif pct >= 0.55: tone = "playing solid hockey"
    elif pct >= 0.45: tone = "middling form"
    elif pct >= 0.30: tone = "struggling"
    else:             tone = "in a deep slump"
    return f"{tri} is {tone} ({pct:.0%} pts in last {gp}g)."

def _stat_edge(label: str, a_tri: str, h_tri: str, av: Any, hv: Any,
               better_high: bool = True, nd: int = 1) -> str:
    af = _to_f(av); hf = _to_f(hv)
    if af is None or hf is None:
        return f"<li>{_safe(label)}: data unavailable.</li>"
    if abs(af - hf) < 0.05:
        return f"<li>{_safe(label)}: essentially even ({af:.{nd}f} vs {hf:.{nd}f}).</li>"
    a_better = (af > hf) if better_high else (af < hf)
    leader = a_tri if a_better else h_tri
    loser  = h_tri if a_better else a_tri
    lv = hf if a_better else af; wv = af if a_better else hf
    return (f"<li>{_safe(label)}: edge to <b class='accent'>{leader}</b> "
            f"({leader} {wv:.{nd}f} vs {loser} {lv:.{nd}f}).</li>")

def keys_to_win(tri: str, opp: str, club: Dict, opp_club: Dict,
                rd: Optional[int], form_pct: Optional[float]) -> str:
    parts: List[str] = []

    rd_s = _rest_sentence(tri, rd)
    if rd_s: parts.append(rd_s)

    oz  = _pct(club.get("OZ EV%"));  oz_a  = _pct(club.get("OZ EV% avg"))
    hd  = _to_f(club.get("HIGH Shots")); hd_a = _to_f(club.get("HIGH Shots avg"))
    hdp = _pct(club.get("HIGH Sh%")); hdp_a = _pct(club.get("HIGH Sh% avg"))
    sh  = _pct(club.get("ALL Sh%")); sh_a  = _pct(club.get("ALL Sh% avg"))
    vol = _to_f(club.get("ALL Shots")); vol_a = _to_f(club.get("ALL Shots avg"))

    if oz is not None and oz_a is not None:
        if oz - oz_a < -1.5:
            parts.append(f"Tilt the ice: {tri} is below-avg in OZ time ({oz:.1f}% vs {oz_a:.1f}% lg avg) — cleaner zone entries and sustained pressure required.")
        elif oz - oz_a > 1.5:
            parts.append(f"Leverage their 5v5 territorial edge ({oz:.1f}% OZ time vs {oz_a:.1f}% avg) — keep the puck deep and force turnovers.")

    if hd is not None and hd_a is not None and hd - hd_a < -1.5:
        parts.append(f"Generate more high-danger looks — they're below average ({hd:.1f} vs {hd_a:.1f}). Drive the net, hunt second chances.")

    if hdp is not None and hdp_a is not None:
        if hdp - hdp_a < -1.0:
            parts.append(f"Finish inside chances — HD Sh% is below avg ({hdp:.1f}% vs {hdp_a:.1f}%). Quick hands and net-front battles matter.")
        elif hdp - hdp_a > 1.0:
            parts.append(f"Keep attacking the slot — HD finishing ({hdp:.1f}%) is a weapon. Force {opp} into penalty-kill situations.")

    if vol is not None and vol_a is not None and vol - vol_a < -2.0:
        parts.append("Win the shot attempt battle — they're below-avg in volume. Keep cycles alive and don't settle for perimeter shots.")

    if sh is not None and sh_a is not None and sh - sh_a < -0.8:
        parts.append("Improve shot quality by going east-west before releasing and looking for seam passes rather than low-percentage wrist shots from the outside.")

    if form_pct is not None:
        if form_pct < 0.35:
            parts.append("Given poor recent form, simplify: defensive structure first, first goal, then build from there.")
        elif form_pct > 0.65:
            parts.append("Strong recent form — stay aggressive, push pace, and don't sit back.")

    if not parts:
        parts = [f"Win the 50/50 battles in the middle, control zone entries, and get pucks to the net with traffic."]

    return " ".join(parts[:4])

def team_profile(tri: str, club: Dict, form_pct: Optional[float], rd: Optional[int]) -> str:
    if club.get("Status") != "OK":
        return f"<p class='muted'>{tri} EDGE detail unavailable ({club.get('Status','?')}). Lean on standings/form data.</p>"

    rec  = club.get("Record","—"); pts = club.get("PTS","—"); gp = club.get("GP","—")
    vol  = club.get("ALL Shots"); vol_a = club.get("ALL Shots avg")
    sh   = club.get("ALL Sh%"); sh_a = club.get("ALL Sh% avg")
    hd   = club.get("HIGH Shots"); hd_a = club.get("HIGH Shots avg")
    hdp  = club.get("HIGH Sh%"); hdp_a = club.get("HIGH Sh% avg")
    oz   = club.get("OZ EV%"); oz_a = club.get("OZ EV% avg")
    smax = club.get("SpeedMax mph"); smax_a = club.get("SpeedMax mph avg")
    dist = club.get("Dist mi"); dist_a = club.get("Dist mi avg")

    form_str = f"{form_pct:.0%}" if form_pct is not None else "—"
    rest_str = f"{rd}d rest" if rd is not None else "rest unknown"

    return (
        f"<p><b>{tri}</b> ({rec}, {pts} pts in {gp} GP, last-10 {form_str}, {rest_str}). "
        f"Shot vol: {delta_badge(vol, vol_a, 1)} "
        f"{mini_bar(vol, vol_a, 10, 40, 72, f'{tri} shot vol vs avg')} • "
        f"Sh%: {delta_badge(sh, sh_a, 2, True)}. "
        f"High-danger: {delta_badge(hd, hd_a, 1)} shots, "
        f"{delta_badge(hdp, hdp_a, 2, True)} Sh%. "
        f"OZ EV%: {delta_badge(oz, oz_a, 1)} "
        f"{mini_bar(oz, oz_a, 35, 65, 72, f'{tri} OZ EV% vs avg')}. "
        f"Max speed: {delta_badge(smax, smax_a, 2)} mph · "
        f"Distance: {delta_badge(dist, dist_a, 2)} mi.</p>"
    )

# ═══════════════════════════════════════════════════════
# YESTERDAY RECAP — PBP
# ═══════════════════════════════════════════════════════

# ── PBP team resolver ──────────────────────────────────
def _pbp_id_to_tri(pbp: Dict) -> Dict[int, str]:
    out: Dict[int, str] = {}
    for k in ("awayTeam","homeTeam"):
        t = pbp.get(k) or {}
        tri = tricode(t)
        tid = t.get("id") or t.get("teamId")
        try:
            if tri and tid: out[int(tid)] = tri
        except Exception: pass
    return out

def _ev_tri(ev: Dict, id_to_tri: Dict[int, str]) -> str:
    raw = (safe_get(ev, ["details","teamAbbrev","default"])
           or safe_get(ev, ["details","eventOwnerTeamAbbrev","default"]))
    if raw: return str(raw).upper()
    tid = (safe_get(ev, ["details","eventOwnerTeamId"])
           or safe_get(ev, ["details","teamId"]))
    try: return id_to_tri.get(int(tid), "")
    except Exception: return ""

def _ev_type(ev: Dict) -> str:
    return str(ev.get("typeDescKey") or ev.get("typeCode") or "").lower()

def _period_label(ev: Dict) -> str:
    p = safe_get(ev, ["periodDescriptor","number"])
    pt = (safe_get(ev, ["periodDescriptor","periodType"]) or "").upper()
    t = ev.get("timeInPeriod","")
    if pt == "OT": return f"OT {t}"
    if pt == "SO": return "SO"
    return f"P{p} {t}" if p else str(t)

# ── Full PBP stats in one pass ──────────────────────────
def parse_pbp_stats(game: Dict, pbp: Dict) -> Dict:
    """
    Single-pass extraction of:
      - turning point goals (first / tying / go-ahead / insurance / empty-net)
      - period-by-period score
      - shots on goal per team
      - PP goals and opportunities per team
      - penalties (count + worst offenders)
      - goalie saves (derived from shots - goals against)
    """
    a_tri, h_tri = matchup(game)
    id_to_tri = _pbp_id_to_tri(pbp)
    plays = pbp.get("plays") or []

    # accumulators
    a_s = h_s = 0                            # running score
    period_scores: Dict[int, Dict[str,int]] = {}  # {period: {a_tri: g, h_tri: g}}
    shots:    Dict[str, int] = {a_tri: 0, h_tri: 0}
    pp_goals: Dict[str, int] = {a_tri: 0, h_tri: 0}
    pp_opps:  Dict[str, int] = {a_tri: 0, h_tri: 0}
    pen_count:   Dict[str, int] = {a_tri: 0, h_tri: 0}
    pen_minutes: Dict[str, int] = {a_tri: 0, h_tri: 0}
    pen_players: Dict[str, List[str]] = {a_tri: [], h_tri: []}
    # goalie saves computed post-pass as shots_faced - goals_against
    goals_against: Dict[str, int] = {a_tri: 0, h_tri: 0}

    # goal turning points
    first_goal = tying_goal = go_ahead_goal = None
    insurance_goals: List[Tuple] = []   # goals that extend lead to 2+
    empty_net_goals: List[Tuple] = []

    # track PP state: who currently has the man advantage
    current_pp_team: Optional[str] = None

    for ev in plays:
        etype = _ev_type(ev)
        tri   = _ev_tri(ev, id_to_tri)
        pnum  = safe_get(ev, ["periodDescriptor","number"])
        try: pnum = int(pnum)
        except Exception: pnum = 0

        # ── SHOTS ──
        if etype in {"shot-on-goal","sog","505"} or etype == "shot_on_goal":
            if tri in shots: shots[tri] += 1

        # ── PENALTIES ──
        if etype in {"penalty","pen"}:
            if tri in pen_count:
                pen_count[tri] += 1
                # penalty minutes: try several field names the API uses
                mins = (safe_get(ev, ["details","duration"])
                        or safe_get(ev, ["details","penaltyMinutes"])
                        or safe_get(ev, ["details","pimMinutes"])
                        or safe_get(ev, ["details","pim"]))
                try: pen_minutes[tri] += int(mins)
                except Exception: pen_minutes[tri] += 2   # assume minor if unknown
                pname = safe_get(ev, ["details","descKey"]) or ""
                pen_players[tri].append(str(pname) if pname else "")
            # track who gets the PP
            opp = h_tri if tri == a_tri else a_tri
            current_pp_team = opp
            if opp in pp_opps: pp_opps[opp] += 1

        # ── GOALS ──
        if etype in {"goal","505"}:
            prev = (a_s, h_s)
            en = bool(safe_get(ev, ["details","emptyNetGoal"])
                      or safe_get(ev, ["details","isEmptyNet"]))
            on_pp = bool(safe_get(ev, ["details","situationCode"])
                         and str(safe_get(ev,["details","situationCode"])or"") in {"1051","1041","1050","1040"})

            if tri == a_tri:
                a_s += 1
                goals_against[h_tri] += 1
                if not pnum in period_scores: period_scores[pnum] = {a_tri:0, h_tri:0}
                period_scores[pnum][a_tri] = period_scores[pnum].get(a_tri,0) + 1
            elif tri == h_tri:
                h_s += 1
                goals_against[a_tri] += 1
                if not pnum in period_scores: period_scores[pnum] = {a_tri:0, h_tri:0}
                period_scores[pnum][h_tri] = period_scores[pnum].get(h_tri,0) + 1
            else:
                continue

            tag = (ev, tri)
            if first_goal is None: first_goal = tag
            if (tying_goal is None and a_s == h_s and prev[0] != prev[1]):
                tying_goal = tag
            if go_ahead_goal is None:
                if tri == a_tri and a_s > h_s and prev[0] <= prev[1]: go_ahead_goal = tag
                if tri == h_tri and h_s > a_s and prev[1] <= prev[0]: go_ahead_goal = tag

            lead = abs(a_s - h_s)
            if lead >= 2: insurance_goals.append(tag)
            if en: empty_net_goals.append(tag)

            if on_pp or current_pp_team == tri:
                if tri in pp_goals: pp_goals[tri] += 1
            current_pp_team = None   # PP used up on goal

    return {
        "a_tri": a_tri, "h_tri": h_tri,
        "shots": shots,
        "pp_goals": pp_goals, "pp_opps": pp_opps,
        "pen_count": pen_count, "pen_minutes": pen_minutes, "pen_players": pen_players,
        "goals_against": goals_against,
        "period_scores": period_scores,
        "first_goal": first_goal,
        "tying_goal": tying_goal,
        "go_ahead_goal": go_ahead_goal,
        "insurance_goals": insurance_goals,
        "empty_net_goals": empty_net_goals,
    }

# ── Render a full recap card from parsed stats ──────────
def render_recap_card(game: Dict, stats: Dict) -> str:
    a_tri = stats["a_tri"]; h_tri = stats["h_tri"]
    sc    = score_str(game)

    # ── Period-by-period table ───────────────────────────
    ps = stats["period_scores"]
    periods = sorted(ps.keys())
    p_labels = {1:"P1", 2:"P2", 3:"P3", 4:"OT", 5:"SO"}
    th_periods = "".join(f"<th>{p_labels.get(p,f'P{p}')}</th>" for p in periods) + "<th>F</th>"
    # compute totals from score_str
    try:
        a_total, h_total = sc.split("–")
    except Exception:
        a_total = h_total = "?"

    def period_goals(tri: str) -> str:
        return "".join(f"<td>{ps[p].get(tri,0)}</td>" for p in periods)

    period_table = (
        "<table class='recap-tbl'>"
        f"<thead><tr><th></th>{th_periods}</tr></thead>"
        "<tbody>"
        f"<tr><td><b>{_safe(a_tri)}</b></td>{period_goals(a_tri)}<td><b>{_safe(a_total)}</b></td></tr>"
        f"<tr><td><b>{_safe(h_tri)}</b></td>{period_goals(h_tri)}<td><b>{_safe(h_total)}</b></td></tr>"
        "</tbody></table>"
    ) if periods else ""

    # ── Shots / saves ────────────────────────────────────
    shots = stats["shots"]
    ga    = stats["goals_against"]
    a_sog = shots.get(a_tri, 0); h_sog = shots.get(h_tri, 0)
    # saves = SOG faced - goals against (crude but no separate goalie endpoint needed)
    a_saves = max(0, h_sog - ga.get(a_tri, 0))
    h_saves = max(0, a_sog - ga.get(h_tri, 0))
    a_svpct = f"{a_saves/h_sog*100:.1f}%" if h_sog else "—"
    h_svpct = f"{h_saves/a_sog*100:.1f}%" if a_sog else "—"

    shots_html = (
        "<div class='recap-stat-row'>"
        f"<div class='recap-stat-cell'><span class='recap-stat-label'>Shots</span>"
        f"<span class='recap-stat-val'>{a_sog} — {h_sog}</span></div>"
        f"<div class='recap-stat-cell'><span class='recap-stat-label'>{a_tri} saves</span>"
        f"<span class='recap-stat-val'>{a_saves} ({a_svpct})</span></div>"
        f"<div class='recap-stat-cell'><span class='recap-stat-label'>{h_tri} saves</span>"
        f"<span class='recap-stat-val'>{h_saves} ({h_svpct})</span></div>"
        "</div>"
    )

    # ── PP ────────────────────────────────────────────────
    ppg = stats["pp_goals"]; ppo = stats["pp_opps"]
    a_pp = f"{ppg.get(a_tri,0)}/{ppo.get(a_tri,0)}"
    h_pp = f"{ppg.get(h_tri,0)}/{ppo.get(h_tri,0)}"
    pp_html = (
        "<div class='recap-stat-row'>"
        f"<div class='recap-stat-cell'><span class='recap-stat-label'>{a_tri} PP</span>"
        f"<span class='recap-stat-val'>{a_pp}</span></div>"
        f"<div class='recap-stat-cell'><span class='recap-stat-label'>{h_tri} PP</span>"
        f"<span class='recap-stat-val'>{h_pp}</span></div>"
        f"<div class='recap-stat-cell'><span class='recap-stat-label'>Penalties (PIM)</span>"
        f"<span class='recap-stat-val'>"
        f"{a_tri} {stats['pen_count'].get(a_tri,0)} pen / {stats['pen_minutes'].get(a_tri,0)} min"
        f" &nbsp;·&nbsp; "
        f"{h_tri} {stats['pen_count'].get(h_tri,0)} pen / {stats['pen_minutes'].get(h_tri,0)} min"
        f"</span></div>"
        "</div>"
    )

    # ── Turning points ───────────────────────────────────
    def goal_tag(tag, label: str, extra: str = "") -> str:
        if not tag: return ""
        ev, tri = tag
        pl = _period_label(ev)
        extra_s = f" <span class='recap-extra'>{_safe(extra)}</span>" if extra else ""
        return (f"<div class='turning-pt'>"
                f"<span class='badge-event'>{_safe(label)}</span> "
                f"<b>{_safe(tri)}</b> "
                f"<span class='muted'>({_safe(pl)})</span>"
                f"{extra_s}</div>")

    tp_html = (
        goal_tag(stats["first_goal"],    "First goal")
        + goal_tag(stats["tying_goal"],  "Tying goal")
        + goal_tag(stats["go_ahead_goal"],"Go-ahead")
        + "".join(goal_tag(t, "Insurance", "(2+ lead)") for t in stats["insurance_goals"][:2])
        + "".join(goal_tag(t, "Empty net") for t in stats["empty_net_goals"])
    ) or "<span class='muted'>Turning points unclear.</span>"

    return (
        f"<div class='recap-row'>"
        # header
        f"<div class='recap-matchup'>"
        f"<b>{_safe(a_tri)} @ {_safe(h_tri)}</b>"
        f"<span class='score-badge'>{_safe(sc)}</span>"
        f"</div>"
        # period table
        f"{period_table}"
        # stat chips
        f"{shots_html}"
        f"{pp_html}"
        # turning points
        f"<div class='recap-tp'>{tp_html}</div>"
        f"</div>"
    )

def build_recap(games_yday: List[Dict]) -> str:
    finals = [g for g in games_yday if is_final(g)]
    if not finals:
        return "<p class='muted'>No completed games yesterday.</p>"

    rows_html = []
    for g in finals:
        gid = game_id(g)
        if not gid:
            a_tri, h_tri = matchup(g)
            rows_html.append(
                f"<div class='recap-row'>"
                f"<div class='recap-matchup'><b>{_safe(a_tri)} @ {_safe(h_tri)}</b>"
                f"<span class='score-badge'>{_safe(score_str(g))}</span></div>"
                f"<p class='muted'>No game ID — PBP unavailable.</p></div>"
            )
            continue
        try:
            pbp   = fetch_pbp(gid)
            stats = parse_pbp_stats(g, pbp)
            rows_html.append(render_recap_card(g, stats))
        except Exception as e:
            a_tri, h_tri = matchup(g)
            rows_html.append(
                f"<div class='recap-row'>"
                f"<div class='recap-matchup'><b>{_safe(a_tri)} @ {_safe(h_tri)}</b>"
                f"<span class='score-badge'>{_safe(score_str(g))}</span></div>"
                f"<p class='muted'>PBP error: {_safe(type(e).__name__)}: {_safe(str(e)[:120])}</p>"
                f"</div>"
            )

    return "".join(rows_html)

# ═══════════════════════════════════════════════════════
# CLUB SNAPSHOT TABLE
# ═══════════════════════════════════════════════════════

def build_club_snapshot(club_map: Dict[str, Dict]) -> str:
    """Rich two-column comparison layout for teams playing today."""
    if not club_map:
        return "<p class='muted'>No EDGE data available.</p>"

    tris = sorted(club_map.keys())
    rows = []
    for tri in tris:
        c = club_map[tri]
        if c.get("Status") != "OK":
            rows.append(f"<tr><td><b>{_safe(tri)}</b></td>"
                        f"<td colspan='8' class='muted'>{_safe(c.get('Status','?'))}</td></tr>")
            continue

        def rk(key: str) -> str: return rank_badge(c.get(key))
        def db(vk: str, ak: str, nd: int = 1, pct: bool = False) -> str:
            return delta_badge(c.get(vk), c.get(ak), nd, pct)

        rows.append(
            f"<tr>"
            f"<td><b>{_safe(tri)}</b><br><span class='muted' style='font-size:11px'>{_safe(c.get('Record','—'))}</span></td>"
            f"<td>{db('ALL Shots','ALL Shots avg',1)} {rk('ALL Shots rk')}</td>"
            f"<td>{db('ALL Sh%','ALL Sh% avg',2,True)} {rk('ALL Sh% rk')}</td>"
            f"<td>{db('HIGH Shots','HIGH Shots avg',1)} {rk('HIGH Shots rk')}</td>"
            f"<td>{db('HIGH Sh%','HIGH Sh% avg',2,True)} {rk('HIGH Sh% rk')}</td>"
            f"<td>{db('OZ EV%','OZ EV% avg',1)} {rk('OZ EV% rk')}</td>"
            f"<td>{db('SpeedMax mph','SpeedMax mph avg',2)} {rk('SpeedMax rk')}</td>"
            f"<td>{db('Dist mi','Dist mi avg',2)} {rk('Dist rk')}</td>"
            f"<td>{rk('SA>90 rk')} / {rk('B>22 rk')}</td>"
            f"</tr>"
        )

    header = ("".join(f"<th>{h}</th>" for h in [
        "Team","Shot Vol (Δavg)","Sh% (Δavg)","HD Vol (Δavg)",
        "HD Sh% (Δavg)","OZ EV% (Δavg)","Max Spd (Δavg)",
        "Dist mi (Δavg)","SA>90 / B>22 rk"
    ]))

    return (
        "<div class='table-wrap'><table class='tbl'>"
        f"<thead><tr>{header}</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        "</table></div>"
        "<div class='small' style='margin-top:6px'>Δavg = difference from league average. "
        "<span class='rk rk-top'>#1</span> top-10 &nbsp;"
        "<span class='rk rk-mid'>#15</span> mid &nbsp;"
        "<span class='rk rk-bot'>#28</span> bottom.</div>"
    )

# ═══════════════════════════════════════════════════════
# STANDINGS
# ═══════════════════════════════════════════════════════

def build_standings_html(standings_js: Dict) -> str:
    rows = []
    for s in (standings_js.get("standings") or []):
        ta = s.get("teamAbbrev")
        tri = ((ta.get("default") if isinstance(ta, dict) else ta) or "").upper()
        pts = s.get("points"); gp = s.get("gamesPlayed")
        pct = s.get("pointPct") or s.get("pointPctg")
        div = s.get("divisionName") or ""; conf = s.get("conferenceName") or ""
        rows.append({"Team": tri, "PTS": _fi(pts), "GP": _fi(gp),
                     "P%": _f(pct, 3), "Div": div, "Conf": conf})

    if not rows:
        return "<p class='muted'>Standings unavailable.</p>"

    rows.sort(key=lambda r: (r["Conf"], r["Div"], -(_to_f(r["PTS"]) or 0)))
    cur_div = None
    html_rows = []
    for r in rows:
        if r["Div"] != cur_div:
            cur_div = r["Div"]
            html_rows.append(
                f"<tr class='div-header'><td colspan='5'>"
                f"<b>{_safe(r['Conf'])} — {_safe(r['Div'])}</b></td></tr>"
            )
        html_rows.append(
            f"<tr><td>{_safe(r['Team'])}</td>"
            f"<td>{_safe(r['PTS'])}</td><td>{_safe(r['GP'])}</td>"
            f"<td>{_safe(r['P%'])}</td><td class='muted'>{_safe(r['Div'])}</td></tr>"
        )
    return (
        "<div class='table-wrap'><table class='tbl'>"
        "<thead><tr><th>Team</th><th>PTS</th><th>GP</th><th>P%</th><th>Div</th></tr></thead>"
        f"<tbody>{''.join(html_rows)}</tbody>"
        "</table></div>"
    )

# ═══════════════════════════════════════════════════════
# LEADERS
# ═══════════════════════════════════════════════════════

def _player_name(x: Dict) -> str:
    pn = safe_get(x, ["playerName","default"]) or x.get("playerName")
    if isinstance(pn, str) and pn.strip(): return pn.strip()
    fn = safe_get(x, ["firstName","default"]) or ""
    ln = safe_get(x, ["lastName","default"]) or ""
    return (f"{fn} {ln}").strip() or "—"

def leaders_html(cat: str, stat_col: str, fetcher, key: str, is_goalie: bool = False) -> str:
    try:
        data = fetcher(cat, 10).get(key, [])
    except Exception as e:
        return f"<p class='muted'>Leaders unavailable: {e}</p>"

    who_col = "Goalie" if is_goalie else "Player"
    rows_html = []
    for i, x in enumerate(data, 1):
        name = _player_name(x)
        team = (x.get("teamAbbrev") or safe_get(x, ["teamAbbrev","default"]) or "").upper() or "—"
        val  = x.get("value","—")
        badge_cls = "ldr-gold" if i == 1 else ("ldr-silver" if i == 2 else ("ldr-bronze" if i == 3 else ""))
        rows_html.append(
            f"<tr><td><span class='ldr-rank {badge_cls}'>{i}</span></td>"
            f"<td><b>{_safe(name)}</b></td>"
            f"<td class='muted'>{_safe(team)}</td>"
            f"<td><b>{_safe(val)}</b></td></tr>"
        )
    return (
        f"<div class='table-wrap'><table class='tbl'>"
        f"<thead><tr><th>#</th><th>{who_col}</th><th>Team</th><th>{_safe(stat_col)}</th></tr></thead>"
        f"<tbody>{''.join(rows_html)}</tbody></table></div>"
    )

# ═══════════════════════════════════════════════════════
# TODAY'S GAME COMMENTARY — MAIN SECTION
# ═══════════════════════════════════════════════════════

def build_commentary(
    games_today: List[Dict],
    today: dt.date,
    tri_to_id: Dict[str, int],
    standings_js: Dict,
    season: str,
) -> str:
    if not games_today:
        return "<p class='muted'>No games scheduled today.</p>"

    # Build standings P% map
    st_map: Dict[str, float] = {}
    for s in (standings_js.get("standings") or []):
        ta = s.get("teamAbbrev")
        tri = ((ta.get("default") if isinstance(ta, dict) else ta) or "").upper()
        pct = s.get("pointPct") or s.get("pointPctg")
        v = _to_f(pct)
        if tri and v is not None: st_map[tri] = v

    blocks: List[str] = []

    for game in games_today:
        a_tri, h_tri = matchup(game)
        if not a_tri or not h_tri: continue

        t_et   = parse_et(game.get("startTimeUTC",""))
        a_id   = tri_to_id.get(a_tri)
        h_id   = tri_to_id.get(h_tri)

        # Fetch data with error isolation
        a_rd   = rest_days(a_tri, today)
        h_rd   = rest_days(h_tri, today)
        a_fp, a_gp = last10_form(a_tri, today)
        h_fp, h_gp = last10_form(h_tri, today)
        a_club = get_edge_detail(a_tri, a_id, season)
        h_club = get_edge_detail(h_tri, h_id, season)
        a_edge_s = edge_now_summary(a_tri, a_id)
        h_edge_s = edge_now_summary(h_tri, h_id)
        a_st_pct = st_map.get(a_tri)
        h_st_pct = st_map.get(h_tri)
        a_spark  = sparkline_form(a_tri, today)
        h_spark  = sparkline_form(h_tri, today)

        # Flags
        flags = []
        if a_rd == 1: flags.append(f"<span class='badge warn'>⚡ {a_tri} B2B</span>")
        if h_rd == 1: flags.append(f"<span class='badge warn'>⚡ {h_tri} B2B</span>")
        flags_html = " ".join(flags) if flags else ""

        # Head-to-head stat comparison
        compare_items: List[str] = []
        if a_club.get("Status") == "OK" and h_club.get("Status") == "OK":
            compare_items = [
                _stat_edge("Shot volume",      a_tri, h_tri, a_club.get("ALL Shots"),   h_club.get("ALL Shots"),   True, 1),
                _stat_edge("Shot quality (Sh%)", a_tri, h_tri, _pct(a_club.get("ALL Sh%")), _pct(h_club.get("ALL Sh%")), True, 2),
                _stat_edge("High-danger vol",  a_tri, h_tri, a_club.get("HIGH Shots"),  h_club.get("HIGH Shots"),  True, 1),
                _stat_edge("HD finishing",     a_tri, h_tri, _pct(a_club.get("HIGH Sh%")), _pct(h_club.get("HIGH Sh%")), True, 2),
                _stat_edge("5v5 OZ time",      a_tri, h_tri, _pct(a_club.get("OZ EV%")), _pct(h_club.get("OZ EV%")), True, 1),
                _stat_edge("Max speed",        a_tri, h_tri, a_club.get("SpeedMax mph"), h_club.get("SpeedMax mph"), True, 2),
                _stat_edge("Distance skated",  a_tri, h_tri, a_club.get("Dist mi"),     h_club.get("Dist mi"),     True, 2),
            ]

        # Keys to win
        a_keys = keys_to_win(a_tri, h_tri, a_club, h_club, a_rd, a_fp)
        h_keys = keys_to_win(h_tri, a_tri, h_club, a_club, h_rd, h_fp)

        # Summary bar (visible when collapsed)
        a_form_s = f"{a_fp:.0%}" if a_fp is not None else "—"
        h_form_s = f"{h_fp:.0%}" if h_fp is not None else "—"
        a_st_s   = f"{a_st_pct:.3f}" if a_st_pct is not None else "—"
        h_st_s   = f"{h_st_pct:.3f}" if h_st_pct is not None else "—"

        summary_html = (
            f"<div class='game-summary-bar'>"
            f"<div class='gsb-matchup'><b>{a_tri} @ {h_tri}</b></div>"
            f"<div class='gsb-time'>{_safe(t_et)}</div>"
            f"<div class='gsb-form'>"
            f"<span>{a_tri} {a_form_s}</span>"
            f"<span class='muted'> vs </span>"
            f"<span>{h_tri} {h_form_s}</span>"
            f"</div>"
            f"<div class='gsb-st'><span class='muted'>P%:</span> {a_st_s} / {h_st_s}</div>"
            f"{flags_html}"
            f"<span class='expand-pill'>Expand ▾</span>"
            f"</div>"
        )

        # Detail body
        rest_html = ""
        rs_a = _rest_sentence(a_tri, a_rd)
        rs_h = _rest_sentence(h_tri, h_rd)
        if rs_a or rs_h:
            rest_html = f"<p class='context-note'>{rs_a} {rs_h}</p>"

        compare_html = ""
        if compare_items:
            compare_html = (
                "<div class='matchup-edges'>"
                "<div class='edges-title'>Head-to-head edges</div>"
                f"<ul>{''.join(compare_items)}</ul>"
                "</div>"
            )

        body_html = (
            f"<div class='game-detail-body'>"
            # Context row
            f"<div class='context-row'>"
            f"<span class='ctx-chip'>Rest: {a_tri} {a_rd if a_rd else '—'}d · {h_tri} {h_rd if h_rd else '—'}d</span>"
            f"<span class='ctx-chip'>EDGE-now: {a_edge_s}</span>"
            f"<span class='ctx-chip'>EDGE-now: {h_edge_s}</span>"
            f"</div>"
            f"{rest_html}"
            # Form sparklines
            f"<div class='spark-row'>"
            f"<div class='spark-item'><span class='muted'>{a_tri} last 10</span> {a_spark}</div>"
            f"<div class='spark-item'><span class='muted'>{h_tri} last 10</span> {h_spark}</div>"
            f"</div>"
            # Team profiles
            f"<div class='profiles-row'>"
            f"<div class='profile-card'>{team_profile(a_tri, a_club, a_fp, a_rd)}</div>"
            f"<div class='profile-card'>{team_profile(h_tri, h_club, h_fp, h_rd)}</div>"
            f"</div>"
            # Matchup edges
            f"{compare_html}"
            # Keys to win
            f"<div class='keys-row'>"
            f"<div class='keys-card'>"
            f"<div class='keys-title'>🔑 {a_tri} keys to win</div>"
            f"<p>{_safe(a_keys)}</p>"
            f"</div>"
            f"<div class='keys-card'>"
            f"<div class='keys-title'>🔑 {h_tri} keys to win</div>"
            f"<p>{_safe(h_keys)}</p>"
            f"</div>"
            f"</div>"
            f"</div>"
        )

        blocks.append(
            f"<details class='game-card'>"
            f"<summary>{summary_html}</summary>"
            f"{body_html}"
            f"</details>"
        )

    return "".join(blocks)

# ═══════════════════════════════════════════════════════
# FORM TABLE
# ═══════════════════════════════════════════════════════

def build_form_html(teams: List[str], today: dt.date) -> str:
    rows = []
    for tri in sorted(set(t for t in teams if t)):
        fp, gp = last10_form(tri, today)
        spark = sparkline_form(tri, today)
        bar   = form_bar(fp)
        rows.append((tri, fp or 0, gp, bar, spark))
    rows.sort(key=lambda r: -r[1])
    html_rows = []
    for tri, fp, gp, bar, spark in rows:
        html_rows.append(
            f"<tr><td><b>{_safe(tri)}</b></td>"
            f"<td>{bar}</td>"
            f"<td>{spark}</td>"
            f"<td class='muted'>{gp} GP</td></tr>"
        )
    return (
        "<div class='table-wrap'><table class='tbl'>"
        "<thead><tr><th>Team</th><th>Last-10 P%</th><th>Results (W◑L)</th><th>GP</th></tr></thead>"
        f"<tbody>{''.join(html_rows)}</tbody></table></div>"
    )

# ═══════════════════════════════════════════════════════
# CSS + HTML TEMPLATE
# ═══════════════════════════════════════════════════════

CSS = r"""
:root{
  --bg0:#030610;--bg1:#060b18;
  --card:rgba(255,255,255,.042);--card2:rgba(255,255,255,.065);
  --border:rgba(255,255,255,.12);
  --muted:rgba(255,255,255,.62);--text:rgba(255,255,255,.93);
  --accent:#a855f7;--accent2:#22d3ee;--accent3:#60a5fa;
  --pos:#34d399;--neg:#f87171;--neu:#fbbf24;
  --warn:#ffcc00;
  --shadow:0 20px 60px rgba(0,0,0,.68);
  --shadow2:0 10px 34px rgba(0,0,0,.50);
  --glow1:0 0 22px rgba(168,85,247,.38);
  --glow2:0 0 26px rgba(34,211,238,.30);
  --glow3:0 0 20px rgba(96,165,250,.24);
  --radius:20px;
}
html[data-theme="light"]{
  --bg0:#f4f6ff;--bg1:#fff;
  --card:rgba(0,0,0,.04);--card2:rgba(0,0,0,.06);
  --border:rgba(0,0,0,.12);
  --muted:rgba(0,0,0,.55);--text:rgba(0,0,0,.88);
  --glow1:none;--glow2:none;--glow3:none;
}
*{box-sizing:border-box;margin:0;padding:0;}
html,body{height:100%;}
body{
  color:var(--text);
  font-family:ui-sans-serif,-apple-system,system-ui,"Segoe UI",Roboto,Arial;
  font-size:14px;line-height:1.5;
  background: linear-gradient(180deg,var(--bg0),var(--bg1));
  min-height:100vh;
}

/* ── HEADER ── */
.header{
  position:sticky;top:0;z-index:60;
  backdrop-filter:blur(18px) saturate(1.4);
  background:linear-gradient(180deg,rgba(0,0,0,.78),rgba(0,0,0,.30));
  border-bottom:1px solid rgba(255,255,255,.09);
  box-shadow:var(--shadow2),var(--glow2);
}
html[data-theme="light"] .header{
  background:linear-gradient(180deg,rgba(255,255,255,.95),rgba(255,255,255,.80));
}
.header-inner{
  max-width:1040px;margin:0 auto;
  padding:12px 16px;
  display:flex;align-items:center;gap:14px;
}
.brand h1{
  font-size:15px;font-weight:800;letter-spacing:.9px;
  text-transform:uppercase;text-shadow:var(--glow1);
}
.brand .sub{font-size:12px;color:var(--muted);margin-top:2px;}
.pills{margin-left:auto;display:flex;gap:10px;align-items:center;}
.live-dot{
  width:9px;height:9px;border-radius:50%;
  background:linear-gradient(135deg,var(--accent),var(--accent2));
  box-shadow:var(--glow1),var(--glow2);
  animation:pulse 2s ease-in-out infinite;
}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}
.pill{
  display:inline-flex;align-items:center;gap:8px;
  padding:6px 12px;border-radius:999px;
  border:1px solid rgba(255,255,255,.14);
  background:rgba(255,255,255,.05);
  font-size:12px;
}
.btn{
  cursor:pointer;padding:7px 13px;border-radius:999px;
  border:1px solid rgba(255,255,255,.14);
  background:rgba(255,255,255,.06);color:var(--text);
  font-size:12px;transition:all .15s ease;
}
.btn:hover{background:rgba(255,255,255,.12);transform:translateY(-1px);}

/* ── LAYOUT ── */
.container{max-width:1040px;margin:0 auto;padding:14px 16px;}
.stack{display:flex;flex-direction:column;gap:14px;}

/* ── SECTION CARDS ── */
.card{
  border:1px solid rgba(255,255,255,.12);
  border-radius:var(--radius);
  padding:16px;
  background:linear-gradient(160deg,var(--card2),var(--card));
  box-shadow:var(--shadow),var(--glow3);
  position:relative;overflow:hidden;
}
.card::before{
  content:"";position:absolute;inset:0;
  background:linear-gradient(120deg,rgba(168,85,247,.10),rgba(34,211,238,.06),transparent 70%);
  pointer-events:none;
}
.card>*{position:relative;}
.section-title{
  font-size:13px;font-weight:700;letter-spacing:.5px;
  text-transform:uppercase;margin-bottom:12px;
  text-shadow:var(--glow1);display:flex;align-items:center;gap:8px;
}
.section-title::after{
  content:"";flex:1;height:1px;
  background:linear-gradient(90deg,var(--border),transparent);
}

/* ── GAME CARDS (commentary) ── */
details.game-card{
  border:1px solid rgba(255,255,255,.10);
  border-left:3px solid rgba(168,85,247,.60);
  border-radius:14px;
  background:rgba(255,255,255,.032);
  margin:8px 0;
  transition:background .2s;
}
details.game-card[open]{
  background:rgba(255,255,255,.055);
  border-left-color:var(--accent2);
  box-shadow:var(--shadow2),var(--glow2);
}
details.game-card>summary{
  cursor:pointer;list-style:none;padding:10px 14px;
}
details.game-card>summary::-webkit-details-marker{display:none;}

.game-summary-bar{
  display:flex;align-items:center;gap:10px;flex-wrap:wrap;
}
.gsb-matchup{font-size:15px;font-weight:800;letter-spacing:.2px;}
.gsb-time{color:var(--muted);font-size:13px;}
.gsb-form{font-size:12px;background:rgba(255,255,255,.06);
  padding:3px 10px;border-radius:999px;border:1px solid var(--border);}
.gsb-st{font-size:12px;color:var(--muted);}
.expand-pill{
  margin-left:auto;
  font-size:11px;letter-spacing:.5px;text-transform:uppercase;
  padding:4px 10px;border-radius:999px;
  border:1px solid rgba(34,211,238,.22);
  background:rgba(34,211,238,.08);color:var(--accent2);
}

/* ── GAME DETAIL BODY ── */
.game-detail-body{padding:10px 14px 14px;}
.context-row{
  display:flex;flex-wrap:wrap;gap:8px;margin-bottom:10px;
}
.ctx-chip{
  font-size:12px;color:var(--muted);
  background:rgba(255,255,255,.05);
  border:1px solid var(--border);
  border-radius:8px;padding:4px 10px;
}
.context-note{
  font-size:12px;color:var(--accent2);
  background:rgba(34,211,238,.06);
  border-left:2px solid var(--accent2);
  padding:6px 10px;border-radius:6px;margin-bottom:10px;
}
.spark-row{
  display:flex;gap:20px;flex-wrap:wrap;margin-bottom:10px;
  font-size:13px;
}
.spark-item{display:flex;align-items:center;gap:8px;}
.profiles-row{
  display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:10px;
}
@media(max-width:680px){.profiles-row{grid-template-columns:1fr;}}
.profile-card{
  background:rgba(255,255,255,.04);border:1px solid var(--border);
  border-radius:12px;padding:10px 12px;font-size:13px;
}
.profile-card p{margin:0;line-height:1.55;}

.matchup-edges{
  background:rgba(255,255,255,.03);border:1px solid var(--border);
  border-radius:12px;padding:10px 14px;margin-bottom:10px;
}
.edges-title{font-size:12px;font-weight:700;text-transform:uppercase;
  letter-spacing:.4px;color:var(--muted);margin-bottom:8px;}
.matchup-edges ul{padding-left:16px;font-size:13px;}
.matchup-edges li{margin:4px 0;}

.keys-row{display:grid;grid-template-columns:1fr 1fr;gap:10px;}
@media(max-width:680px){.keys-row{grid-template-columns:1fr;}}
.keys-card{
  background:rgba(255,255,255,.035);border:1px solid var(--border);
  border-radius:12px;padding:10px 12px;
}
.keys-title{font-size:12px;font-weight:700;margin-bottom:6px;color:var(--accent2);}
.keys-card p{font-size:13px;line-height:1.5;margin:0;}

/* ── RECAP ── */
.recap-row{
  border:1px solid var(--border);border-radius:12px;
  padding:10px 14px;margin:8px 0;
  background:rgba(255,255,255,.03);
}
.recap-matchup{
  display:flex;align-items:center;gap:10px;
  font-size:14px;margin-bottom:6px;
}
.score-badge{
  font-size:18px;font-weight:900;
  background:linear-gradient(135deg,var(--accent),var(--accent2));
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;
  background-clip:text;
}
.recap-tp{font-size:13px;}
.badge-event{
  display:inline-block;padding:2px 8px;border-radius:999px;
  font-size:11px;font-weight:700;letter-spacing:.4px;
  background:rgba(168,85,247,.15);border:1px solid rgba(168,85,247,.30);
  color:var(--accent);margin-right:4px;
}

/* ── TABLE ── */
.table-wrap{
  width:100%;overflow-x:auto;-webkit-overflow-scrolling:touch;
  border-radius:12px;border:1px solid rgba(255,255,255,.09);
  background:rgba(255,255,255,.022);
}
.tbl{width:100%;border-collapse:collapse;font-size:13px;}
.tbl th,.tbl td{
  padding:8px 10px;border-bottom:1px solid rgba(255,255,255,.07);
  text-align:left;vertical-align:middle;
}
.tbl th{
  position:sticky;top:0;z-index:2;
  background:rgba(10,15,30,.90);
  font-size:11px;font-weight:700;text-transform:uppercase;
  letter-spacing:.35px;color:var(--muted);
  border-bottom:1px solid rgba(255,255,255,.10);
}
.tbl tr:hover td{background:rgba(34,211,238,.07);}
.div-header td{
  background:rgba(168,85,247,.08)!important;
  font-size:12px;color:var(--muted);
  padding:5px 10px;
}

/* ── RANK BADGES ── */
.rk{
  display:inline-block;padding:2px 6px;border-radius:6px;
  font-size:11px;font-weight:700;letter-spacing:.3px;
  margin-left:3px;vertical-align:middle;
}
.rk-top{background:rgba(52,211,153,.18);color:#34d399;border:1px solid rgba(52,211,153,.30);}
.rk-mid{background:rgba(251,191,36,.12);color:#fbbf24;border:1px solid rgba(251,191,36,.28);}
.rk-bot{background:rgba(248,113,113,.14);color:#f87171;border:1px solid rgba(248,113,113,.28);}
.rk-na{background:rgba(255,255,255,.06);color:var(--muted);border:1px solid var(--border);}

/* ── LEADER RANKS ── */
.ldr-rank{
  display:inline-block;width:22px;height:22px;border-radius:50%;
  text-align:center;line-height:22px;font-size:11px;font-weight:800;
  background:rgba(255,255,255,.08);
}
.ldr-gold{background:rgba(255,215,0,.18);color:#ffd700;border:1px solid rgba(255,215,0,.35);}
.ldr-silver{background:rgba(192,192,192,.14);color:#c0c0c0;border:1px solid rgba(192,192,192,.30);}
.ldr-bronze{background:rgba(205,127,50,.14);color:#cd7f32;border:1px solid rgba(205,127,50,.28);}

/* ── HELPERS ── */
.pos{color:var(--pos);} .neg{color:var(--neg);} .neu{color:var(--neu);}
.accent{color:var(--accent2);}
.muted{color:var(--muted);}
.small{font-size:12px;color:var(--muted);margin:4px 0 10px;}
.small-delta{font-size:11px;opacity:.85;}
b{font-weight:700;}
h2{font-size:14px;font-weight:700;letter-spacing:.3px;}
h3{font-size:13px;color:var(--muted);margin:12px 0 6px;}

/* ── BADGE ── */
.badge{
  display:inline-flex;align-items:center;
  padding:3px 10px;border-radius:999px;
  border:1px solid var(--border);font-size:12px;
  background:rgba(255,255,255,.05);
}
.badge.warn{border-color:rgba(255,204,0,.38);color:#ffe89a;}

/* ── RECAP ENHANCED ── */
.recap-tbl{
  width:100%;border-collapse:collapse;font-size:13px;
  margin:8px 0 10px;
}
.recap-tbl th,.recap-tbl td{
  padding:5px 10px;border:1px solid rgba(255,255,255,.09);
  text-align:center;
}
.recap-tbl th{
  background:rgba(255,255,255,.06);font-size:11px;
  text-transform:uppercase;letter-spacing:.3px;color:var(--muted);
}
.recap-tbl tr:first-child td{border-top:none;}
.recap-stat-row{
  display:flex;flex-wrap:wrap;gap:8px;margin:6px 0 8px;
}
.recap-stat-cell{
  display:flex;flex-direction:column;
  background:rgba(255,255,255,.04);
  border:1px solid rgba(255,255,255,.09);
  border-radius:8px;padding:5px 10px;min-width:100px;
}
.recap-stat-label{font-size:10px;text-transform:uppercase;
  letter-spacing:.4px;color:var(--muted);margin-bottom:2px;}
.recap-stat-val{font-size:13px;font-weight:700;}
.turning-pt{margin:4px 0;font-size:13px;}
.recap-extra{font-size:11px;color:var(--muted);}
"""

HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>NHL Daily Dashboard — $date</title>
<style>$css</style>
</head>
<body>
<div class="header">
  <div class="header-inner">
    <div class="brand">
      <h1>⬡ NHL Daily Dashboard</h1>
      <div class="sub">$date &nbsp;·&nbsp; Updated $updated</div>
    </div>
    <div class="pills">
      <div class="pill"><span class="live-dot"></span> Live build</div>
      <button class="btn" id="themeBtn" type="button">☀ Theme</button>
    </div>
  </div>
</div>

<div class="container">
<div class="stack">

  <div class="card">
    <div class="section-title">📺 Today's Games — $date</div>
    <div class="small">Click any matchup to expand full analysis · EDGE team-detail + form + rest + head-to-head edges</div>
    $commentary
  </div>

  <div class="card">
    <div class="section-title">📅 Yesterday's Results</div>
    <div class="small">Turning points from play-by-play — first / tying / go-ahead goal.</div>
    $recap
  </div>

  <div class="card">
    <div class="section-title">🏒 Standings Snapshot</div>
    <div class="small">Sorted by conference → division → points.</div>
    $standings
  </div>

  <div class="card">
    <div class="section-title">📈 Team Form — Teams Playing Today</div>
    <div class="small">Last-10 games points% before today. ● W &nbsp; ◑ OTL &nbsp; ● L</div>
    $team_form
  </div>

  <div class="card">
    <div class="section-title">🔬 Club Snapshot — EDGE Team Detail</div>
    <div class="small">Teams playing today · season stats vs league avg (Δ) · color-coded ranks · Source: /v1/edge/team-detail</div>
    $club_snapshot
  </div>

  <div class="card">
    <div class="section-title">⭐ Skater Leaders</div>
    <h3>Points</h3>$pts_leaders
    <h3 style="margin-top:14px">Goals</h3>$g_leaders
  </div>

  <div class="card">
    <div class="section-title">🥅 Goalie Leaders</div>
    <h3>Wins</h3>$w_leaders
    <h3 style="margin-top:14px">Save %</h3>$sv_leaders
  </div>

</div>
</div>

<script>
(function(){
  const k="nhl_dash_theme";
  const s=localStorage.getItem(k);
  if(s) document.documentElement.setAttribute("data-theme",s);
  const btn=document.getElementById("themeBtn");
  btn&&btn.addEventListener("click",function(){
    const c=document.documentElement.getAttribute("data-theme")||"dark";
    const n=c==="light"?"dark":"light";
    document.documentElement.setAttribute("data-theme",n);
    localStorage.setItem(k,n);
  });
})();
</script>
</body>
</html>
"""

# ═══════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════

def main():
    # Ensure stdout handles Unicode on Windows (cp1252 default console)
    import sys, io
    if hasattr(sys.stdout, "reconfigure"):
        try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception: pass

    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="Dashboard date YYYY-MM-DD (default: today ET)")
    ap.add_argument("--game_type", type=int, default=2, help="2=regular, 3=playoffs")
    args = ap.parse_args()

    Path("docs/archive").mkdir(parents=True, exist_ok=True)

    now     = dt.datetime.now(TZ)
    today   = dt.date.fromisoformat(args.date) if args.date else now.date()
    yday    = today - dt.timedelta(days=1)
    season  = season_str(today)
    updated = now.strftime("%I:%M %p ET").lstrip("0")

    print(f"[NHL Dashboard] date={today} season={season}")

    # ── Core data ──
    print("  fetching standings...")
    standings_js = fetch_standings()
    tri_to_id    = {**tri_to_id_map(standings_js)}

    print("  fetching scores...")
    score_today  = fetch_score(today.isoformat())
    score_yday   = fetch_score(yday.isoformat())
    games_today  = parse_games(score_today)
    games_yday   = parse_games(score_yday)
    tri_to_id.update(tri_to_id_from_games(games_today))

    teams_today: List[str] = []
    for g in games_today:
        a, h = matchup(g)
        if a: teams_today.append(a)
        if h: teams_today.append(h)

    # ── EDGE detail (pre-fetch for teams playing) ──
    print("  fetching EDGE detail...")
    club_map: Dict[str, Dict] = {}
    for tri in sorted(set(teams_today)):
        tid = tri_to_id.get(tri)
        club_map[tri] = get_edge_detail(tri, tid, season, args.game_type)

    # ── Build sections ──
    print("  building commentary...")
    commentary_html = build_commentary(
        games_today, today, tri_to_id, standings_js, season
    )

    print("  building recap...")
    recap_html = build_recap(games_yday)

    print("  building standings...")
    standings_html = build_standings_html(standings_js)

    print("  building form...")
    form_html = build_form_html(teams_today, today)

    print("  building club snapshot...")
    snapshot_html = build_club_snapshot(club_map)

    print("  fetching leaders...")
    pts_html = leaders_html("points",   "PTS", fetch_skater_leaders, "points")
    g_html   = leaders_html("goals",    "G",   fetch_skater_leaders, "goals")
    w_html   = leaders_html("wins",     "W",   fetch_goalie_leaders, "wins",     True)
    sv_html  = leaders_html("savePctg", "SV%", fetch_goalie_leaders, "savePctg", True)

    # ── Render ──
    html = Template(HTML_TEMPLATE).substitute(
        date=today.isoformat(),
        updated=updated,
        css=CSS,
        commentary=commentary_html,
        recap=recap_html,
        standings=standings_html,
        team_form=form_html,
        club_snapshot=snapshot_html,
        pts_leaders=pts_html,
        g_leaders=g_html,
        w_leaders=w_html,
        sv_leaders=sv_html,
    )

    latest  = Path("docs/latest.html")
    archive = Path(f"docs/archive/{today.isoformat()}.html")
    latest.write_text(html, encoding="utf-8")
    archive.write_text(html, encoding="utf-8")
    print(f"  [OK] wrote {latest}")
    print(f"  [OK] wrote {archive}")

if __name__ == "__main__":
    main()