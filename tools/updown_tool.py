# OptionStrat/tools/updown_tool.py

import tkinter as tk
from tkinter import ttk
# Support running as part of the OptionStrat package OR direct script import via UI.py
try:
    # Package-relative (preferred)
    from ..theme import THEME_BG, init_style as _theme_init_style
except ImportError:
    # Absolute import (when UI.py is run directly)
    from theme import THEME_BG, init_style as _theme_init_style

class UpDownTool(tk.Toplevel):
    def __init__(self, master, on_home=None):
        super().__init__(master)
        self._on_home = on_home
        self.title("UpDown (Coming Soon)")
        self.configure(bg=THEME_BG)
        self.minsize(480, 300)
        _theme_init_style(self)

        self.protocol("WM_DELETE_WINDOW", self._on_close)

        frm = ttk.Frame(self, padding=20, style="Card.TFrame")
        frm.pack(fill="both", expand=True)
        ttk.Label(frm, text="UpDown Tool", style="MAIN.TLabel").pack(pady=(0,12))
        ttk.Label(frm, text="This is a placeholder. Build your tool here.").pack()
        ttk.Button(frm, text="Back to Home", command=self._go_home).pack(pady=20)

    def _go_home(self):
        if callable(getattr(self, "_on_home", None)):
            try: self._on_home()
            except Exception: pass

    def _on_close(self):
        try: self.destroy()
        finally:
            if callable(getattr(self, "_on_home", None)):
                try: self._on_home()
                except Exception: pass