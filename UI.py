"""
Tkinter Options Strategy UI — v11
---------------------------------
"""
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, PhotoImage, simpledialog
from datetime import datetime
import platform
import json
import sys, os, traceback, copy
import io
import tempfile
from typing import List, Dict, Any, Optional, Tuple
 
 
from tkcalendar import DateEntry
try:
    import blpapi
except Exception as e:
    print(f"Failed to import blpapi in {__file__}: {e}")

# Package imports
from tools.options_pnl import OptionsPnL
from tools.updown_tool import UpDownTool
from theme import (
    THEME_BG, THEME_SURFACE, THEME_ACCENT, THEME_TEXT,
    THEME_MAIN, THEME_DANGER, THEME_ENTRY, THEME_FONT_FAMILY,
    init_style as _theme_init_style,
)
# Bloomberg Desktop API connection (local Terminal)
BLOOM_HOST = "127.0.0.1"
BLOOM_PORT = 8194
# Start with a neutral placeholder; will be replaced on Update Data
MATURITY_CHOICES = ["refresh data"]
# Example pricing - wire to BBG later
UNDER_PRICE = 302

class Launcher(tk.Tk):
    """Home screen that lets you open different tools."""
    def __init__(self):
        super().__init__()
        self.title("Options Suite — Home")
        self.configure(bg=THEME_BG)
        self.minsize(520, 360)
        _theme_init_style(self)
        self._build_home_ui()
        
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def _build_home_ui(self):
        wrap = ttk.Frame(self, padding=20, style="Card.TFrame")
        wrap.pack(fill="both", expand=True)
        ttk.Label(wrap, text="Welcome", style="MAIN.TLabel").pack(pady=(8, 16))
        ttk.Label(wrap, text="Choose a tool to launch:", style="TLabel").pack()
        btns = ttk.Frame(wrap)
        btns.pack(pady=16)
        ttk.Button(btns, text="Options P&L Simulator", style="Accent.TButton", command=self._open_pnl).grid(row=0, column=0, padx=8)
        ttk.Button(btns, text="UpDown (placeholder)", command=self._open_updown).grid(row=0, column=1, padx=8)
        ttk.Button(wrap, text="Quit", style="Danger.TButton", command=self.destroy).pack(pady=(12, 0))

    def _open_pnl(self):
        win = OptionsPnL(self, on_home=self._show_home)
        try:
            self.update_idletasks()
            rx, ry = self.winfo_rootx(), self.winfo_rooty()
            win.geometry(f"+{rx + 40}+{ry + 40}")
            win.lift(); win.focus_force()
        except Exception:
            pass

    def _open_updown(self):
        win = UpDownTool(self, on_home=self._show_home)
        try:
            self.update_idletasks()
            rx, ry = self.winfo_rootx(), self.winfo_rooty()
            win.geometry(f"+{rx + 40}+{ry + 40}")
            win.lift(); win.focus_force()
        except Exception:
            pass

    def _show_home(self):
        try:
            self.lift()
            self.focus_force()
        except Exception:
            pass


if __name__ == "__main__":
    Launcher().mainloop()


