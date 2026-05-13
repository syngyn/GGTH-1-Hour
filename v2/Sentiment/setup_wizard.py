"""
GGTH Predictor — One-Click Setup Wizard
========================================
A complete guided installer for non-technical users.
Steps: Python check → Install packages → MT5 path → MT5 login → EA install → Launch

Run via:  setup.bat   (handles Python detection first)
"""

import json
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

SCRIPT_DIR     = Path(__file__).parent.resolve()
CONFIG_PATH    = SCRIPT_DIR / "config.json"
REQ_PATH       = SCRIPT_DIR / "requirements.txt"
CONFIG_VERSION = "2.3"
_APPDATA       = Path(os.environ.get("APPDATA", "~")).expanduser()
MT5_ROOT       = _APPDATA / "MetaQuotes" / "Terminal"

BG      = "#0a0e14"
PANEL   = "#0f1520"
CARD    = "#141c28"
BORDER  = "#1e2d42"
ACCENT  = "#00c9a7"
BLUE    = "#0090ff"
OK      = "#22c55e"
WARN    = "#f59e0b"
ERR     = "#ef4444"
DIM     = "#2a3a50"
FG      = "#e2e8f0"
FG2     = "#94a3b8"
FG3     = "#64748b"

F_BIG  = ("Consolas", 20, "bold")
F_MED  = ("Consolas", 13, "bold")
F_HEAD = ("Consolas", 14, "bold")
F_STEP = ("Consolas", 10, "bold")
F_BODY = ("Consolas", 10)
F_SM   = ("Consolas", 9)
F_MONO = ("Consolas", 9)

STEPS = [
    ("1", "Python Check",   "Verify Python version"),
    ("2", "Install Packages","Install required libraries"),
    ("3", "MT5 Folder",     "Find MetaTrader 5 folder"),
    ("4", "MT5 Connection", "Verify MT5 is running"),
    ("5", "EA Setup",       "Install Expert Advisor"),
    ("6", "Done!",          "Launch GGTH Predictor"),
]


def scan_mt5_paths():
    found = []
    if not MT5_ROOT.is_dir():
        return found
    for child in sorted(MT5_ROOT.iterdir()):
        if not child.is_dir() or child.name.lower() == "common":
            continue
        fd = child / "MQL5" / "Files"
        if fd.is_dir():
            label = child.name
            origin = child / "origin.txt"
            if origin.is_file():
                try:
                    t = origin.read_text(encoding="utf-8", errors="ignore").strip()
                    if t:
                        label = t
                except OSError:
                    pass
            found.append({"label": label, "path": fd, "is_common": False})
    common = MT5_ROOT / "Common" / "Files"
    if common.is_dir():
        found.append({"label": "Common Files  (recommended for most users)", "path": common, "is_common": True})
    return found


def read_config():
    if CONFIG_PATH.is_file():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def write_config(mt5_path: str):
    import tempfile
    payload = {"mt5_files_path": mt5_path, "version": CONFIG_VERSION}
    fd, tmp = tempfile.mkstemp(prefix=".cfg_", dir=str(SCRIPT_DIR))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        os.replace(tmp, CONFIG_PATH)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def L(parent, text, font=F_BODY, fg=FG, bg=None, anchor="w", **kw):
    return tk.Label(parent, text=text, font=font, fg=fg,
                    bg=bg or BG, anchor=anchor, **kw)


def mkbtn(parent, text, cmd, bg=ACCENT, fg=BG, state="normal", font=F_STEP, **kw):
    return tk.Button(
        parent, text=text, command=cmd,
        font=font, fg=fg, bg=bg,
        relief="flat", bd=0, padx=16, pady=9,
        cursor="hand2" if state == "normal" else "arrow",
        state=state,
        activebackground=BLUE, activeforeground=FG,
        **kw
    )


class SetupWizard(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("GGTH Predictor — Setup Wizard")
        self.configure(bg=BG)
        self.resizable(False, False)
        self._step     = 0
        self._status   = ["wait"] * len(STEPS)
        self._mt5_path = None
        self._sel_card = None
        self._pkg_done = False
        self._build()
        self._centre(940, 640)
        self.after(80, self._go, 0)

    # ── Window ────────────────────────────────────────────────────────────────

    def _build(self):
        # Top bar
        bar = tk.Frame(self, bg=PANEL, height=54)
        bar.pack(side="top", fill="x")
        bar.pack_propagate(False)
        tk.Frame(bar, bg=ACCENT, width=4).pack(side="left", fill="y")
        h = tk.Frame(bar, bg=PANEL)
        h.pack(side="left", padx=18)
        L(h, "GGTH PREDICTOR", font=F_HEAD, fg=ACCENT, bg=PANEL).pack(side="left", pady=14)
        L(h, "  ·  Setup Wizard  v2.3", font=F_SM, fg=FG3, bg=PANEL).pack(side="left", pady=14)
        tk.Frame(self, bg=BORDER, height=1).pack(side="top", fill="x")

        # Sidebar
        self._sb = tk.Frame(self, bg=PANEL, width=210)
        self._sb.pack(side="left", fill="y")
        self._sb.pack_propagate(False)
        tk.Frame(self._sb, bg=BORDER, height=1).pack(fill="x")
        tk.Frame(self._sb, bg=PANEL, height=14).pack()
        self._sf = []
        for i, (num, title, desc) in enumerate(STEPS):
            f = tk.Frame(self._sb, bg=PANEL)
            f.pack(fill="x", padx=10, pady=2)
            row = tk.Frame(f, bg=PANEL)
            row.pack(fill="x")
            cv = tk.Canvas(row, width=28, height=28, bg=PANEL, highlightthickness=0)
            cv.pack(side="left", padx=(4, 8), pady=4)
            r = tk.Frame(row, bg=PANEL)
            r.pack(side="left", fill="x", expand=True)
            L(r, title, font=F_STEP, fg=FG3, bg=PANEL).pack(anchor="w")
            L(r, desc,  font=F_SM,   fg=FG3, bg=PANEL).pack(anchor="w")
            self._sf.append({"f": f, "row": row, "cv": cv, "r": r})
        tk.Frame(self._sb, bg=BORDER, height=1).pack(fill="x", side="bottom")

        # Content
        tk.Frame(self, bg=BORDER, width=1).pack(side="left", fill="y")
        wrap = tk.Frame(self, bg=BG)
        wrap.pack(side="left", fill="both", expand=True)
        self._cont = tk.Frame(wrap, bg=BG)
        self._cont.pack(fill="both", expand=True, padx=30, pady=22)
        tk.Frame(wrap, bg=BORDER, height=1).pack(fill="x", side="bottom")
        self._foot = tk.Frame(wrap, bg=PANEL)
        self._foot.pack(fill="x", side="bottom")

    def _centre(self, w, h):
        self.update_idletasks()
        x = (self.winfo_screenwidth()  - w) // 2
        y = (self.winfo_screenheight() - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")

    def _refresh_sb(self):
        for i, sf in enumerate(self._sf):
            is_cur = i == self._step
            st     = self._status[i]
            pbg    = CARD if is_cur else PANEL
            pfg    = FG   if is_cur else (FG2 if st != "wait" else FG3)
            sf["f"].configure(bg=pbg)
            sf["row"].configure(bg=pbg)
            sf["r"].configure(bg=pbg)
            for w in sf["r"].winfo_children():
                try: w.configure(bg=pbg, fg=pfg)
                except tk.TclError: pass
            cv = sf["cv"]
            cv.configure(bg=pbg)
            cv.delete("all")
            if st == "ok":
                cv.create_oval(2,2,26,26, fill=OK, outline="")
                cv.create_text(14,14, text="✓", fill=BG, font=("Consolas",10,"bold"))
            elif st == "error":
                cv.create_oval(2,2,26,26, fill=ERR, outline="")
                cv.create_text(14,14, text="✗", fill=FG, font=("Consolas",10,"bold"))
            elif is_cur:
                cv.create_oval(2,2,26,26, fill=ACCENT, outline="")
                cv.create_text(14,14, text=STEPS[i][0], fill=BG, font=("Consolas",10,"bold"))
            else:
                cv.create_oval(2,2,26,26, fill=DIM, outline="")
                cv.create_text(14,14, text=STEPS[i][0], fill=FG3, font=("Consolas",9))

    def _clear(self):
        for w in self._cont.winfo_children(): w.destroy()
        for w in self._foot.winfo_children(): w.destroy()

    def _go(self, idx):
        self._step = idx
        if self._status[idx] == "wait":
            self._status[idx] = "active"
        self._refresh_sb()
        self._clear()
        [self._s1_python, self._s2_packages, self._s3_path,
         self._s4_mt5,    self._s5_ea,       self._s6_done][idx]()

    def _done(self, idx):
        self._status[idx] = "ok"
        self._refresh_sb()
        if idx + 1 < len(STEPS):
            self._go(idx + 1)

    def _fb(self, text, cmd, side="right", bg=ACCENT, fg=BG, state="normal", **kw):
        b = mkbtn(self._foot, text, cmd, bg=bg, fg=fg, state=state, **kw)
        b.pack(side=side, padx=12, pady=10)
        return b

    def _sp(self, h=10):
        tk.Frame(self._cont, bg=BG, height=h).pack()

    def _rule(self):
        tk.Frame(self._cont, bg=BORDER, height=1).pack(fill="x")

    # ══════════════════════════════════════════════════════════════════════════
    # STEP 1 — Python
    # ══════════════════════════════════════════════════════════════════════════

    def _s1_python(self):
        c = self._cont
        v   = sys.version_info
        vs  = f"{v.major}.{v.minor}.{v.micro}"
        ok  = v.major == 3 and 9 <= v.minor <= 11

        L(c, "Step 1  —  Python Version Check", font=F_MED, fg=ACCENT).pack(anchor="w")
        self._sp(6); self._rule(); self._sp(14)

        box = tk.Frame(c, bg=CARD, padx=22, pady=18)
        box.pack(fill="x")
        L(box, ("✓" if ok else "✗") + f"  Python {vs}",
          font=F_BIG, fg=OK if ok else ERR, bg=CARD).pack(anchor="w")
        self._sp_in(box, 8)

        if ok:
            L(box, "Great — Python version is compatible. Setup can continue.",
              font=F_BODY, fg=FG2, bg=CARD).pack(anchor="w")
            self._sp(8)
            L(c, f"   Location:  {sys.executable}", font=F_SM, fg=FG3).pack(anchor="w")
            self._status[0] = "ok"; self._refresh_sb()
            self._fb("Next  →", lambda: self._go(1))
        else:
            L(box, f"Python {v.major}.{v.minor} is not supported.",
              font=F_BODY, fg=ERR, bg=CARD).pack(anchor="w")
            L(box, "GGTH requires Python 3.9, 3.10, or 3.11.",
              font=F_BODY, fg=FG2, bg=CARD).pack(anchor="w")
            L(box, "Python 3.12+ breaks TensorFlow 2.15 which powers the AI models.",
              font=F_SM,   fg=FG3, bg=CARD).pack(anchor="w")
            self._sp(16)
            fix = tk.Frame(c, bg=CARD, padx=18, pady=14)
            fix.pack(fill="x")
            L(fix, "How to fix:", font=F_STEP, fg=WARN, bg=CARD).pack(anchor="w")
            self._sp_in(fix, 6)
            for s in [
                '1.  Click "Download Python 3.11" below',
                "2.  Run the installer that downloads",
                '3.  CRITICAL: tick  "Add Python to PATH"  during install',
                "4.  Click Install Now and wait for it to finish",
                "5.  Close this window and re-run  setup.bat",
            ]:
                L(fix, f"    {s}", font=F_BODY, fg=FG2, bg=CARD).pack(anchor="w", pady=1)
            self._status[0] = "error"; self._refresh_sb()
            self._fb("Download Python 3.11  (opens browser)",
                     lambda: __import__("webbrowser").open(
                         "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"),
                     bg=BLUE, fg=FG)
            self._fb("Exit", self.destroy, bg=DIM, fg=FG2)

    def _sp_in(self, parent, h=8):
        tk.Frame(parent, bg=CARD, height=h).pack()

    # ══════════════════════════════════════════════════════════════════════════
    # STEP 2 — Packages
    # ══════════════════════════════════════════════════════════════════════════

    def _s2_packages(self):
        c = self._cont
        L(c, "Step 2  —  Install Required Packages", font=F_MED, fg=ACCENT).pack(anchor="w")
        self._sp(6); self._rule(); self._sp(12)
        L(c, "This installs TensorFlow, LightGBM, MetaTrader5, and all other required libraries.",
          font=F_BODY, fg=FG2).pack(anchor="w")
        L(c, "Takes 5–15 minutes on first install. Only needs to run once.",
          font=F_SM, fg=FG3).pack(anchor="w")
        self._sp(14)

        # Progress bar
        pb_outer = tk.Frame(c, bg=BORDER, height=16)
        pb_outer.pack(fill="x"); pb_outer.pack_propagate(False)
        self._pb = tk.Frame(pb_outer, bg=ACCENT, width=0)
        self._pb.pack(side="left", fill="y")
        self._sp(6)
        self._pb_lbl = L(c, "Click  Install Packages  to begin.", font=F_SM, fg=FG3)
        self._pb_lbl.pack(anchor="w")
        self._sp(10)

        # Log
        lf = tk.Frame(c, bg=CARD)
        lf.pack(fill="both", expand=True)
        self._log = tk.Text(lf, bg=CARD, fg=FG3, font=F_MONO,
                            relief="flat", bd=0, state="disabled",
                            wrap="word", padx=12, pady=10)
        sb = tk.Scrollbar(lf, command=self._log.yview, bg=CARD)
        self._log.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self._log.pack(fill="both", expand=True)
        self._lq = queue.Queue()

        if self._pkg_done:
            self._log_put("Packages already installed this session.\n")
            self._pb_lbl.configure(text="Already installed.", fg=OK)
            self._set_pb(100)
            self._fb("Next  →", lambda: self._go(2))
        else:
            self._inst_btn = self._fb("Install Packages", self._pkg_start)

        self.after(120, self._pkg_poll)

    def _log_put(self, t):
        self._log.configure(state="normal")
        self._log.insert("end", t)
        self._log.see("end")
        self._log.configure(state="disabled")

    def _set_pb(self, pct):
        w = max(0, int((self._cont.winfo_width() - 4) * pct / 100))
        self._pb.configure(width=w)

    def _pkg_poll(self):
        try:
            while True:
                m = self._lq.get_nowait()
                if m == "__DONE__":
                    self._pkg_done = True
                    self._status[1] = "ok"; self._refresh_sb()
                    self._pb_lbl.configure(text="Installation complete!", fg=OK)
                    self._set_pb(100)
                    for w in self._foot.winfo_children(): w.destroy()
                    self._fb("Next  →", lambda: self._go(2))
                    return
                elif m == "__ERR__":
                    self._status[1] = "error"; self._refresh_sb()
                    self._pb_lbl.configure(text="Installation failed — see log above.", fg=ERR)
                    for w in self._foot.winfo_children(): w.destroy()
                    self._fb("Retry", self._pkg_start)
                    return
                elif m.startswith("__P__:"):
                    pct = float(m[6:])
                    self._set_pb(pct)
                    self._pb_lbl.configure(
                        text=f"Installing...  {int(pct)}%  (please wait, this takes a few minutes)",
                        fg=FG2)
                else:
                    self._log_put(m)
        except queue.Empty:
            pass
        self.after(120, self._pkg_poll)

    def _pkg_start(self):
        for w in self._foot.winfo_children(): w.destroy()
        self._log.configure(state="normal"); self._log.delete("1.0","end")
        self._log.configure(state="disabled")
        threading.Thread(target=self._pkg_thread, daemon=True).start()

    def _pkg_thread(self):
        q = self._lq
        if not REQ_PATH.is_file():
            q.put("ERROR: requirements.txt not found in:\n")
            q.put(f"{SCRIPT_DIR}\n")
            q.put("Make sure all GGTH files are in the same folder as setup.bat\n")
            q.put("__ERR__"); return
        q.put("Starting installation...\n\n")
        cmd = [sys.executable, "-m", "pip", "install",
               "-r", str(REQ_PATH), "--no-warn-script-location"]
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT,
                                    text=True, encoding="utf-8", errors="replace")
        except Exception as e:
            q.put(f"Failed to start pip: {e}\n"); q.put("__ERR__"); return
        n = 0
        q.put("__P__:5")
        for line in proc.stdout:
            n += 1
            q.put("  " + line)
            if n % 4 == 0:
                q.put(f"__P__:{min(90, 5 + n*0.25)}")
        proc.wait()
        if proc.returncode == 0:
            q.put("\nAll packages installed successfully.\n")
            q.put("__DONE__")
        else:
            q.put(f"\npip exited with error code {proc.returncode}\n\n")
            q.put("Common fixes:\n")
            q.put("  - Make sure you are using Python 3.9, 3.10, or 3.11\n")
            q.put("  - Check your internet connection\n")
            q.put("  - Try right-clicking setup.bat and selecting 'Run as administrator'\n")
            q.put("__ERR__")

    # ══════════════════════════════════════════════════════════════════════════
    # STEP 3 — MT5 path
    # ══════════════════════════════════════════════════════════════════════════

    def _s3_path(self):
        c = self._cont
        L(c, "Step 3  —  MetaTrader 5 Folder", font=F_MED, fg=ACCENT).pack(anchor="w")
        self._sp(6); self._rule(); self._sp(10)
        L(c, "GGTH writes signal files to a folder inside MetaTrader 5.", font=F_BODY, fg=FG2).pack(anchor="w")
        self._sp(4)

        tip = tk.Frame(c, bg=CARD, padx=14, pady=10)
        tip.pack(fill="x")
        L(tip, "★  If you see  Common Files  in the list below, select that — it is correct for most users.",
          font=F_SM, fg=WARN, bg=CARD).pack(anchor="w")
        L(tip, "   To verify: open MetaTrader 5 → File → Open Data Folder → navigate to MQL5 → Files",
          font=F_SM, fg=FG3, bg=CARD).pack(anchor="w")

        self._sp(8)

        # Card list
        lf = tk.Frame(c, bg=BORDER, bd=1)
        lf.pack(fill="both", expand=True)
        cv = tk.Canvas(lf, bg=CARD, highlightthickness=0, bd=0)
        sb = tk.Scrollbar(lf, command=cv.yview, bg=CARD)
        cv.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        cv.pack(fill="both", expand=True)
        self._cf = tk.Frame(cv, bg=CARD)
        cw = cv.create_window((0,0), window=self._cf, anchor="nw")
        self._cf.bind("<Configure>", lambda e: cv.configure(
            scrollregion=cv.bbox("all")))
        cv.bind("<Configure>", lambda e: cv.itemconfig(cw, width=e.width))
        cv.bind_all("<MouseWheel>", lambda e: cv.yview_scroll(
            int(-1*(e.delta/120)), "units"))

        self._sp(8)

        row = tk.Frame(c, bg=BG)
        row.pack(fill="x")
        L(row, "Custom path:", font=F_SM, fg=FG3).pack(side="left")
        self._cv = tk.StringVar()
        tk.Entry(row, textvariable=self._cv, font=F_MONO,
                 bg=CARD, fg=FG, insertbackground=ACCENT,
                 relief="flat", highlightthickness=1,
                 highlightbackground=BORDER, highlightcolor=ACCENT,
                 width=40).pack(side="left", padx=(8,6), ipady=4)
        self._cv.trace_add("write", self._path_typed)
        tk.Button(row, text="Browse...", command=self._path_browse,
                  font=F_SM, bg=CARD, fg=FG2, relief="flat", bd=0,
                  padx=8, pady=4, cursor="hand2",
                  activebackground=BORDER, activeforeground=FG
                  ).pack(side="left")

        self._sp(4)
        self._path_lbl = L(c, "", font=F_SM, fg=FG3)
        self._path_lbl.pack(anchor="w")

        self._path_next = self._fb("Next  →", self._path_confirm,
                                   state="disabled", bg=DIM, fg=FG3)
        self._fb("← Back", lambda: self._go(1), bg=DIM, fg=FG2, side="left")

        self._cards = []
        threading.Thread(target=lambda: self.after(0, self._path_populate,
                                                   scan_mt5_paths()),
                         daemon=True).start()

    def _path_populate(self, results):
        for w in self._cf.winfo_children(): w.destroy()
        self._cards = []
        if not results:
            L(self._cf,
              "\n  MetaTrader 5 not found automatically.\n"
              "  Use Browse... below to locate your MQL5\\Files folder.\n\n"
              "  How to find it:\n"
              "    1. Open MetaTrader 5\n"
              "    2. Click File → Open Data Folder\n"
              "    3. Open MQL5 → Files\n"
              "    4. Copy the address bar and paste into Custom path below.",
              font=F_BODY, fg=FG3, bg=CARD, justify="left"
              ).pack(padx=14, pady=10, anchor="w")
            return

        for entry in results:
            f = tk.Frame(self._cf, bg=CARD, cursor="hand2",
                         highlightthickness=1, highlightbackground=BORDER)
            f.pack(fill="x", padx=2, pady=2)
            f._entry = entry
            top = tk.Frame(f, bg=CARD)
            top.pack(fill="x", padx=12, pady=(8,2))
            badge    = "COMMON ★" if entry["is_common"] else "TERMINAL"
            badge_fg = WARN      if entry["is_common"] else ACCENT
            L(top, badge, font=F_SM,   fg=badge_fg, bg=CARD).pack(side="left", padx=(0,10))
            L(top, entry["label"], font=F_STEP, fg=FG, bg=CARD).pack(side="left")
            L(f, str(entry["path"]), font=F_MONO, fg=FG3, bg=CARD, anchor="w"
              ).pack(fill="x", padx=12, pady=(0,8))
            tk.Frame(f, bg=BORDER, height=1).pack(fill="x")

            for w in [f, top] + list(top.winfo_children()) + list(f.winfo_children()):
                try: w.bind("<Button-1>", lambda e, card=f: self._path_select(card))
                except Exception: pass

            self._cards.append(f)

        # Auto-select Common if present, else first
        default = next((cd for cd in self._cards if cd._entry["is_common"]),
                       self._cards[0])
        self._path_select(default)

    def _path_select(self, card):
        if self._sel_card and self._sel_card is not card:
            self._sel_card.configure(bg=CARD, highlightbackground=BORDER)
            for w in self._sel_card.winfo_children():
                try:
                    w.configure(bg=CARD)
                    for ww in w.winfo_children():
                        try: ww.configure(bg=CARD)
                        except tk.TclError: pass
                except tk.TclError: pass
        self._sel_card = card
        card.configure(bg=ACCENT, highlightbackground=ACCENT)
        for w in card.winfo_children():
            try:
                w.configure(bg=ACCENT)
                for ww in w.winfo_children():
                    try: ww.configure(bg=ACCENT, fg=BG)
                    except tk.TclError: pass
            except tk.TclError: pass
        self._mt5_path = card._entry["path"]
        self._cv.set("")
        if card._entry["is_common"]:
            self._path_lbl.configure(
                text=f"  ✓  Selected (Common — recommended): {self._mt5_path}", fg=OK)
        else:
            self._path_lbl.configure(
                text=f"  ✓  Selected: {self._mt5_path}", fg=OK)
        self._path_next.configure(state="normal", bg=ACCENT, fg=BG, cursor="hand2")

    def _path_typed(self, *_):
        raw = self._cv.get().strip()
        if not raw:
            return
        if self._sel_card:
            self._sel_card.configure(bg=CARD, highlightbackground=BORDER)
            self._sel_card = None
        p = Path(raw)
        if p.is_dir():
            self._mt5_path = p
            self._path_lbl.configure(text=f"  ✓  {p}", fg=OK)
            self._path_next.configure(state="normal", bg=ACCENT, fg=BG, cursor="hand2")
        else:
            self._path_lbl.configure(text="  ✗  Folder not found.", fg=ERR)
            self._path_next.configure(state="disabled", bg=DIM, fg=FG3, cursor="arrow")

    def _path_browse(self):
        ch = filedialog.askdirectory(
            title="Select your MT5 MQL5\\Files folder",
            initialdir=str(MT5_ROOT) if MT5_ROOT.is_dir() else str(Path.home()))
        if ch:
            self._cv.set(ch)

    def _path_confirm(self):
        if not self._mt5_path:
            return
        try:
            write_config(str(self._mt5_path))
        except Exception as e:
            messagebox.showerror("Error", f"Could not save config.json:\n{e}")
            return
        self._done(2)

    # ══════════════════════════════════════════════════════════════════════════
    # STEP 4 — MT5 connection
    # ══════════════════════════════════════════════════════════════════════════

    def _s4_mt5(self):
        c = self._cont
        L(c, "Step 4  —  MetaTrader 5 Connection", font=F_MED, fg=ACCENT).pack(anchor="w")
        self._sp(6); self._rule(); self._sp(12)
        L(c, "GGTH connects to MetaTrader 5 to download price data for training.",
          font=F_BODY, fg=FG2).pack(anchor="w")
        L(c, "MetaTrader 5 must be open and logged in before you click Check.",
          font=F_SM, fg=FG3).pack(anchor="w")
        self._sp(12)

        self._mt5_box = tk.Frame(c, bg=CARD, padx=20, pady=18)
        self._mt5_box.pack(fill="x")
        self._mt5_lbl = L(self._mt5_box, "Click  Check Connection  to test.",
                          font=F_BODY, fg=FG3, bg=CARD)
        self._mt5_lbl.pack(anchor="w")

        self._sp(14)
        ck = tk.Frame(c, bg=CARD, padx=16, pady=12)
        ck.pack(fill="x")
        L(ck, "Before clicking Check, make sure:", font=F_STEP, fg=FG2, bg=CARD).pack(anchor="w")
        self._sp_c(ck, 6)
        for s in ["MetaTrader 5 is installed and currently open",
                  "You are logged in to your broker account in MT5",
                  "The  Auto Trading  button in the MT5 toolbar is green"]:
            L(ck, f"   ☐  {s}", font=F_SM, fg=FG3, bg=CARD).pack(anchor="w", pady=1)

        self._mt5_next = self._fb("Next  →", lambda: self._done(3),
                                  state="disabled", bg=DIM, fg=FG3)
        self._chk_btn  = self._fb("Check Connection", self._mt5_check, bg=BLUE, fg=FG)
        self._fb("← Back", lambda: self._go(2), bg=DIM, fg=FG2, side="left")

    def _sp_c(self, p, h=8):
        tk.Frame(p, bg=CARD, height=h).pack()

    def _mt5_check(self):
        self._mt5_lbl.configure(text="  Checking...", fg=FG3)
        self._chk_btn.configure(state="disabled")
        threading.Thread(target=self._mt5_thread, daemon=True).start()

    def _mt5_thread(self):
        try:
            import MetaTrader5 as mt5
        except ImportError:
            self.after(0, self._mt5_result, False,
                       "MetaTrader5 package not found.\n"
                       "Go back to Step 2 and re-run the installation.")
            return
        if not mt5.initialize():
            err = mt5.last_error()
            self.after(0, self._mt5_result, False,
                       f"Could not connect to MetaTrader 5.\nError: {err}\n\n"
                       "Make sure MT5 is open and you are logged in to your broker.")
            return
        info = mt5.account_info()
        mt5.shutdown()
        if info:
            msg = (f"  ✓  Connected!\n\n"
                   f"  Account:  {info.login}\n"
                   f"  Broker:   {info.company}\n"
                   f"  Balance:  {info.balance:.2f} {info.currency}\n"
                   f"  Server:   {info.server}")
        else:
            msg = "  ✓  Connected to MetaTrader 5."
        self.after(0, self._mt5_result, True, msg)

    def _mt5_result(self, ok, msg):
        self._chk_btn.configure(state="normal")
        self._mt5_lbl.configure(text=msg, fg=OK if ok else ERR)
        if ok:
            self._status[3] = "ok"; self._refresh_sb()
            self._mt5_next.configure(state="normal", bg=ACCENT, fg=BG, cursor="hand2")
        else:
            self._status[3] = "error"; self._refresh_sb()

    # ══════════════════════════════════════════════════════════════════════════
    # STEP 5 — EA setup
    # ══════════════════════════════════════════════════════════════════════════

    def _s5_ea(self):
        c = self._cont
        L(c, "Step 5  —  Install the Expert Advisor", font=F_MED, fg=ACCENT).pack(anchor="w")
        self._sp(6); self._rule(); self._sp(10)
        L(c, "The Expert Advisor (EA) is the part that runs inside MetaTrader 5 and places trades.",
          font=F_BODY, fg=FG2).pack(anchor="w")
        L(c, "This only needs to be done once. Follow the steps below exactly.",
          font=F_SM, fg=FG3).pack(anchor="w")
        self._sp(12)

        steps = [
            ("Open MetaEditor",
             'In MetaTrader 5, press  F4  on your keyboard.\n'
             'A separate MetaEditor window will open.'),
            ("Open the EA file",
             'In MetaEditor: click  File → Open.\n'
             'Navigate to your GGTH folder and open  GGTH_2026_v18.mq5'),
            ("Compile it",
             'Press  F7  (or click the Build button at the top).\n'
             'The bottom bar should say:  0 errors, 0 warnings\n'
             'If it shows errors, make sure you opened the right file.'),
            ("Open a chart",
             'Back in MetaTrader 5, open a  EURUSD  chart.\n'
             'Right-click the chart → Timeframe → M5'),
            ("Attach the EA",
             'Open the Navigator panel (press  Ctrl+N  if not visible).\n'
             'Under Expert Advisors, find  GGTH_2026_v18.\n'
             'Drag it onto the EURUSD M5 chart.'),
            ("Enable auto-trading",
             'In the settings dialog that appears:\n'
             '  - Tick  "Allow algorithmic trading"\n'
             '  - Click OK\n'
             'Make sure the Auto Trading button in the MT5 toolbar is green.'),
        ]

        for i, (title, detail) in enumerate(steps):
            row = tk.Frame(c, bg=CARD)
            row.pack(fill="x", pady=2)
            num = tk.Frame(row, bg=ACCENT, width=34)
            num.pack(side="left", fill="y")
            num.pack_propagate(False)
            L(num, str(i+1), font=F_HEAD, fg=BG, bg=ACCENT, anchor="center"
              ).pack(expand=True, fill="both")
            txt = tk.Frame(row, bg=CARD)
            txt.pack(side="left", fill="x", expand=True, padx=14, pady=10)
            L(txt, title, font=F_STEP, fg=FG, bg=CARD).pack(anchor="w")
            L(txt, detail, font=F_SM, fg=FG3, bg=CARD,
              wraplength=530, justify="left").pack(anchor="w", pady=(2,0))

        self._sp(4)
        self._fb("All done — Next  →", lambda: self._done(4))
        self._fb("← Back", lambda: self._go(3), bg=DIM, fg=FG2, side="left")

    # ══════════════════════════════════════════════════════════════════════════
    # STEP 6 — Done
    # ══════════════════════════════════════════════════════════════════════════

    def _s6_done(self):
        c = self._cont
        self._status[5] = "ok"; self._refresh_sb()

        self._sp(16)
        L(c, "✓  Setup Complete!", font=F_BIG, fg=OK, anchor="center").pack(fill="x")
        self._sp(8)
        tk.Frame(c, bg=BORDER, height=1).pack(fill="x")
        self._sp(16)

        box = tk.Frame(c, bg=CARD, padx=24, pady=18)
        box.pack(fill="x")
        L(box, "Everything is ready:", font=F_STEP, fg=FG2, bg=CARD).pack(anchor="w")
        self._sp_c(box, 8)
        cfg = read_config()
        for icon, text in [
            ("✓", "Python version verified"),
            ("✓", "All packages installed"),
            ("✓", f"MT5 path saved: {cfg.get('mt5_files_path','(see config.json)')}"),
            ("✓", "MetaTrader 5 connection tested"),
            ("✓", "EA installation guide completed"),
        ]:
            r = tk.Frame(box, bg=CARD)
            r.pack(anchor="w", pady=2)
            L(r, f"  {icon}", font=F_BODY, fg=OK,  bg=CARD).pack(side="left")
            L(r, f"  {text}", font=F_SM,   fg=FG2, bg=CARD).pack(side="left")

        self._sp(18)
        L(c, "From now on, just double-click  run_ggth_gui.bat  to start GGTH each day.",
          font=F_BODY, fg=FG2).pack(anchor="w")
        L(c, "That single file starts the sentiment pipeline and the prediction GUI together.",
          font=F_SM, fg=FG3).pack(anchor="w")

        self._sp(8)
        self._fb("Launch GGTH Now  →", self._launch, bg=OK, fg=BG)
        self._fb("Close", self.destroy, bg=DIM, fg=FG2, side="left")

    def _launch(self):
        target = SCRIPT_DIR / "run_ggth_gui.bat"
        if not target.is_file():
            target = SCRIPT_DIR / "ggth_gui.py"
        if not target.is_file():
            messagebox.showwarning("Not Found",
                "run_ggth_gui.bat was not found.\nPlease launch it manually.")
            return
        try:
            if target.suffix == ".bat":
                os.startfile(str(target))
            else:
                subprocess.Popen([sys.executable, str(target)], cwd=str(SCRIPT_DIR))
        except Exception as e:
            messagebox.showerror("Error", str(e))
        self.destroy()


if __name__ == "__main__":
    SetupWizard().mainloop()
