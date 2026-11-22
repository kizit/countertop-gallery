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
        for bad in ({"countertop": "tile", "format": 1, "name": "x"}, dict(THEME, format=2)):
            with self.assertRaises(g.Bad):
                g.check(bad)

    def test_read_code(self):
        self.assertEqual(g.read_code(code(THEME))["name"], "Glass")
        self.assertEqual(g.read_code("```json\n" + json.dumps(THEME) + "\n```")["name"], "Glass")
        with self.assertRaises(g.Bad):
            g.read_code("CT1.not-base64!!")


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


class RealItems(unittest.TestCase):
    def test_items_in_this_repo(self):
        self.assertEqual(g.cmd_check(), 0)


if __name__ == "__main__":
    unittest.main()
