#!/usr/bin/env python3
"""The Countertop community gallery: check items, read submissions, and build the index the app reads.

    python3 scripts/gallery.py check              every item in items/ is valid (CI runs this on pull requests)
    python3 scripts/gallery.py build site         writes site/index.json and site/items/... for GitHub Pages
    python3 scripts/gallery.py submit result.json reads a submission issue (env BODY, AUTHOR, NUMBER) and writes its item

Items are the same .countertop files Countertop shares (Library > Share, or Share on a theme or effect),
plus a "gallery" block: {"author": GitHub login, "version": n, "updated": "YYYY-MM-DD"}. A tile is a .countertop file
with "countertop": "tile" (its manifest and its code); it may have a screenshot beside it, items/tiles/<id>.png or .jpg.
Tile code is only ever read and published here, never run.
Countertop checks everything again when someone downloads an item; these checks keep the gallery tidy
and catch problems before review. Only the standard library is used.
"""

import base64
import datetime
import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent.parent
ITEMS = ROOT / "items"
KINDS = {"layout": "layouts", "theme": "themes", "effect": "effects", "tile": "tiles"}
FORMAT = 1                     # the newest .countertop format Countertop reads
MAX_BYTES = 64 * 1024
MAX_TILE_BYTES = 96 * 1024     # a tile's code may be up to 64 KB, plus its manifest
MAX_SHOT_BYTES = 600_000       # Countertop skips bigger screenshots
NO_CODE_TILES = {"custom"}     # "Your own tile" runs code that never went through the gallery; community tiles replace it

# the theme settings a theme (or a layout's look) may hold, as in Countertop's settings schema
LOOK = {
    "mode": ("choice", ["Dark", "Light"]),
    "accent": ("color",),
    "holiday": ("bool",),
    "tiles": ("choice", ["Solid", "See-through", "Clear"]),
    "opacity": ("int", 10, 100),
    "textScale": ("int", 80, 140),
    "titles": ("bool",),
    "bg": ("choice", ["Sky", "Color", "Photos"]),
    "bgColor": ("color",),
    "dim": ("int", 0, 80),
    "fx": ("choice", ["On", "Off"]),
}
MOTIONS = ["fall", "rise", "fly", "flutter"]
SIZES = ["Small", "Medium", "Big"]
SPEEDS = ["Slow", "Normal", "Fast"]
COLOR = re.compile(r"^#[0-9a-fA-F]{3,8}$")
MD = re.compile(r"^(1[0-2]|0?[1-9])-(3[01]|[12]\d|0?[1-9])$")
TILE_TYPE = re.compile(r"^[a-z][a-z0-9_-]{0,39}$")
DESIGN_WORD = re.compile(r"^[\w #.,%()\-]{0,60}$")


class Bad(ValueError):
    pass


def is_emoji(g):
    """One emoji (with its joiners, skin tones and variation marks). Countertop checks this exactly; this is a close first pass."""
    if not isinstance(g, str) or not 1 <= len(g) <= 16:
        return False
    keycap = "⃣" in g
    for ch in g:
        o = ord(ch)
        if o >= 0x2000 or (keycap and ch in "#*0123456789"):
            continue
        return False
    return True


def text(v, n):
    return v.strip()[:n] if isinstance(v, str) else ""


def clean_look(v, where):
    if v is None:
        return {}
    if not isinstance(v, dict):
        raise Bad(where + " should be a list of theme settings")
    out = {}
    for k, x in v.items():
        spec = LOOK.get(k)
        if not spec:
            continue                                   # settings this version doesn't know: left out, as the app does
        t = spec[0]
        ok = (t == "choice" and x in spec[1]) or (t == "color" and isinstance(x, str) and COLOR.match(x)) or \
             (t == "bool" and isinstance(x, bool)) or (t == "int" and isinstance(x, (int, float)) and not isinstance(x, bool))
        if not ok:
            raise Bad("%s: %r isn't a valid value for %s" % (where, x, k))
        out[k] = max(spec[1], min(spec[2], round(x))) if t == "int" else x
    return out


def clean_design(v, depth=0):
    if not isinstance(v, dict) or depth > 4:
        return None
    out = {}
    for k, x in v.items():
        if not re.match(r"^\w{1,30}$", k):
            continue
        if isinstance(x, bool) or (isinstance(x, (int, float)) and x == x and abs(x) != float("inf")):
            out[k] = x
        elif isinstance(x, str) and DESIGN_WORD.match(x):
            out[k] = x
        elif isinstance(x, dict):
            c = clean_design(x, depth + 1)
            if c is not None:
                out[k] = c
    return out


def clean_setting(x):
    """Tile settings are checked against each tile's own file by Countertop; here: plain values only, nothing large."""
    if isinstance(x, (bool, int, float)) or x is None:
        return True
    if isinstance(x, str):
        return len(x) <= 2000
    if isinstance(x, list):
        return len(x) <= 60 and all(isinstance(i, str) and len(i) <= 200 for i in x)
    return False


# ---- community tiles: the same rules Countertop applies when it downloads one (tools/server/sandbox.py in the app) ----
# Countertop checks every tile again, so a copy that drifts from the app is caught there. This is the first, friendlier check.
TILE_ID = re.compile(r"^[a-z][a-z0-9-]{1,39}$")
SLOT = re.compile(r"^[a-z][a-z0-9_]{0,19}$")
SETTING_KEY = re.compile(r"^[A-Za-z_]\w{0,30}$")
FEEDS = ("wx", "aqi", "events", "notes", "team", "photos", "sales")
PERSONAL_FEEDS = ("events", "notes", "photos", "sales")      # personal data or the internet, never both
USES = ("store", "fetch", "events", "sources", "feed")
SETTING_TYPES = ("bool", "int", "number", "text", "list", "choice", "color", "source", "secret")
SOURCE_KINDS = {"calendars": "events", "teams": "team", "lists": "notes", "albums": "photos"}
MAX_CODE = 64 * 1024
MAX_DEVICES, MAX_CONTROLS, MAX_SECRETS = 8, 12, 3
SECURE_DOMAINS = ("lock", "alarm_control_panel", "cover")
HOST = re.compile(r"^(\*\.)?(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{0,61}[a-z0-9]$")
HEADER = re.compile(r"^[A-Za-z][A-Za-z0-9-]{0,39}$")
QUERY = re.compile(r"^[A-Za-z0-9_.-]{1,40}$")
PREFIX = re.compile(r"^[\x20-\x7e]{0,20}$")
REFUSED_HEADERS = {"host", "content-length", "transfer-encoding", "connection", "keep-alive", "te", "upgrade", "expect",
                   "cookie", "user-agent", "accept", "accept-encoding", "proxy-authorization", "proxy-connection",
                   "forwarded", "x-forwarded-for", "x-forwarded-host", "x-real-ip", "origin", "referer"}
# what the buttons of a control tile may do (Home Assistant kinds and their actions)
HA_ACTIONS = {
    "light": {"toggle", "turn_on", "turn_off"}, "switch": {"toggle", "turn_on", "turn_off"},
    "fan": {"toggle", "turn_on", "turn_off", "set_percentage"}, "input_boolean": {"toggle", "turn_on", "turn_off"},
    "scene": {"turn_on"}, "script": {"turn_on"},
    "climate": {"toggle", "turn_on", "turn_off", "set_temperature", "set_hvac_mode"},
    "water_heater": {"toggle", "turn_on", "turn_off", "set_temperature", "set_away_mode", "set_operation_mode"},
    "cover": {"toggle", "open_cover", "close_cover", "stop_cover", "set_cover_position"},
    "lock": {"lock", "unlock", "open"},
    "media_player": {"toggle", "media_play_pause", "media_play", "media_pause", "media_stop", "media_next_track",
                     "media_previous_track", "volume_set", "volume_up", "volume_down"},
    "vacuum": {"start", "pause", "stop", "return_to_base", "toggle"},
    "alarm_control_panel": {"disarm", "arm_home", "arm_away", "arm_night", "arm_vacation"},
    "number": {"set_value"}, "input_number": {"set_value"},
    "select": {"select_option", "select_next", "select_previous"}, "input_select": {"select_option", "select_next", "select_previous"},
    "text": {"set_value"}, "input_text": {"set_value"}, "button": {"press"}, "input_button": {"press"},
}
HA_DATA_KEYS = {"temperature", "hvac_mode", "operation_mode", "away_mode", "brightness_pct", "brightness",
                "percentage", "position", "volume_level", "code", "value", "option"}
# tiles that come with Countertop: a community tile can't take their id
BUILTIN_TILES = {"agenda", "cam", "clock", "countdown", "custom", "daily", "dinner", "forecast", "ha", "hasensor", "hourly", "image",
                 "inseason", "iss", "joke", "list", "month", "nextevent", "nexthours", "nightclock", "note", "onthisday", "photos",
                 "planes", "radar", "sales", "space", "stocks", "sunmoon", "team", "tempo", "timeline", "tip", "weather", "week", "worldclock"}


def plain(v, depth=0):
    """JSON values only, cut down to a sensible size (as Countertop does)."""
    if isinstance(v, bool) or v is None or isinstance(v, int):
        return v
    if isinstance(v, float):
        return v if v == v and abs(v) < 1e15 else None
    if isinstance(v, str):
        return v[:4000]
    if depth < 6 and isinstance(v, list):
        return [plain(x, depth + 1) for x in v[:200]]
    if depth < 6 and isinstance(v, dict):
        return {str(k)[:60]: plain(x, depth + 1) for k, x in list(v.items())[:200]}
    return None


def clean_hosts(v):
    out = []
    for h in v if isinstance(v, (list, tuple)) else []:
        h = str(h).strip().lower().rstrip(".")
        if HOST.match(h) and h not in out:
            out.append(h)
    return out[:10]


def host_allowed(host, hosts):
    for h in hosts:
        if h == host or (h.startswith("*.") and host.endswith(h[1:]) and "." not in host[:-len(h) + 1]):
            return True
    return False


def clean_secret(name, s, hosts):
    host = str(s.get("host") or "").strip().lower().rstrip(".")
    if not HOST.match(host) or host.startswith("*."):
        raise Bad("setting %s must name the one site its key is sent to, like api.example.com" % name)
    if not host_allowed(host, hosts):
        raise Bad("setting %s sends its key to %s, which isn't one of the tile's hosts" % (name, host))
    header, query = s.get("header"), s.get("query")
    if (header is None) == (query is None):
        raise Bad("setting %s must say how its key is sent: a header or a query" % name)
    out = {"type": "secret", "label": text(s.get("label") or name, 60), "help": text(s.get("help"), 300), "host": host}
    if header is not None:
        if not isinstance(header, str) or not HEADER.match(header) or header.lower() in REFUSED_HEADERS:
            raise Bad("setting %s can't send its key in that header" % name)
        prefix = s.get("prefix") or ""
        if not isinstance(prefix, str) or not PREFIX.match(prefix):
            raise Bad("setting %s has a prefix that can't be sent" % name)
        out.update(header=header, prefix=prefix)
    else:
        if not isinstance(query, str) or not QUERY.match(query):
            raise Bad("setting %s can't send its key as that part of the address" % name)
        out["query"] = query
    return out


def clean_controls(pkg):
    rd, rc = pkg.get("devices"), pkg.get("controls")
    if rd is None and rc is None:
        return {}, []
    if not isinstance(rd, dict) or not rd or len(rd) > MAX_DEVICES:
        raise Bad("devices must list 1 to %d kinds of thing the tile controls" % MAX_DEVICES)
    devices = {}
    for k, d in rd.items():
        if not SLOT.match(str(k)) or not isinstance(d, dict):
            raise Bad("device %s needs a short lower-case name" % str(k)[:20])
        doms = d.get("domains")
        if not isinstance(doms, list) or not doms or not all(isinstance(x, str) and x in HA_ACTIONS for x in doms):
            raise Bad("device %s must list the Home Assistant kinds it works with, like light or switch" % k)
        devices[k] = {"label": text(d.get("label") or k, 40), "domains": sorted(set(doms))}
    if not isinstance(rc, list) or not rc or len(rc) > MAX_CONTROLS:
        raise Bad("controls must list 1 to %d buttons" % MAX_CONTROLS)
    controls, seen = [], set()
    for c in rc:
        if not isinstance(c, dict) or not SLOT.match(str(c.get("id") or "")) or c["id"] in seen:
            raise Bad("each control needs its own short lower-case id")
        seen.add(c["id"])
        dev = devices.get(str(c.get("device") or ""))
        if not dev:
            raise Bad("control %s names a device the tile doesn't list" % c["id"])
        action = c.get("action")
        if not isinstance(action, str) or not all(action in HA_ACTIONS[x] for x in dev["domains"]):
            raise Bad("control %s: %s isn't something every kind of thing in its device can do" % (c["id"], str(action)[:30]))
        data = c.get("data") if c.get("data") is not None else {}
        if not isinstance(data, dict) or any(k not in HA_DATA_KEYS or k == "code" or not isinstance(v, (int, float, str, bool)) or
                                             (isinstance(v, str) and len(v) > 60) for k, v in data.items()):
            raise Bad("control %s sends data Countertop doesn't pass on" % c["id"])
        controls.append({"id": c["id"], "device": c["device"], "action": action, "data": dict(data)})
    return devices, controls


def check_tile(pkg):
    """A clean copy of a tile's manifest and code, or Bad. Everything Countertop would refuse is refused here too."""
    tid = pkg.get("id")
    if not isinstance(tid, str) or not TILE_ID.match(tid):
        raise Bad("A tile's id must be 2 to 40 lower-case letters, digits or dashes.")
    if tid in BUILTIN_TILES:
        raise Bad("The id %s is the same as a tile that comes with Countertop. Pick another." % tid)
    code = pkg.get("code")
    if not isinstance(code, str) or not code.strip():
        raise Bad("This tile has no code.")
    if len(code.encode("utf-8")) > MAX_CODE:
        raise Bad("The tile's code is larger than %d KB." % (MAX_CODE // 1024))
    size = pkg.get("size") if isinstance(pkg.get("size"), list) else [12, 8, 8, 6]
    if len(size) != 4 or not all(isinstance(n, int) and not isinstance(n, bool) and 2 <= n <= 48 for n in size):
        raise Bad("size must be [width, height, min width, min height] on the 48 by 32 grid.")
    feeds = pkg.get("feeds") if isinstance(pkg.get("feeds"), list) else []
    if [f for f in feeds if f not in FEEDS]:
        raise Bad("It asks for data that doesn't exist: %s." % ", ".join(str(f) for f in feeds if f not in FEEDS)[:80])
    feeds = list(dict.fromkeys(feeds))
    hosts = clean_hosts(pkg.get("hosts"))
    if isinstance(pkg.get("hosts"), list) and len(hosts) != len(pkg["hosts"]):
        raise Bad("Its hosts must be public names like api.example.com, not addresses, ports or paths (at most 10).")
    settings = {}
    raw_settings = pkg.get("settings")
    if raw_settings is not None and not isinstance(raw_settings, dict):
        raise Bad("settings aren't readable.")
    for k, s in (raw_settings or {}).items():
        if not SETTING_KEY.match(str(k)) or not isinstance(s, dict) or s.get("type") not in SETTING_TYPES:
            raise Bad("Setting %s isn't one Countertop knows." % str(k)[:30])
        if s["type"] == "source" and SOURCE_KINDS.get(s.get("kind")) not in feeds:
            raise Bad("Setting %s picks %s, which needs the matching data in feeds." % (k, str(s.get("kind"))[:20]))
        settings[k] = plain(s)
    devices, controls = clean_controls(pkg)
    personal = [f for f in feeds if f in PERSONAL_FEEDS] + (["devices"] if devices else [])
    if personal and hosts:
        raise Bad("A tile that reads personal data (%s) can't also read from sites. Take out the hosts or the data." % ", ".join(personal))
    keys = [k for k, s in settings.items() if s.get("type") == "secret"]
    if len(keys) > MAX_SECRETS:
        raise Bad("It asks for more than %d keys." % MAX_SECRETS)
    for k in keys:
        settings[k] = clean_secret(k, settings[k], hosts)
    uses = pkg.get("uses") if isinstance(pkg.get("uses"), list) else []
    out = {"countertop": "tile", "id": tid, "name": "", "description": "", "size": size}
    out["uses"] = [u for u in USES if u in uses]
    out["feeds"] = feeds
    out["hosts"] = hosts
    out["taps"] = pkg.get("taps") is True
    every = pkg.get("every")
    out["every"] = every if isinstance(every, int) and not isinstance(every, bool) and 1 <= every <= 86400 else 0
    out["settings"] = settings
    if devices:
        out["devices"], out["controls"] = devices, controls
    for k in ("demo", "demoData", "lang"):
        if isinstance(pkg.get(k), dict):
            out[k] = plain(pkg[k])
    out["code"] = code
    return out


def check(pkg):
    """A clean copy of a shared item, or Bad with what's wrong."""
    if not isinstance(pkg, dict):
        raise Bad("That isn't a Countertop file.")
    kind = pkg.get("countertop")
    if kind not in KINDS:
        raise Bad("That isn't a Countertop layout, theme, effect or tile.")
    if kind == "tile" and pkg.get("format") is None:
        pkg = dict(pkg, format=1)               # hand-written tile files often leave it out
    if not isinstance(pkg.get("format"), int) or not 1 <= pkg["format"] <= FORMAT:
        raise Bad("Unknown format %r (this gallery reads up to %d)." % (pkg.get("format"), FORMAT))
    name = text(pkg.get("name"), 60 if kind == "effect" else 80)
    if not name:
        raise Bad("It needs a name.")
    out = {"countertop": kind, "format": pkg["format"], "name": name, "description": text(pkg.get("description"), 500),
           "made": text(pkg.get("made"), 10)}
    if kind == "tile":
        name = text(pkg.get("name"), 60)
        if not name:
            raise Bad("It needs a name.")
        out = check_tile(pkg)
        out.update(format=pkg["format"], name=name, description=text(pkg.get("description"), 500))
        return out
    if kind == "theme":
        values = clean_look(pkg.get("values"), "values")
        if not values:
            raise Bad("This theme has no colors or settings in it.")
        out["values"] = values
    elif kind == "effect":
        e = pkg.get("effect")
        if not isinstance(e, dict):
            raise Bad("This effect has nothing in it.")
        glyphs = e.get("glyphs")
        if not isinstance(glyphs, list) or not glyphs or len(glyphs) > 8 or not all(is_emoji(g) for g in glyphs):
            raise Bad("An effect needs 1 to 8 emoji, and only emoji.")
        for k, L in (("motion", MOTIONS), ("size", SIZES), ("speed", SPEEDS)):
            if e.get(k, L[0] if k == "motion" else L[1]) not in L:
                raise Bad("%s should be one of %s." % (k, ", ".join(L)))
        f, t = e.get("from", ""), e.get("to", "")
        if (f or t) and not (isinstance(f, str) and isinstance(t, str) and MD.match(f) and MD.match(t)):
            raise Bad("A season needs both from and to, as month-day (10-1).")
        out["effect"] = {"glyphs": glyphs, "motion": e.get("motion", "fall"), "size": e.get("size", "Medium"),
                         "speed": e.get("speed", "Normal"), "spin": e.get("spin") is not False, "from": f or "", "to": t or ""}
    else:
        pages = pkg.get("pages")
        if not isinstance(pages, list) or not pages or not isinstance(pages[0], dict) or not isinstance(pages[0].get("boxes"), list):
            raise Bad("This layout has no page in it.")
        boxes = []
        for b in pages[0]["boxes"][:60]:
            if not isinstance(b, dict):
                raise Bad("A box in this layout isn't readable.")
            nums = [b.get(k) for k in ("x", "y", "w", "h")]
            if not all(isinstance(n, int) and not isinstance(n, bool) for n in nums):
                raise Bad("Each box needs whole-number x, y, w and h.")
            x, y, w, h = nums
            if not (0 <= x < 48 and 0 <= y < 32 and 1 <= w <= 48 - x and 1 <= h <= 32 - y):
                raise Bad("A box is outside the 48 by 32 grid.")
            tiles = []
            for t in (b.get("tiles") or [])[:12]:
                if not isinstance(t, dict) or not isinstance(t.get("type"), str) or not TILE_TYPE.match(t["type"]):
                    raise Bad("A tile in this layout has no readable type.")
                if t["type"] in NO_CODE_TILES:
                    raise Bad("Layouts with a Your own tile (its own code) can't go in the gallery yet. Take that tile out and submit again.")
                s = t.get("settings") or {}
                if not isinstance(s, dict):
                    raise Bad("A tile's settings aren't readable.")
                cs = {}
                for k, v in s.items():
                    if k == "design":
                        d = clean_design(v)
                        if d is not None:
                            cs["design"] = d
                    elif isinstance(k, str) and re.match(r"^\w{1,40}$", k) and clean_setting(v):
                        cs[k] = v
                o = {"type": t["type"], "settings": cs}
                f = t.get("from")             # a community tile: where Countertop gets it (never its code)
                if isinstance(f, dict) and isinstance(f.get("id"), str):
                    if f["id"] != "tiles/" + t["type"] or not TILE_ID.match(t["type"]):
                        raise Bad("A tile's 'from' should name the gallery tile it is (tiles/%s)." % t["type"])
                    v = f.get("v")
                    o["from"] = {"id": f["id"], "v": v if isinstance(v, int) and not isinstance(v, bool) and v >= 1 else 1}
                if text(t.get("name"), 60):
                    o["name"] = text(t.get("name"), 60)
                tiles.append(o)
            box = {"x": x, "y": y, "w": w, "h": h, "tiles": tiles}
            if len(tiles) > 1:
                ev = b.get("every")
                box["every"] = max(5, min(3600, int(ev))) if isinstance(ev, (int, float)) and not isinstance(ev, bool) else 45
            boxes.append(box)
        if not any(b["tiles"] for b in boxes):
            raise Bad("This layout has no tiles in it.")
        out["look"] = clean_look(pkg.get("look"), "look")
        out["pages"] = [{"name": text(pages[0].get("name"), 80) or name, "boxes": boxes}]
    return out


def read_code(raw):
    """A share code (CT1.…) or the JSON of a .countertop file."""
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```\w*\s*|\s*```$", "", raw)
    try:
        if raw.startswith("CT1."):
            b = re.sub(r"\s+", "", raw[4:])
            raw = base64.urlsafe_b64decode(b + "=" * (-len(b) % 4)).decode("utf-8")
        return json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise Bad("That isn't a share code or the text of a .countertop file. Copy it again from Countertop (Share → Copy share code).")


def slug(name):
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:48].strip("-")
    return s or "item"


def item_files():
    for kind, folder in KINDS.items():
        for p in sorted((ITEMS / folder).glob("*.countertop")):
            yield kind, p


def load_item(kind, p):
    limit = MAX_TILE_BYTES if kind == "tile" else MAX_BYTES
    if p.stat().st_size > limit:
        raise Bad("bigger than %d KB" % (limit // 1024))
    pkg = json.loads(p.read_text(encoding="utf-8"))
    g = pkg.get("gallery")
    if not isinstance(g, dict) or not isinstance(g.get("author"), str) or not isinstance(g.get("version"), int):
        raise Bad("needs a gallery block with author and version")
    clean = check(pkg)
    if clean["countertop"] != kind:
        raise Bad("is a %s but sits in %s/" % (clean["countertop"], KINDS[kind]))
    if kind == "tile":
        if p.stem != clean["id"]:
            raise Bad("file name should be its id: %s.countertop" % clean["id"])
    elif p.stem != slug(clean["name"]) and not p.stem.startswith(slug(clean["name"]) + "-"):
        raise Bad("file name should come from its name: %s.countertop" % slug(clean["name"]))
    if g["version"] < 1 or isinstance(g["version"], bool):
        raise Bad("version should be 1 or more")
    clean["gallery"] = {"author": g["author"], "version": g["version"], "updated": text(g.get("updated"), 10)}
    if kind == "tile":
        clean["author"] = g["author"]
    return clean


def shots():
    """{tile id: path} for the screenshots beside tiles (items/tiles/<id>.png or .jpg)."""
    out = {}
    for p in sorted((ITEMS / "tiles").glob("*")) if (ITEMS / "tiles").is_dir() else []:
        if p.suffix in (".png", ".jpg"):
            out.setdefault(p.stem, []).append(p)
    return out


def check_shot(p):
    if p.stat().st_size > MAX_SHOT_BYTES:
        raise Bad("%s is bigger than %d KB" % (p.name, MAX_SHOT_BYTES // 1000))
    head = p.read_bytes()[:8]
    if (p.suffix == ".png") != (head == b"\x89PNG\r\n\x1a\n") or (p.suffix == ".jpg" and head[:3] != b"\xff\xd8\xff"):
        raise Bad("%s isn't really a %s picture" % (p.name, p.suffix[1:].upper()))


def tile_refs(clean):
    """Gallery tiles a layout's boxes name with 'from'."""
    return {t["from"]["id"] for pg in clean.get("pages", []) for b in pg["boxes"] for t in b["tiles"] if t.get("from")}


def cmd_check():
    bad = 0
    n = 0
    tiles, refs = set(), {}
    for kind, p in item_files():
        n += 1
        try:
            clean = load_item(kind, p)
            if kind == "tile":
                tiles.add(clean["id"])
            elif kind == "layout":
                refs[p] = tile_refs(clean)
        except (Bad, ValueError) as e:
            bad += 1
            print("✗ %s: %s" % (p.relative_to(ROOT), e))
    for p, ids in refs.items():
        for gid in sorted(ids):
            if gid[len("tiles/"):] not in tiles:
                bad += 1
                print("✗ %s: uses the community tile %s, which isn't in the gallery" % (p.relative_to(ROOT), gid))
    for tid, files in shots().items():
        for f in files:
            try:
                if tid not in tiles:
                    raise Bad("%s has no tile %s.countertop beside it" % (f.name, tid))
                check_shot(f)
                if len(files) > 1:
                    raise Bad("%s has more than one screenshot" % tid)
            except Bad as e:
                bad += 1
                print("✗ %s: %s" % (f.relative_to(ROOT), e))
    revoked = json.loads((ROOT / "revoked.json").read_text())
    if not isinstance(revoked, list) or not all(isinstance(x, str) for x in revoked):
        bad += 1
        print("✗ revoked.json should be a list of item ids")
    print(("%d of %d items have problems" % (bad, n)) if bad else "✓ %d items" % n)
    return 1 if bad else 0


def cmd_build(out):
    out = Path(out)
    (out / "items").mkdir(parents=True, exist_ok=True)
    items = []
    pics = shots()
    for kind, p in item_files():
        clean = load_item(kind, p)
        g = clean.pop("gallery")
        iid = KINDS[kind] + "/" + p.stem
        dest = out / "items" / KINDS[kind]
        dest.mkdir(parents=True, exist_ok=True)
        (dest / p.name).write_text(json.dumps(clean, ensure_ascii=False, indent=1), encoding="utf-8")
        entry = {"id": iid, "kind": kind, "name": clean["name"], "description": clean["description"], "author": g["author"],
                 "version": g["version"], "updated": g["updated"], "file": "items/" + KINDS[kind] + "/" + p.name, "item": clean}
        if kind == "tile" and pics.get(p.stem):
            pic = pics[p.stem][0]
            check_shot(pic)
            (dest / pic.name).write_bytes(pic.read_bytes())
            entry["shot"] = "items/tiles/" + pic.name
        items.append(entry)
    index = {"countertop": "gallery", "format": 1, "updated": datetime.date.today().isoformat(),
             "items": items, "revoked": json.loads((ROOT / "revoked.json").read_text())}
    (out / "index.json").write_text(json.dumps(index, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    (out / ".nojekyll").write_text("")
    print("✓ index.json with %d items" % len(items))
    return 0


def form_fields(body):
    """An issue form's answers: '### Label' headings, each followed by its answer."""
    out, cur = {}, None
    for line in (body or "").replace("\r\n", "\n").split("\n"):
        m = re.match(r"^###\s+(.+?)\s*$", line)
        if m:
            cur = m.group(1).lower()
            out[cur] = []
        elif cur is not None:
            out[cur].append(line)
    return {k: "\n".join(v).strip() for k, v in out.items()}


def cmd_submit(result):
    """Turns a submission issue into an item file. Writes result.json: {ok, message, path, title}."""
    author = os.environ.get("AUTHOR", "").strip()
    res = {"ok": False, "message": "", "path": "", "title": ""}
    try:
        if not re.match(r"^[A-Za-z0-9-]{1,39}$", author):
            raise Bad("Couldn't tell who submitted this.")
        f = form_fields(os.environ.get("BODY", ""))
        code = f.get("share code", "")
        if not code or code == "_No response_":
            raise Bad("The share code is empty. In Countertop, open what you want to share, press Share, then Copy share code, and paste it here.")
        ok = f.get("permission", "")
        if "[x]" not in ok.lower():
            raise Bad("Please tick the box that says you made it and it can be shared under the MIT license.")
        pkg = read_code(code)
        clean = check(pkg)
        desc = f.get("what it's for", "")
        if desc and desc != "_No response_":
            clean["description"] = text(desc, 500)
        kind = clean["countertop"]
        folder = ITEMS / KINDS[kind]
        folder.mkdir(parents=True, exist_ok=True)
        for gid in sorted(tile_refs(clean)) if kind == "layout" else []:
            if not (ITEMS / "tiles" / (gid[len("tiles/"):] + ".countertop")).is_file():
                raise Bad("This layout uses the community tile %s, which isn't in the gallery. Submit the tile first, or take it out of the layout." % gid[len("tiles/"):])
        base = clean["id"] if kind == "tile" else slug(clean["name"])
        if kind == "tile" and "tiles/" + base in json.loads((ROOT / "revoked.json").read_text()):
            raise Bad("A tile called %s was taken down from the gallery, so it can't be submitted again here. Open an issue to talk about it." % base)
        path = folder / (base + ".countertop")
        version = 1
        if path.exists():
            old = json.loads(path.read_text(encoding="utf-8")).get("gallery") or {}
            if old.get("author") == author:
                version = int(old.get("version") or 1) + 1        # the author's update to their own item
            elif kind == "tile":
                raise Bad("There's already a tile with the id %s, by someone else. A tile's id is its name in Countertop, so pick a different id and submit again." % base)
            else:
                i = 2
                while (folder / ("%s-%d.countertop" % (base, i))).exists():
                    i += 1
                path = folder / ("%s-%d.countertop" % (base, i))
        clean.pop("author", None)
        clean["gallery"] = {"author": author, "version": version, "updated": datetime.date.today().isoformat()}
        data = json.dumps(clean, ensure_ascii=False, indent=1) + "\n"
        limit = MAX_TILE_BYTES if kind == "tile" else MAX_BYTES
        if len(data.encode("utf-8")) > limit:
            raise Bad("It's bigger than %d KB." % (limit // 1024))
        path.write_text(data, encoding="utf-8")
        res.update(ok=True, path=str(path.relative_to(ROOT)), title="Add %s: %s%s" % (kind, clean["name"], " (version %d)" % version if version > 1 else ""),
                   message="Thanks! It checks out: %s %s called **%s**. A pull request is open for review%s; once it's merged it shows up in Library → Community." % (
                       "an" if kind == "effect" else "a", kind, clean["name"].replace("*", ""),
                       " (a tile runs its own code, so it's read through line by line before it can be merged, which can take a little longer)" if kind == "tile" else ""))
    except Bad as e:
        res["message"] = str(e)
    Path(result).write_text(json.dumps(res, ensure_ascii=False))
    print(json.dumps(res, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["check"]:
        sys.exit(cmd_check())
    if a[:1] == ["build"] and len(a) == 2:
        sys.exit(cmd_build(a[1]))
    if a[:1] == ["submit"] and len(a) == 2:
        sys.exit(cmd_submit(a[1]))
    print(__doc__)
    sys.exit(2)
