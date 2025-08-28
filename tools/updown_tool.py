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

        # --- Menu bar ---
        menubar = tk.Menu(self)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Go to Home", command=self._go_home)
        file_menu.add_separator()
        file_menu.add_command(label="Close", command=self._on_close)
        menubar.add_cascade(label="File", menu=file_menu)
        self.config(menu=menubar)

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
        norm_ticker = ticker.upper()
        last = getattr(self, "_last_ticker", None)
        need_chain = (last != norm_ticker) or (not getattr(self, "chain_tree", None))
        if not ticker:
            messagebox.showwarning("Missing Ticker", "Please enter a ticker symbol (e.g., AAPL)", parent=self)
            return
        # Disable button and show loading state
        try:
            self.update_btn.configure(state="disabled")
        except Exception:
            pass

        if need_chain:
            try:
                self.maturity_var.set("Loading…")
                self.maturity_combo["values"] = []
            except Exception:
                pass
            try:
                self.root_var.set("Loading…")
                self.root_combo["values"] = []
            except Exception:
                pass
    
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
                # Always cache the latest parsed tree for downstream lookups
                self.chain_tree = tree  # keep for later lookups

                # Only refresh maturities/roots if the current list is empty
                existing_mats = list(self.maturity_combo.cget("values") or [])
                if not existing_mats:
                    mats = bbg.list_maturities(tree)
                    print(f"[UpDownTool] Maturities: {mats}")

                    self.maturity_combo["values"] = mats
                    if mats:
                        self.maturity_var.set(mats[0])
                        # Populate roots for the default maturity
                        roots = self._roots_for_maturity(tree, mats[0])
                        print(f"[UpDownTool] Roots for {mats[0]}: {roots}")
                        self.root_combo["values"] = roots
                        if roots:
                            self.root_var.set(roots[0])
                        else:
                            self.root_var.set("")
                    else:
                        self.maturity_var.set("(none)")
                        self.root_combo["values"] = []
                        self.root_var.set("")
                    self._last_ticker = norm_ticker
                else:
                    print("[UpDownTool] Skipping maturity refresh (values already populated).")
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

    def _roots_for_maturity(self, tree: dict, ymd: str) -> list[str]:
        """Collect unique underlyings (roots) for a given maturity across all rights/strikes."""
        roots = set()
        try:
            rights = tree.get(ymd, {})
            for right in ("C", "P"):
                strikes = rights.get(right, {})
                for strike_key, under_map in strikes.items():
                    for under in under_map.keys():
                        roots.add(under)
        except Exception:
            pass
        return sorted(roots)

    def _on_maturity_selected(self, event=None):
        tree = getattr(self, 'chain_tree', None)
        if not isinstance(tree, dict):
            return
        ymd = (self.maturity_var.get() or "").strip()
        roots = self._roots_for_maturity(tree, ymd)
        self.root_combo["values"] = roots
        if roots:
            self.root_var.set(roots[0])
        else:
            self.root_var.set("")

    def _sf(self, s: str):
        """Safe float parse -> float or None."""
        try:
            v = float(str(s).strip())
            if v == v:  # not NaN
                return v
        except Exception:
            pass
        return None

    def _update_chain(self):
        """
        Build a detailed maturity chain for the selected ticker/maturity/root,
        using min/max from the UI. Saves result to self.detailed_maturity_chain.
        """
        # Preconditions
        tree = getattr(self, "chain_tree", None)
        if not isinstance(tree, dict) or not tree:
            messagebox.showwarning("No Chain", "Please click 'Update Data' first to load the option chain.", parent=self)
            return

        ticker = (self.ticker_var.get() or "").strip()
        ymd = (self.maturity_var.get() or "").strip()
        root = (self.root_var.get() or "").strip()

        if not ymd:
            messagebox.showwarning("Missing Maturity", "Select a maturity first.", parent=self)
            return
        if not root:
            messagebox.showwarning("Missing Root", "Select a root first.", parent=self)
            return

        # Pull min/max from the UI; we currently map Down $ -> min, Up $ -> max.
        # (If you add dedicated strike fields later, we can switch to those.)
        min_val = self._sf(self.down_dollar_var.get())
        max_val = self._sf(self.up_dollar_var.get())

        # If both provided and inverted, swap them
        if (min_val is not None) and (max_val is not None) and (min_val > max_val):
            min_val, max_val = max_val, min_val

        print(f"[UpDownTool] Update Chain for {ticker}  maturity={ymd}  root={root}  min={min_val}  max={max_val}")

        # Disable button while fetching
        try:
            self.update_chain_btn.configure(state="disabled")
        except Exception:
            pass

        try:
            # Rebuild detailed chain on every request so snapshots are fresh
            self.detailed_maturity_chain = {}
            with BloombergClient() as bbg:
                detailed = bbg.get_detailed_option_chain(
                    root=root,
                    maturity=ymd,
                    max_strike=max_val,
                    min_strike=min_val,
                    parsed_tree=tree,
                )
            self.detailed_maturity_chain = detailed
            # Simple console feedback
            try:
                rights = list(detailed.get(ymd, {}).keys())
                print(f"[UpDownTool] Detailed chain built for {ymd}. Rights: {rights}. Keys: {list(detailed.get(ymd, {}).keys())}")
                print("[UpDownTool] Detailed chain stored.")
                # if you want to see full ting 
                d_ymd = detailed.get(ymd, {})
                print(f"[UpDownTool] Detailed chain summary for {ymd} / {root}:")
                for right, strikes in d_ymd.items():
                    strike_count = len(strikes)
                    under_set = set()
                    leaf_count = 0
                    for strike_key, under_map in strikes.items():
                        for under, desc_map in under_map.items():
                            under_set.add(under)
                            leaf_count += len(desc_map)
                    print(f"  Right={right}: strikes={strike_count}, roots={len(under_set)}, contracts={leaf_count}")
            except Exception as _e:
                print(f"[UpDownTool] Detailed chain stored (summary unavailable): {_e}")

            messagebox.showinfo("Chain Updated", f"Detailed chain built for {ymd} / {root}.", parent=self)
        except Exception as e:
            print(f"[UpDownTool] Update Chain failed: {e}")
            try:
                messagebox.showerror("Update Chain Failed", str(e), parent=self)
            except Exception:
                pass
        finally:
            try:
                self.update_chain_btn.configure(state="normal")
            except Exception:
                pass

    def _on_ticker_changed(self, *args):
        """When the ticker text changes, clear dependent dropdowns so Update Data will repopulate them."""
        try:
            self.maturity_combo["values"] = []
            self.maturity_var.set("")
        except Exception:
            pass
        try:
            self.root_combo["values"] = []
            self.root_var.set("")
        except Exception:
            pass
        # clear cached tree so future updates know to repopulate
        self.chain_tree = None

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
        # Add ticker trace once to clear maturity/root when ticker changes
        if not hasattr(self, "_ticker_trace_added"):
            try:
                self.ticker_var.trace_add("write", lambda *a: self._on_ticker_changed())
                self._ticker_trace_added = True
            except Exception:
                pass

        ttk.Label(ticker_frame, text="Price:", style="Title.TLabel").grid(row=0, column=2, sticky="w", padx=(16,6))
        ttk.Label(ticker_frame, textvariable=self.price_var, style="OnCard.TLabel").grid(row=0, column=3, sticky="w")

        ttk.Label(ticker_frame, text="Maturity:", style="Title.TLabel").grid(row=0, column=4, sticky="w", padx=(16,6))
        self.maturity_combo = ttk.Combobox(ticker_frame, textvariable=self.maturity_var, width=16, state="readonly", values=[])
        self.maturity_combo.grid(row=0, column=5, sticky="w")
        self.maturity_combo.bind("<<ComboboxSelected>>", self._on_maturity_selected)

        ttk.Label(ticker_frame, text="Root:", style="Title.TLabel").grid(row=0, column=6, sticky="w", padx=(16,6))
        self.root_var = getattr(self, 'root_var', tk.StringVar(value=""))
        self.root_combo = ttk.Combobox(ticker_frame, textvariable=self.root_var, width=12, state="readonly", values=[])
        self.root_combo.grid(row=0, column=7, sticky="w")

        self.update_btn = ttk.Button(
            ticker_frame,
            text="Update Data",
            command=self._update_data,
            style="Accent.TButton"
        )
        self.update_btn.grid(row=0, column=8, sticky="w", padx=(16,0))
        

        for c in range(0, 9):
            ticker_frame.grid_columnconfigure(c, weight=0)
        ticker_frame.grid_columnconfigure(9, weight=1)

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

        # Update Chain button
        self.update_chain_btn = ttk.Button(scenario_frame, text="Update Chain", command=self._update_chain)
        self.update_chain_btn.grid(row=0, column=8, sticky="w", padx=(16,0))

        for c in range(0, 9):
            scenario_frame.grid_columnconfigure(c, weight=0)
        scenario_frame.grid_columnconfigure(9, weight=1)