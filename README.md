# Countertop gallery

Layouts, themes and effects made by people who use [Countertop](https://github.com/kizit/countertop), the kitchen dashboard.

In Countertop, open **Library → Community** to browse them. Nothing from here goes into your own Library until you press **Download**. A downloaded item gets a note when its author ships a new version, and you can remove it any time.

## Share something you made

1. In Countertop, open what you want to share and press **Share**, then **Copy share code**:
   - a layout: Library → Share a layout
   - a theme: Library → Themes → your theme → Share
   - an effect you made: Library → Effects → your effect → Share
2. [Open a submission](../../issues/new?template=submit.yml) and paste the code.

It's checked right away. If something's wrong, a comment on the issue says what, and you can edit the issue to try again. Otherwise a pull request opens. Once it's reviewed and merged, it shows up in Community, usually within a few minutes.

To update something you shared, submit it again under the same name. It replaces your earlier version, and people who downloaded it see that an update is available.

## What can go in

- **Layouts**: which tiles go where, and their settings. Your calendars, lists, teams, photos, Home Assistant devices and personal text are left out when Countertop makes a share code. Layouts with a *Your own tile* (one that runs its own code) can't be submitted yet; they'll come with the tile sandbox.
- **Themes**: colors, background, tiles, text size and dimming.
- **Effects**: up to 8 emoji and how they move (fall, float up, fly across or wander), with a size, a speed and an optional season. Effects are plain data: there's no code in them.

Everything here is shared under the [MIT license](LICENSE). Please submit only things you made or may share, with nothing private in them.

## How it works

- `items/layouts`, `items/themes` and `items/effects` hold `.countertop` files, the same format Countertop shares, plus a `gallery` block with the author's GitHub name and a version number. The format is described in [sharing layouts, themes and effects](https://github.com/kizit/countertop/blob/main/docs/sharing-layouts.md).
- `scripts/gallery.py` checks items, turns a submission issue into an item, and builds `index.json`.
- The **Submission** workflow runs on submission issues and opens a pull request. **Check** runs on every pull request. **Publish** puts `index.json` on GitHub Pages when `main` changes; Countertop reads it from there.
- `revoked.json` lists item ids (like `themes/calm-evening`) that were taken down. Countertop stops offering them and tells anyone who downloaded one.
- Countertop checks every item again when it's downloaded, so a file here can never change anything beyond what the Library allows.

Run the checks locally with `python3 scripts/gallery.py check` and `python3 -m unittest discover -s tests`. Only the Python standard library is needed.
