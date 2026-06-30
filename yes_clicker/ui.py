"""Dark-themed tkinter UI.

Threading model: the engine runs on its own worker thread and pushes events into
a queue; the UI drains that queue on the Tk thread via ``after`` so widgets are
only ever touched from the main thread. Redraws happen on real events — the
counter and log update on a click, the status dot on a state change — never on a
periodic repaint.
"""

from __future__ import annotations

import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox

from . import config, paths
from .audit import format_audit, run_audit
from .engine import Engine, EngineEvent
from .stats import Stats, _fmt_duration

# Palette
BG = "#1b1b1d"
PANEL = "#242427"
CARD = "#2b2b2f"
TEXT = "#e6e6e6"
DIM = "#9a9aa0"
ACCENT = "#4ea1ff"
GREEN = "#2ecc71"
RED = "#e74c3c"
BTN = "#33333a"
BTN_HOVER = "#3e3e47"


class App:
    def __init__(self, settings: config.Settings, stats: Stats, engine: Engine,
                 relaunch_argv, tray=None):
        self.settings = settings
        self.stats = stats
        self.engine = engine
        self.relaunch_argv = relaunch_argv  # list -> base command to re-run app
        self.tray = tray

        self._events: "queue.Queue[tuple]" = queue.Queue()
        self.engine.on_event = self._post_event

        self.root = tk.Tk()
        self.root.title("Yes Clicker")
        self.root.configure(bg=BG)
        self.root.geometry("440x640")
        self.root.minsize(420, 560)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._stats_open = tk.BooleanVar(value=False)
        self._settings_open = tk.BooleanVar(value=True)

        self._build()
        self._refresh_status()
        self._refresh_stats()
        self._refresh_log()
        self.root.after(120, self._drain_events)

    # --- event plumbing ---
    def _post_event(self, kind, payload=None):
        self._events.put((kind, payload))

    def _drain_events(self):
        try:
            while True:
                kind, payload = self._events.get_nowait()
                self._handle_event(kind, payload)
        except queue.Empty:
            pass
        self._update_self_rect()
        self.root.after(120, self._drain_events)

    def _update_self_rect(self):
        """Tell the engine where our own window is, so it never clicks itself."""
        try:
            if not self.root.winfo_viewable():
                self.engine.exclude_logical_rect = None
            else:
                self.engine.exclude_logical_rect = (
                    self.root.winfo_rootx(), self.root.winfo_rooty(),
                    self.root.winfo_width(), self.root.winfo_height())
        except tk.TclError:
            self.engine.exclude_logical_rect = None

    def _handle_event(self, kind, payload):
        if kind == EngineEvent.CLICK:
            self._refresh_counter()
            self._refresh_log()
            self._refresh_stats()
        elif kind == EngineEvent.STATE:
            self._refresh_status()
            if self.tray:
                self.tray.update_state()
        elif kind == EngineEvent.RATE_TRIPPED:
            self._refresh_status()
            if self.tray:
                self.tray.update_state()
            messagebox.showwarning(
                "Yes Clicker — auto-stopped",
                f"More than {payload} clicks in a minute. Something may be wrong, "
                f"so the clicker stopped itself.\n\nReview the log, then press Start "
                f"to resume.")
        elif kind == EngineEvent.IDLE_ALERT:
            if self.tray:
                self.tray.notify(f"No prompt for {payload} minutes — still watching.")
        elif kind == EngineEvent.RECAPTURE:
            if self.tray:
                self.tray.notify("Match confidence is low — consider recapturing templates.")
            self._set_banner("Low match confidence lately — try Recapture Templates.", RED)
        elif kind == EngineEvent.PANIC:
            self._refresh_status()
            self._set_banner("PANIC (F9) — clicker stopped.", RED)
        elif kind == EngineEvent.DPI_CHANGED:
            self._set_banner("Display/DPI change detected — re-detected monitors.", ACCENT)

    # --- layout ---
    def _build(self):
        pad = {"padx": 16, "pady": 6}

        # Banner (hidden until needed)
        self.banner = tk.Label(self.root, text="", bg=BG, fg=DIM,
                               font=("Segoe UI", 9), anchor="w", justify="left",
                               wraplength=400)
        self.banner.pack(fill="x", padx=16, pady=(8, 0))

        # Status row
        status = tk.Frame(self.root, bg=BG)
        status.pack(fill="x", **pad)
        self.dot = tk.Canvas(status, width=26, height=26, bg=BG, highlightthickness=0)
        self.dot.pack(side="left")
        self._dot_id = self.dot.create_oval(3, 3, 23, 23, fill=RED, outline="")
        self.status_label = tk.Label(status, text="Stopped", bg=BG, fg=TEXT,
                                     font=("Segoe UI", 15, "bold"))
        self.status_label.pack(side="left", padx=10)

        self.start_btn = self._button(status, "Start", self._toggle, width=10)
        self.start_btn.pack(side="right")

        # Counter + quick mute toggle
        crow = tk.Frame(self.root, bg=BG)
        crow.pack(fill="x", padx=16, pady=(0, 4))
        self.counter_label = tk.Label(
            crow, text="Clicked 0 times this session", bg=BG, fg=ACCENT,
            font=("Segoe UI", 11))
        self.counter_label.pack(side="left")
        self.mute_btn = self._button(crow, "", self._toggle_mute, width=12)
        self.mute_btn.pack(side="right")
        self._refresh_mute()

        # Action buttons row
        actions = tk.Frame(self.root, bg=BG)
        actions.pack(fill="x", **pad)
        self._button(actions, "Run Live Test", self._run_test).pack(side="left", expand=True, fill="x", padx=(0, 4))
        self._button(actions, "Audit", self._run_audit).pack(side="left", expand=True, fill="x", padx=4)
        self._button(actions, "Recapture", self._recapture).pack(side="left", expand=True, fill="x", padx=(4, 0))

        # Real-prompt detection test (the one that actually tells you if it'll work
        # in Antigravity). Counts down so you can switch to the real prompt.
        self._button(self.root, "Test detection on the REAL prompt (5s countdown)",
                     self._probe_real).pack(fill="x", padx=16, pady=(0, 4))

        # Recent log card
        logcard = self._card(self.root, "Recent clicks")
        self.log_text = tk.Label(logcard, text="", bg=CARD, fg=DIM, justify="left",
                                 anchor="nw", font=("Consolas", 9))
        self.log_text.pack(fill="both", expand=True, padx=12, pady=(0, 10))

        # Collapsible stats
        self._collapsible(self.root, "Statistics", self._stats_open, self._build_stats)
        # Settings
        self._collapsible(self.root, "Settings", self._settings_open, self._build_settings)

    def _card(self, parent, title):
        wrap = tk.Frame(parent, bg=CARD)
        wrap.pack(fill="x", padx=16, pady=6)
        tk.Label(wrap, text=title, bg=CARD, fg=TEXT, font=("Segoe UI", 10, "bold"),
                 anchor="w").pack(fill="x", padx=12, pady=(8, 4))
        return wrap

    def _collapsible(self, parent, title, var, body_builder):
        header = tk.Frame(parent, bg=PANEL)
        header.pack(fill="x", padx=16, pady=(8, 0))
        arrow = tk.Label(header, text="▾" if var.get() else "▸", bg=PANEL, fg=ACCENT,
                         font=("Segoe UI", 10))
        arrow.pack(side="left", padx=(10, 4), pady=6)
        tk.Label(header, text=title, bg=PANEL, fg=TEXT, font=("Segoe UI", 10, "bold")
                 ).pack(side="left")
        body = tk.Frame(parent, bg=CARD)
        if var.get():
            body.pack(fill="x", padx=16)

        def toggle(_e=None):
            if var.get():
                var.set(False)
                body.pack_forget()
                arrow.config(text="▸")
            else:
                var.set(True)
                body.pack(fill="x", padx=16)
                arrow.config(text="▾")
        for w in (header, arrow):
            w.bind("<Button-1>", toggle)
        header.bind("<Button-1>", toggle)
        body_builder(body)

    def _button(self, parent, text, cmd, width=0):
        b = tk.Button(parent, text=text, command=cmd, bg=BTN, fg=TEXT,
                      activebackground=BTN_HOVER, activeforeground=TEXT,
                      relief="flat", bd=0, font=("Segoe UI", 10), cursor="hand2",
                      padx=10, pady=6)
        if width:
            b.config(width=width)
        b.bind("<Enter>", lambda e: b.config(bg=BTN_HOVER))
        b.bind("<Leave>", lambda e: b.config(bg=BTN))
        return b

    # --- stats panel ---
    def _build_stats(self, parent):
        self.stats_labels = {}
        for key in ("today", "week", "all", "avg", "busiest", "saved"):
            row = tk.Frame(parent, bg=CARD)
            row.pack(fill="x", padx=12, pady=2)
            tk.Label(row, text="", bg=CARD, fg=DIM, font=("Segoe UI", 9), anchor="w",
                     width=18).pack(side="left")
            val = tk.Label(row, text="", bg=CARD, fg=TEXT, font=("Segoe UI", 9, "bold"),
                           anchor="w")
            val.pack(side="left")
            self.stats_labels[key] = (row.winfo_children()[0], val)
        tk.Frame(parent, bg=CARD, height=8).pack()

    def _refresh_stats(self):
        if not hasattr(self, "stats_labels"):
            return
        s = self.stats
        busiest = s.busiest_hour() or "—"
        data = {
            "today": ("Clicks today", str(s.today())),
            "week": ("This week", str(s.this_week())),
            "all": ("All time", str(s.all_time())),
            "avg": ("Avg / day", f"{s.avg_per_day():.1f}"),
            "busiest": ("Busiest hour", f"{busiest} is your peak" if busiest != "—" else "—"),
            "saved": ("Saved this week", f"~{_fmt_duration(s.time_saved_week_seconds())}"),
        }
        for key, (label, value) in data.items():
            lab, val = self.stats_labels[key]
            lab.config(text=label)
            val.config(text=value)

    # --- settings panel ---
    def _build_settings(self, parent):
        s = self.settings

        self.interval_var = tk.IntVar(value=s.scan_interval_ms)
        self._slider(parent, "Scan interval (ms)", self.interval_var, 100, 2000, 50,
                     self._apply_settings)

        self.conf_var = tk.DoubleVar(value=s.confidence_threshold)
        self._slider(parent, "Match confidence", self.conf_var, 0.70, 0.99, 0.01,
                     self._apply_settings, is_float=True)

        self.rate_var = tk.IntVar(value=s.max_clicks_per_minute)
        self._slider(parent, "Max clicks / minute", self.rate_var, 1, 120, 1,
                     self._apply_settings)

        self.restore_var = tk.BooleanVar(value=s.restore_mouse)
        self._check(parent, "Move mouse back after clicking", self.restore_var,
                    self._apply_settings)
        self.sound_var = tk.BooleanVar(value=s.play_sound)
        self._check(parent, "Play a soft sound on click", self.sound_var,
                    self._apply_settings)
        self.autostart_var = tk.BooleanVar(value=s.auto_start)
        self._check(parent, "Auto-start scanning on launch", self.autostart_var,
                    self._apply_settings)
        self.enter_var = tk.BooleanVar(value=s.confirm_enter)
        self._check(parent, "Press Enter after clicking Yes", self.enter_var,
                    self._apply_settings)
        self.strict_var = tk.BooleanVar(value=s.require_highlight)
        self._check(parent, "Strict: only click the highlighted Yes (fewer false clicks)",
                    self.strict_var, self._apply_settings)
        self.tray_var = tk.BooleanVar(value=s.close_to_tray)
        self._check(parent, "Keep running in the tray when window is closed (X)",
                    self.tray_var, self._apply_settings)
        tk.Frame(parent, bg=CARD, height=8).pack()

    def _slider(self, parent, label, var, lo, hi, res, cmd, is_float=False):
        row = tk.Frame(parent, bg=CARD)
        row.pack(fill="x", padx=12, pady=(6, 0))
        tk.Label(row, text=label, bg=CARD, fg=DIM, font=("Segoe UI", 9), anchor="w"
                 ).pack(side="left")
        valfmt = (lambda v: f"{float(v):.2f}") if is_float else (lambda v: str(int(float(v))))
        vlabel = tk.Label(row, text=valfmt(var.get()), bg=CARD, fg=TEXT,
                          font=("Segoe UI", 9, "bold"))
        vlabel.pack(side="right")
        sc = tk.Scale(parent, from_=lo, to=hi, resolution=res, orient="horizontal",
                      variable=var, showvalue=False, bg=CARD, fg=TEXT, troughcolor=PANEL,
                      highlightthickness=0, bd=0, sliderrelief="flat",
                      activebackground=ACCENT,
                      command=lambda v: (vlabel.config(text=valfmt(v)), cmd()))
        sc.pack(fill="x", padx=12)

    def _check(self, parent, label, var, cmd):
        cb = tk.Checkbutton(parent, text=label, variable=var, command=cmd, bg=CARD,
                            fg=TEXT, selectcolor=PANEL, activebackground=CARD,
                            activeforeground=TEXT, font=("Segoe UI", 9),
                            anchor="w", highlightthickness=0, bd=0)
        cb.pack(fill="x", padx=10, pady=1)

    def _apply_settings(self):
        s = self.settings
        s.scan_interval_ms = int(self.interval_var.get())
        s.confidence_threshold = float(self.conf_var.get())
        s.max_clicks_per_minute = int(self.rate_var.get())
        s.restore_mouse = bool(self.restore_var.get())
        s.play_sound = bool(self.sound_var.get())
        s.auto_start = bool(self.autostart_var.get())
        s.confirm_enter = bool(self.enter_var.get())
        s.require_highlight = bool(self.strict_var.get())
        s.close_to_tray = bool(self.tray_var.get())
        s.clamp()
        config.save(s)
        self.engine.reload_settings()
        self._refresh_mute()

    # --- status / counter / log ---
    def _refresh_status(self):
        running = self.engine.running
        self.dot.itemconfig(self._dot_id, fill=GREEN if running else RED)
        self.status_label.config(text="Running" if running else "Stopped")
        self.start_btn.config(text="Stop" if running else "Start")

    def _refresh_counter(self):
        n = self.stats.session_clicks
        self.counter_label.config(text=f"Clicked {n} time{'s' if n != 1 else ''} this session")

    def _refresh_log(self):
        recent = self.stats.recent(5)
        if not recent:
            self.log_text.config(text="  (no clicks yet)")
            return
        lines = []
        for r in recent:
            lines.append(f"[{time.strftime('%H:%M:%S', time.localtime(r.ts))}] "
                         f"mon #{r.monitor}  conf {r.confidence:.2f}")
        self.log_text.config(text="\n".join(lines))

    def _set_banner(self, text, color=DIM):
        self.banner.config(text=text, fg=color)

    # --- actions ---
    def _toggle(self):
        self.engine.toggle()
        self._refresh_status()

    def _toggle_mute(self):
        self.settings.play_sound = not self.settings.play_sound
        config.save(self.settings)
        self.engine.reload_settings()
        # Keep the Settings checkbox in sync if it's been built.
        if hasattr(self, "sound_var"):
            self.sound_var.set(self.settings.play_sound)
        self._refresh_mute()
        if self.tray:
            self.tray.refresh_menu()

    def _refresh_mute(self):
        on = self.settings.play_sound
        self.mute_btn.config(text="Sound: ON" if on else "Sound: OFF",
                             fg=GREEN if on else DIM)

    def _run_test(self):
        self._set_banner("Running live test…", ACCENT)
        self._run_subprocess_dialog(["--test"], "Live Test")

    def _recapture(self):
        if getattr(self.engine, "mode", "template") == "ocr":
            messagebox.showinfo(
                "Yes Clicker",
                "No setup needed.\n\nThis build reads the on-screen text directly "
                "(Windows OCR), so there are no templates to capture. Just press "
                "Start and it watches for Antigravity prompts automatically.\n\n"
                "Use 'Test detection on the REAL prompt' to confirm it sees a live "
                "prompt.")
            return
        if not messagebox.askokcancel(
                "Recapture templates",
                "A capture window will open. Trigger a real 'Allow this bash "
                "command?' prompt in Antigravity, then drag a box around each "
                "element.\n\nContinue?"):
            return
        self._set_banner("Capturing templates…", ACCENT)

        def work():
            try:
                subprocess.run(self.relaunch_argv + ["--capture"], check=False)
            finally:
                self.root.after(0, self._after_recapture)
        threading.Thread(target=work, daemon=True).start()

    def _after_recapture(self):
        ok = self.engine.reload_templates()
        self._set_banner("Templates reloaded." if ok else
                         "Required templates still missing.", GREEN if ok else RED)

    def _probe_real(self):
        """Count down (so the user can show the real prompt), then scan the live
        screen once and report per-element detection."""
        from .probe import probe_once

        def countdown(n):
            if n > 0:
                self._set_banner(f"Switch to the Antigravity prompt — scanning in {n}s…", ACCENT)
                self.root.after(1000, lambda: countdown(n - 1))
            else:
                self._set_banner("Scanning live screen…", ACCENT)
                threading.Thread(target=work, daemon=True).start()

        def work():
            detected, report = probe_once(self.settings)
            self.root.after(0, lambda: self._show_text("Real-prompt Detection Test", report))
            self.root.after(0, lambda: self._set_banner(
                "Prompt DETECTED — it should click it." if detected
                else "No prompt detected — see the per-element numbers.",
                GREEN if detected else RED))

        countdown(5)

    def _run_audit(self):
        self._set_banner("Running audit…", ACCENT)

        def work():
            worst, checks = run_audit()
            text = format_audit(worst, checks)
            self.root.after(0, lambda: self._show_text("Self-Audit", text))
            self.root.after(0, lambda: self._set_banner(f"Audit: {worst}",
                                                        GREEN if worst != "FAIL" else RED))
        threading.Thread(target=work, daemon=True).start()

    def _run_subprocess_dialog(self, extra_args, title):
        def work():
            try:
                proc = subprocess.run(self.relaunch_argv + extra_args,
                                      capture_output=True, text=True, timeout=30)
                out = (proc.stdout or "") + (proc.stderr or "")
            except subprocess.TimeoutExpired:
                out = "Timed out."
            except Exception as e:
                out = f"Could not run: {e}"
            self.root.after(0, lambda: self._show_text(title, out.strip() or "(no output)"))
            self.root.after(0, lambda: self._set_banner("", DIM))
        threading.Thread(target=work, daemon=True).start()

    def _show_text(self, title, text):
        win = tk.Toplevel(self.root)
        win.title(title)
        win.configure(bg=BG)
        win.geometry("520x420")
        t = tk.Text(win, bg=PANEL, fg=TEXT, font=("Consolas", 9), bd=0, padx=12, pady=12,
                    wrap="word")
        t.insert("1.0", text)
        t.config(state="disabled")
        t.pack(fill="both", expand=True, padx=10, pady=10)
        self._button(win, "Close", win.destroy).pack(pady=(0, 10))

    # --- window / tray ---
    def show_window(self):
        self.root.after(0, self._show_window_main)

    def _show_window_main(self):
        try:
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
        except tk.TclError:
            pass

    def _on_close(self):
        # Hide to tray only if the user wants it AND a tray is actually available
        # (otherwise hiding would leave no way to get the window back).
        if self.tray is not None and self.settings.close_to_tray:
            self.root.withdraw()
            self.tray.notify("Still running in the tray. Right-click to Quit.")
        else:
            self.quit()

    def quit(self):
        try:
            config.save(self.settings)
        except Exception:
            pass
        self.engine.shutdown()
        if self.tray:
            self.tray.stop()
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def run(self):
        self.root.mainloop()
