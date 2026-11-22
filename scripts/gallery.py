#!/usr/bin/env python3
"""The Countertop community gallery: check items, read submissions, and build the index the app reads.

    python3 scripts/gallery.py check              every item in items/ is valid (CI runs this on pull requests)
    python3 scripts/gallery.py build site         writes site/index.json and site/items/... for GitHub Pages
    python3 scripts/gallery.py submit result.json reads a submission issue (env BODY, AUTHOR, NUMBER) and writes its item

Items are the same .countertop files Countertop shares (Library > Share, or Share on a theme or effect),
plus a "gallery" block: {"author": GitHub login, "version": n, "updated": "YYYY-MM-DD"}.
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
KINDS = {"layout": "layouts", "theme": "themes", "effect": "effects"}
FORMAT = 1                     # the newest .countertop format Countertop reads
MAX_BYTES = 64 * 1024
NO_CODE_TILES = {"custom"}     # tiles that run their own code wait for the tile sandbox

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


def check(pkg):
    """A clean copy of a shared item, or Bad with what's wrong."""
    if not isinstance(pkg, dict):
        raise Bad("That isn't a Countertop file.")
    kind = pkg.get("countertop")
    if kind not in KINDS:
        raise Bad("That isn't a Countertop layout, theme or effect.")
    if not isinstance(pkg.get("format"), int) or not 1 <= pkg["format"] <= FORMAT:
        raise Bad("Unknown format %r (this gallery reads up to %d)." % (pkg.get("format"), FORMAT))
    name = text(pkg.get("name"), 60 if kind == "effect" else 80)
    if not name:
        raise Bad("It needs a name.")
    out = {"countertop": kind, "format": pkg["format"], "name": name, "description": text(pkg.get("description"), 500),
           "made": text(pkg.get("made"), 10)}
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
    if p.stat().st_size > MAX_BYTES:
        raise Bad("bigger than %d KB" % (MAX_BYTES // 1024))
    pkg = json.loads(p.read_text(encoding="utf-8"))
    g = pkg.get("gallery")
    if not isinstance(g, dict) or not isinstance(g.get("author"), str) or not isinstance(g.get("version"), int):
        raise Bad("needs a gallery block with author and version")
    clean = check(pkg)
    if clean["countertop"] != kind:
        raise Bad("is a %s but sits in %s/" % (clean["countertop"], KINDS[kind]))
    if p.stem != slug(clean["name"]) and not p.stem.startswith(slug(clean["name"]) + "-"):
        raise Bad("file name should come from its name: %s.countertop" % slug(clean["name"]))
    clean["gallery"] = {"author": g["author"], "version": g["version"], "updated": text(g.get("updated"), 10)}
    return clean


def cmd_check():
    bad = 0
    n = 0
    for kind, p in item_files():
        n += 1
        try:
            load_item(kind, p)
        except (Bad, ValueError) as e:
            bad += 1
            print("✗ %s: %s" % (p.relative_to(ROOT), e))
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
    for kind, p in item_files():
        clean = load_item(kind, p)
        g = clean.pop("gallery")
        iid = KINDS[kind] + "/" + p.stem
        dest = out / "items" / KINDS[kind]
        dest.mkdir(parents=True, exist_ok=True)
        (dest / p.name).write_text(json.dumps(clean, ensure_ascii=False, indent=1), encoding="utf-8")
        items.append({"id": iid, "kind": kind, "name": clean["name"], "description": clean["description"], "author": g["author"],
                      "version": g["version"], "updated": g["updated"], "file": "items/" + KINDS[kind] + "/" + p.name, "item": clean})
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
        base = slug(clean["name"])
        path = folder / (base + ".countertop")
        version = 1
        if path.exists():
            old = json.loads(path.read_text(encoding="utf-8")).get("gallery") or {}
            if old.get("author") == author:
                version = int(old.get("version") or 1) + 1        # the author's update to their own item
            else:
                i = 2
                while (folder / ("%s-%d.countertop" % (base, i))).exists():
                    i += 1
                path = folder / ("%s-%d.countertop" % (base, i))
        clean["gallery"] = {"author": author, "version": version, "updated": datetime.date.today().isoformat()}
        data = json.dumps(clean, ensure_ascii=False, indent=1) + "\n"
        if len(data.encode("utf-8")) > MAX_BYTES:
            raise Bad("It's bigger than %d KB." % (MAX_BYTES // 1024))
        path.write_text(data, encoding="utf-8")
        res.update(ok=True, path=str(path.relative_to(ROOT)), title="Add %s: %s%s" % (kind, clean["name"], " (version %d)" % version if version > 1 else ""),
                   message="Thanks! It checks out: %s %s called **%s**. A pull request is open for review; once it's merged it shows up in Library → Community." % ("an" if kind == "effect" else "a", kind, clean["name"].replace("*", "")))
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
