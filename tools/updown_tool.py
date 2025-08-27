# OptionStrat/tools/updown_tool.py
import tkinter as tk
from tkinter import ttk, messagebox
# Support running as part of the OptionStrat package OR as a direct script import via UI.py
try:
    # Package-relative (preferred)
    from ..theme import (
        THEME_BG, THEME_SURFACE, THEME_TEXT, THEME_FONT_FAMILY,
        THEME_MAIN, THEME_ACCENT, THEME_DANGER, THEME_ENTRY,
        init_style as _theme_init_style,
    )
    from ..data_class import BloombergClient
    from ..scenario_analysis import portfolio_profit_curves
    from ..chart_widget import ChartWidget
except ImportError:
    # Absolute imports (when UI.py is run directly)
    from theme import (
        THEME_BG, THEME_SURFACE, THEME_TEXT, THEME_FONT_FAMILY,
        THEME_MAIN, THEME_ACCENT, THEME_DANGER, THEME_ENTRY,
        init_style as _theme_init_style,
    )
    from data_class import BloombergClient
    from scenario_analysis import portfolio_profit_curves
    from chart_widget import ChartWidget

try:
    import blpapi
except Exception as e:
    print(f"Failed to import blpapi in {__file__}: {e}")

class UpDownTool(tk.Toplevel):
    def __init__(self, master, on_home=None):
        super().__init__(master)
        self._on_home = on_home
        self.title("UpDown Tool")
        self.configure(bg=THEME_BG)
        self.minsize(480, 300)
        _theme_init_style(self)

        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # --- Root content frame ---
        frm = ttk.Frame(self, padding=12, style="Card.TFrame")
        frm.pack(fill="both", expand=True)

        # --- Top-level inputs section ---
        self.build_top_section(parent=frm)

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

    def _update_data(self):
        ticker = (self.ticker_var.get() or "").strip()
        if not ticker:
            messagebox.showwarning("Missing Ticker", "Please enter a ticker symbol (e.g., AAPL)", parent=self)
            return
        # Disable button and show loading state
        try:
            self.update_btn.configure(state="disabled")
        except Exception:
            pass
        self.maturity_var.set("Loading…")
        self.maturity_combo["values"] = []
        self.update_idletasks()

        try:
            print(f"[UpDownTool] Updating data for ticker: {ticker}")
            with BloombergClient() as bbg:
                # get equity mid price
                px = bbg.get_equity_px_mid(ticker)
                try:
                    self.price_var.set(f"{px:.2f}")
                except Exception:
                    self.price_var.set(str(px))
                print(f"[UpDownTool] PX_MID={px}")

                # get option chain descriptions & parse
                chain = bbg.get_opt_chain_descriptions(ticker)
                print(f"[UpDownTool] Retrieved {len(chain)} chain rows")
                tree = bbg.parse_opt_chain_descriptions(chain)
                mats = bbg.list_maturities(tree)
                print(f"[UpDownTool] Maturities: {mats}")

                self.maturity_combo["values"] = mats
                if mats:
                    self.maturity_var.set(mats[0])
                else:
                    self.maturity_var.set("(none)")
        except Exception as e:
            print(f"[UpDownTool] Update failed: {e}")
            try:
                messagebox.showerror("Update Failed", str(e), parent=self)
            except Exception:
                pass
        finally:
            try:
                self.update_btn.configure(state="normal")
            except Exception:
                pass

    def build_top_section(self, parent):
        """
        Build two stacked frames:
          1) "Ticker Entry" — Ticker (Entry), Price (Label), Maturity (Combobox)
          2) "Scenario Entry" — Up $, Down $, Up Prob %, Down Prob %
        """
        # Container for this section
        container = ttk.Frame(parent, padding=8, style="Card.TFrame")
        container.pack(fill="x", pady=(8, 4))

        # --------------------
        # Frame 1: Ticker Entry
        # --------------------
        ticker_frame = ttk.LabelFrame(container, text="Ticker Entry", padding=8)
        ticker_frame.pack(fill="x")
        
        # Vars
        self.ticker_var = getattr(self, 'ticker_var', tk.StringVar(value=""))
        self.price_var = getattr(self, 'price_var', tk.StringVar(value="—"))  # label only
        self.maturity_var = getattr(self, 'maturity_var', tk.StringVar(value=""))

        ttk.Label(ticker_frame, text="Ticker:", style="Title.TLabel").grid(row=0, column=0, sticky="w", padx=(0,6))
        ttk.Entry(ticker_frame, textvariable=self.ticker_var, width=14).grid(row=0, column=1, sticky="w")

        ttk.Label(ticker_frame, text="Price:", style="Title.TLabel").grid(row=0, column=2, sticky="w", padx=(16,6))
        ttk.Label(ticker_frame, textvariable=self.price_var, style="OnCard.TLabel").grid(row=0, column=3, sticky="w")

        ttk.Label(ticker_frame, text="Maturity:", style="Title.TLabel").grid(row=0, column=4, sticky="w", padx=(16,6))
        self.maturity_combo = ttk.Combobox(ticker_frame, textvariable=self.maturity_var, width=16, state="readonly", values=[])
        self.maturity_combo.grid(row=0, column=5, sticky="w")

        self.update_btn = ttk.Button(
            ticker_frame,
            text="Update Data",
            command=self._update_data,
            style="Accent.TButton"
        )
        self.update_btn.grid(row=0, column=6, sticky="w", padx=(16,0))

        for c in range(0, 6):
            ticker_frame.grid_columnconfigure(c, weight=0)
        ticker_frame.grid_columnconfigure(6, weight=1)

        # -----------------------
        # Frame 2: Scenario Entry
        # -----------------------
        scenario_frame = ttk.LabelFrame(container, text="Scenario Entry", padding=8)
        scenario_frame.pack(fill="x", pady=(8,0))

        # Vars
        self.up_dollar_var = getattr(self, 'up_dollar_var', tk.StringVar(value=""))
        self.down_dollar_var = getattr(self, 'down_dollar_var', tk.StringVar(value=""))
        self.up_prob_var = getattr(self, 'up_prob_var', tk.StringVar(value=""))
        self.down_prob_var = getattr(self, 'down_prob_var', tk.StringVar(value=""))

        ttk.Label(scenario_frame, text="Up $", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Entry(scenario_frame, textvariable=self.up_dollar_var, width=12).grid(row=0, column=1, sticky="w", padx=(6,16))

        ttk.Label(scenario_frame, text="Down $", style="Title.TLabel").grid(row=0, column=2, sticky="w")
        ttk.Entry(scenario_frame, textvariable=self.down_dollar_var, width=12).grid(row=0, column=3, sticky="w", padx=(6,16))

        ttk.Label(scenario_frame, text="Up Prob %", style="Title.TLabel").grid(row=0, column=4, sticky="w")
        ttk.Entry(scenario_frame, textvariable=self.up_prob_var, width=10).grid(row=0, column=5, sticky="w", padx=(6,16))

        ttk.Label(scenario_frame, text="Down Prob %", style="Title.TLabel").grid(row=0, column=6, sticky="w")
        ttk.Entry(scenario_frame, textvariable=self.down_prob_var, width=10).grid(row=0, column=7, sticky="w", padx=(6,0))

        for c in range(0, 8):
            scenario_frame.grid_columnconfigure(c, weight=0)
        scenario_frame.grid_columnconfigure(8, weight=1)