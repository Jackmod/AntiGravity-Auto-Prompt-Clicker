"""Template capture (--capture flag / first-run setup / Recapture button).

A self-contained tkinter "snipping tool" — no console needed (important for the
windowed .exe) and it captures the **entire virtual desktop** (all monitors), so
the prompt can be on any screen or either Antigravity instance.

Flow:
  1. A "Get ready" window: bring a real "Allow this bash command?" prompt up in
     Antigravity, then click *Capture screen*.
  2. We hide our window, grab every monitor into one image, and show it.
  3. For each element, drag a box and click *Next* (or *Skip* for optional ones).
  4. Crops are saved to templates/*.png; the caller then runs a self-test.
"""

from __future__ import annotations

import time
import tkinter as tk
from tkinter import messagebox

import cv2
import numpy as np

from . import paths
from .logger import log, warn

# (role, file Path, human description, required)
CAPTURE_STEPS = [
    ("header", paths.HEADER_TEMPLATE, "the 'Allow this bash command?' HEADER text", True),
    ("yes", paths.YES_TEMPLATE, "the '1 Yes' button (option 1)", True),
    ("no", paths.LIST_TEMPLATE, "the '2 No' row", False),
    ("input", paths.INPUT_TEMPLATE, "the 'Tell Claude what to do instead' input", False),
    ("footer", paths.FOOTER_TEMPLATE, "the 'Esc to cancel' footer", False),
]

BG = "#1b1b1d"
PANEL = "#242427"
TEXT = "#e6e6e6"
ACCENT = "#4ea1ff"
GREEN = "#2ecc71"
BTN = "#33333a"
SEL = "#ff3b30"


def _grab_virtual_desktop() -> np.ndarray:
    """Grab all monitors as one RGB image (the full virtual desktop)."""
    import mss
    with mss.mss() as sct:
        mon = sct.monitors[0]  # bounding box of every monitor
        raw = sct.grab(mon)
    arr = np.frombuffer(raw.raw, dtype=np.uint8).reshape(raw.height, raw.width, 4)
    rgb = np.ascontiguousarray(arr[:, :, :3][:, :, ::-1])  # BGRA -> RGB
    return rgb


class _CaptureFlow:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("Yes Clicker — capture templates")
        self.root.configure(bg=BG)
        self.full_rgb: np.ndarray | None = None
        self.saved_required = False
        self.cancelled = False

    # --- phase 1: readiness ---
    def run(self) -> bool:
        self._build_ready()
        self.root.mainloop()
        return self.saved_required and not self.cancelled

    def _build_ready(self) -> None:
        self.root.geometry("460x240")
        f = tk.Frame(self.root, bg=BG)
        f.pack(fill="both", expand=True, padx=20, pady=18)
        tk.Label(f, text="Capture the prompt", bg=BG, fg=TEXT,
                 font=("Segoe UI", 14, "bold")).pack(anchor="w")
        tk.Label(f, text=("1.  In Antigravity, bring up a real\n"
                          "     'Allow this bash command?' prompt.\n"
                          "2.  Leave it visible on screen.\n"
                          "3.  Click the button below — this window hides,\n"
                          "     then you'll draw a box around each element."),
                 bg=BG, fg=TEXT, font=("Segoe UI", 10), justify="left").pack(
            anchor="w", pady=12)
        b = tk.Button(f, text="Capture screen  →", command=self._do_grab,
                      bg=ACCENT, fg="#0b1b30", activebackground=ACCENT,
                      relief="flat", bd=0, font=("Segoe UI", 11, "bold"),
                      padx=14, pady=8, cursor="hand2")
        b.pack(anchor="w", pady=(6, 0))
        tk.Button(f, text="Cancel", command=self._cancel, bg=BTN, fg=TEXT,
                  relief="flat", bd=0, font=("Segoe UI", 9), padx=10, pady=4,
                  cursor="hand2").pack(anchor="w", pady=(8, 0))

    def _do_grab(self) -> None:
        # Hide so our own window isn't in the screenshot, give the compositor a
        # moment, then grab the whole desktop.
        self.root.withdraw()
        self.root.update()
        time.sleep(0.4)
        try:
            self.full_rgb = _grab_virtual_desktop()
        except Exception as e:
            warn(f"screen grab failed: {e}")
            messagebox.showerror("Yes Clicker", f"Could not capture the screen:\n{e}")
            self._cancel()
            return
        self._build_selector()

    # --- phase 2: selector ---
    def _build_selector(self) -> None:
        h, w = self.full_rgb.shape[:2]
        self.root.deiconify()
        self.root.state("normal")
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        max_w, max_h = sw - 80, sh - 200
        self.scale = min(1.0, max_w / w, max_h / h)
        disp_w, disp_h = int(w * self.scale), int(h * self.scale)

        from PIL import Image, ImageTk
        small = cv2.resize(self.full_rgb, (disp_w, disp_h),
                           interpolation=cv2.INTER_AREA) if self.scale < 1 else self.full_rgb
        self._tkimg = ImageTk.PhotoImage(Image.fromarray(small))

        self.root.geometry(f"{disp_w + 24}x{disp_h + 96}")
        self.root.title("Draw a box around each element")

        self.instr = tk.Label(self.root, text="", bg=BG, fg=ACCENT,
                              font=("Segoe UI", 12, "bold"))
        self.instr.pack(fill="x", padx=12, pady=(8, 2))

        self.canvas = tk.Canvas(self.root, width=disp_w, height=disp_h,
                                bg=PANEL, highlightthickness=1,
                                highlightbackground="#444", cursor="crosshair")
        self.canvas.pack(padx=12)
        self.canvas.create_image(0, 0, anchor="nw", image=self._tkimg)
        self.canvas.bind("<Button-1>", self._on_down)
        self.canvas.bind("<B1-Motion>", self._on_move)
        self.canvas.bind("<ButtonRelease-1>", self._on_up)

        bar = tk.Frame(self.root, bg=BG)
        bar.pack(fill="x", padx=12, pady=8)
        self._action = tk.IntVar(value=0)
        self.next_btn = tk.Button(bar, text="Next  →", command=lambda: self._action.set(1),
                                  bg=GREEN, fg="#0b1b12", relief="flat", bd=0,
                                  font=("Segoe UI", 10, "bold"), padx=14, pady=6,
                                  cursor="hand2")
        self.next_btn.pack(side="right")
        self.skip_btn = tk.Button(bar, text="Skip (optional)", command=lambda: self._action.set(2),
                                  bg=BTN, fg=TEXT, relief="flat", bd=0,
                                  font=("Segoe UI", 10), padx=12, pady=6, cursor="hand2")
        self.skip_btn.pack(side="right", padx=8)
        tk.Button(bar, text="Cancel", command=lambda: self._action.set(3), bg=BTN,
                  fg=TEXT, relief="flat", bd=0, font=("Segoe UI", 10), padx=12, pady=6,
                  cursor="hand2").pack(side="left")
        self.hint = tk.Label(bar, text="", bg=BG, fg=TEXT, font=("Segoe UI", 9))
        self.hint.pack(side="left", padx=12)

        self._rect_id = None
        self._start = None
        self._sel = None
        self.root.after(50, self._run_steps)

    def _on_down(self, e):
        self._start = (e.x, e.y)
        if self._rect_id:
            self.canvas.delete(self._rect_id)
        self._rect_id = self.canvas.create_rectangle(e.x, e.y, e.x, e.y,
                                                     outline=SEL, width=2)

    def _on_move(self, e):
        if self._start and self._rect_id:
            self.canvas.coords(self._rect_id, self._start[0], self._start[1], e.x, e.y)

    def _on_up(self, e):
        if not self._start:
            return
        x1, y1 = self._start
        x2, y2 = e.x, e.y
        self._sel = (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))

    def _clear_sel(self):
        self._sel = None
        self._start = None
        if self._rect_id:
            self.canvas.delete(self._rect_id)
            self._rect_id = None

    def _run_steps(self):
        paths.ensure_dirs()
        try:
            for role, path, desc, required in CAPTURE_STEPS:
                self._clear_sel()
                tag = "REQUIRED" if required else "optional"
                self.instr.config(text=f"Draw a box around {desc}")
                self.hint.config(text=f"({tag})  drag a box, then click Next"
                                      + ("" if required else " — or Skip"))
                self.skip_btn.config(state=("disabled" if required else "normal"))

                while True:
                    self._action.set(0)
                    self.root.wait_variable(self._action)
                    act = self._action.get()
                    if act == 3:  # cancel
                        self.cancelled = True
                        self._finish()
                        return
                    if act == 2 and not required:  # skip optional
                        log(f"skipped optional template '{role}'")
                        break
                    if act == 1:  # next
                        if self._sel is None:
                            if required:
                                messagebox.showwarning(
                                    "Yes Clicker",
                                    "Draw a box around the element first.")
                                continue
                            break
                        if self._save_crop(path, self._sel):
                            log(f"saved {path.name}")
                            break
                        messagebox.showwarning("Yes Clicker",
                                               "That box was too small — try again.")
            self.saved_required = paths.HEADER_TEMPLATE.exists() and paths.YES_TEMPLATE.exists()
        finally:
            self._finish()

    def _save_crop(self, path, sel) -> bool:
        x1, y1, x2, y2 = sel
        # Map display coords back to full-resolution pixels.
        fx1, fy1 = int(x1 / self.scale), int(y1 / self.scale)
        fx2, fy2 = int(x2 / self.scale), int(y2 / self.scale)
        if fx2 - fx1 < 8 or fy2 - fy1 < 6:
            return False
        crop_rgb = self.full_rgb[fy1:fy2, fx1:fx2]
        if crop_rgb.size == 0:
            return False
        crop_bgr = crop_rgb[:, :, ::-1]
        cv2.imwrite(str(path), crop_bgr)
        return True

    def _finish(self):
        try:
            self.root.quit()
            self.root.destroy()
        except tk.TclError:
            pass

    def _cancel(self):
        self.cancelled = True
        self._finish()


def run_capture(interactive: bool = True) -> bool:
    """Capture templates interactively. Returns True if required ones were saved."""
    paths.ensure_dirs()
    flow = _CaptureFlow()
    ok = flow.run()
    if flow.cancelled:
        log("capture cancelled")
        return False
    if not ok:
        warn("required templates not saved")
        return False
    log("templates captured")
    return True
