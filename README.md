# Countertop gallery

Layouts, themes, effects and tiles made by people who use [Countertop](https://github.com/kizit/countertop), the home dashboard.

In Countertop, open **Library → Community** to browse them. Nothing from here goes into your own Library until you press **Download**. A downloaded item gets a note when its author ships a new version, and you can remove it any time.

## Share something you made

1. In Countertop, open what you want to share:
   - a layout: Library → Share a layout
   - a theme: Library → Themes → open your theme → Share
   - an effect you made: Library → Effects → open your effect → Share
   - a tile: Library → New tile (Tile Studio) → open your tile → Submit to the gallery
2. On a Share screen, press **Submit to the gallery**. It opens the [submission form](../../issues/new?template=submit.yml) with the share code filled in (or copied, if it's too long for an address; paste it into the form). You can also copy the code yourself and paste it into the form, or use **Library → Browse community → Submit yours**.

It's checked right away. If something's wrong, a comment on the issue says what, and you can edit the issue to try again. Otherwise a pull request opens. Once it's reviewed and merged, it shows up in Community, usually within a few minutes.

To update something you shared, submit it again under the same name. It replaces your earlier version, and people who downloaded it see that an update is available.

## What can go in

- **Layouts**: which tiles go where, and their settings. Your calendars, lists, teams, photos, Home Assistant devices and personal text are left out when Countertop makes a share code. Layouts with a *Your own tile* (one that runs its own code) can't be submitted; publish the tile as a community tile instead. A layout can use community tiles from this gallery: the tile has to be here first, and people who download the layout are offered the tile too.
- **Themes**: colors, background, tiles, text size and dimming.
- **Effects**: up to 8 emoji and how they move (fall, float up, fly across or wander), with a size, a speed and an optional season. Effects are plain data: there's no code in them.
- **Tiles**: a tile with its own code. See below.

## Tiles

A community tile is one `.countertop` file with `"countertop": "tile"`: what it is (`id`, `name`, `description`, `size`, `settings`), what it can reach, and its code. Countertop runs it in a locked box and shows everyone what it can do before they download it, so the file has to say so up front:

- `feeds`: the shared data it reads: `wx`, `aqi`, `events`, `notes`, `team`, `photos`, `sales`.
- `hosts`: public sites it reads from, like `api.example.com` (at most 10, no addresses, ports or paths).
- `devices` and `controls`: buttons for Home Assistant things (lights, locks and so on). The tile's code never sends actions itself; Countertop draws the buttons and the person picks which device each one works.
- `settings` of type `secret`: an API key the person types in. It's kept by Countertop and sent only to the one host the setting names.
- `taps`: whether it does something when tapped.

**Personal data or the internet, never both.** A tile that reads `events`, `notes`, `photos` or `sales`, or that has `devices`, can't also list `hosts`, and a `secret` needs a host. The check refuses the combination.

The code is limited to 64 KB, the id (2 to 40 lower-case letters, digits and dashes) must be one nobody has used and not the id of a tile that comes with Countertop, and the file is named `<id>.countertop`. A tile's code is only ever read and published here, never run. Every tile is read through by a person before it's merged, and again for each new version. The same checks run in Countertop when someone downloads it.

The issue form takes the text of the file. Updating works as for everything else: submit it again with the same id from the same GitHub account and the version goes up by one. Someone else can't take over an id. A screenshot is optional: add `items/tiles/<id>.png` (or `.jpg`, under 600 KB) to the pull request and Community shows it.

Everything here is shared under the [MIT license](LICENSE). Please submit only things you made or may share, with nothing private in them.

## How it works

- `items/layouts`, `items/themes`, `items/effects` and `items/tiles` hold `.countertop` files, the same format Countertop shares, plus a `gallery` block with the author's GitHub name and a version number. The format is described in [sharing layouts, themes and effects](https://github.com/kizit/countertop/blob/main/docs/sharing-layouts.md).
- `scripts/gallery.py` checks items, turns a submission issue into an item, and builds `index.json`.
- The **Submission** workflow runs on submission issues and opens a pull request. **Check** runs on every pull request. **Publish** puts `index.json` on GitHub Pages when `main` changes; Countertop reads it from there.
- `revoked.json` lists item ids (like `themes/calm-evening` or `tiles/moon-facts`) that were taken down. Countertop stops offering them and tells anyone who downloaded one; a downloaded tile stops running on their screens. A taken-down tile id can't be submitted again by issue.
- Countertop checks every item again when it's downloaded, so a file here can never change anything beyond what the Library allows.

Run the checks locally with `python3 scripts/gallery.py check` and `python3 -m unittest discover -s tests`. Only the Python standard library is needed.
