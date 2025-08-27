# OptionStrat/theme.py
THEME_BG = "#E1E1E0"
THEME_SURFACE = "#E1E1E0"
THEME_ACCENT = "#51284F"
THEME_TEXT = "#000000"
THEME_MAIN = "#51284F"
THEME_DANGER = "#AC1E2E"
THEME_ENTRY = "#E1E1E0"
THEME_FONT_FAMILY = "SF Pro Text"

import tkinter as tk
from tkinter import ttk

def init_style(root: tk.Misc):
    style = ttk.Style(root)
    try: style.theme_use("clam")
    except tk.TclError: pass
    style.configure("TFrame", background=THEME_BG)
    style.configure("Card.TFrame", background=THEME_SURFACE)
    style.configure("TLabel", background=THEME_BG, foreground=THEME_TEXT, font=(THEME_FONT_FAMILY, 10))
    style.configure("OnCard.TLabel", background=THEME_SURFACE, foreground=THEME_TEXT, font=(THEME_FONT_FAMILY, 10))
    style.configure("MAIN.TLabel", foreground=THEME_MAIN, font=(THEME_FONT_FAMILY,14,"bold"))
    style.configure("Title.TLabel", font=(THEME_FONT_FAMILY, 12, "bold"))
    style.configure("LegTitle.TLabel", background=THEME_SURFACE, foreground=THEME_TEXT, font=(THEME_FONT_FAMILY, 12, "bold"))
    style.configure("Accent.TButton", background=THEME_ACCENT, foreground="#ffffff", padding=(10,6), borderwidth=0)
    style.configure("Danger.TButton", background=THEME_DANGER, foreground="#ffffff", padding=(10,6), borderwidth=0)
    style.configure("TEntry", fieldbackground=THEME_ENTRY, foreground=THEME_TEXT, insertcolor=THEME_TEXT, padding=4)
    style.configure("TCombobox", fieldbackground=THEME_ENTRY, foreground=THEME_TEXT)
    style.configure("TRadiobutton", background=THEME_BG, foreground=THEME_TEXT)
    style.configure("Leg.TRadiobutton", background=THEME_SURFACE, foreground=THEME_TEXT)
    style.map("Accent.TButton", background=[("active","black"),("disabled","lightgrey")], foreground=[("active","white"),("disabled","darkgrey")])
    style.map("Danger.TButton", background=[("active","black"),("disabled","lightgrey")], foreground=[("active","white"),("disabled","darkgrey")])