"""Checks for scripts/gallery.py. Run with: python3 -m unittest discover -s tests"""

import base64
import importlib.util
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("gallery", ROOT / "scripts" / "gallery.py")
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)


def code(pkg):
    return "CT1." + base64.urlsafe_b64encode(json.dumps(pkg).encode()).decode().rstrip("=")


THEME = {"countertop": "theme", "format": 1, "name": "Glass", "values": {"tiles": "See-through", "opacity": 45, "nope": 1}}
EFFECT = {"countertop": "effect", "format": 1, "name": "Hearts", "effect": {"glyphs": ["💕", "❤️"], "motion": "rise"}}
LAYOUT = {"countertop": "layout", "format": 1, "name": "Two up", "look": {"mode": "Light"},
          "pages": [{"name": "Two up", "boxes": [{"x": 0, "y": 0, "w": 24, "h": 32, "tiles": [{"type": "clock", "settings": {"style": "Bold"}}]}]}]}


TILE = {"countertop": "tile", "format": 1, "id": "moon-facts", "name": "Moon facts", "description": "A fact about the moon.", "size": [12, 8, 8, 6],
        "uses": ["store", "fetch"], "feeds": ["wx"], "hosts": ["api.example.com"], "taps": True, "every": 60,
        "settings": {"label": {"type": "text", "label": "Label", "default": "Taps"}},
        "code": 'Tile("moon-facts", {render(el){ el.textContent = "hi"; }});'}
PORCH = {"countertop": "tile", "format": 1, "id": "front-porch", "name": "Front porch", "size": [12, 10, 10, 8], "taps": True,
         "devices": {"light": {"label": "Porch light", "domains": ["light", "switch"]}, "lock": {"label": "Front door", "domains": ["lock"]}},
         "controls": [{"id": "on", "device": "light", "action": "turn_on"}, {"id": "lock", "device": "lock", "action": "lock"}],
         "code": 'Tile("front-porch", {render(el){}});'}


def tile(**change):
    t = json.loads(json.dumps(TILE)); t.update(change)
    return t


def issue(c, desc="", ok=True):
    return "### Share code\n\n```text\n%s\n```\n\n### What it's for\n\n%s\n\n### Permission\n\n- [%s] I made this" % (c, desc or "_No response_", "X" if ok else " ")


class Check(unittest.TestCase):
    def test_theme_keeps_known_settings(self):
        self.assertEqual(g.check(THEME)["values"], {"tiles": "See-through", "opacity": 45})

    def test_theme_bad_value(self):
        with self.assertRaises(g.Bad):
            g.check(dict(THEME, values={"accent": "url(x)"}))

    def test_effect_needs_emoji(self):
        self.assertEqual(g.check(EFFECT)["effect"]["glyphs"], ["💕", "❤️"])
        for bad in (["<b>"], ["hi"], [], ["⭐"] * 9):
            with self.assertRaises(g.Bad):
                g.check(dict(EFFECT, effect={"glyphs": bad}))

    def test_effect_season(self):
        with self.assertRaises(g.Bad):
            g.check(dict(EFFECT, effect={"glyphs": ["⭐"], "from": "13-1", "to": "1-1"}))
        self.assertEqual(g.check(dict(EFFECT, effect={"glyphs": ["⭐"], "from": "12-1", "to": "12-31"}))["effect"]["to"], "12-31")

    def test_layout(self):
        c = g.check(LAYOUT)
        self.assertEqual(c["pages"][0]["boxes"][0]["tiles"][0]["type"], "clock")
        with self.assertRaises(g.Bad):
            bad = json.loads(json.dumps(LAYOUT)); bad["pages"][0]["boxes"][0]["w"] = 49
            g.check(bad)

    def test_layout_with_code_tile_waits(self):
        bad = json.loads(json.dumps(LAYOUT)); bad["pages"][0]["boxes"][0]["tiles"] = [{"type": "custom", "settings": {"html": "<script>"}}]
        with self.assertRaises(g.Bad):
            g.check(bad)

    def test_unknown_kind_and_newer_format(self):
        for bad in ({"countertop": "widget", "format": 1, "name": "x"}, dict(THEME, format=2)):
            with self.assertRaises(g.Bad):
                g.check(bad)

    def test_read_code(self):
        self.assertEqual(g.read_code(code(THEME))["name"], "Glass")
        self.assertEqual(g.read_code("```json\n" + json.dumps(THEME) + "\n```")["name"], "Glass")
        with self.assertRaises(g.Bad):
            g.read_code("CT1.not-base64!!")


class CheckTile(unittest.TestCase):
    def bad(self, **change):
        with self.assertRaises(g.Bad):
            g.check(tile(**change))

    def test_good_tile(self):
        c = g.check(TILE)
        self.assertEqual((c["countertop"], c["id"], c["hosts"], c["feeds"], c["uses"], c["taps"], c["every"]),
                         ("tile", "moon-facts", ["api.example.com"], ["wx"], ["store", "fetch"], True, 60))
        self.assertEqual(c["settings"]["label"]["default"], "Taps")
        self.assertNotIn("version", c)

    def test_identity(self):
        for bad in ("Moon", "m", "moon_facts", "-moon", "x" * 41, "", None, "clock", "custom"):
            self.bad(id=bad)

    def test_code(self):
        self.bad(code="")
        self.bad(code=" \n")
        self.bad(code="x" * (64 * 1024 + 1))
        self.assertEqual(g.check(tile(code="x" * (64 * 1024)))["code"][:1], "x")

    def test_size_and_data(self):
        self.bad(size=[12, 8, 8])
        self.bad(size=[12, 8, 8, 1])
        self.bad(size=[49, 8, 8, 6])
        self.bad(feeds=["wx", "passwords"])
        self.bad(hosts=["127.0.0.1"])
        self.bad(hosts=["http://api.example.com"])
        self.bad(hosts=["a%d.example.com" % i for i in range(11)])
        self.bad(settings={"x": {"type": "html"}})
        self.bad(settings={"x": {"type": "source", "kind": "lists"}})        # needs the notes feed

    def test_personal_data_or_sites_never_both(self):
        self.bad(feeds=["events"])                                           # hosts are still there
        c = g.check(tile(feeds=["events"], hosts=[]))
        self.assertEqual(c["feeds"], ["events"])
        for f in ("notes", "photos", "sales"):
            self.bad(feeds=[f])
        self.assertEqual(g.check(tile(feeds=["wx", "aqi", "team"]))["hosts"], ["api.example.com"])

    def test_keys(self):
        key = {"type": "secret", "label": "API key", "host": "api.example.com", "header": "X-Api-Key"}
        c = g.check(tile(settings={"key": key}))
        self.assertEqual(c["settings"]["key"]["prefix"], "")
        for change in ({"host": "other.example.com"}, {"host": "*.example.com"}, {"header": "Cookie"}, {"header": "Bad Header"},
                       {"query": "k"}, {"header": None}, {"prefix": "é" * 3}):
            self.bad(settings={"key": dict(key, **change)})
        self.assertEqual(g.check(tile(settings={"key": {"type": "secret", "host": "api.example.com", "query": "appid"}}))["settings"]["key"]["query"], "appid")
        self.bad(settings={"key": key}, feeds=["notes"])                    # a key means sites, and personal data has none
        self.bad(settings={"k%d" % i: dict(key) for i in range(4)})

    def test_control_tile(self):
        c = g.check(PORCH)
        self.assertEqual(sorted(c["devices"]), ["light", "lock"])
        self.assertEqual(c["controls"][0], {"id": "on", "device": "light", "action": "turn_on", "data": {}})
        self.assertEqual(c["hosts"], [])
        for change in ({"controls": [{"id": "x", "device": "light", "action": "lock"}]},          # not a light's action
                       {"controls": [{"id": "x", "device": "nope", "action": "turn_on"}]},
                       {"controls": [{"id": "on", "device": "light", "action": "turn_on"}] * 2},
                       {"controls": [{"id": "x", "device": "light", "action": "turn_on", "data": {"code": "1234"}}]},
                       {"controls": [{"id": "x", "device": "light", "action": "turn_on", "data": {"entity_id": "lock.door"}}]},
                       {"devices": {"light": {"label": "x", "domains": ["toaster"]}}},
                       {"controls": []}, {"devices": {}}):
            with self.assertRaises(g.Bad):
                g.check(dict(PORCH, **change))
        with self.assertRaises(g.Bad):
            g.check(dict(PORCH, hosts=["api.example.com"]))                  # devices are personal too

    def test_layout_names_its_community_tile(self):
        lay = json.loads(json.dumps(LAYOUT))
        lay["pages"][0]["boxes"][0]["tiles"] = [{"type": "moon-facts", "from": {"id": "tiles/moon-facts", "v": 2}, "settings": {"label": "Hi"}}]
        c = g.check(lay)
        self.assertEqual(c["pages"][0]["boxes"][0]["tiles"][0]["from"], {"id": "tiles/moon-facts", "v": 2})
        self.assertEqual(g.tile_refs(c), {"tiles/moon-facts"})
        lay["pages"][0]["boxes"][0]["tiles"][0]["from"]["id"] = "tiles/other"
        with self.assertRaises(g.Bad):
            g.check(lay)

    def test_layout_with_your_own_tile_still_refused(self):
        bad = json.loads(json.dumps(LAYOUT)); bad["pages"][0]["boxes"][0]["tiles"] = [{"type": "custom", "settings": {}}]
        with self.assertRaises(g.Bad):
            g.check(bad)


class Submit(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.old = g.ITEMS, g.ROOT
        g.ROOT = self.tmp; g.ITEMS = self.tmp / "items"
        (self.tmp / "revoked.json").write_text("[]")

    def tearDown(self):
        g.ITEMS, g.ROOT = self.old
        shutil.rmtree(self.tmp)

    def run_submit(self, body, author="someone"):
        os.environ["BODY"], os.environ["AUTHOR"] = body, author
        out = self.tmp / "r.json"
        g.cmd_submit(out)
        return json.loads(out.read_text())

    def test_new_then_update_then_someone_else(self):
        r = self.run_submit(issue(code(THEME), "For sunny days."))
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["path"], "items/themes/glass.countertop")
        item = json.loads((self.tmp / r["path"]).read_text())
        self.assertEqual((item["description"], item["gallery"]["version"], item["gallery"]["author"]), ("For sunny days.", 1, "someone"))
        r = self.run_submit(issue(code(THEME)))
        self.assertEqual(json.loads((self.tmp / r["path"]).read_text())["gallery"]["version"], 2)
        r = self.run_submit(issue(code(THEME)), author="other")
        self.assertEqual(r["path"], "items/themes/glass-2.countertop")
        self.assertEqual(g.cmd_check(), 0)

    def test_refusals(self):
        self.assertFalse(self.run_submit(issue(code(THEME), ok=False))["ok"])
        self.assertFalse(self.run_submit(issue("hello"))["ok"])
        self.assertFalse(self.run_submit(issue(code(THEME)), author="bad name")["ok"])
        self.assertFalse((self.tmp / "items").exists())

    def test_build(self):
        self.run_submit(issue(code(EFFECT)))
        self.run_submit(issue(code(LAYOUT)))
        g.cmd_build(self.tmp / "site")
        idx = json.loads((self.tmp / "site" / "index.json").read_text())
        self.assertEqual(sorted(i["id"] for i in idx["items"]), ["effects/hearts", "layouts/two-up"])
        self.assertNotIn("gallery", idx["items"][0]["item"])
        self.assertTrue((self.tmp / "site" / "items" / "effects" / "hearts.countertop").exists())


class SubmitTiles(Submit):
    def test_tile_then_update_then_someone_else(self):
        r = self.run_submit(issue(code(TILE), "Lunar trivia."))
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["path"], "items/tiles/moon-facts.countertop")
        self.assertIn("line by line", r["message"])
        item = json.loads((self.tmp / r["path"]).read_text())
        self.assertEqual((item["description"], item["gallery"], item["id"]), ("Lunar trivia.", item["gallery"], "moon-facts"))
        self.assertEqual((item["gallery"]["version"], item["gallery"]["author"]), (1, "someone"))
        self.assertNotIn("author", item)
        r = self.run_submit(issue(code(tile(code='Tile("moon-facts", {render(){}});'))))
        self.assertEqual(json.loads((self.tmp / r["path"]).read_text())["gallery"]["version"], 2)
        r = self.run_submit(issue(code(TILE)), author="other")
        self.assertFalse(r["ok"])
        self.assertIn("different id", r["message"])
        self.assertEqual(g.cmd_check(), 0)

    def test_taken_down_tile_stays_down(self):
        (self.tmp / "revoked.json").write_text('["tiles/moon-facts"]')
        r = self.run_submit(issue(code(TILE)))
        self.assertFalse(r["ok"])
        self.assertIn("taken down", r["message"])

    def test_bad_tile_is_explained(self):
        r = self.run_submit(issue(code(tile(feeds=["events"]))))
        self.assertFalse(r["ok"])
        self.assertIn("personal data", r["message"])
        self.assertFalse((self.tmp / "items").exists())

    def test_layout_needs_its_tile_in_the_gallery(self):
        lay = json.loads(json.dumps(LAYOUT))
        lay["pages"][0]["boxes"][0]["tiles"] = [{"type": "moon-facts", "from": {"id": "tiles/moon-facts", "v": 1}}]
        r = self.run_submit(issue(code(lay)))
        self.assertFalse(r["ok"])
        self.assertIn("Submit the tile first", r["message"])
        self.assertTrue(self.run_submit(issue(code(TILE)))["ok"])
        self.assertTrue(self.run_submit(issue(code(lay)))["ok"])
        self.assertEqual(g.cmd_check(), 0)

    def test_check_finds_a_layout_without_its_tile(self):
        self.run_submit(issue(code(TILE)))
        lay = json.loads(json.dumps(LAYOUT))
        lay["pages"][0]["boxes"][0]["tiles"] = [{"type": "moon-facts", "from": {"id": "tiles/moon-facts", "v": 1}}]
        self.assertTrue(self.run_submit(issue(code(lay)))["ok"])
        (self.tmp / "items" / "tiles" / "moon-facts.countertop").unlink()
        self.assertEqual(g.cmd_check(), 1)

    def test_build_lists_the_tile_the_way_the_app_reads_it(self):
        self.run_submit(issue(code(TILE)))
        self.run_submit(issue(code(PORCH)))
        shot = self.tmp / "items" / "tiles" / "moon-facts.png"
        shot.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 20)
        self.assertEqual(g.cmd_check(), 0)
        g.cmd_build(self.tmp / "site")
        idx = json.loads((self.tmp / "site" / "index.json").read_text())
        e = {i["id"]: i for i in idx["items"]}["tiles/moon-facts"]
        self.assertEqual((e["kind"], e["author"], e["version"], e["shot"]), ("tile", "someone", 1, "items/tiles/moon-facts.png"))
        self.assertEqual((e["item"]["countertop"], e["item"]["id"], e["item"]["author"]), ("tile", "moon-facts", "someone"))
        self.assertNotIn("version", e["item"])
        self.assertNotIn("gallery", e["item"])
        self.assertIn("code", e["item"])
        self.assertNotIn("shot", {i["id"]: i for i in idx["items"]}["tiles/front-porch"])
        self.assertTrue((self.tmp / "site" / "items" / "tiles" / "moon-facts.png").exists())

    def test_screenshots_are_checked(self):
        self.run_submit(issue(code(TILE)))
        pics = self.tmp / "items" / "tiles"
        (pics / "moon-facts.png").write_bytes(b"not a picture")
        self.assertEqual(g.cmd_check(), 1)
        (pics / "moon-facts.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 600_000)
        self.assertEqual(g.cmd_check(), 1)
        (pics / "moon-facts.png").unlink()
        (pics / "nobody.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        self.assertEqual(g.cmd_check(), 1)                      # a picture with no tile


class RealItems(unittest.TestCase):
    def test_items_in_this_repo(self):
        self.assertEqual(g.cmd_check(), 0)


if __name__ == "__main__":
    unittest.main()
