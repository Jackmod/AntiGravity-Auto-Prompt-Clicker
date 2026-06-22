# Auto Picker

**Auto Picker** watches your screen and automatically clicks **"Yes"** on Claude Code
approval prompts inside the **Antigravity IDE** — so you stop breaking flow to confirm
every action. The moment it sees anything it _doesn't_ confidently recognize, it
**pauses** instead of guessing.

- 🖥️ **Windows & macOS** — same code, native on both.
- 🧠 **On-device only** — screen reading and OCR happen locally. Nothing is uploaded.
- 🛟 **Safe by design** — only clicks inside a trusted prompt, double-confirms, rate-limits, and pauses on anything ambiguous.
- 🎛️ **Real settings** — every toggle and slider changes behaviour live.
- ✨ **Fluid UI** — GPU-only animations, light on the CPU.
- 🔓 **Open source (MIT)** — clone it, read it, change it.

---

## Quick start (no build needed)

1. Install **Node.js LTS** once from <https://nodejs.org> (only needed if you run from source).
2. Download / clone this folder.
3. Double-click the launcher for your OS:
   - **Windows:** `start-windows.bat`
   - **macOS:** `start-macos.command` (first time: right-click → **Open**)

The launcher installs dependencies on the first run, then opens the app. Every run after
that just opens it.

> First launch downloads the English OCR model (~a few MB) once, then works offline.

### macOS permissions
macOS will ask for **Screen Recording** and **Accessibility** permission the first time
(System Settings → Privacy & Security). These are required for any app that reads the
screen or moves the mouse. Grant both, then relaunch.

---

## How it works

```
        ┌───────────── main process (Node) ─────────────┐
screen ─▶ screen-capture ─▶ ocr ─▶ analyzer ─▶ engine ─▶ clicker ─▶ mouse
        └───────────────────────┬───────────────────────┘
                                │ IPC (secure preload bridge)
                        ┌───────▼────────┐
                        │  renderer UI   │  dashboard · settings · activity
                        └────────────────┘
```

1. **Capture** — grabs the screen (or a region you choose) via `nut-js`.
2. **OCR** — `tesseract.js` reads the words and their on-screen positions.
3. **Analyze** — decides `click` / `pause` / `none`:
   - **click**: a trusted prompt phrase _and_ an accept word ("Yes/Allow/…") are present.
   - **pause**: a prompt clearly needs a decision but "Yes" isn't safely identifiable.
   - **none**: nothing actionable — keep watching.
4. **Click** — moves to the button and clicks, respecting cooldown, rate limits, and dry-run.

## Settings that actually do something

| Group | Highlights |
|------|-----------|
| **General** | auto-start, launch minimized, live preview, theme, accent colour |
| **Detection** | scan interval, OCR confidence, accept/reject words, trusted phrases, pause-on-unknown |
| **Automation** | auto-click master switch, **dry run**, double-confirm, click delay, cooldown, cursor restore |
| **Safety** | corner fail-safe, max clicks/min, global toggle hotkey |

**Tip:** turn on **Dry run** first. The app will detect and log what it _would_ click
without touching your mouse, so you can tune the keywords for your setup. Then turn it off.

## Build installers

```bash
npm run dist:win   # → release/AutoPicker-Setup-1.0.0.exe
npm run dist:mac   # → release/AutoPicker-1.0.0-<arch>.dmg
```

## Project layout

```
src/
  main/        main.js · ipc.js · engine.js · settings-store.js · util/logger.js
    detector/  screen-capture.js · ocr.js · analyzer.js
    automation/clicker.js
  preload/     preload.js   (secure renderer bridge)
  renderer/    index.html · styles/ · js/ (app.js, animations.js)
```

## License

MIT — see [LICENSE](LICENSE).
