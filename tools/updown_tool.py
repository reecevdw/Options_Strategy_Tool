"""
 
"""
# OptionStrat/tools/updown_tool.py
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
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
        file_menu.add_command(label="Load Run…", command=self._menu_load_run)
        file_menu.add_command(label="Save Run…", command=self._menu_save_run)
        file_menu.add_separator()
        file_menu.add_command(label="Close", command=self._on_close)
        menubar.add_cascade(label="File", menu=file_menu)

        view_menu = tk.Menu(menubar, tearoff=0)
        view_menu.add_command(label="Select Strategies…", command=self._menu_select_strategies)
        menubar.add_cascade(label="View", menu=view_menu)

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
            print(f"[UpDownTool] Updating data for ticker: {norm_ticker}")
            with BloombergClient() as bbg:
                # get equity mid price
                px = bbg.get_equity_px_mid(norm_ticker)
                try:
                    self.price_var.set(f"{px:.2f}")
                except Exception:
                    self.price_var.set(str(px))
                print(f"[UpDownTool] PX_MID={px}")
 
                # get option chain descriptions & parse
                chain = bbg.get_opt_chain_descriptions(norm_ticker)
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
 
    # =========================
    # Helpers for strategy calcs
    # =========================
    def _get_spot(self) -> float:
        """Parse current equity price from label; returns float or raises."""
        try:
            v = float((self.price_var.get() or "").replace(",", "").strip())
            return v
        except Exception:
            raise RuntimeError("Spot/Price not available. Click 'Update Data' first.")
 
    def _prob(self, s: str) -> float:
        """Parse probability that may be provided as percent or fraction."""
        try:
            p = float(str(s).strip())
            return p/100.0 if p > 1.0 else p
        except Exception:
            return 0.0
 
    def _targets(self) -> tuple[float, float, float, float]:
        """Return (up_price, down_price, up_prob, down_prob)."""
        up_p = float(str(self.up_dollar_var.get() or "0").replace(",", ""))
        dn_p = float(str(self.down_dollar_var.get() or "0").replace(",", ""))
        up_prob = self._prob(self.up_prob_var.get() or "0")
        dn_prob = self._prob(self.down_prob_var.get() or "0")
        return up_p, dn_p, up_prob, dn_prob
 
    def _strike_key(self, strike: float | str) -> str:
        """Format a strike to match keys in detailed chain (trim trailing .0)."""
        s = str(strike).strip()
        try:
            f = float(s)
            if abs(f - int(f)) < 1e-9:
                return str(int(round(f)))
            # trim trailing zeros
            as_str = f"{f:.6f}".rstrip("0").rstrip(".")
            return as_str
        except Exception:
            return s
 
    def _get_option_snapshot(self, right: str, strike: float | str) -> dict | None:
        """
        Look up a single option snapshot from self.detailed_maturity_chain
        using current maturity/root, right ('C'/'P'), and strike.
        Returns the snapshot dict or None.
        """
        tree = getattr(self, "detailed_maturity_chain", {}) or {}
        ymd = (self.maturity_var.get() or "").strip()
        root = (self.root_var.get() or "").strip()
        if not (ymd and root and isinstance(tree, dict)):
            print("[UpDownTool] No detailed chain available. Run 'Update Chain'.")
            return None
        k = self._strike_key(strike)
        try:
            leaf = tree.get(ymd, {}).get(right.upper(), {}).get(k, {}).get(root, {})
            # pick the first description in deterministic order
            if not leaf:
                return None
            desc = sorted(leaf.keys())[0]
            return leaf.get(desc)
        except Exception as e:
            print(f"[UpDownTool] lookup snapshot error ({right} {k}): {e}")
            return None
 
    def _option_price(self, right: str, strike: float | str) -> float | None:
        """
        Derive a working option price from the snapshot.
        Preference: PX_MID -> (bid+ask)/2 -> bid -> ask -> None.
        """
        snap = self._get_option_snapshot(right, strike)
        if not isinstance(snap, dict):
            print(f"[UpDownTool] No snapshot for {right} {strike}")
            return None
        bid = snap.get("PX_BID")
        mid = snap.get("PX_MID")
        ask = snap.get("PX_ASK")
        price = None
        if isinstance(mid, (int, float)):
            price = float(mid)
        elif isinstance(bid, (int, float)) and isinstance(ask, (int, float)):
            price = (float(bid) + float(ask)) / 2.0
        elif isinstance(bid, (int, float)):
            price = float(bid)
        elif isinstance(ask, (int, float)):
            price = float(ask)
        print(f"[UpDownTool] price {right} {strike} -> {price}  (bid={bid}, mid={mid}, ask={ask})")
        return price
 
    def _price_buy(self, right: str, strike: float | str) -> float | None:
        """BUY entry price using (MID + ASK)/2 with robust fallbacks and inference."""
        snap = self._get_option_snapshot(right, strike)
        if not isinstance(snap, dict):
            print(f"[UpDownTool] BUY: no snapshot for {right} {strike}")
            return None
        def _sf(v):
            try:
                f = float(v)
                return f if f == f else None
            except Exception:
                return None
        b = _sf(snap.get("PX_BID")); m = _sf(snap.get("PX_MID")); a = _sf(snap.get("PX_ASK"))
        EPS = 1e-9
        if b is None and m is None and a is None:
            return None
        if b is None and a is not None:
            if m is None:
                b = 0.0
                m = (b + a) / 2.0
            else:
                if abs(m - a) <= EPS:
                    b = 0.0
                    m = (b + a) / 2.0
                else:
                    b = max(0.0, 2.0 * m - a)
        if m is None and (b is not None) and (a is not None):
            m = (b + a) / 2.0
        if a is None and (b is not None) and (m is not None):
            a = max(0.0, 2.0 * m - b)
        if (m is not None) and (a is not None):
            return (m + a) / 2.0
        if m is not None:
            return float(m)
        if a is not None:
            return float(a)
        if b is not None:
            return float(b)
        return None
 
    def _price_sell(self, right: str, strike: float | str) -> float | None:
        """SELL entry price using (BID + MID)/2 with robust fallbacks and inference."""
        snap = self._get_option_snapshot(right, strike)
        if not isinstance(snap, dict):
            print(f"[UpDownTool] SELL: no snapshot for {right} {strike}")
            return None
        def _sf(v):
            try:
                f = float(v)
                return f if f == f else None
            except Exception:
                return None
        b = _sf(snap.get("PX_BID")); m = _sf(snap.get("PX_MID")); a = _sf(snap.get("PX_ASK"))
        if b is None and m is None and a is None:
            return None
        if m is None and (b is not None) and (a is not None):
            m = (b + a) / 2.0
        if b is None and (m is not None) and (a is not None):
            b = max(0.0, 2.0 * m - a)
        if (b is not None) and (m is not None):
            return (b + m) / 2.0
        if m is not None:
            return float(m)
        if b is not None:
            return float(b)
        if a is not None:
            return float(a)
        return None
 
    def _intrinsic_call(self, S: float, K: float) -> float:
        return max(S - K, 0.0)
 
    def _intrinsic_put(self, S: float, K: float) -> float:
        return max(K - S, 0.0)
 
    def _result(self, up: float, down: float) -> dict:
        denom = abs(down) if abs(down) > 1e-9 else 1e-9
        return {"up": up, "down": down, "ratio": (up / denom)}
 
    # =========================
    # Implied probability helper (price-to-cap heuristic)
    # =========================
    def _implied_prob_from_caps(self, entry_net: float, up_pnl: float, down_pnl: float):
        """
        Intuitively, P_current = p * P_deal + (1-p) * P_break
        Rearrange the above and we have: p = (P_c - P_b) / (P_d - P_b)
        Essentially: p = down_pnl / (down_pnl + up_pnl)
        """
        eps = 1e-12
        total = abs(up_pnl) + abs(down_pnl)
        if total < eps:
            return None
        else:
            return abs(down_pnl) / (abs(up_pnl) + abs(down_pnl))
 
    # =========================
    # 1) Stock outright
    # =========================
    def strat_stock_outright(self, premium_override: float | None = None) -> dict:
        """Outright long stock using scenario targets.
        Uses current spot price S; computes expected UP/DOWN payoffs weighted by up/down probabilities.
        Returns dict {up, down, ratio} where ratio = up / |down|.
        """
        S = self._get_spot()
        up_p, dn_p, _, _ = self._targets()
        up_payoff = (up_p - S)
        dn_payoff = (dn_p - S)
        entry = 0.0
        implied = self._implied_prob_from_caps(entry, up_payoff, dn_payoff)
        res = self._result(up_payoff, -dn_payoff)
        res["premium"] = None
        res["implied"] = implied
        return res
 
    # =========================
    # 2) Stock + Put (protective put)
    # =========================
    def strat_stock_put(self, put_strike: float, premium_override: float | None = None) -> dict:
        """Protective put: long stock + long put @Kp.
        Premium pulled from snapshots. Expected UP/DOWN payoffs are stock PnL ± put premium/intrinsic, weighted by probabilities.
        Returns {up, down, ratio}.
        """
        S = self._get_spot()
        up_p, dn_p, _, _ = self._targets()
        put_px = self._price_buy("P", put_strike) or 0.0
        entry = put_px
        if isinstance(premium_override, (int, float)):
            entry = float(premium_override)
        up_payoff = (up_p - S) + max(put_strike - up_p, 0.0) - entry
        dn_payoff = (dn_p - S) + max(put_strike - dn_p, 0.0) - entry
        implied = self._implied_prob_from_caps(entry, up_payoff, dn_payoff)
        res = self._result(up_payoff, -dn_payoff)
        res["premium"] = entry
        res["implied"] = implied
        return res
 
    # =========================
    # 3) Stock + Put Spread
    # =========================
    def strat_stock_put_spread(self, low_strike: float, high_strike: float, premium_override: float | None = None) -> dict:
        """Stock + put spread: long stock, long higher-K put, short lower-K put.
        Net debit = P(high) - P(low) from snapshots. Treat net debit/credit as cashflow vs. stock PnL.
        Returns {up, down, ratio}.
        """
        S = self._get_spot()
        up_p, dn_p, _, _ = self._targets()
        p_high = self._price_buy("P", high_strike) or 0.0     # buy higher K
        p_low  = self._price_sell("P", low_strike)  or 0.0    # sell lower K
        net_debit = p_high - p_low
        entry = net_debit
        if isinstance(premium_override, (int, float)):
            entry = float(premium_override)
        up_payoff = (up_p - S) + (max(high_strike - up_p, 0.0) - max(low_strike - up_p, 0.0)) - entry
        dn_payoff = (dn_p - S) + (max(high_strike - dn_p, 0.0) - max(low_strike - dn_p, 0.0)) - entry
        implied = self._implied_prob_from_caps(entry, up_payoff, dn_payoff)
        res = self._result(up_payoff, -dn_payoff)
        res["premium"] = entry
        res["implied"] = implied
        return res
 
    # =========================
    # 4) Bullish Risk Reversal (long C, short P)
    # =========================
    def strat_bullish_risk_reversal(self, call_strike: float, put_strike: float, premium_override: float | None = None) -> dict:
        """Bullish risk reversal: long call @Kc, short put @Kp (no stock).
        Net debit = C(Kc) - P(Kp). Expected UP/DOWN from scenario targets with premium credit/debit applied.
        Returns {up, down, ratio}.
        """
        S = self._get_spot()
        up_p, dn_p, _, _ = self._targets()
        c_px = self._price_buy("C", call_strike) or 0.0
        p_px = self._price_sell("P", put_strike) or 0.0
        net_debit = c_px - p_px  # could be negative (credit)
        entry = net_debit
        if isinstance(premium_override, (int, float)):
            entry = float(premium_override)
        up_payoff = max(up_p - call_strike, 0.0) - max(put_strike - up_p, 0.0) - entry
        dn_payoff = max(dn_p - call_strike, 0.0) - max(put_strike - dn_p, 0.0) - entry
        implied = self._implied_prob_from_caps(entry, up_payoff, dn_payoff)
        res = self._result(up_payoff, -dn_payoff)
        res["premium"] = entry
        res["implied"] = implied
        return res
 
    # =========================
    # 5) Call outright
    # =========================
    def strat_call_outright(self, strike: float, premium_override: float | None = None) -> dict:
        """Long call @K: payoff = max(S - K, 0) - call premium at scenario prices.
        Uses snapshot-derived premium. Returns {up, down, ratio} for UP/DOWN targets.
        """
        entry = self._price_buy("C", strike) or 0.0
        if isinstance(premium_override, (int, float)):
            entry = float(premium_override)
        up_p, dn_p, _, _ = self._targets()
        up_payoff = max(up_p - strike, 0.0) - entry
        dn_payoff = 0.0 - entry
        implied = self._implied_prob_from_caps(entry, up_payoff, dn_payoff)
        res = self._result(up_payoff, abs(dn_payoff))
        res["premium"] = entry
        res["implied"] = implied
        return res
 
    # =========================
    # 6) Put outright
    # =========================
    def strat_put_outright(self, strike: float, premium_override: float | None = None) -> dict:
        """Long put @K: payoff = max(K - S, 0) - put premium at scenario prices.
        Uses snapshot-derived premium. Returns {up, down, ratio} for UP/DOWN targets.
        """
        entry = self._price_buy("P", strike) or 0.0
        if isinstance(premium_override, (int, float)):
            entry = float(premium_override)
        up_p, dn_p, _, _ = self._targets()
        up_payoff = 0.0 - entry
        dn_payoff = max(strike - dn_p, 0.0) - entry
        implied = self._implied_prob_from_caps(entry, up_payoff, dn_payoff)
        res = self._result(abs(up_payoff), dn_payoff)
        res["premium"] = entry
        res["implied"] = implied
        return res
 
    # =========================
    # 7) Call spread (long K1, short K2>K1)
    # =========================
    def strat_call_spread(self, low_strike: float, high_strike: float, premium_override: float | None = None) -> dict:
        """Call vertical: long call @K1, short call @K2>K1.
        Net debit = C(K1) - C(K2). UP payoff capped at (K2-K1) minus net debit; DOWN = -net debit. Returns {up, down, ratio}.
        """
        c1 = self._price_buy("C", low_strike)   or 0.0  # buy
        c2 = self._price_sell("C", high_strike) or 0.0  # sell
        net_debit = c1 - c2
        entry = net_debit
        if isinstance(premium_override, (int, float)):
            entry = float(premium_override)
        up_p, dn_p, _, _ = self._targets()
        width = max(0.0, high_strike - low_strike)
        up_payoff = min(max(up_p - low_strike, 0.0), width) - entry
        dn_payoff = 0.0 - entry
        implied = self._implied_prob_from_caps(entry, up_payoff, dn_payoff)
        res = self._result(up_payoff, dn_payoff)
        res["premium"] = entry
        res["implied"] = implied
        return res
 
    # =========================
    # 8) Call spread 1x2 (long 1 low, short 2 high)
    # =========================
    def strat_call_spread_one_by_two(self, low_strike: float, high_strike: float, premium_override: float | None = None) -> dict:
        """Call 1x2: long 1 call @K1, short 2 calls @K2>K1.
        Net debit = C(K1) - 2*C(K2). UP payoff reflects convex short above K2; DOWN = -net debit. Returns {up, down, ratio}.
        """
        c1 = self._price_buy("C", low_strike)  or 0.0
        c2 = self._price_sell("C", high_strike) or 0.0
        net_debit = c1 - 2.0*c2
        entry = net_debit
        if isinstance(premium_override, (int, float)):
            entry = float(premium_override)
        up_p, dn_p, _, _ = self._targets()
        up_payoff = max(up_p - low_strike, 0.0) - 2.0*max(up_p - high_strike, 0.0) - entry
        dn_payoff = 0.0 - entry
        implied = self._implied_prob_from_caps(entry, up_payoff, dn_payoff)
        res = self._result(up_payoff, dn_payoff)
        res["premium"] = entry
        res["implied"] = implied
        return res
 
    # =========================
    # Call Backspreads (ratio: long more higher-K calls, short fewer lower-K calls)
    # =========================
    def strat_call_backspread_2x1(self, short_low: float, long_high: float, premium_override: float | None = None) -> dict:
        """Call backspread 2x1: short 1 call @K_low, long 2 calls @K_high (K_high > K_low).
        Payoff(S) = 2*max(S-K_high,0) - max(S-K_low,0) - net_debit,
        where net_debit = 2*C(K_high) - C(K_low). Returns {up, down, ratio} using scenario targets.
        """
        c_low  = self._price_sell("C", short_low)  or 0.0
        c_high = self._price_buy("C", long_high) or 0.0
        net_debit = 2.0*c_high - c_low
        entry = net_debit
        if isinstance(premium_override, (int, float)):
            entry = float(premium_override)
        up_p, dn_p, _, _ = self._targets()
        up_payoff = 2.0*max(up_p - long_high, 0.0) - max(up_p - short_low, 0.0) - entry
        dn_payoff = 2.0*max(dn_p - long_high, 0.0) - max(dn_p - short_low, 0.0) - entry
        implied = self._implied_prob_from_caps(entry, up_payoff, dn_payoff)
        res = self._result(up_payoff, dn_payoff)
        res["premium"] = entry
        res["implied"] = implied
        return res
 
    def strat_call_backspread_3x1(self, short_low: float, long_high: float, premium_override: float | None = None) -> dict:
        """Call backspread 3x1: short 1 call @K_low, long 3 calls @K_high (K_high > K_low).
        Payoff(S) = 3*max(S-K_high,0) - max(S-K_low,0) - net_debit,
        where net_debit = 3*C(K_high) - C(K_low). Returns {up, down, ratio} using scenario targets.
        """
        c_low  = self._price_sell("C", short_low)  or 0.0
        c_high = self._price_buy("C", long_high) or 0.0
        net_debit = 3.0*c_high - c_low
        entry = net_debit
        if isinstance(premium_override, (int, float)):
            entry = float(premium_override)
        up_p, dn_p, _, _ = self._targets()
        up_payoff = 3.0*max(up_p - long_high, 0.0) - max(up_p - short_low, 0.0) - entry
        dn_payoff = 3.0*max(dn_p - long_high, 0.0) - max(dn_p - short_low, 0.0) - entry
        implied = self._implied_prob_from_caps(entry, up_payoff, dn_payoff)
        res = self._result(up_payoff, dn_payoff)
        res["premium"] = entry
        res["implied"] = implied
        return res
 
    # =========================
    # Put Backspreads (ratio: long more lower-K puts, short fewer higher-K puts)
    # =========================
    def strat_put_backspread_2x1(self, short_high: float, long_low: float, premium_override: float | None = None) -> dict:
        """Put backspread 2x1: short 1 put @K_high, long 2 puts @K_low (K_high > K_low).
        Payoff(S) = 2*max(K_low-S,0) - max(K_high-S,0) - net_debit,
        where net_debit = 2*P(K_low) - P(K_high). Returns {up, down, ratio} using scenario targets.
        """
        p_high = self._price_sell("P", short_high) or 0.0
        p_low  = self._price_buy("P", long_low)  or 0.0
        net_debit = 2.0*p_low - p_high
        entry = net_debit
        up_p, dn_p, _, _ = self._targets()
        up_payoff = 2.0*max(long_low - up_p, 0.0) - max(short_high - up_p, 0.0) - entry
        dn_payoff = 2.0*max(long_low - dn_p, 0.0) - max(short_high - dn_p, 0.0) - entry
        if isinstance(premium_override, (int, float)):
            entry = float(premium_override)
            up_payoff = 2.0*max(long_low - up_p, 0.0) - max(short_high - up_p, 0.0) - entry
            dn_payoff = 2.0*max(long_low - dn_p, 0.0) - max(short_high - dn_p, 0.0) - entry
        implied = self._implied_prob_from_caps(entry, up_payoff, dn_payoff)
        res = self._result(up_payoff, dn_payoff)
        res["premium"] = entry
        res["implied"] = implied
        return res
 
    def strat_put_backspread_3x1(self, short_high: float, long_low: float, premium_override: float | None = None) -> dict:
        """Put backspread 3x1: short 1 put @K_high, long 3 puts @K_low (K_high > K_low).
        Payoff(S) = 3*max(K_low-S,0) - max(K_high-S,0) - net_debit,
        where net_debit = 3*P(K_low) - P(K_high). Returns {up, down, ratio} using scenario targets.
        """
        p_high = self._price_sell("P", short_high) or 0.0
        p_low  = self._price_buy("P", long_low)  or 0.0
        net_debit = 3.0*p_low - p_high
        entry = net_debit
        up_p, dn_p, _, _ = self._targets()
        up_payoff = 3.0*max(long_low - up_p, 0.0) - max(short_high - up_p, 0.0) - entry
        dn_payoff = 3.0*max(long_low - dn_p, 0.0) - max(short_high - dn_p, 0.0) - entry
        if isinstance(premium_override, (int, float)):
            entry = float(premium_override)
            up_payoff = 3.0*max(long_low - up_p, 0.0) - max(short_high - up_p, 0.0) - entry
            dn_payoff = 3.0*max(long_low - dn_p, 0.0) - max(short_high - dn_p, 0.0) - entry
        implied = self._implied_prob_from_caps(entry, up_payoff, dn_payoff)
        res = self._result(up_payoff, dn_payoff)
        res["premium"] = entry
        res["implied"] = implied
        return res
 
    # =========================
    # Call / Put Butterflies (1:-2:1)
    # =========================
    def strat_call_butterfly(self, k_low: float, k_mid: float, k_high: float, premium_override: float | None = None) -> dict:
        """Call butterfly: long 1 @K_low, short 2 @K_mid, long 1 @K_high (K_low < K_mid < K_high).
        Net debit = C(K_low) - 2*C(K_mid) + C(K_high).
        Payoff(S) = max(S-K_low,0) - 2*max(S-K_mid,0) + max(S-K_high,0) - net_debit.
        Returns {up, down, ratio} with scenario targets.
        """
        cL = self._price_buy("C", k_low)  or 0.0
        cM = self._price_sell("C", k_mid)  or 0.0
        cH = self._price_buy("C", k_high) or 0.0
        net_debit = cL - 2.0*cM + cH
        entry = net_debit
        if isinstance(premium_override, (int, float)):
            entry = float(premium_override)
        up_p, dn_p, _, _ = self._targets()
        up_payoff = max(up_p - k_low, 0.0) - 2.0*max(up_p - k_mid, 0.0) + max(up_p - k_high, 0.0) - entry
        dn_payoff = max(dn_p - k_low, 0.0) - 2.0*max(dn_p - k_mid, 0.0) + max(dn_p - k_high, 0.0) - entry
        implied = self._implied_prob_from_caps(entry, up_payoff, dn_payoff)
        res = self._result(up_payoff, dn_payoff)
        res["premium"] = entry
        res["implied"] = implied
        return res
 
    def strat_put_butterfly(self, k_low: float, k_mid: float, k_high: float, premium_override: float | None = None) -> dict:
        """Put butterfly: long 1 @K_high, short 2 @K_mid, long 1 @K_low (K_low < K_mid < K_high).
        Net debit = P(K_high) - 2*P(K_mid) + P(K_low).
        Payoff(S) = max(K_high-S,0) - 2*max(K_mid-S,0) + max(K_low-S,0) - net_debit.
        Returns {up, down, ratio} with scenario targets.
        """
        pH = self._price_buy("P", k_high) or 0.0
        pM = self._price_sell("P", k_mid)  or 0.0
        pL = self._price_buy("P", k_low)  or 0.0
        net_debit = pH - 2.0*pM + pL
        entry = net_debit
        if isinstance(premium_override, (int, float)):
            entry = float(premium_override)
        up_p, dn_p, _, _ = self._targets()
        up_payoff = max(k_high - up_p, 0.0) - 2.0*max(k_mid - up_p, 0.0) + max(k_low - up_p, 0.0) - entry
        dn_payoff = max(k_high - dn_p, 0.0) - 2.0*max(k_mid - dn_p, 0.0) + max(k_low - dn_p, 0.0) - entry
        implied = self._implied_prob_from_caps(entry, up_payoff, dn_payoff)
        res = self._result(up_payoff, dn_payoff)
        res["premium"] = entry
        res["implied"] = implied
        return res
 
    # =========================
    # Put-Spread Collars (with and without stock)
    # =========================
    def strat_put_spread_collar(self, put_high: float, put_low: float, call_strike: float, premium_override: float | None = None) -> dict:
        """Put-spread collar (options only): long put @K_high, short put @K_low, short call @Kc; no stock.
        Net debit = P(K_high) - P(K_low) - C(Kc).
        Payoff(S) = [max(K_high-S,0) - max(K_low-S,0)] - max(S-Kc,0) - net_debit.
        Returns {up, down, ratio} with scenario targets.
        """
        pH = self._price_buy("P", put_high) or 0.0
        pL = self._price_sell("P", put_low)  or 0.0
        c  = self._price_sell("C", call_strike) or 0.0
        net_debit = pH - pL - c
        entry = net_debit
        if isinstance(premium_override, (int, float)):
            entry = float(premium_override)
        up_p, dn_p, _, _ = self._targets()
        def payoff(S: float) -> float:
            return (max(put_high - S, 0.0) - max(put_low - S, 0.0)) - max(S - call_strike, 0.0) - net_debit
        up_payoff = payoff(up_p)
        dn_payoff = payoff(dn_p)
        implied = self._implied_prob_from_caps(entry, up_payoff, dn_payoff)
        res = self._result(up_payoff, dn_payoff)
        res["premium"] = entry
        res["implied"] = implied
        return res
 
    def strat_put_spread_collar_with_stock(self, put_high: float, put_low: float, call_strike: float, premium_override: float | None = None) -> dict:
        """Put-spread collar WITH stock: long stock, long put @K_high, short put @K_low, short call @Kc.
        Net debit = [P(K_high) - P(K_low)] - C(Kc). Stock component uses current spot S.
        Scenario payoff adds stock PnL (S_t - S) plus options payoff minus net_debit.
        Returns {up, down, ratio}.
        """
        S0 = self._get_spot()
        pH = self._price_buy("P", put_high) or 0.0
        pL = self._price_sell("P", put_low)  or 0.0
        c  = self._price_sell("C", call_strike) or 0.0
        net_debit = (pH - pL) - c
        entry = net_debit
        if isinstance(premium_override, (int, float)):
            entry = float(premium_override)
        up_p, dn_p, _, _ = self._targets()
        def payoff(S: float) -> float:
            stock_pnl = S - S0
            opt = (max(put_high - S, 0.0) - max(put_low - S, 0.0)) - max(S - call_strike, 0.0)
            return stock_pnl + opt - net_debit
        up_payoff = payoff(up_p)
        dn_payoff = payoff(dn_p)
        implied = self._implied_prob_from_caps(entry, up_payoff, dn_payoff)
        res = self._result(up_payoff, dn_payoff)
        res["premium"] = entry
        res["implied"] = implied
        return res
 
    # =========================
    # Call / Put Trees (assumed 1x1x1):
    # For calls: long 1 @K1, short 1 @K2, short 1 @K3 (K1 < K2 < K3).
    # For puts:  long 1 @K3, short 1 @K2, short 1 @K1 (K1 < K2 < K3).
    # =========================
    def strat_call_tree_1x1x1(self, k1_long: float, k2_short: float, k3_short: float, premium_override: float | None = None) -> dict:
        """Call tree 1x1x1 (assumption): long 1 call @K1, short 1 @K2, short 1 @K3 with K1<K2<K3.
        Net debit = C(K1) - C(K2) - C(K3).
        Payoff(S) = max(S-K1,0) - max(S-K2,0) - max(S-K3,0) - net_debit.
        Returns {up, down, ratio}. If you prefer a different 1x1x1 convention, we can adjust.
        """
        c1 = self._price_buy("C", k1_long)  or 0.0
        c2 = self._price_sell("C", k2_short) or 0.0
        c3 = self._price_sell("C", k3_short) or 0.0
        net_debit = c1 - c2 - c3
        entry = net_debit
        if isinstance(premium_override, (int, float)):
            entry = float(premium_override)
        up_p, dn_p, _, _ = self._targets()
        up_payoff = max(up_p - k1_long, 0.0) - max(up_p - k2_short, 0.0) - max(up_p - k3_short, 0.0) - entry
        dn_payoff = max(dn_p - k1_long, 0.0) - max(dn_p - k2_short, 0.0) - max(dn_p - k3_short, 0.0) - entry
        implied = self._implied_prob_from_caps(entry, up_payoff, dn_payoff)
        res = self._result(up_payoff, dn_payoff)
        res["premium"] = entry
        res["implied"] = implied
        return res
 
    def strat_put_tree_1x1x1(self, k1_short: float, k2_short: float, k3_long: float, premium_override: float | None = None) -> dict:
        """Put tree 1x1x1 (assumption): short 1 put @K1, short 1 @K2, long 1 @K3 with K1<K2<K3.
        Net debit = -P(K1) - P(K2) + P(K3)  (i.e., often a credit).
        Payoff(S) = -max(K1-S,0) - max(K2-S,0) + max(K3-S,0) - net_debit.
        Returns {up, down, ratio}. If you prefer a different 1x1x1 convention, we can adjust.
        """
        p1 = self._price_sell("P", k1_short) or 0.0
        p2 = self._price_sell("P", k2_short) or 0.0
        p3 = self._price_buy("P", k3_long)  or 0.0
        net_debit = -p1 - p2 + p3
        entry = net_debit
        if isinstance(premium_override, (int, float)):
            entry = float(premium_override)
        up_p, dn_p, _, _ = self._targets()
        up_payoff = -max(k1_short - up_p, 0.0) - max(k2_short - up_p, 0.0) + max(k3_long - up_p, 0.0) - entry
        dn_payoff = -max(k1_short - dn_p, 0.0) - max(k2_short - dn_p, 0.0) + max(k3_long - dn_p, 0.0) - entry
        implied = self._implied_prob_from_caps(entry, up_payoff, dn_payoff)
        res = self._result(up_payoff, dn_payoff)
        res["premium"] = entry
        res["implied"] = implied
        return res
 
    # =========================
    # 9) Buy-write (covered call: long stock + short call)
    # =========================
    def strat_buy_write(self, call_strike: float, premium_override: float | None = None) -> dict:
        """Covered call: long stock + short call @K.
        Approximates with stock PnL plus call premium (ignores hard cap at K by default). Returns {up, down, ratio}.
        """
        S = self._get_spot()
        c_px = self._price_sell("C", call_strike) or 0.0
        entry = -c_px  # credit
        if isinstance(premium_override, (int, float)):
            entry = float(premium_override)
        up_p, dn_p, _, _ = self._targets()
        up_payoff = (up_p - S) - max(up_p - call_strike, 0.0) - entry
        dn_payoff = (dn_p - S) - max(dn_p - call_strike, 0.0) - entry
        implied = self._implied_prob_from_caps(entry, up_payoff, dn_payoff)
        res = self._result(up_payoff, -dn_payoff)
        res["premium"] = c_px
        res["implied"] = implied
        return res
 
    # =========================
    # 10) Straddle (long call + long put at same K)
    # =========================
    def strat_straddle(self, strike: float, premium_override: float | None = None) -> dict:
        """Long straddle @K: long call + long put.
        Total cost = C+P from snapshots. UP/DOWN payoffs use intrinsic at scenario prices minus cost. Returns {up, down, ratio}.
        """
        c = self._price_buy("C", strike) or 0.0
        p = self._price_buy("P", strike) or 0.0
        cost = c + p
        entry = cost
        if isinstance(premium_override, (int, float)):
            entry = float(premium_override)
        up_p, dn_p, _, _ = self._targets()
        up_payoff = max(up_p - strike, 0.0) + max(strike - up_p, 0.0) - cost
        dn_payoff = max(dn_p - strike, 0.0) + max(strike - dn_p, 0.0) - cost
        implied = self._implied_prob_from_caps(entry, up_payoff, dn_payoff)
        res = self._result(up_payoff, dn_payoff)
        res["premium"] = entry
        res["implied"] = implied
        return res
 
    # =========================
    # 11) Collar (long stock, long put, short call)
    # =========================
    def strat_collar(self, put_strike: float, call_strike: float, premium_override: float | None = None) -> dict:
        """Collar with stock: long stock, long put @Kp, short call @Kc.
        Net debit = P - C. Approximates scenario UP/DOWN with stock PnL adjusted by collar net debit/credit. Returns {up, down, ratio}.
        """
        S = self._get_spot()
        up_p, dn_p, _, _ = self._targets()
        p = self._price_buy("P", put_strike) or 0.0
        c = self._price_sell("C", call_strike) or 0.0
        net_debit = p - c
        entry = net_debit
        if isinstance(premium_override, (int, float)):
            entry = float(premium_override)
        up_payoff = (up_p - S) - entry
        dn_payoff = (S - dn_p) + entry
        implied = self._implied_prob_from_caps(entry, up_payoff, dn_payoff)
        res = self._result(up_payoff, dn_payoff)
        res["premium"] = entry
        res["implied"] = implied
        return res
 
    # =========================
    # 11b) Collar without stock (long put, short call)
    # =========================
    def strat_collar_no_stock(self, put_strike: float, call_strike: float, premium_override: float | None = None) -> dict:
        """Options-only collar: long put @Kp, short call @Kc (no stock).
        Payoff at S is: (max(Kp-S,0) - P) + (C - max(S-Kc,0)).
        Uses scenario up/down prices and probabilities from the UI.
        Returns dict with keys {up, down, ratio} like other strategies.
        """
        up_p, dn_p, _, _= self._targets()
        # Prices from snapshots (PX_MID fallback logic via _option_price)
        p = self._price_buy("P", put_strike) or 0.0
        c = self._price_sell("C", call_strike) or 0.0
 
        entry = p - c
        if isinstance(premium_override, (int, float)):
            entry = float(premium_override)
       
        up_payoff = (max(put_strike - up_p, 0.0) - max(up_p - call_strike, 0.0)) - entry
        dn_payoff = (max(put_strike - dn_p, 0.0) - max(dn_p - call_strike, 0.0)) - entry
 
        res = self._result(up_payoff, dn_payoff)
        try:
            res["premium"] = float(p) - float(c)
        except Exception:
            res["premium"] = None
 
        implied = self._implied_prob_from_caps(entry, up_payoff, dn_payoff)
        res["implied"] = implied
        return res
 
    # =========================
    # 12) Call-spread collar (long stock, long put, short call spread)
    # =========================
    def strat_call_spread_collar(self, put_strike: float, call_low: float, call_high: float, premium_override: float | None = None) -> dict:
        """Call-spread collar: long stock, long put @Kp, short call spread (short @K1, long @K2>K1).
        Net debit = Put - (CallLow - CallHigh). Returns {up, down, ratio} using scenario targets.
        """
        S = self._get_spot()
        up_p, dn_p, _, _ = self._targets()
        p      = self._price_buy("P", put_strike) or 0.0
        c_low  = self._price_sell("C", call_low)  or 0.0  # short
        c_high = self._price_buy("C", call_high) or 0.0  # long
        net_debit = p - (c_low - c_high)  # pay for put, receive call-spread credit
        entry = net_debit
        if isinstance(premium_override, (int, float)):
            entry = float(premium_override)
        up_payoff = (up_p - S) - entry
        dn_payoff = (S - dn_p) + entry
        res = self._result(up_payoff, dn_payoff)
        res["premium"] = entry
        implied = self._implied_prob_from_caps(entry, up_payoff, dn_payoff)
        res["implied"] = implied
        return res
 
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
 
        # -----------------------
        # Frame 3: Strategies Grid (scrollable)
        # -----------------------
        self._strategies_container = ttk.LabelFrame(parent, text="Strategies", padding=8)
        self._strategies_container.pack(fill="both", expand=True, pady=(8, 4))

        # Registry for inputs/outputs per strategy
        self._strategy_cards = {}

        # Define strategies once for reuse
        self._strategies_def = [
            ("Stock Outright", self.strat_stock_outright, []),
            ("Put and Stock", self.strat_stock_put, [("Put Strike", "put_strike")]),
            ("Call Outright", self.strat_call_outright, [("Call Strike", "strike")]),
            ("Put Outright", self.strat_put_outright, [("Put Strike", "strike")]),
            ("Call Spread", self.strat_call_spread, [("Low Strike", "low_strike"), ("High Strike", "high_strike")]),
            ("Call 1x2", self.strat_call_spread_one_by_two, [("Low Strike", "low_strike"), ("High Strike", "high_strike")]),
            ("Call Backspread 1x2", self.strat_call_backspread_2x1, [("Short Low Strike", "short_low"), ("Long High Strike", "long_high")]),
            ("Call Backspread 1x3", self.strat_call_backspread_3x1, [("Short Low Strike", "short_low"), ("Long High Strike", "long_high")]),
            ("Put Backspread 1x2", self.strat_put_backspread_2x1, [("Short High Strike", "short_high"), ("Long Low Strike", "long_low")]),
            ("Put Backspread 1x3", self.strat_put_backspread_3x1, [("Short High Strike", "short_high"), ("Long Low Strike", "long_low")]),
            ("Call Butterfly", self.strat_call_butterfly, [("Low Strike", "k_low"), ("Mid Strike", "k_mid"), ("High Strike", "k_high")]),
            ("Put Butterfly", self.strat_put_butterfly, [("Low Strike", "k_low"), ("Mid Strike", "k_mid"), ("High Strike", "k_high")]),
            ("Bullish Risk Reversal", self.strat_bullish_risk_reversal, [("Call Strike", "call_strike"), ("Put Strike", "put_strike")]),
            ("Buy Stock Sell Call", self.strat_buy_write, [("Call Strike", "call_strike")]),
            ("Straddle", self.strat_straddle, [("Strike", "strike")]),
            ("Collar (w/ stock)", self.strat_collar, [("Put Strike", "put_strike"), ("Call Strike", "call_strike")]),
            ("Collar (no stock)", self.strat_collar_no_stock, [("Put Strike", "put_strike"), ("Call Strike", "call_strike")]),
            ("Call-Spread Collar", self.strat_call_spread_collar, [("Put Strike", "put_strike"), ("Call Low Strike", "call_low"), ("Call High Strike", "call_high")]),
            ("Put-Spread Collar", self.strat_put_spread_collar, [("Put High Strike", "put_high"), ("Put Low Strike", "put_low"), ("Call Strike", "call_strike")]),
            ("Put-Spread Collar + Stock", self.strat_put_spread_collar_with_stock, [("Put High Strike", "put_high"), ("Put Low Strike", "put_low"), ("Call Strike", "call_strike")]),
            ("Call Tree 1x1x1", self.strat_call_tree_1x1x1, [("Long Strike1", "k1_long"), ("Short Strike2", "k2_short"), ("Short Strike3", "k3_short")]),
            ("Put Tree 1x1x1", self.strat_put_tree_1x1x1, [("Short Strike1", "k1_short"), ("Short Strike2", "k2_short"), ("Long Strike3", "k3_long")]),
        ]

        # Default selection: all strategies
        self._selected_strategies = set(title for title, _, _ in self._strategies_def)
        self._rebuild_strategies_grid()

    # -----------------------
    # Strategies: UI building and selection dialog
    # -----------------------
    def _clear_strategies_grid(self):
        try:
            for child in self._strategies_container.winfo_children():
                child.destroy()
        except Exception:
            pass
        self._strategy_cards = {}

    def _rebuild_strategies_grid(self):
        self._clear_strategies_grid()
        grid_container = self._strategies_container
        canvas = tk.Canvas(grid_container, highlightthickness=0, bg=THEME_BG)
        vsb = ttk.Scrollbar(grid_container, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner_id = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        def _on_inner_config(event=None):
            canvas.configure(scrollregion=canvas.bbox("all"))
            try:
                canvas.itemconfig(inner_id, width=canvas.winfo_width())
            except Exception:
                pass
        inner.bind("<Configure>", _on_inner_config)

        def _add_strategy_card(parent_frame, row: int, col: int, title: str, func, fields: list[tuple[str, str]]):
            card = ttk.LabelFrame(parent_frame, text=title, padding=8, style="Card.TFrame")
            card.grid(row=row, column=col, sticky="nsew", padx=6, pady=6)
            in_vars = {}
            for i, (lab, key) in enumerate(fields):
                ttk.Label(card, text=lab+":").grid(row=i, column=0, sticky="w")
                var = tk.StringVar(value="")
                in_vars[key] = var
                ttk.Entry(card, textvariable=var, width=12).grid(row=i, column=1, sticky="w", padx=(6,0))
            ov_row = len(fields)
            ttk.Label(card, text="Premium Override:").grid(row=ov_row, column=0, sticky="w")
            in_vars["premium_override"] = tk.StringVar(value="")
            ttk.Entry(card, textvariable=in_vars["premium_override"], width=12).grid(row=ov_row, column=1, sticky="w", padx=(6,0))
            r0 = len(fields) + 1
            ttk.Separator(card, orient="horizontal").grid(row=r0, column=0, columnspan=3, sticky="ew", pady=4)
            ttk.Label(card, text="Premium:").grid(row=r0+1, column=0, sticky="w")
            out_prem = ttk.Label(card, text="—", style="OnCard.TLabel"); out_prem.grid(row=r0+1, column=1, sticky="w")
            ttk.Label(card, text="Up:").grid(row=r0+2, column=0, sticky="w")
            out_up = ttk.Label(card, text="—", style="OnCard.TLabel"); out_up.grid(row=r0+2, column=1, sticky="w")
            ttk.Label(card, text="Down:").grid(row=r0+3, column=0, sticky="w")
            out_dn = ttk.Label(card, text="—", style="OnCard.TLabel"); out_dn.grid(row=r0+3, column=1, sticky="w")
            ttk.Label(card, text="Ratio:").grid(row=r0+4, column=0, sticky="w")
            out_rt = ttk.Label(card, text="—", style="OnCard.TLabel"); out_rt.grid(row=r0+4, column=1, sticky="w")
            ttk.Label(card, text="Implied Prob:").grid(row=r0+5, column=0, sticky="w")
            out_ip = ttk.Label(card, text="—", style="OnCard.TLabel"); out_ip.grid(row=r0+5, column=1, sticky="w")

            def _compute():
                try:
                    args = []
                    for _, key in fields:
                        v = self._sf(in_vars[key].get())
                        if v is None:
                            raise ValueError(f"Missing/invalid input for '{key}'")
                        args.append(v)
                    pov = self._sf(in_vars.get("premium_override").get()) if in_vars.get("premium_override") else None
                    res = func(*args, premium_override=pov) if (args and pov is not None) else (func(*args) if args else (func(premium_override=pov) if pov is not None else func()))
                    prem = res.get("premium", None); ip = res.get("implied", None)
                    upv = float(res.get("up", 0.0)); dnv = float(res.get("down", 0.0)); rtv = float(res.get("ratio", 0.0))
                    out_prem.configure(text=(f"{prem:,.2f}" if isinstance(prem, float) else "—"))
                    out_up.configure(text=f"{upv:,.2f}"); out_dn.configure(text=f"{dnv:,.2f}"); out_rt.configure(text=f"{rtv:,.2f}")
                    out_ip.configure(text=(f"{ip:.2%}" if isinstance(ip, float) else "—"))
                except Exception as e:
                    print(f"[UpDownTool] Compute '{title}' failed: {e}")
                    try:
                        messagebox.showwarning("Compute Failed", f"{title}: {e}", parent=self)
                    except Exception:
                        pass
            btn = ttk.Button(card, text="Compute", command=_compute, style="Accent.TButton")
            btn.grid(row=r0+6, column=0, columnspan=2, sticky="ew", pady=(6,0))
            self._strategy_cards[title] = {"frame": card, "in_vars": in_vars, "out": (out_prem, out_up, out_dn, out_rt, out_ip), "button": btn}
            for cidx in range(0, 3):
                card.grid_columnconfigure(cidx, weight=0)
            card.grid_columnconfigure(2, weight=1)

        # Build selected strategies in a 2-col grid
        cols = 2
        idx = 0
        for title, func, fields in self._strategies_def:
            if title not in self._selected_strategies:
                continue
            r = idx // cols; c = idx % cols; idx += 1
            _add_strategy_card(inner, r, c, title, func, fields)
        for c in range(cols):
            inner.grid_columnconfigure(c, weight=1)

    def _menu_select_strategies(self):
        win = tk.Toplevel(self)
        win.title("Select Strategies")
        win.transient(self)
        frm = ttk.Frame(win, padding=10)
        frm.pack(fill="both", expand=True)
        checks = {}
        # Controls
        btns = ttk.Frame(frm); btns.pack(fill="x", pady=(0,8))
        def _select_all():
            for v in checks.values(): v.set(True)
        def _clear_all():
            for v in checks.values(): v.set(False)
        ttk.Button(btns, text="Select All", command=_select_all).pack(side="left")
        ttk.Button(btns, text="Clear", command=_clear_all).pack(side="left", padx=(8,0))

        listfrm = ttk.Frame(frm); listfrm.pack(fill="both", expand=True)
        for title, _, _ in self._strategies_def:
            var = tk.BooleanVar(value=(title in self._selected_strategies))
            checks[title] = var
            ttk.Checkbutton(listfrm, text=title, variable=var).pack(anchor="w")

        def _apply():
            self._selected_strategies = {t for t,v in checks.items() if v.get()}
            if not self._selected_strategies:
                messagebox.showwarning("No Strategies", "Select at least one strategy to display.", parent=win)
                return
            self._rebuild_strategies_grid()
            win.destroy()
        ttk.Button(frm, text="Apply", style="Accent.TButton", command=_apply).pack(side="right")

    # -----------------------
    # Save/Load current run
    # -----------------------
    def _collect_run_data(self) -> dict:
        data = {
            "ticker": (self.ticker_var.get() or "").strip(),
            "price": (self.price_var.get() or "").strip(),
            "maturity": (self.maturity_var.get() or "").strip(),
            "root": (self.root_var.get() or "").strip(),
            "up_dollar": (self.up_dollar_var.get() or "").strip(),
            "down_dollar": (self.down_dollar_var.get() or "").strip(),
            "up_prob": (self.up_prob_var.get() or "").strip(),
            "down_prob": (self.down_prob_var.get() or "").strip(),
            "selected_strategies": sorted(list(self._selected_strategies or set())),
            "strategies_inputs": {},
        }
        # Capture inputs per visible strategy card
        for title, card in self._strategy_cards.items():
            in_vars = card.get("in_vars", {})
            data["strategies_inputs"][title] = {k: (v.get() if hasattr(v, 'get') else "") for k, v in in_vars.items()}
        return data

    def _apply_run_data(self, data: dict):
        # Basic fields
        try: self.ticker_var.set(str(data.get("ticker", "")))
        except Exception: pass
        try: self.price_var.set(str(data.get("price", "")))
        except Exception: pass
        try: self.maturity_var.set(str(data.get("maturity", "")))
        except Exception: pass
        try: self.root_var.set(str(data.get("root", "")))
        except Exception: pass
        try: self.up_dollar_var.set(str(data.get("up_dollar", "")))
        except Exception: pass
        try: self.down_dollar_var.set(str(data.get("down_dollar", "")))
        except Exception: pass
        try: self.up_prob_var.set(str(data.get("up_prob", "")))
        except Exception: pass
        try: self.down_prob_var.set(str(data.get("down_prob", "")))
        except Exception: pass
        # Selected strategies
        sel = data.get("selected_strategies", None)
        if isinstance(sel, list):
            self._selected_strategies = set(str(s) for s in sel)
        self._rebuild_strategies_grid()
        # Populate inputs for visible cards
        inputs = data.get("strategies_inputs", {}) or {}
        for title, card in self._strategy_cards.items():
            try:
                in_vars = card.get("in_vars", {})
                vals = inputs.get(title, {})
                for k, var in in_vars.items():
                    try:
                        var.set(str(vals.get(k, "")))
                    except Exception:
                        continue
            except Exception:
                continue

    def _menu_save_run(self):
        data = self._collect_run_data()
        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON files", "*.json")])
        if not path:
            return
        import json
        try:
            with open(path, "w") as f:
                json.dump(data, f, indent=2)
            messagebox.showinfo("Saved", f"Run saved to:\n{path}")
        except Exception as e:
            messagebox.showerror("Save Error", f"Could not save file:\n{e}")

    def _menu_load_run(self):
        path = filedialog.askopenfilename(filetypes=[("JSON files", "*.json")])
        if not path:
            return
        import json
        try:
            with open(path, "r") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("Invalid file format (expected JSON object)")
        except Exception as e:
            messagebox.showerror("Load Error", f"Invalid or unreadable file:\n{e}")
            return
        try:
            self._apply_run_data(data)
        except Exception as e:
            messagebox.showerror("Load Error", f"Failed to load run:\n{e}")
 

