"""Pixel-faithful replica of Antigravity's "Allow this bash command?" dialog.

Rendered as a real tkinter window so the self-test can run the full detection +
click pipeline against the live screen. The geometry of each element is exposed
(``element_bounds``) so the test can both (a) verify a click landed on Yes and
(b) bootstrap synthetic templates by cropping the known regions.
"""

from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass

# Antigravity dark palette (approximate but consistent).
BG = "#1e1e1e"
PANEL = "#252526"
BORDER = "#3c3c3c"
CODE_BG = "#1a1a1a"
TEXT = "#cccccc"
DIM = "#8a8a8a"
YES_BLUE = "#0a64c8"
YES_TEXT = "#ffffff"
ACCENT = "#4ea1ff"

SAMPLE_CMD = "npm run build && node scripts/deploy.js --prod"


@dataclass
class Bounds:
    x: int
    y: int
    w: int
    h: int

    def center(self) -> tuple[int, int]:
        return self.x + self.w // 2, self.y + self.h // 2


class ReplicaDialog:
    """Builds the dialog into a given tk container and tracks element widgets."""

    def __init__(self, parent: tk.Misc, on_yes=None):
        self.parent = parent
        self.on_yes = on_yes
        self._widgets: dict[str, tk.Widget] = {}
        self.clicked_on_yes = False
        self.click_xy: tuple[int, int] | None = None
        self.click_missed = False
        self._build()

    def _build(self) -> None:
        frame = tk.Frame(self.parent, bg=PANEL, highlightbackground=BORDER,
                         highlightthickness=1, bd=0)
        frame.pack(fill="both", expand=True, padx=2, pady=2)

        # Header: "Allow this bash command?"
        header = tk.Label(frame, text="Allow this bash command?", bg=PANEL,
                          fg=TEXT, font=("Segoe UI", 13, "bold"), anchor="w",
                          padx=16, pady=12)
        header.pack(fill="x")
        self._widgets["header"] = header

        # Code block with the sample command.
        code = tk.Label(frame, text="  " + SAMPLE_CMD, bg=CODE_BG, fg=ACCENT,
                        font=("Consolas", 11), anchor="w", padx=12, pady=10)
        code.pack(fill="x", padx=16, pady=(0, 12))
        self._widgets["code"] = code

        # Numbered options — "1 Yes" highlighted blue, "2 No" below.
        yes = tk.Label(frame, text="  1  Yes", bg=YES_BLUE, fg=YES_TEXT,
                       font=("Segoe UI", 12, "bold"), anchor="w", padx=14, pady=9)
        yes.pack(fill="x", padx=16, pady=(0, 4))
        yes.bind("<Button-1>", self._hit_yes)
        self._widgets["yes"] = yes

        no = tk.Label(frame, text="  2  No", bg=PANEL, fg=TEXT,
                      font=("Segoe UI", 12), anchor="w", padx=14, pady=9)
        no.pack(fill="x", padx=16, pady=(0, 12))
        no.bind("<Button-1>", self._hit_other)
        self._widgets["no"] = no

        # Input field: "Tell Claude what to do instead"
        inp = tk.Label(frame, text="  Tell Claude what to do instead",
                       bg=CODE_BG, fg=DIM, font=("Segoe UI", 11), anchor="w",
                       padx=12, pady=10)
        inp.pack(fill="x", padx=16, pady=(0, 12))
        self._widgets["input"] = inp

        # Footer: "Esc to cancel"
        footer = tk.Label(frame, text="Esc to cancel", bg=PANEL, fg=DIM,
                          font=("Segoe UI", 10), anchor="e", padx=16, pady=10)
        footer.pack(fill="x")
        self._widgets["footer"] = footer

        # A click anywhere that isn't Yes counts as a miss for the test.
        for w in (frame, header, code, inp, footer):
            w.bind("<Button-1>", self._hit_other)

    def _hit_yes(self, event):
        self.clicked_on_yes = True
        self.click_xy = (event.x_root, event.y_root)
        if self.on_yes:
            self.on_yes()
        return "break"

    def _hit_other(self, event):
        # Only mark a miss if it wasn't the yes label bubbling.
        if event.widget is not self._widgets.get("yes"):
            self.click_missed = True
            self.click_xy = (event.x_root, event.y_root)

    # --- geometry ---
    def element_bounds(self, role: str) -> Bounds | None:
        w = self._widgets.get(role)
        if w is None:
            return None
        w.update_idletasks()
        return Bounds(w.winfo_rootx(), w.winfo_rooty(),
                      w.winfo_width(), w.winfo_height())

    def yes_center_screen(self) -> tuple[int, int]:
        b = self.element_bounds("yes")
        return b.center() if b else (0, 0)


def make_replica_window(on_yes=None, title="Allow this bash command?",
                        topmost=True) -> tuple[tk.Tk, ReplicaDialog]:
    """Standalone replica window centred on the primary screen."""
    root = tk.Tk()
    root.title(title)
    root.configure(bg=BG)
    root.overrideredirect(False)
    width, height = 520, 360
    root.update_idletasks()
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    x = (sw - width) // 2
    y = (sh - height) // 2
    root.geometry(f"{width}x{height}+{x}+{y}")
    if topmost:
        root.attributes("-topmost", True)
    dialog = ReplicaDialog(root, on_yes=on_yes)
    root.update()
    return root, dialog
