"""
GGTH Predictor v2.3 — Install Wizard
======================================
Scans for MetaTrader 5 installations, lets the user pick or browse,
validates the path, then writes config.json.

Run standalone:  python install_wizard.py
Or via bat:      install.bat  (bootstraps venv first)
"""

import json
import os
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, font as tkfont, messagebox

# ── Constants ─────────────────────────────────────────────────────────────────

SCRIPT_DIR  = Path(__file__).parent.resolve()
CONFIG_PATH = SCRIPT_DIR / "config.json"
CONFIG_VERSION = "2.3"

# Scan roots — covers per-terminal and Common paths
_APPDATA = Path(os.environ.get("APPDATA", "~/.wine")).expanduser()
MT5_SCAN_ROOTS = [
    _APPDATA / "MetaQuotes" / "Terminal",
]

DARK_BG       = "#0d1117"
PANEL_BG      = "#161b22"
BORDER        = "#30363d"
ACCENT        = "#00d4aa"          # teal — matches trading terminal feel
ACCENT_HOVER  = "#00f5c4"
TEXT_PRIMARY  = "#e6edf3"
TEXT_MUTED    = "#7d8590"
TEXT_WARN     = "#f0883e"
TEXT_ERROR    = "#ff7b72"
TEXT_OK       = "#3fb950"

FONT_HEADING  = ("Consolas", 18, "bold")
FONT_SUBHEAD  = ("Consolas", 11, "bold")
FONT_BODY     = ("Consolas", 10)
FONT_SMALL    = ("Consolas", 9)
FONT_MONO     = ("Consolas", 9)


# ── Path scanning ─────────────────────────────────────────────────────────────

def _terminal_label(terminal_dir: Path) -> str:
    """Return a human-readable label for a terminal folder."""
    tid = terminal_dir.name
    # Try to read the broker name from the origin.txt if it exists
    origin = terminal_dir / "origin.txt"
    if origin.is_file():
        try:
            broker = origin.read_text(encoding="utf-8", errors="ignore").strip()
            if broker:
                return f"{broker}  [{tid[:12]}…]"
        except OSError:
            pass
    return f"Terminal [{tid[:16]}…]"


def scan_mt5_paths() -> list[dict]:
    """
    Walk known MT5 roots and return a list of dicts:
      { "label": str, "path": Path, "is_common": bool }
    sorted so per-terminal entries come first, Common last.
    """
    found = []
    for root in MT5_SCAN_ROOTS:
        if not root.is_dir():
            continue
        for child in sorted(root.iterdir()):
            if not child.is_dir():
                continue
            # Per-terminal
            files_dir = child / "MQL5" / "Files"
            if files_dir.is_dir():
                found.append({
                    "label": _terminal_label(child),
                    "path":  files_dir,
                    "is_common": False,
                })
            # Common folder (sits at the root level, not under a hash)
            common = root / "Common" / "Files"
            if common.is_dir() and not any(
                e["path"] == common for e in found
            ):
                found.append({
                    "label": "Common Files  [shared across all terminals]",
                    "path":  common,
                    "is_common": True,
                })
    return found


# ── Helpers ───────────────────────────────────────────────────────────────────

def read_current_config() -> dict:
    if CONFIG_PATH.is_file():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def write_config(mt5_path: str) -> None:
    payload = {
        "mt5_files_path": mt5_path,
        "version": CONFIG_VERSION,
    }
    import tempfile
    tmp_fd, tmp_name = tempfile.mkstemp(
        prefix=".cfg_", dir=str(CONFIG_PATH.parent)
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=True)
        os.replace(tmp_name, CONFIG_PATH)
    finally:
        if os.path.exists(tmp_name):
            try:
                os.remove(tmp_name)
            except OSError:
                pass


# ── Styled widgets ────────────────────────────────────────────────────────────

class HoverButton(tk.Label):
    """Label styled as a button with hover effect."""

    def __init__(self, parent, text, command,
                 bg=ACCENT, fg=DARK_BG,
                 hover_bg=ACCENT_HOVER,
                 pad_x=18, pad_y=8, **kw):
        super().__init__(
            parent, text=text,
            bg=bg, fg=fg,
            font=FONT_SUBHEAD,
            cursor="hand2",
            padx=pad_x, pady=pad_y,
            relief="flat",
            **kw
        )
        self._bg       = bg
        self._hover_bg = hover_bg
        self._command  = command
        self.bind("<Enter>",    lambda _: self.configure(bg=self._hover_bg))
        self.bind("<Leave>",    lambda _: self.configure(bg=self._bg))
        self.bind("<Button-1>", lambda _: self._command())

    def set_state(self, enabled: bool) -> None:
        """Visually enable/disable."""
        if enabled:
            self._bg       = ACCENT
            self._hover_bg = ACCENT_HOVER
            self.configure(bg=ACCENT, fg=DARK_BG, cursor="hand2")
        else:
            self._bg       = BORDER
            self._hover_bg = BORDER
            self.configure(bg=BORDER, fg=TEXT_MUTED, cursor="")

    def flash(self) -> None:
        """Brief visual feedback on click."""
        orig = self._bg
        self.configure(bg=ACCENT_HOVER)
        self.after(120, lambda: self.configure(bg=orig))


class PathCard(tk.Frame):
    """Selectable card for one detected MT5 installation."""

    def __init__(self, parent, entry: dict, select_cb, **kw):
        super().__init__(parent, bg=PANEL_BG, bd=0, **kw)
        self._entry     = entry
        self._select_cb = select_cb
        self._selected  = False

        self.configure(cursor="hand2")
        self.bind("<Button-1>", self._on_click)

        # Top row: label
        top = tk.Frame(self, bg=PANEL_BG)
        top.pack(fill="x", padx=14, pady=(10, 2))
        top.bind("<Button-1>", self._on_click)

        badge_text = "COMMON" if entry["is_common"] else "PER-TERMINAL"
        badge_col  = TEXT_WARN if entry["is_common"] else ACCENT

        tk.Label(top, text=badge_text,
                 font=FONT_SMALL, bg=PANEL_BG, fg=badge_col
                 ).pack(side="left", padx=(0, 8))
        tk.Label(top, text=entry["label"],
                 font=FONT_SUBHEAD, bg=PANEL_BG, fg=TEXT_PRIMARY,
                 anchor="w"
                 ).pack(side="left", fill="x", expand=True)

        # Bottom row: path
        bot = tk.Frame(self, bg=PANEL_BG)
        bot.pack(fill="x", padx=14, pady=(0, 10))
        bot.bind("<Button-1>", self._on_click)

        self._path_lbl = tk.Label(
            bot, text=str(entry["path"]),
            font=FONT_MONO, bg=PANEL_BG, fg=TEXT_MUTED,
            anchor="w", wraplength=560, justify="left",
        )
        self._path_lbl.pack(side="left", fill="x", expand=True)
        self._path_lbl.bind("<Button-1>", self._on_click)

        # Separator line
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

    def _on_click(self, _=None) -> None:
        self._select_cb(self)

    def set_selected(self, val: bool) -> None:
        self._selected = val
        col = ACCENT if val else PANEL_BG
        self.configure(bg=col if val else PANEL_BG,
                       highlightbackground=col,
                       highlightthickness=2 if val else 0)
        for w in self.winfo_children():
            try:
                w.configure(bg=col if val else PANEL_BG)
                for ww in w.winfo_children():
                    ww.configure(bg=col if val else PANEL_BG,
                                 fg=DARK_BG if val else (
                                     TEXT_PRIMARY
                                     if ww.cget("font") == str(FONT_SUBHEAD)
                                     else TEXT_MUTED
                                 ))
            except tk.TclError:
                pass

    @property
    def path(self) -> Path:
        return self._entry["path"]


# ── Main window ───────────────────────────────────────────────────────────────

class InstallWizard(tk.Tk):

    def __init__(self):
        super().__init__()
        self.title("GGTH Predictor — Install Wizard")
        self.configure(bg=DARK_BG)
        self.resizable(False, False)

        self._selected_card: PathCard | None = None
        self._manual_path: str | None = None
        self._scan_results: list[dict] = []

        self._build_ui()
        self._centre_window(680, 620)
        self._start_scan()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        # ── Header ────────────────────────────────────────────────────────────
        hdr = tk.Frame(self, bg=PANEL_BG)
        hdr.pack(fill="x")

        tk.Frame(hdr, bg=ACCENT, width=4).pack(side="left", fill="y")

        inner = tk.Frame(hdr, bg=PANEL_BG)
        inner.pack(side="left", fill="x", expand=True, padx=20, pady=18)

        tk.Label(inner, text="GGTH PREDICTOR",
                 font=FONT_HEADING, bg=PANEL_BG, fg=ACCENT
                 ).pack(anchor="w")
        tk.Label(inner, text="MetaTrader 5 Path Configuration  ·  v2.3",
                 font=FONT_BODY, bg=PANEL_BG, fg=TEXT_MUTED
                 ).pack(anchor="w")

        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

        # ── Instructions ──────────────────────────────────────────────────────
        info = tk.Frame(self, bg=DARK_BG)
        info.pack(fill="x", padx=22, pady=(16, 6))

        tk.Label(info,
                 text="Select the MQL5\\Files folder where your EA reads/writes JSON signals.",
                 font=FONT_BODY, bg=DARK_BG, fg=TEXT_PRIMARY, anchor="w"
                 ).pack(anchor="w")
        tk.Label(info,
                 text="Auto-detected installations are listed below. "
                      "Use Browse for a custom path.",
                 font=FONT_SMALL, bg=DARK_BG, fg=TEXT_MUTED, anchor="w"
                 ).pack(anchor="w")

        # ── Scan status ───────────────────────────────────────────────────────
        status_row = tk.Frame(self, bg=DARK_BG)
        status_row.pack(fill="x", padx=22, pady=(4, 0))

        self._status_lbl = tk.Label(
            status_row, text="⟳  Scanning for MetaTrader 5 installations…",
            font=FONT_SMALL, bg=DARK_BG, fg=TEXT_MUTED, anchor="w"
        )
        self._status_lbl.pack(side="left")

        # ── Scrollable card area ──────────────────────────────────────────────
        frame_outer = tk.Frame(self, bg=BORDER, bd=1, relief="flat")
        frame_outer.pack(fill="both", expand=True, padx=22, pady=10)

        canvas = tk.Canvas(frame_outer, bg=PANEL_BG, highlightthickness=0,
                           bd=0)
        vsb = tk.Scrollbar(frame_outer, orient="vertical",
                           command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)

        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        self._card_frame = tk.Frame(canvas, bg=PANEL_BG)
        self._card_win   = canvas.create_window(
            (0, 0), window=self._card_frame, anchor="nw"
        )

        self._card_frame.bind("<Configure>", lambda e: canvas.configure(
            scrollregion=canvas.bbox("all")
        ))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(
            self._card_win, width=e.width
        ))
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(
            int(-1 * (e.delta / 120)), "units"
        ))

        self._canvas = canvas

        # ── Manual path row ───────────────────────────────────────────────────
        manual_row = tk.Frame(self, bg=DARK_BG)
        manual_row.pack(fill="x", padx=22, pady=(0, 6))

        tk.Label(manual_row, text="Custom path:",
                 font=FONT_BODY, bg=DARK_BG, fg=TEXT_MUTED
                 ).pack(side="left")

        self._manual_var = tk.StringVar()
        self._manual_entry = tk.Entry(
            manual_row,
            textvariable=self._manual_var,
            font=FONT_MONO, bg=PANEL_BG, fg=TEXT_PRIMARY,
            insertbackground=ACCENT, relief="flat",
            highlightthickness=1, highlightbackground=BORDER,
            highlightcolor=ACCENT, width=42,
        )
        self._manual_entry.pack(side="left", padx=(8, 6), ipady=5)
        self._manual_var.trace_add("write", self._on_manual_type)

        HoverButton(
            manual_row, text="Browse…",
            command=self._on_browse,
            bg=PANEL_BG, fg=TEXT_PRIMARY,
            hover_bg=BORDER,
            pad_x=10, pad_y=5,
        ).pack(side="left")

        # ── Validation message ────────────────────────────────────────────────
        self._validation_lbl = tk.Label(
            self, text="", font=FONT_SMALL, bg=DARK_BG, fg=TEXT_MUTED
        )
        self._validation_lbl.pack(anchor="w", padx=26, pady=(0, 2))

        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

        # ── Footer buttons ────────────────────────────────────────────────────
        footer = tk.Frame(self, bg=PANEL_BG)
        footer.pack(fill="x")

        self._current_lbl = tk.Label(
            footer, text="", font=FONT_SMALL,
            bg=PANEL_BG, fg=TEXT_MUTED
        )
        self._current_lbl.pack(side="left", padx=18, pady=14)

        self._save_btn = HoverButton(
            footer, text="✓  Save Configuration",
            command=self._on_save,
        )
        self._save_btn.pack(side="right", padx=(6, 18), pady=12)
        self._save_btn.set_state(False)

        HoverButton(
            footer, text="Cancel",
            command=self.destroy,
            bg=PANEL_BG, fg=TEXT_MUTED,
            hover_bg=BORDER,
            pad_x=12, pad_y=8,
        ).pack(side="right", pady=12)

        # Show current config if present
        cur = read_current_config()
        if cur.get("mt5_files_path"):
            self._current_lbl.configure(
                text=f"Current: {cur['mt5_files_path']}"
            )

    def _centre_window(self, w: int, h: int) -> None:
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        x  = (sw - w) // 2
        y  = (sh - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")

    # ── Scanning ──────────────────────────────────────────────────────────────

    def _start_scan(self) -> None:
        threading.Thread(target=self._scan_thread, daemon=True).start()

    def _scan_thread(self) -> None:
        results = scan_mt5_paths()
        self.after(0, lambda: self._on_scan_done(results))

    def _on_scan_done(self, results: list[dict]) -> None:
        self._scan_results = results
        # Clear placeholder
        for w in self._card_frame.winfo_children():
            w.destroy()

        if not results:
            self._status_lbl.configure(
                text="⚠  No MT5 installations found automatically. Use Browse to set a custom path.",
                fg=TEXT_WARN,
            )
            self._show_no_results_hint()
            return

        count = len(results)
        self._status_lbl.configure(
            text=f"✓  Found {count} installation{'s' if count != 1 else ''}. "
                 f"Click one to select it.",
            fg=TEXT_OK,
        )

        cards = []
        for entry in results:
            card = PathCard(self._card_frame, entry, self._on_card_select)
            card.pack(fill="x", pady=(0, 1))
            cards.append(card)

        # Auto-select the first one
        if cards:
            self._on_card_select(cards[0])

    def _show_no_results_hint(self) -> None:
        tk.Label(
            self._card_frame,
            text=(
                "MetaTrader 5 was not found in the standard location.\n\n"
                "Click Browse… below to navigate to your MQL5\\Files folder.\n\n"
                "Tip: In MetaTrader 5 → File → Open Data Folder, then\n"
                "open the MQL5\\Files subfolder and copy that path."
            ),
            font=FONT_BODY, bg=PANEL_BG, fg=TEXT_MUTED,
            justify="left", anchor="w",
        ).pack(padx=20, pady=30, anchor="w")

    # ── Card selection ────────────────────────────────────────────────────────

    def _on_card_select(self, card: PathCard) -> None:
        if self._selected_card and self._selected_card is not card:
            self._selected_card.set_selected(False)
        self._selected_card = card
        card.set_selected(True)

        # Clear manual entry
        self._manual_var.set("")
        self._manual_path = None

        self._validate_path(card.path)

    # ── Manual entry ──────────────────────────────────────────────────────────

    def _on_manual_type(self, *_) -> None:
        raw = self._manual_var.get().strip()
        if not raw:
            self._manual_path = None
            # Revert to card selection validation if a card is selected
            if self._selected_card:
                self._validate_path(self._selected_card.path)
            else:
                self._save_btn.set_state(False)
            return

        # Deselect cards
        if self._selected_card:
            self._selected_card.set_selected(False)
            self._selected_card = None

        self._manual_path = raw
        self._validate_path(Path(raw))

    def _on_browse(self) -> None:
        initial = (
            str(self._selected_card.path)
            if self._selected_card
            else str(_APPDATA)
        )
        chosen = filedialog.askdirectory(
            title="Select your MT5 MQL5\\Files folder",
            initialdir=initial if Path(initial).is_dir() else str(_APPDATA),
        )
        if not chosen:
            return

        # Deselect cards
        if self._selected_card:
            self._selected_card.set_selected(False)
            self._selected_card = None

        self._manual_var.set(chosen)
        self._manual_path = chosen
        self._validate_path(Path(chosen))

    # ── Validation ────────────────────────────────────────────────────────────

    def _validate_path(self, path: Path) -> None:
        if path.is_dir():
            # Warn if it doesn't look like MQL5\Files
            hint = str(path).lower()
            if "mql5" not in hint:
                self._validation_lbl.configure(
                    text="⚠  This folder does not appear to be inside an MQL5 directory. "
                         "Continue if you're sure.",
                    fg=TEXT_WARN,
                )
            else:
                self._validation_lbl.configure(
                    text=f"✓  Path verified: {path}",
                    fg=TEXT_OK,
                )
            self._save_btn.set_state(True)
        else:
            self._validation_lbl.configure(
                text="✗  Path does not exist or is not a directory.",
                fg=TEXT_ERROR,
            )
            self._save_btn.set_state(False)

    # ── Save ──────────────────────────────────────────────────────────────────

    def _on_save(self) -> None:
        # Determine active path
        if self._manual_path:
            chosen = Path(self._manual_path.strip())
        elif self._selected_card:
            chosen = self._selected_card.path
        else:
            messagebox.showwarning("No Path Selected",
                                   "Please select or enter an MT5 Files path first.")
            return

        if not chosen.is_dir():
            messagebox.showerror("Invalid Path",
                                 f"The path does not exist:\n{chosen}")
            return

        try:
            write_config(str(chosen))
        except Exception as exc:
            messagebox.showerror("Write Error",
                                 f"Failed to write config.json:\n{exc}")
            return

        self._save_btn.flash()

        launch = messagebox.askyesno(
            "Configuration Saved",
            f"✓  Saved successfully!\n\n"
            f"Path:  {chosen}\n"
            f"File:  {CONFIG_PATH}\n\n"
            "Launch GGTH Predictor GUI now?",
        )

        if launch:
            self._launch_gui()

        self.destroy()

    def _launch_gui(self) -> None:
        gui_script = SCRIPT_DIR / "ggth_gui.py"
        if not gui_script.is_file():
            messagebox.showwarning("GUI Not Found",
                                   "ggth_gui.py was not found in the same folder.")
            return
        import subprocess
        subprocess.Popen(
            [sys.executable, str(gui_script)],
            cwd=str(SCRIPT_DIR),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = InstallWizard()
    app.mainloop()
