# Yes Clicker

A lightweight Windows utility that auto-clicks the **Yes** button in Antigravity
IDE's Claude Code permission prompts (e.g. *"Allow this bash command?"*). It
watches the screen, and only when it sees a *complete, genuine* prompt does it
click — otherwise it does nothing at all (no clicks, no mouse movement).

**Plug and play: no templates, no capture, no setup. Run it and it works.**

---

## Why

Inside the Antigravity IDE, Claude Code's native auto-accept doesn't work, so you
have to sit there clicking **Yes** on every command approval. Yes Clicker does it
for you in the background, so agents can keep working while you do something else.

---

## How it works

On Windows it reads the on-screen text with the built-in OCR engine
(`Windows.Media.Ocr`, ~0.1s, nothing to install) plus a bit of colour analysis,
every ~300ms (adaptive). It only clicks when it sees a real prompt:

- the **footer** — `Esc to cancel` / `Tell Claude what to do instead`
- a second signal in the same column — the `Allow this bash command?` header, a
  `2 No` option, or the **blue selection highlight bar** (detected by colour, so
  it works even when OCR misreads the highlighted "Yes" text)

It then clicks the highlighted **Yes** and presses Enter. Requiring the footer +
a tightly-grouped second element is what keeps it from firing on stray "yes" text
in your code or chat.

Safety layers: clicks only inside a confirmed prompt, a per-prompt cooldown (no
double-clicks), a pre-click re-check, a max-clicks-per-minute cap that auto-stops
if tripped, it never clicks its own window, and an **F9 panic key** stops
everything instantly from anywhere.

> **Note:** detection reads on-screen text, so if your editor/chat literally
> shows a prompt's exact phrases *and* a matching highlight bar, it could match
> that. Normal work doesn't, so it's reliable in real use. Use **Test detection on
> the REAL prompt** to confirm what it sees.

It handles **multiple agents at once** — every prompt visible on screen (any
window, any monitor) is clicked in the same pass.

---

## Get it

### Option A — download the .exe (easiest, no Python)
Grab `yes-clicker.exe` from the [Releases](../../releases) page and double-click
it. That's the whole install.

### Option B — run from source
```bash
pip install -r requirements.txt
python -m yes_clicker
```
Python 3.9+ on Windows.

---

## Using it

1. Open it — it **auto-starts** (green dot = watching). No setup.
2. Work in Antigravity. When a permission prompt appears, it clicks **Yes**.
3. Closing the window (**X**) keeps it running in the system tray by default
   (toggle in Settings). Fully quit from the tray menu → **Quit**.
4. **F9** stops it instantly from anywhere.

### The window
- Status dot + Start/Stop, live click counter
- **Sound: ON / OFF** mute toggle (also in the tray menu)
- **Run Live Test** (renders a fake prompt and clicks it), **Test detection on the
  REAL prompt** (scans your live screen and reports what it sees), **Audit**
- Collapsible **Statistics** (today / week / all-time, busiest hour, time saved)
- **Settings**: scan interval, max clicks/minute, and toggles for restore-mouse,
  click sound, auto-start, press-Enter-after-click, **Strict mode** (only click a
  visibly-highlighted option), and keep-running-in-tray-on-close

---

## CLI flags

| Flag        | Does                                                          |
|-------------|--------------------------------------------------------------|
| (none)      | Launch the GUI + tray                                         |
| `--test`    | Render a replica prompt, run the full detect+click pipeline, print PASS/FAIL |
| `--probe`   | 4s countdown, then scan the live screen once and report what it detected |
| `--audit`   | Health checks (OCR, capture, mouse, DPI, false-positive risk); exit 0/1 |
| `--stats`   | Print statistics and exit                                     |
| `--no-tray` | GUI without the system tray                                   |

---

## Build the .exe yourself

```bash
pip install -r requirements.txt
python build.py            # add --clean to wipe build/ dist/ first
```
Output: `dist/yes-clicker.exe` (`--onefile`, bundles the OCR engine — nothing to
install on the target machine).

---

## Performance

- `mss` capture, on-device OCR, and frame-change gating so a static screen costs
  almost nothing
- Adaptive polling (slows when idle, speeds up on activity)
- Only scans while Antigravity is the foreground window
- Single background thread; the UI never blocks

---

## Platform notes

Built and tested on Windows. On macOS/Linux there's no `Windows.Media.Ocr`, so it
falls back to OpenCV template matching, which needs a one-time capture via the
**Recapture** button (and on macOS, Screen Recording + Accessibility permissions —
`--audit` checks these).

---

## Files it writes (next to the app)

`settings.json` (your settings), `clicks.json` (click history, pruned to 90 days),
`yes-clicker.log` (timestamped log).

---

## License

MIT — see [LICENSE](LICENSE).
