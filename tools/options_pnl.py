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

# Start with a neutral placeholder; will be replaced on Update Data
MATURITY_CHOICES = ["refresh data"]

class DateField(ttk.Frame):
    """Calendar-only date picker: readonly entry + button that opens tkcalendar.Calendar."""
    def __init__(self, parent, textvariable: tk.StringVar, *, date_pattern: str = "yyyy-mm-dd", on_prev=None, on_next=None):
        super().__init__(parent)
        self.var = textvariable
        self.date_pattern = date_pattern
        # readonly entry shows the date text
        self.entry = ttk.Entry(self, textvariable=self.var, width=10, state="readonly")
        self.entry.grid(row=0, column=0, sticky="ew")
        # Optional callbacks for keyboard navigation between date fields
        self._on_prev = on_prev
        self._on_next = on_next
        self.entry.bind("<Left>",  lambda e: self._on_prev(self) if self._on_prev else None)
        self.entry.bind("<Right>", lambda e: self._on_next(self) if self._on_next else None)
        # calendar button
        self.btn = ttk.Button(self, text="🗓", width=2, command=self.open_calendar)
        self.btn.grid(row=0, column=1, padx=(2, 0))
        self.columnconfigure(0, weight=1)
    def open_calendar(self):
        top = tk.Toplevel(self)
        top.title("Select date")
        top.transient(self.winfo_toplevel())
        top.grab_set()
        frm = ttk.Frame(top, padding=8)
        frm.pack(fill="both", expand=True)
        # Prefill calendar selection from current var if parseable
        year = month = day = None
        try:
            if self.var.get().strip():
                dt = datetime.strptime(self.var.get().strip(), "%Y-%m-%d")
                year, month, day = dt.year, dt.month, dt.day
        except Exception:
            pass
        from tkcalendar import Calendar
        cal_kwargs = dict(selectmode="day")
        if all(x is not None for x in (year, month, day)):
            cal_kwargs.update(year=year, month=month, day=day)
        cal = Calendar(
            frm,
            **cal_kwargs,
            showweeknumbers=False,
            headersbackground=THEME_ACCENT,   # gugg color
            headersforeground="#ffffff",
            background="#ffffff",
            foreground="#000000",
            normalbackground="#ffffff",
            normalforeground="#000000",
            weekendbackground="#ffffff",
            weekendforeground=THEME_DANGER,
            othermonthbackground="#f0f0f0",
            othermonthforeground="#6b6b6b",
            bordercolor="#bdbdbd",
            selectbackground=THEME_ACCENT,
            selectforeground="#ffffff",
        )
        cal.pack(fill="both", expand=True, pady=(0, 8))
        btns = ttk.Frame(frm)
        btns.pack(fill="x")
        def _ok():
            # Calendar.get_date() returns locale string; normalize to YYYY-MM-DD
            sel = cal.selection_get()  # datetime.date
            self.var.set(sel.strftime("%Y-%m-%d"))
            top.destroy()
        def _cancel():
            top.destroy()
        ttk.Button(btns, text="OK", command=_ok).pack(side="right", padx=(8,0))
        ttk.Button(btns, text="Cancel", command=_cancel).pack(side="right")
        # Position dialog near widget
        top.update_idletasks()
        x = self.winfo_rootx()
        y = self.winfo_rooty() + self.winfo_height() + 6
        top.geometry(f"+{x}+{y}")
        # Keep modal behavior but not freezing UI
        self.winfo_toplevel().wait_window(top)
 
class LegFrame(ttk.Frame):
    def clear_stats(self):
        for v in (self.stat_finance, self.stat_div, self.stat_delta, self.stat_gamma, self.stat_vega, self.stat_ivol, self.stat_theta):
            v.set("-")
    def set_snapshot(self, snap: Dict[str, Any]):
        self._snapshot = dict(snap) if isinstance(snap, dict) else None
    def clear_snapshot(self):
        self._snapshot = None
    def get_snapshot(self) -> Optional[Dict[str, Any]]:
        return getattr(self, "_snapshot", None)
    def _required_snapshot_keys(self) -> tuple:
        # Fields required for a “complete” leg snapshot (prices handled leniently elsewhere)
        return (
            "OPT_FINANCE_RT", "OPT_DIV_YIELD",
            "DELTA_MID_RT", "GAMMA_MID_RT", "VEGA_MID_RT",
            "IVOL_MID_RT", "THETA_MID_RT",
        )
    def has_full_snapshot(self) -> bool:
        snap = getattr(self, "_snapshot", None)
        if not isinstance(snap, dict):
            return False
        # Require greeks/finance fields
        for k in self._required_snapshot_keys():
            if k not in snap or snap.get(k) is None:
                return False
        # Require at least one of bid/mid/ask to be available
        if not any(snap.get(k) is not None for k in ("PX_BID", "PX_MID", "PX_ASK")):
            return False
        return True
    def set_stats_from_snapshot(self, snap: Dict[str, Any]):
        """Update stats labels from a Bloomberg snapshot dict, formatting to 3 decimals.
        Keys expected: OPT_FINANCE_RT, OPT_DIV_YIELD, DELTA_MID_RT, GAMMA_MID_RT, VEGA_MID_RT, IVOL_MID_RT, THETA_MID_RT
        """
        def fmt3(x):
            try:
                if x is None or (isinstance(x, str) and x.strip() == ""):
                    return "-"
                return f"{float(x):.3f}"
            except Exception:
                return "-"
        try:
            self.stat_finance.set(fmt3(snap.get("OPT_FINANCE_RT")))
            self.stat_div.set(fmt3(snap.get("OPT_DIV_YIELD")))
            self.stat_delta.set(fmt3(snap.get("DELTA_MID_RT")))
            self.stat_gamma.set(fmt3(snap.get("GAMMA_MID_RT")))
            self.stat_vega.set(fmt3(snap.get("VEGA_MID_RT")))
            self.stat_ivol.set(f"{snap.get('IVOL_MID_RT'):.1f}")
            self.stat_theta.set(fmt3(snap.get("THETA_MID_RT")))
        except Exception:
            self.clear_stats()
    def get_delta_trade(self) -> float:
        try:
            delta = float(self.delta_var.get())
            qty = float(self.qty_var.get())
            return delta * qty * 100.0
        except Exception:
            return 0.0
    def get_delta_notional(self, equity_price: float) -> float:
        try:
            return self.get_delta_trade() * equity_price
        except Exception:
            return 0.0
    def set_maturities(self, values: list[str]):
        # print(f"[DBG] Leg {getattr(self, '_index', '?')} set_maturities -> {values}")
        cur = self.maturity.get().strip()
        try:
            self.maturity.configure(values=values)
        except Exception:
            self.maturity["values"] = values
        if cur and cur in values:
            self.maturity.set(cur)
        else:
            self.maturity.set("")
    def set_strikes(self, values: list[str]):
        """Set available strikes (combobox values) and clear selection unless current is valid."""
        try:
            self.strike_combo.configure(values=values)
        except Exception:
            self.strike_combo["values"] = values
        cur = (self.strike_combo.get() or "").strip()
        if cur and cur in values:
            # keep current selection
            return
        # set placeholder if provided
        placeholder = values[0] if values else ""
        try:
            self.strike_combo.set(placeholder)
        except Exception:
            pass
    def _refresh_strikes(self):
        """Ask parent for strikes for current maturity and CP, then apply to combobox."""
        try:
            mat = self.maturity.get().strip()
            cp_label = self.cp_var.get()
            values = self.get_strikes(mat, cp_label) if callable(self.get_strikes) else ["refresh data"]
            self.set_strikes(values)
        except Exception:
            self.set_strikes(["(none)"])
    def set_roots(self, values: list[str]):
        """Set available roots and keep/clear selection with placeholders."""
        try:
            self.root_combo.configure(values=values)
        except Exception:
            self.root_combo["values"] = values
        cur = (self.root_combo.get() or "").strip()
        if cur and cur in values:
            return
        placeholder = values[0] if values else ""
        try:
            self.root_combo.set(placeholder)
        except Exception:
            pass
    def _refresh_roots(self):
        """Refresh roots whenever maturity / CP / strike changes."""
        try:
            mat = self.maturity.get().strip()
            cp_label = self.cp_var.get()
            strike = (self.strike_combo.get() or "").strip()
            values = self.get_roots(mat, cp_label, strike) if callable(self.get_roots) else ["refresh data"]
            self.set_roots(values)
        except Exception:
            self.set_roots(["(none)"])
    def __init__(self, parent, index: int, get_mode, get_spot, get_strikes, get_roots, on_change):
        super().__init__(parent, style="Card.TFrame", padding=8)
        self.get_mode = get_mode
        self.on_change = on_change
        self._index = index
        self.get_spot = get_spot
        self.get_strikes = get_strikes
        self.get_roots = get_roots
 
        self._snapshot: Optional[Dict[str, Any]] = None  # Bloomberg snapshot for this leg
        # Only the left-most column stretches; the rest stay compact
        self.columnconfigure(0, weight=1)
        for c in range(1, 6):
            self.columnconfigure(c, weight=0)
        # Header (compact): title | buy\sell | call/put | maturity
        hdr = ttk.Frame(self, style="Card.TFrame")
        hdr.grid(row=0, column=0, columnspan=5, sticky="w")
        self.title_lbl = ttk.Label(hdr, text=f"Leg {index}", style="LegTitle.TLabel")
        self.title_lbl.grid(row=0, column=0, sticky="w", padx=(0,20))
        # --- Buy/Sell dropdown (visual only; sign is applied on save) ---
        self.side_var = tk.StringVar(value="BUY")
        self.side_combo = ttk.Combobox(hdr, values=["BUY","SELL"], state="readonly", width=6, textvariable=self.side_var)
        self.side_combo.grid(row=0, column=1, padx=(2,2), sticky="w")
        # --- call/put radiobutton ---
        self.cp_var = tk.StringVar(value="Call")
        self.call_rb = ttk.Radiobutton(hdr, text="Call", variable=self.cp_var, value="Call",
                                       style="Leg.TRadiobutton", command=self.on_change)
        self.call_rb.grid(row=0, column=2, sticky="w", padx=(10,4))
        self.put_rb = ttk.Radiobutton(hdr, text="Put", variable=self.cp_var, value="Put",
                                      style="Leg.TRadiobutton", command=self.on_change)
        self.put_rb.grid(row=0, column=3, sticky="w", padx=(10,14))
        self.cp_var.trace_add("write", lambda *_: self._on_cp_changed())
        ttk.Label(hdr, text="Maturity:", style="OnCard.TLabel").grid(row=0, column=4, sticky="w", padx=(0,4))
        self.maturity = ttk.Combobox(hdr, values=MATURITY_CHOICES, state="readonly", width=16)
        self.maturity.grid(row=0, column=5, sticky="w")
        self.maturity.set("")
        self.maturity.bind("<<ComboboxSelected>>", self._on_maturity_selected)
        # Set dropdown menu background to white for consistency
        try:
            self.maturity["menu"].config(bg="white")
        except Exception:
            pass
        # Keep header compact: let first column expand slightly, others natural size
        hdr.columnconfigure(0, weight=0)
        hdr.columnconfigure(1, weight=0)
        hdr.columnconfigure(2, weight=0)
        hdr.columnconfigure(3, weight=0)
        hdr.columnconfigure(4, weight=0)
        ttk.Separator(self).grid(row=1, column=0, columnspan=8, sticky="ew", pady=(6,8))
        # ---- Inputs layout (2 rows) ----
        # Row 1: [Strike/%OTM radios] | [Strike dropdown] | [%OTM entry]
        self.strike_mode = tk.StringVar(value="Strike")  # "Strike" or "%OTM"
        strike_mode_frame = ttk.Frame(self, style="Card.TFrame")
        strike_mode_frame.grid(row=2, column=0, sticky="w")
        ttk.Radiobutton(
            strike_mode_frame, text="Strike", variable=self.strike_mode, value="Strike",
            style="Leg.TRadiobutton"
        ).grid(row=0, column=0, padx=(0,8))
        ttk.Radiobutton(
            strike_mode_frame, text="%OTM", variable=self.strike_mode, value="%OTM",
            style="Leg.TRadiobutton"
        ).grid(row=0, column=1)
        # Strike dropdown (populate later from Bloomberg)
        ttk.Label(self, text="Strike:", style="OnCard.TLabel").grid(row=2, column=1, sticky="w", padx=(12,4))
        self.strike_choices: List[str] = ["refresh data"]
        self.strike_combo = ttk.Combobox(self, values=self.strike_choices, state="readonly", width=8)
        self.strike_combo.grid(row=2, column=2, sticky="w", padx=(0,10))
        try:
            self.strike_combo.set("refresh data")
        except Exception:
            pass
        self.strike_combo.bind("<<ComboboxSelected>>", self._on_strike_chosen)
        # Set dropdown menu background to white for consistency
        try:
            self.strike_combo["menu"].config(bg="white")
        except Exception:
            pass
        # %OTM entry
        ttk.Label(self, text="%OTM:", style="OnCard.TLabel").grid(row=2, column=3, sticky="w", padx=(8,4))
        self.pct_otm_var = tk.StringVar()
        self.pct_otm_ent = ttk.Entry(self, textvariable=self.pct_otm_var, width=10)
        self.pct_otm_ent.grid(row=2, column=4, sticky="w")
        self.pct_otm_var.trace_add("write", self._on_pct_otm_changed)
        # Row 2 below: place each directly under its column from row 2
        # Option Price as a combined label (shows N/A until priced)
        self.price_var = tk.StringVar(value="")  # raw numeric value for data/validation
        self.price_label_var = tk.StringVar(value="Option Price: N/A")
        self.price_lbl = ttk.Label(self, textvariable=self.price_label_var, style="OnCard.TLabel")
        self.price_lbl.grid(row=3, column=0, columnspan=2, sticky="w")
        # Root directly below Strike (label at col=1, combo at col=2), matching Strike spacing
        ttk.Label(self, text="Root:", style="OnCard.TLabel").grid(row=3, column=1, sticky="w", padx=(12,4))
        self.root_choices: List[str] = ["refresh data"]
        self.root_combo = ttk.Combobox(self, values=self.root_choices, state="readonly", width=10)
        self.root_combo.grid(row=3, column=2, sticky="w", padx=(0,10))
        try:
            self.root_combo.set("refresh data")
        except Exception:
            pass
        self.root_combo.bind("<<ComboboxSelected>>", self._on_root_chosen)
        try:
            self.root_combo["menu"].config(bg="white")
        except Exception:
            pass
        # Contracts directly below %OTM (label at col=3, entry at col=4), matching %OTM spacing
        ttk.Label(self, text="#Contracts:", style="OnCard.TLabel").grid(row=3, column=3, sticky="w", padx=(8,4))
        self.qty_var = tk.StringVar()                 # signed quantity used in calculations/save
        self.display_qty_var = tk.StringVar()         # UI-only, always positive
        self.qty_ent = ttk.Entry(self, textvariable=self.display_qty_var, width=10)
        self.qty_ent.grid(row=3, column=4, sticky="w")
        # attach a trace that strips the sign visually but applies sign based on buy/sell
        def _qty_sanitize(*_):
            try:
                raw = (self.display_qty_var.get() or "").strip()
                if raw == "":
                     # keep calc var empty too so is_complete() can gate properly
                    self.qty_var.set("")
                    return
                val = abs(int(raw))
                if self.side_var.get() == "SELL":
                    val *= -1
                self.qty_var.set(str(int(val)))
                self.display_qty_var.set(str(abs(int(val))))
            except Exception:
                # do not clobber on bad input; leave current qty_var as-is
                pass
        # sanitize when UI display qty changes
        self.display_qty_var.trace_add("write", _qty_sanitize)
        # also re-apply sign if user flips BUY/SELL
        self.side_var.trace_add("write", lambda *_: _qty_sanitize())
        # Also notify parent if backend qty_var is altered programmatically
        def _qty_backend_changed(*_):
            try:
                self.on_change()
            except Exception:
                pass
        self.qty_var.trace_add("write", _qty_backend_changed)
        # StringVars for stats values (default '-')
        self.stat_finance = tk.StringVar(value="-")
        self.stat_div = tk.StringVar(value="-")
        self.stat_delta = tk.StringVar(value="-")
        self.stat_gamma = tk.StringVar(value="-")
        self.stat_vega = tk.StringVar(value="-")
        self.stat_ivol = tk.StringVar(value="-")
        self.stat_theta = tk.StringVar(value="-")
        # Visual separator between leg inputs and stats
        try:
            ttk.Separator(self, orient="vertical").grid(row=0, column=5, rowspan=4, sticky="ns", padx=(12,12))
        except Exception:
            pass
        # Header row stats (row 0 of parent): Finance Rate, Div Yield
        ttk.Label(self, text="Finance Rt:", style="OnCard.TLabel").grid(row=0, column=6, sticky="w")
        ttk.Label(self, textvariable=self.stat_finance, style="OnCard.TLabel").grid(row=0, column=7, sticky="w", padx=(4,12))
        ttk.Label(self, text="Div Yield:", style="OnCard.TLabel").grid(row=0, column=8, sticky="w")
        ttk.Label(self, textvariable=self.stat_div, style="OnCard.TLabel").grid(row=0, column=9, sticky="w", padx=(4,12))
        # First input row alignment (row 2): Delta, Gamma, Vega
        ttk.Label(self, text="Delta:", style="OnCard.TLabel").grid(row=2, column=6, sticky="w")
        ttk.Label(self, textvariable=self.stat_delta, style="OnCard.TLabel").grid(row=2, column=7, sticky="w", padx=(4,12))
        ttk.Label(self, text="Gamma:", style="OnCard.TLabel").grid(row=2, column=8, sticky="w")
        ttk.Label(self, textvariable=self.stat_gamma, style="OnCard.TLabel").grid(row=2, column=9, sticky="w", padx=(4,12))
        ttk.Label(self, text="Vega:", style="OnCard.TLabel").grid(row=2, column=10, sticky="w")
        ttk.Label(self, textvariable=self.stat_vega, style="OnCard.TLabel").grid(row=2, column=11, sticky="w", padx=(4,12))
        # Second input row alignment (row 3): Ivol, Theta
        ttk.Label(self, text="Ivol Mid:", style="OnCard.TLabel").grid(row=3, column=6, sticky="w")
        ttk.Label(self, textvariable=self.stat_ivol, style="OnCard.TLabel").grid(row=3, column=7, sticky="w", padx=(4,12))
        ttk.Label(self, text="Theta:", style="OnCard.TLabel").grid(row=3, column=8, sticky="w")
        ttk.Label(self, textvariable=self.stat_theta, style="OnCard.TLabel").grid(row=3, column=9, sticky="w", padx=(4,12))
        # Per-leg volatility shock (decimal, e.g. 0.10 for +10%)
        self.vol_shock_leg_var = tk.StringVar()
        ttk.Label(self, text="Vol Shock:", style="OnCard.TLabel").grid(row=0, column=10, sticky="w")
        ttk.Entry(self, textvariable=self.vol_shock_leg_var, width=10).grid(row=0, column=11, sticky="w", padx=(4,12))
        # Ensure extra grid columns don't expand
        for c in range(6, 12):
            self.columnconfigure(c, weight=0)
        # Wiring and initial state
        self.strike_mode.trace_add("write", lambda *_: self._on_strike_mode_changed())
        self._on_strike_mode_changed()  # ensure default Strike mode is applied without a click
        # Any change to qty should notify the parent for add/duplicate button enablement
        self.qty_var.trace_add("write", lambda *_: self.on_change())
 
    def _on_maturity_selected(self, event=None):
        """Single maturity-selection handler.
        Defaults CP to Call, clears displayed price & stats, clears snapshot,
        refreshes strikes/roots, and notifies parent.
        """
        try:
            self.cp_var.set("Call")
        except Exception:
            pass
        self.cp_var.set("Call")
        # to make it closest to ATM
        self.strike_mode.set("%OTM")
        self._on_strike_mode_changed()
        self.set_option_price(None)
        self.clear_stats()
        self.clear_snapshot()
        self._refresh_strikes()
        self._refresh_roots()
        try:
            self.on_change()
        except Exception:
            pass
        self.strike_mode.set("Strike")
        try:
            self.on_change()
        except Exception:
            pass
 
 
    def _on_cp_changed(self):
        """When Call/Put selection changes:
        - clear snapshot and stats
        - clear displayed option price
        - if in %OTM mode, recompute and snap the strike from current %OTM
        - refresh strikes and roots
        - notify parent of change
        """
        try:
            # Clear price, stats, and snapshot
            self.set_option_price(None)
            self.clear_stats()
            self.clear_snapshot()
        except Exception:
            pass
 
        # If working in %OTM mode, recompute the strike based on current %OTM and the new CP
        try:
            if self.strike_mode.get() == "%OTM":
                spot = self._get_spot_float()
                if spot is not None:
                    try:
                        raw = (self.pct_otm_var.get() or "0").replace("%", "").strip()
                        pct = float(raw) if raw != "" else 0.0
                    except Exception:
                        pct = 0.0
                    # This helper should already include the Call/Put sign logic implemented earlier
                    self._snap_strike_to_pct_otm(spot, pct)
        except Exception:
            pass
 
        # Refresh dependent dropdowns
        try:
            self._refresh_strikes()
            self._refresh_roots()
        except Exception:
            pass
 
        # Notify parent/app
        try:
            self.on_change()
        except Exception:
            pass
 
    def _on_strike_chosen(self, event=None):
        """Strike selection handler that also clears current price/stats and snapshot,
        snaps %OTM display, refreshes roots, and notifies parent."""
        self.set_option_price(None)
        self.clear_stats()
        self.clear_snapshot()
        # keep existing behavior of reflecting %OTM when in Strike mode
        self._on_strike_selected()
        self._refresh_roots()
        try:
            self.on_change()
        except Exception:
            pass
 
    def _on_root_chosen(self, event=None):
        """Root selection handler that clears price/stats and snapshot, then notifies parent."""
        self.set_option_price(None)
        self.clear_stats()
        self.clear_snapshot()
        try:
            self.on_change()
        except Exception:
            pass
    def _get_spot_float(self) -> Optional[float]:
        try:
            s = (self.get_spot() or "").strip()
            return float(s)
        except Exception:
            return None
    def _parse_available_strikes(self) -> List[float]:
        vals = self.strike_combo.cget("values") or self.strike_choices or []
        out: List[float] = []
        for v in vals:
            try:
                out.append(float(v))
            except Exception:
                continue
        return out
    def _compute_pct_otm_from_strike(self, spot: float, strike: float) -> float:
        # simple signed %OTM relative to spot; positive when strike above spot
        if spot and spot != 0:
            return (strike / spot - 1.0) * 100.0
        return 0.0
    def _desired_strike_from_pct(self, spot: float, pct: float) -> float:
        """Compute target strike from %OTM.
        For Calls: strike = spot * (1 + pct/100)
        For Puts:  strike = spot * (1 - pct/100)
        """
        try:
            pct_dec = float(pct) / 100.0
        except Exception:
            pct_dec = 0.0
        is_call = (self.cp_var.get() or "Call") == "Call"
        adj = pct_dec if is_call else -pct_dec
        return spot * (1.0 + adj)
    def _snap_strike_to_pct_otm(self, spot: float, pct: float) -> Optional[float]:
        target = self._desired_strike_from_pct(spot, pct)
        strikes = self._parse_available_strikes()
        if not strikes:
            return None
        nearest = min(strikes, key=lambda x: abs(x - target))
        # set the combobox display to the exact string that matches the nearest
        try:
            self.strike_combo.set(f"{nearest:g}")
        except Exception:
            self.strike_combo.set(str(nearest))
        return nearest
    def _on_strike_selected(self):
        # In Strike mode, reflect %OTM based on selected strike and current spot
        if self.strike_mode.get() != "Strike":
            self.on_change()
            return
        spot = self._get_spot_float()
        try:
            strike = float(self.strike_combo.get())
        except Exception:
            strike = None
        if spot and strike:
            pct = self._compute_pct_otm_from_strike(spot, strike)
            # write without triggering recursion noise
            if getattr(self, "_updating_pct", False):
                pass
            else:
                self._updating_pct = True
                try:
                    self.pct_otm_var.set(f"{pct:.2f}")
                finally:
                    self._updating_pct = False
        self.on_change()
    def _on_pct_otm_changed(self, *_):
        # In %OTM mode, snap strike, otherwise ignore user edits (field is read-only then)
        if getattr(self, "_updating_pct", False):
            return
        if self.strike_mode.get() != "%OTM":
            self.on_change()
            return
        spot = self._get_spot_float()
        if spot is None:
            self.on_change()
            return
        try:
            pct = float((self.pct_otm_var.get() or "0").replace("%",""))
        except Exception:
            self.on_change()
            return
        self._snap_strike_to_pct_otm(spot, pct)
        self.on_change()
    def _on_strike_mode_changed(self):
        self._update_strike_mode_visibility()
        # Recompute derived display when switching modes
        if self.strike_mode.get() == "Strike":
            self._on_strike_selected()
        else:
            self._on_pct_otm_changed()
        self.on_change()
    def set_option_price(self, text: Optional[str]):
        """Update displayed option price label and store a raw value.
        - If text is None/empty -> show "Option Price: N/A" and clear stored value
        - Else -> show "Option Price: <value>" and store value
        """
        if text is None or str(text).strip() == "":
            self.price_var.set("")
            try:
                self.price_label_var.set("Option Price: N/A")
            except Exception:
                pass
        else:
            val = str(text)
            self.price_var.set(val)
            try:
                self.price_label_var.set(f"Option Price: {val}")
            except Exception:
                pass
        self.on_change()
    def _update_strike_mode_visibility(self):
        mode = self.strike_mode.get()
        if mode == "Strike":
            # Enable strike dropdown; %OTM shows computed value but is read-only
            try:
                self.strike_combo.configure(state="readonly")
            except Exception:
                pass
            try:
                self.pct_otm_ent.configure(state="readonly")
            except Exception:
                pass
        else:
            # Enable %OTM editing; strike dropdown is disabled (snapped automatically)
            try:
                self.strike_combo.configure(state="disabled")
            except Exception:
                pass
            try:
                self.pct_otm_ent.configure(state="normal")
            except Exception:
                pass
    def set_index(self, i: int):
        self._index = i
        self.title_lbl.configure(text=f"Leg {i}")
    def apply_mode(self, mode: str):
        # Price is a label now; nothing to toggle here
        pass
    def is_complete(self) -> bool:
        if self.cp_var.get() not in ("Call", "Put"):
            return False
        if self.maturity.get().strip() == "":
            return False
        # require a resolved price (set when snapshot arrives)
        if (self.price_var.get() or "").strip() == "":
            return False
        # require a full snapshot payload
        if not self.has_full_snapshot():
            return False
        if self.strike_mode.get() == "Strike":
            return self.strike_combo.get().strip() != ""
        else:
            return self.pct_otm_var.get().strip() != ""
    def set_values(self, cp, maturity, strike, qty, price, strike_mode="Strike", pct_otm="", resolved_strike="",vol_shock_leg=None):
        self.cp_var.set(cp or "Call")
        self.maturity.set(maturity or "")
        self.qty_var.set(qty or "")
        self.set_option_price(price or "")
        self.strike_mode.set(strike_mode or "Strike")
        if vol_shock_leg is not None and hasattr(self, "vol_shock_leg_var"):
            self.vol_shock_leg_var.set(str(vol_shock_leg))
        # Set strike/pct according to mode
        if self.strike_mode.get() == "Strike":
            try:
                self.strike_combo.set(strike or "")
            except Exception:
                self.strike_combo.set(strike or "")
            # Reflect %OTM if we have spot
            self._on_strike_selected()
        else:
            self.pct_otm_var.set(pct_otm or "")
            # Snap strike to supplied %OTM if spot is available
            self._on_pct_otm_changed()
        # keep resolved strike text if provided
        try:
            if hasattr(self, 'resolved_strike') and resolved_strike:
                self.resolved_strike.set(resolved_strike)
        except Exception:
            pass   
        self.on_change()
    def to_dict(self) -> Dict[str, str]:
        d: Dict[str, str] = {
            "type": self.cp_var.get(),
            "maturity": self.maturity.get(),
            "qty": self.qty_var.get(),
            "price": self.price_var.get(),
            "strike_mode": self.strike_mode.get(),
        }
        if self.strike_mode.get() == "Strike":
            d["strike"] = self.strike_combo.get()
            # also expose computed %OTM for completeness if spot is present
            try:
                spot = self._get_spot_float()
                strike = float(self.strike_combo.get())
                if spot and strike:
                    d["pct_otm"] = f"{self._compute_pct_otm_from_strike(spot, strike):.2f}"
            except Exception:
                pass
        else:
            d["pct_otm"] = self.pct_otm_var.get()
            # include current snapped strike if any
            if (self.strike_combo.get() or "").strip():
                d["strike"] = self.strike_combo.get()
        # include selected root if any
        root_sel = (getattr(self, 'root_combo', None).get() if hasattr(self, 'root_combo') else "") or ""
        if root_sel:
            d["root"] = root_sel
        snap = self.get_snapshot()
        if isinstance(snap, dict):
            d["snapshot"] = snap
        return d

class OptionsPnL(tk.Toplevel):
    def __init__(self, master, on_home=None):
        super().__init__(master)
        self._on_home = on_home  # callback to return to launcher
        self.title("Options Strategy P&L")
        self.configure(bg=THEME_BG)
        # Guard to prevent update callbacks from firing before UI is fully built
        self._ui_ready = False
     
        # icon = PhotoImage(file="trend.png")
        # self.iconphoto(True,icon)
        self.minsize(900, 600)
        # Track if a tkcalendar popup is open
        self.calendar_open = False
        # Root grid rows: status, fields, dates, legs, chart
        self.columnconfigure(0, weight=1)
        for r, w in [(0,0), (1,0), (2,0), (3,1), (4,1)]:
            self.rowconfigure(r, weight=w)
        # Add this fine-tuning so equity doesn't expand, legs + chart do:
        self.rowconfigure(3, weight=0)  # equity row: natural height
        self.rowconfigure(4, weight=0)  # legs row: expands (scrolls inside)
        self.rowconfigure(5, weight=0)  # summary row: natural height
        self.rowconfigure(6, weight=1)  # chart row expands
        # State
        self.mode = tk.StringVar(value="NEW")  # "NEW" or "LOAD"
        self.current_maturities = list(MATURITY_CHOICES)
        self.intervals = 100  # default computation grid intervals
 
        # Show earliest maturity
        self.show_earliest_curve_var = tk.BooleanVar(value=True)
 
        # Chart customization options (user-adjustable via dialog)
        self.chart_opts = {
            "show_grid": True,
            "show_legend": True,
            "y_commas": True,
 
            # reference/center line options
            "spot_line": True,
            "spot_line_style": "-.",   # "-", "--", "-.", ":"
            "spot_line_width": 1.25,
            "spot_line_alpha": 0.9,
 
            # axis granularity options
            "x_granularity": 5,   # number of x ticks
            "y_granularity": 5,   # number of y ticks
 
            # center point for the vertical reference line: "spot" or "custom"
            "center_mode": "spot",
            "center_value": "",   # used when center_mode == "custom"
        }
        # UI
        self._init_style()
        self._build_menubar()
        self._build_top_status()
        self._build_primary_inputs()
        self._build_dynamic_dates()
        self._build_equity_section()
        self._build_legs_section()
        self._build_summary_strip()
        self._build_graph_placeholder()
        self._apply_mode_to_legs()
        # Robust exception hook so callback errors don't freeze silently
        self.report_callback_exception = self._tk_exception_hook
        self.bbg = None  # data_class.BloombergClient will be created on demand
        # cache for option chain
        self.chain_raw = None   # list[str] from OPT_CHAIN
        self.chain_tree = None  # parsed nested dict
        self.chain_ticker = None  # remembers which ticker the cached chain belongs to
        self.opt_snapshots = {}  # description -> snapshot dict
 
        # UI is fully constructed; allow change handlers to run
        self._ui_ready = True
        self._chart_win = None
        self._suspend_chart = False
 
        # Chart recompute gating: require explicit Update Data
        self._dirty = False  # when True, chart will show an update-required placeholder
        self.bind("<Return>", lambda e: self._update_data_from_bloomberg())
 
        self.protocol("WM_DELETE_WINDOW", self._on_close)
       
    def _resolve_leg_description(self, leg) -> Optional[str]:
        """From leg selections (maturity, C/P, strike, root), return first matching full description.
        Returns None if anything is missing or not found.
        Accepts either a string or a list from get_descriptions.
        """
        if self.chain_tree is None:
            return None
        try:
            ymd = (leg.maturity.get() or "").strip()
            if not ymd:
                print("[PRICE][DBG] maturity empty; cannot resolve description")
                return None
            right = "C" if (leg.cp_var.get() or "Call") == "Call" else "P"
            strike = (leg.strike_combo.get() or "").strip()
            root = (getattr(leg, 'root_combo', None).get() if hasattr(leg, 'root_combo') else "").strip()
            if not (strike and root):
                print(f"[PRICE][DBG] missing strike/root -> strike={strike!r}, root={root!r}")
                return None
            descs = self.bbg.get_descriptions(self.chain_tree, ymd, right, strike, root)
            # Accept either a string or a list of strings
            if isinstance(descs, str):
                desc = descs.strip()
                return desc if desc else None
            if isinstance(descs, list) and descs:
                return str(descs[0])
            print(f"[PRICE][DBG] get_descriptions returned empty for {ymd} {right} {strike} {root}")
            return None
        except Exception as e:
            print(f"[PRICE][ERR] resolving description failed: {e}")
            return None
    def _update_leg_option_prices(self):
        """For each leg with complete selections, fetch snapshot and set option price.
        Implements normalization and user prompting for missing bid/mid/ask.
        Caches snapshots in self.opt_snapshots keyed by description.
        """
        if self.chain_tree is None or not getattr(self, 'bbg', None):
            return
        # Always refresh snapshot cache on each Update Data click
        self.opt_snapshots = {}
        for leg in getattr(self, 'legs', []):
            try:
                sel_maturity = (leg.maturity.get() or "").strip()
                sel_cp = leg.cp_var.get()
                sel_strike = (leg.strike_combo.get() or "").strip()
                sel_root = (getattr(leg, 'root_combo', None).get() if hasattr(leg, 'root_combo') else "").strip()
                print(f"[PRICE] Leg {getattr(leg, '_index', '?')} selections -> maturity={sel_maturity!r}, CP={sel_cp!r}, strike={sel_strike!r}, root={sel_root!r}")
            except Exception:
                pass
            desc = self._resolve_leg_description(leg)
            print(f"[PRICE] resolved description: {desc}")
            if not desc:
                # no valid selection -> default price 0
                try:
                    leg.set_option_price(None)
                except Exception:
                    pass
                try:
                    leg.clear_stats()
                except Exception:
                    pass
                try:
                    leg.clear_snapshot()
                except Exception:
                    pass
                continue
            try:
                print(f"[INFO] requesting snapshot for: {desc}")
                snap = self.bbg.get_option_snapshot(desc)
                try:
                    # cache a deep copy so we never mutate the original pulled from BBG
                    self.opt_snapshots[desc] = copy.deepcopy(snap)
                    # if you pass it into the leg, pass a copy too
                    leg.set_snapshot(copy.deepcopy(snap))
                except Exception:
                    print(f"[WARNING] Failed to cache a deep copy of snap: {snap}")
                print(f"[SNAPSHOT] fetched for: {desc}")
                print(f"[SNAPSHOT] payload: {snap}")
                # --- Normalize/compute missing bid/mid/ask per rules ---
                def _sf(v):
                    try:
                        if v is None:
                            return None
                        f = float(v)
                        if f != f:  # NaN
                            return None
                        return f
                    except Exception:
                        return None

                bid = _sf(snap.get("PX_BID"))
                mid = _sf(snap.get("PX_MID"))
                ask = _sf(snap.get("PX_ASK"))
                # --- UI diagnostics + epsilon for float equality ---
                ui_logs = []
                def _log(msg):
                    ui_logs.append(msg)
                    print(msg)
                EPS = 1e-9

                # If all three are missing -> prompt for user input; raise message if cancel
                if bid is None and mid is None and ask is None:
                    try:
                        val = simpledialog.askfloat(
                            title="Missing Option Prices",
                            prompt=(
                                "No bid/mid/ask reported for this option.\n\n"
                                f"{desc}\n\n"
                                "Please input a unit price to continue:"
                            ),
                            parent=self,
                            minvalue=0.0,
                        )
                    except Exception:
                        val = None
                    if val is None:
                        # User canceled: mark leg as incomplete and continue to next leg
                        try:
                            leg.set_option_price(None)
                            leg.clear_stats()
                            leg.clear_snapshot()
                        except Exception:
                            pass
                        continue
                    # Store user-entered price as MID only
                    mid = float(val)
                    snap["PX_MID"] = mid

                # If only MID present (no BID/ASK) -> warn but continue
                if mid is not None and bid is None and ask is None:
                    try:
                        messagebox.showwarning(
                            "Only MID available",
                            (
                                "Only PX_MID is available for this option; no BID or ASK were reported.\n\n"
                                f"{desc}\n\nContinuing with MID."
                            ),
                            parent=self,
                        )
                    except Exception:
                        pass
                    _log(f"[UI] Only MID available for {desc}; proceeding with MID={mid}")

                # Handle BID-missing cases with nuance:
                # - If BID is missing and ASK exists:
                #   * If MID is missing: assume BID=0, set MID=(BID+ASK)/2
                #   * If MID is present and MID == ASK: ignore reported MID, set BID=0, recompute MID
                #   * If MID is present and MID != ASK: keep MID as true mid; infer BID = max(0, 2*MID - ASK)
                if bid is None and ask is not None:
                    if mid is None:
                        bid = 0.0
                        snap["PX_BID"] = 0.0
                        mid = (bid + ask) / 2.0
                        snap["PX_MID"] = mid
                        _log(f"[UI] BID missing & MID missing for {desc} → assume BID=0.0, set MID=(BID+ASK)/2={mid}")
                    else:
                        if abs(mid - ask) <= EPS:
                            bid = 0.0
                            snap["PX_BID"] = 0.0
                            mid = (bid + ask) / 2.0
                            snap["PX_MID"] = mid
                            _log(f"[UI] BID missing & MID==ASK ({ask}) for {desc} → ignore MID, set BID=0.0, recompute MID={mid}")
                        else:
                            inferred_bid = max(0.0, 2.0 * mid - ask)
                            bid = inferred_bid
                            snap["PX_BID"] = bid
                            _log(f"[UI] BID missing & MID({mid})!=ASK({ask}) for {desc} → infer BID=max(0,2*MID-ASK)={bid}")

                # If MID is None but have BID and ASK -> compute MID
                if mid is None and (bid is not None) and (ask is not None):
                    mid = (bid + ask) / 2.0
                    snap["PX_MID"] = mid
                    _log(f"[UI] MID missing for {desc} → recompute MID=(BID+ASK)/2={mid}")

                # If ASK is None but have BID and MID -> compute ASK = max(0, 2*MID - BID)
                if (ask is None) and (bid is not None) and (mid is not None):
                    ask = max(0.0, 2.0 * mid - bid)
                    snap["PX_ASK"] = ask
                    _log(f"[UI] ASK missing for {desc} → infer ASK=max(0,2*MID-BID)={ask}")

                # --- Compute display price using clarified BUY/SELL rules ---
                try:
                    qty_val = int(leg.qty_var.get())
                except Exception:
                    qty_val = 1  # default BUY if unspecified

                # Local copies we can mutate
                b = bid
                m = mid
                a = ask

                if qty_val > 0:
                    # BUY: price = (MID + ASK)/2, with fallbacks
                    if (m is not None) and (a is not None):
                        price = (m + a) / 2.0
                        dbg = f"(MID {m} + ASK {a})/2"
                    elif m is not None:
                        price = float(m)
                        dbg = f"MID {m} (fallback)"
                    elif a is not None:
                        price = float(a)
                        dbg = f"ASK {a} (fallback)"
                    elif b is not None:
                        price = float(b)
                        dbg = f"BID {b} (fallback)"
                    else:
                        price = 0.0
                        dbg = "0.0 (no prices)"
                else:
                    # SELL: price = (BID + MID)/2, with fallbacks
                    if (b is not None) and (m is not None):
                        price = (b + m) / 2.0
                        dbg = f"(BID {b} + MID {m})/2"
                    elif m is not None:
                        price = float(m)
                        dbg = f"MID {m} (fallback)"
                    elif b is not None:
                        price = float(b)
                        dbg = f"BID {b} (fallback)"
                    elif a is not None:
                        price = float(a)
                        dbg = f"ASK {a} (fallback)"
                    else:
                        price = 0.0
                        dbg = "0.0 (no prices)"

                _log(f"[UI] computed option price {dbg} -> {price:.4f}")

                # Save normalized snapshot back to the leg
                try:
                    leg.set_snapshot(copy.deepcopy(snap))
                except Exception:
                    pass
                leg.set_option_price(f"{price:.2f}")
                try:
                    leg.set_stats_from_snapshot(snap)
                except Exception:
                    pass
            except Exception as e:
                # On failure, set to 0 and continue
                print(f"[SNAPSHOT][ERR] {e}")
                try:
                    leg.set_option_price(None)
                except Exception:
                    pass
                try:
                    leg.clear_stats()
                except Exception:
                    pass
                try:
                    leg.clear_snapshot()
                except Exception:
                    pass
    def _apply_maturities_to_legs(self, maturities):
        self.current_maturities = list(maturities)
        print("[DBG] _apply_maturities_to_legs applying:", self.current_maturities)
        for leg in getattr(self, 'legs', []):
            try:
                leg.set_maturities(self.current_maturities)
                try:
                    leg._refresh_strikes()
                    try:
                        leg._refresh_roots()
                        try:
                            self._maybe_autoselect_strike(leg)
                        except Exception:
                            pass
                    except Exception:
                        pass
                except Exception:
                    pass
            except Exception as e:
                print("[DBG] set_maturities failed on a leg:", e)
    def _get_strikes_for(self, maturity: str, cp_label: str) -> list[str]:
        """Return strikes list for a given maturity and CP label using cached chain.
        Defaults:
          - If chain not fetched -> ["refresh data"]
          - If maturity empty   -> ["select maturity"]
        """
        if self.chain_tree is None:
            return ["refresh data"]
        if not (maturity or "").strip():
            return ["select maturity"]
        right = "C" if (cp_label or "Call") == "Call" else "P"
        try:
            strikes = self.bbg.list_strikes(self.chain_tree, maturity.strip(), right)
            return strikes if strikes else ["(none)"]
        except Exception:
            return ["(none)"]
    def _get_roots_for(self, maturity: str, cp_label: str, strike: str) -> list[str]:
        """Return list of underlyings (roots) for maturity/right/strike using cached chain.
        Placeholders:
        - No chain -> ["refresh data"]
        - No maturity -> ["select maturity"]
        - No strike -> ["select strike"]
        """
        if self.chain_tree is None:
            return ["refresh data"]
        if not (maturity or "").strip():
            return ["select maturity"]
        if not (strike or "").strip():
            return ["select strike"]
        right = "C" if (cp_label or "Call") == "Call" else "P"
        try:
            roots = self.bbg.list_underlyings(self.chain_tree, maturity.strip(), right, str(strike).strip())
            return roots if roots else ["(none)"]
        except Exception:
            return ["(none)"]
    # ----------------------
    # Styling / ttk theme
    # ----------------------
    def _init_style(self):
        _theme_init_style(self)
    # ----------------------
    # Menubar
    # ----------------------
    def _build_menubar(self):
        is_mac = platform.system() == "Darwin"
        menubar = tk.Menu(self)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Go to Home…", command=self._go_home)
        file_menu.add_separator()
        file_menu.add_command(label="New Strategy", accelerator="Cmd+N" if is_mac else "Ctrl+N", command=self._menu_new)
        file_menu.add_command(label="Load Strategy…", accelerator="Cmd+O" if is_mac else "Ctrl+O", command=self._menu_load)
        file_menu.add_command(label="Save…", accelerator="Cmd+S" if is_mac else "Ctrl+S", command=self._menu_save)
        file_menu.add_separator()
        file_menu.add_command(label="Set Computation Intervals…", command=self._menu_set_intervals)
        file_menu.add_separator()
        def _toggle_earliest_curve():
            # just refresh the chart using the new toggle state
            self._refresh_chart()
 
        file_menu.add_checkbutton(
            label="Show Earliest Maturity Curve",
            variable=self.show_earliest_curve_var,
            onvalue=True, offvalue=False,
            command=_toggle_earliest_curve
        )
        file_menu.add_separator()
        file_menu.add_command(label="Quit", accelerator="Cmd+Q" if is_mac else "Ctrl+Q", command=self._menu_quit)
        menubar.add_cascade(label="File", menu=file_menu)
        edit_menu = tk.Menu(menubar, tearoff=0)
        edit_menu.add_command(label="Clear Dates", command=self._menu_clear_dates)
        edit_menu.add_command(label="Reset Legs", command=self._menu_reset_legs)
        menubar.add_cascade(label="Edit", menu=edit_menu)
        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="About", command=lambda: messagebox.showinfo("About", "Options Strategy P&L UI\nTkinter scaffold"))
        # Help menu for information
        menubar.add_cascade(label="Help", menu=help_menu)
        # Diagnostics menu for debugging
        diag_menu = tk.Menu(menubar, tearoff=0)
        diag_menu.add_command(label="Environment Info…", command=self._menu_diag_env_info)
        diag_menu.add_command(label="Calendar Sanity Window…", command=self._menu_diag_calendar_window)
        diag_menu.add_command(label="Print Current Dates to Console", command=self._menu_diag_print_dates)
        menubar.add_cascade(label="Diagnostics", menu=diag_menu)
        # Attach to root window
        self.config(menu=menubar)
        print("[INFO] Menubar built")
 
    def _go_home(self):
        """Return to the launcher without closing or hiding this tool."""
        if callable(getattr(self, "_on_home", None)):
            try:
                self._on_home()  # bring launcher to front; keep this window visible
            except Exception:
                pass

    # ----------------------
    # Status bar (mode text)
    # ----------------------
    def _build_top_status(self):
        bar = ttk.Frame(self)
        bar.grid(row=0, column=0, sticky="ew", padx=20, pady=(16,8))
        bar.columnconfigure(0, weight=1)
        bar.columnconfigure(1, weight=0)
        bar.columnconfigure(2, weight=0)
        self.status_label = ttk.Label(bar, text=self._mode_text(), style="MAIN.TLabel")
        self.status_label.grid(row=0, column=0, sticky="w")
        # Button to (re)open the chart window if it was closed
        self.show_chart_btn = ttk.Button(bar, text="Show Chart", command=self._ensure_chart_window)
        self.show_chart_btn.grid(row=0, column=1, sticky="e", padx=(0,8))
        # Add Update Data button to fetch latest price from Bloomberg for the current ticker
        self.update_btn = ttk.Button(bar, text="Update Data", style="Accent.TButton", command=self._update_data_from_bloomberg)
        self.update_btn.grid(row=0, column=2, sticky="e")
    def _normalize_bbg_ticker(self, s: str) -> str:
        """Heuristics: if user types just 'AAPL', try 'AAPL US Equity'.
        If 'AAPL Equity', insert 'US' -> 'AAPL US Equity'.
        Leave Index/Curncy/Comdty codes alone.
        """
        s = (s or "").strip()
        if not s:
            return s
        su = s.upper()
        # If it's already using a non-Equity yellow key, don't touch
        if su.endswith(" INDEX") or su.endswith(" CURNCY") or su.endswith(" COMDTY") or su.endswith(" GOVT") or su.endswith(" MUNI") or su.endswith(" CORP"):
            return s
        # If it already looks like '<SYM> <CNTRY> Equity', leave it
        parts = s.split()
        if len(parts) >= 3 and parts[-1].lower() == "equity" and len(parts[-2]) in (1,2,3):
            return s
        # If it is '<SYM> Equity' -> inject 'US'
        if len(parts) == 2 and parts[1].lower() == "equity":
            return f"{parts[0]} US Equity"
        # If single token like 'AAPL' -> assume US Equity
        if len(parts) == 1:
            return f"{parts[0]} US Equity"
        # Otherwise, return as-is
        return s
    def _update_data_from_bloomberg(self):
        """Fetch latest PX_LAST for the current ticker using data_class.BloombergClient and update the cash equity price field."""
      
        # Block updates in LOAD mode
        if self.mode.get() == "LOAD":
            print("[UPDATE] Ignored: Update Data is disabled in LOAD mode.")
            return
      
        ticker = (self.ticker_var.get() or "").strip()
        if not ticker:
            messagebox.showwarning("Missing ticker", "Please enter a ticker (e.g., 'AAPL US Equity') before updating.")
            return
        orig_ticker = ticker
        ticker = self._normalize_bbg_ticker(ticker)
        if ticker != orig_ticker:
            try:
                self.ticker_var.set(ticker)
            except Exception:
                pass
        # Suspend chart refreshes while we update data to avoid duplicate popouts
        self._suspend_chart = True
        # Disable button during fetch
        try:
            self.update_btn.configure(state=tk.DISABLED)
        except Exception:
            pass
        self.config(cursor="watch")
        self.update_idletasks()
        print("[UPDATE] Update Data clicked")
        try:
            # Ensure a single shared Bloomberg client
            self._ensure_bbg()
            # 1) Fetch spot and display it (always refresh price)
            px_int = self.bbg.get_equity_px_mid(ticker)
            self.set_equity_price(str(px_int))
            # 2) Pull/Cache option chain only when ticker changes or cache is empty
            need_chain = (self.chain_tree is None) or (self.chain_ticker != ticker)
            if need_chain:
                print(f"[INFO] Fetching new chain for {ticker}")
                # Fetch and parse chain, then remember which ticker it's for
                self.chain_raw = self.bbg.get_opt_chain_descriptions(ticker)
                self.chain_tree = self.bbg.parse_opt_chain_descriptions(self.chain_raw)
                self.chain_ticker = ticker
            else:
                print(f"[INFO] Using cached chain for {ticker}")
                # Using cached chain for the same ticker
                pass
            # 3) Derive maturities from cached/updated chain and update leg dropdowns
            if self.chain_tree:
                maturities = self.bbg.list_maturities(self.chain_tree)
                self._apply_maturities_to_legs(maturities)
                # 4) With selections in place, fetch option snapshots and update prices
                self._update_leg_option_prices()
            # 5) Warn if any legs are missing contract quantities
            self._validate_leg_warning()
        except Exception as e:
            messagebox.showerror("Bloomberg Update Failed", str(e))
        finally:
            # Re-enable chart refreshes and do one consolidated refresh
            self._suspend_chart = False
            # Clear dirty state so chart can recompute now
            self._dirty = False
            try:
                self._refresh_chart()
            except Exception:
                pass
            try:
                self.update_btn.configure(state=tk.NORMAL)
            except Exception:
                pass
            self.config(cursor="")
            self.update_idletasks()
    def _ensure_bbg(self):
        """Create a BloombergClient once and reuse it."""
        if getattr(self, 'bbg', None) is None:
            self.bbg = BloombergClient()
    def _on_vol_shock_term_change(self):
        """When the global term shock changes:
        - If non-empty: set every leg's vol_shock to this value and make those entries read-only
        - If empty: make per-leg vol_shock editable again (keep the current per-leg values)
        Then refresh chart/summary.
        """
        try:
            val_txt = (self.vol_shock_term_var.get() or "").strip()
            has_val = (val_txt != "")
 
            # Normalize UI like Min/Max (e.g., "10" -> "10%")
            try:
                self._format_percent_var(self.vol_shock_term_var)
                val_txt = (self.vol_shock_term_var.get() or "").strip()
            except Exception:
                pass
 
            for lf in getattr(self, 'legs', []):
                if hasattr(lf, 'vol_shock_leg_var') and lf.vol_shock_leg_var is not None:
                    if has_val:
                        # Push the same percent string down to leg UIs
                        try:
                            lf.vol_shock_leg_var.set(val_txt)
                        except Exception:
                            pass
                    else:
                        # Clear per-leg UI field
                        try:
                            lf.vol_shock_leg_var.set("")
                        except Exception:
                            pass
 
                # Toggle read-only state on the leg entry
                self._set_leg_vol_shock_readonly(lf, readonly=has_val)
 
            # Require explicit Update Data after term shock changes
            self._mark_dirty_and_show_update_placeholder()
            self._update_summary()
        except Exception:
            pass
    def _set_leg_vol_shock_readonly(self, leg, *, readonly: bool):
        """Best-effort: set the per-leg vol shock entry widget to readonly / editable.
        Supports either a dedicated setter on the leg or common attribute names.
        """
        try:
            # If LegFrame exposes a method, prefer that.
            if hasattr(leg, 'set_vol_shock_readonly') and callable(getattr(leg, 'set_vol_shock_readonly')):
                try:
                    leg.set_vol_shock_readonly(bool(readonly))
                    return
                except Exception:
                    pass
 
            # Otherwise try to find an Entry widget with common names.
            entry = None
            for name in ('vol_shock_leg_entry', 'vol_shock_entry', 'vol_entry', 'shock_entry'):
                entry = getattr(leg, name, None)
                if entry is not None:
                    break
 
            if entry is not None:
                try:
                    if readonly:
                        entry.state(['readonly'])
                    else:
                        entry.state(['!readonly'])
                except Exception:
                    try:
                        entry.configure(state=('readonly' if readonly else 'normal'))
                    except Exception:
                        pass
        except Exception:
            pass

    def _widen_chart_popout(self, width: int = 1200, min_width: int = 800, min_height: int = 600):
        """Widen the chart pop-out window only. Prefers ChartWidget.ensure_wide_parent
        if available; falls back to resizing the popout Toplevel directly."""
        try:
            win = getattr(self, "_chart_win", None)
            if not win or not tk.Toplevel.winfo_exists(win):
                return
            # Prefer the chart widget helper if present
            chart = getattr(self, "_chart_widget", None)
            if chart is not None and hasattr(chart, "ensure_wide_parent") and callable(chart.ensure_wide_parent):
                try:
                    chart.ensure_wide_parent(width=width, min_width=min_width, min_height=min_height)
                    return
                except Exception:
                    pass
            # Fallback: set geometry/minsize on the popout toplevel directly
            try:
                win.update_idletasks()
            except Exception:
                pass
            try:
                cur_h = int(win.winfo_height() or 0)
            except Exception:
                cur_h = 0
            h = max(cur_h, min_height)
            try:
                win.geometry(f"{int(width)}x{h}")
            except Exception:
                pass
            try:
                win.minsize(int(min_width), int(min_height))
            except Exception:
                pass
        except Exception:
            pass

    def _on_close(self):
        """Gracefully close Bloomberg client and exit this tool window."""
        try:
            if getattr(self, 'bbg', None) is not None:
                try:
                    self.bbg.close()
                except Exception:
                    pass
        finally:
            try:
                if getattr(self, "_chart_win", None) and tk.Toplevel.winfo_exists(self._chart_win):
                    self._chart_win.destroy()
            except Exception:
                pass
            try:
                self.destroy()
            finally:
                # Return to launcher (home) if available
                if callable(getattr(self, "_on_home", None)):
                    try:
                        self._on_home()
                    except Exception:
                        pass
    def _mode_text(self) -> str:
        return f"Strategy Mode: {self.mode.get()}"
    def _update_mode_label(self):
        self.status_label.configure(text=self._mode_text())
    def _format_percent_var(self, var: tk.StringVar):
        """Format an Entry StringVar as a percentage with 1 decimal place (e.g., '12.3%').
        Accepts input with or without trailing '%'. Empty stays empty.
        If parsing fails, clears the field so the user can re-enter.
        """
        try:
            raw = (var.get() or "").strip()
            if raw == "":
                return
            if raw.endswith("%"):
                raw = raw[:-1].strip()
            val = float(raw)
            var.set(f"{val:.1f}%")
        except Exception:
            var.set("")
    @staticmethod
    def _parse_float_safe(s: str, default: float = 0.0) -> float:
        try:
            return float((s or "").strip())
        except Exception:
            return default
    @staticmethod
    def _parse_percent_to_decimal(s: str, default: float = 0.0) -> float:
        try:
            raw = (s or "").strip()
            if raw.endswith("%"):
                raw = raw[:-1]
            return float(raw) / 100.0
        except Exception:
            return default
        
    def _get_total_premium_override(self) -> Optional[float]:
        """
        Return the Total Premium Override as a float if the user entered one,
        otherwise None. Accepts plain numbers or numbers with commas. Empty -> None.
        """
        try:
            txt = (self.total_prem_override_var.get() or "").strip()
        except Exception:
            return None
        if not txt:
            return None
        try:
            return float(txt.replace(",", ""))
        except Exception:
            return None
    # ----------------------
    # Row: Ticker / Max / Min
    # ----------------------
    def _build_primary_inputs(self):
        row = ttk.Frame(self)
        # Add vertical padding below this row to match the gap between equity and legs
        row.grid(row=1, column=0, sticky="ew", padx=20, pady=(0,10))
        for c in range(6):
            row.columnconfigure(c, weight=1, uniform="x")
        def labeled_entry(parent, label_text, col):
            ttk.Label(parent, text=label_text+":").grid(row=0, column=col, sticky="w", padx=(0,6))
            ent = ttk.Entry(parent, width=14)
            ent.grid(row=1, column=col, sticky="ew", padx=(0,12))
            return ent
        self.ticker_var = tk.StringVar()
        self.max_var = tk.StringVar(value=10)
        self.min_var = tk.StringVar(value=-10)
        self.eq_price_var = tk.StringVar()
        self.eq_qty_var = tk.StringVar()
        self.ticker_entry = labeled_entry(row, "Ticker", 0)
        self.ticker_entry.configure(textvariable=self.ticker_var)
      
        self.eq_qty_var.set("0")
        self.max_entry = labeled_entry(row, "Equity Scenerio Max", 1)
        self.max_entry.configure(textvariable=self.max_var)
        self.min_entry = labeled_entry(row, "Equity Scenerio Min", 2)
        self.min_entry.configure(textvariable=self.min_var)
        # Override total premium entry
        self.total_prem_override_var = tk.StringVar()
        self.total_prem_entry = labeled_entry(row, "Total Premium Override", 3)
        self.total_prem_entry.configure(textvariable=self.total_prem_override_var)
        # --- Term Volatility Shock (global override) ---
        self.vol_shock_term_var = tk.StringVar()
        self.vol_term_entry = ttk.Entry(row, width=14, textvariable=self.vol_shock_term_var)
        ttk.Label(row, text="Term Volatility Shock:").grid(row=0, column=4, sticky="w", padx=(0,6))
        self.vol_term_entry.grid(row=1, column=4, sticky="ew", padx=(0,12))
 
        # When the global term shock changes: format as percent and propagate to legs
        def _term_shock_ui_change(*_):
            try:
                # Normalize like Min/Max: show "10%" (no hidden decimal caching)
                self._format_percent_var(self.vol_shock_term_var)
            except Exception:
                pass
            try:
                # Push down to legs + refresh
                self._on_vol_shock_term_change()
            except Exception:
                pass
 
        try:
            self.vol_shock_term_var.trace_add("write", _term_shock_ui_change)
        except Exception:
            pass
 
        def _fmt2(var: tk.StringVar):
            try:
                raw = (var.get() or "").strip()
                if raw == "":
                    return
                var.set(f"{float(raw):.2f}")
            except Exception:
                var.set("")
        self.total_prem_entry.bind("<FocusOut>", lambda e: _fmt2(self.total_prem_override_var))
        self.total_prem_entry.bind("<Return>",   lambda e: _fmt2(self.total_prem_override_var))
    
        try:
            self.total_prem_override_var.trace_add("write", lambda *_: self._update_summary())
        except Exception:
            pass

        # Auto-format Max/Min as percentages (1 decimal) on blur or Return
        self.max_entry.bind("<FocusOut>", lambda e: self._format_percent_var(self.max_var))
        self.max_entry.bind("<Return>",   lambda e: self._format_percent_var(self.max_var))
        self.min_entry.bind("<FocusOut>", lambda e: self._format_percent_var(self.min_var))
        self.min_entry.bind("<Return>",   lambda e: self._format_percent_var(self.min_var))
    # --------------------------------
    # Dynamic date entry row behavior
    # --------------------------------
    def _build_dynamic_dates(self):
        wrap = ttk.Frame(self)
        wrap.grid(row=2, column=0, sticky="ew", padx=20, pady=(0,8))
        wrap.columnconfigure(0, weight=1)
        wrap.columnconfigure(1, weight=0)
        self.dates_frame = ttk.Frame(wrap, style="Card.TFrame")
        self.dates_frame.grid(row=0, column=0, sticky="ew")
        for i in range(1, 9):
            self.dates_frame.columnconfigure(i, weight=1)
        # Insert the label inside the dates_frame (card)
        ttk.Label(self.dates_frame, text="Scenario Dates:", style="LegTitle.TLabel").grid(row=0, column=0, sticky="w", padx=(12,0), pady=(0,0))
        # Buttons to manually add/delete the rightmost date
        btns = ttk.Frame(wrap)
        btns.grid(row=0, column=2, sticky="w", padx=(8,0))
        self.add_date_btn = ttk.Button(btns, text="Add Date", style="Accent.TButton", command=self._btn_add_date)
        self.add_date_btn.grid(row=0, column=0, padx=(0,6))
        self.del_date_btn = ttk.Button(btns, text="Delete Date", style="Danger.TButton", command=self._btn_del_date)
        self.del_date_btn.grid(row=0, column=1)
        self.date_vars: List[tk.StringVar] = []
        self.date_entries: List[DateField] = []   # was List[DateEntry]
        self._add_date_box()
        self._update_date_buttons_state()
    def _add_date_box(self, value: str = ""):
        var = tk.StringVar(value=value)
        df = DateField(self.dates_frame, textvariable=var, on_prev=self._date_prev, on_next=self._date_next)
        col = len(self.date_entries)+1
        df.grid(row=0, column=col, padx=(8 if col > 0 else 12, 8), pady=12, sticky="ew")
        self.date_vars.append(var)
        self.date_entries.append(df)
    def _date_prev(self, field_widget):
        """Focus the previous DateField entry if it exists."""
        try:
            idx = self.date_entries.index(field_widget)
            if idx > 0:
                self.date_entries[idx-1].entry.focus_set()
        except ValueError:
            pass
    def _date_next(self, field_widget):
        """Focus the next DateField entry if it exists."""
        try:
            idx = self.date_entries.index(field_widget)
            if idx < len(self.date_entries) - 1:
                self.date_entries[idx+1].entry.focus_set()
        except ValueError:
            pass
    def _btn_add_date(self):
        # Add a new blank DateEntry at the end
        self._add_date_box("")
        self._update_date_buttons_state()
    def _btn_del_date(self):
        # Delete the rightmost date, but keep at least one
        if len(self.date_entries) > 1:
            self._remove_last_date_box()
        self._update_date_buttons_state()
    def _update_date_buttons_state(self):
        # Always allow adding; disable delete when only one date remains
        can_delete = len(self.date_entries) > 1
        self.del_date_btn.configure(state=(tk.NORMAL if can_delete else tk.DISABLED))
    def _remove_last_date_box(self):
        if not self.date_entries:
            return
        widget = self.date_entries.pop()
        self.date_vars.pop()
        widget.destroy()
    def _validate_date(self, var: tk.StringVar) -> bool:
        val = var.get().strip()
        if val == "":
            return True
        try:
            datetime.strptime(val, "%Y-%m-%d")
            return True
        except ValueError:
            messagebox.showerror("Invalid Date", f"Date '{val}' must be in YYYY-MM-DD format")
            var.set("")
            return False
    
    # ----------------------
    # Equity section
    # ----------------------
    def _build_equity_section(self):
        wrap = ttk.Frame(self)
        wrap.grid(row=3, column=0, sticky="ew", padx=20, pady=(0,8))
        wrap.columnconfigure(0, weight=1)
        # Card frame that contains both the title and the inputs
        card = ttk.Frame(wrap, style="Card.TFrame", padding=8)
        card.grid(row=0, column=0, sticky="ew")
        for c in range(4):
            card.columnconfigure(c, weight=0)
        ttk.Label(card, text="Cash Equity Position:", style="LegTitle.TLabel").grid(row=0, column=0, sticky="w", padx=(0,18), pady=(0,0))
        # Inputs row
        ttk.Label(card, text="Price:", style="OnCard.TLabel").grid(row=0, column=1, sticky="w", padx=(0,2))
        self.eq_price_entry = ttk.Entry(card, textvariable=self.eq_price_var, state="readonly")
        self.eq_price_entry.grid(row=0, column=2, sticky="ew", padx=(0,6))
        ttk.Label(card, text="Quantity:", style="OnCard.TLabel").grid(row=0, column=3, sticky="w", padx=(0,2))
        ttk.Entry(card, textvariable=self.eq_qty_var).grid(row=0, column=4, sticky="ew", padx=(0,6))
        # Update summary whenever equity fields change
        self.eq_price_var.trace_add("write", self._on_strategy_change)
        self.eq_qty_var.trace_add("write", self._on_strategy_change)
 
    # ----------------------
    # Legs section
    # ----------------------
 
    def _build_legs_section(self):
        # A scrollable legs area that never grows into other sections
        outer = ttk.Frame(self)
        outer.grid(row=4, column=0, sticky="ew", padx=20, pady=(2,6))
        # Only the scroll area row expands; controls row stays natural height
        outer.rowconfigure(0, weight=0)
        outer.columnconfigure(0, weight=1)
        # ---- Scrollable viewport (Canvas + inner frame) ----
        self.legs_canvas = tk.Canvas(
            outer,
            height=300,                  # visible height cap; tweak if you want more/less
            highlightthickness=0,
            bg=THEME_SURFACE,
            bd=0,
        )
        self.legs_canvas.grid(row=0, column=0, sticky="nsew")
        self.legs_scroll = ttk.Scrollbar(outer, orient="vertical", command=self.legs_canvas.yview)
        self.legs_scroll.grid(row=0, column=1, sticky="ns", padx=(6,0))
        self.legs_canvas.configure(yscrollcommand=self.legs_scroll.set)
        # Inner holder where LegFrame widgets live
        self.legs_inner = ttk.Frame(self.legs_canvas, style="Card.TFrame")
        self.legs_window = self.legs_canvas.create_window((0, 0), window=self.legs_inner, anchor="nw")
        # Make inner frame follow canvas width
        def _sync_inner_width(event=None):
            self.legs_canvas.itemconfigure(self.legs_window, width=self.legs_canvas.winfo_width())
        self.legs_canvas.bind("<Configure>", _sync_inner_width)
        # Update scrollregion whenever inner size changes
        def _update_scrollregion(event=None):
            self.legs_canvas.configure(scrollregion=self.legs_canvas.bbox("all"))
        self.legs_inner.bind("<Configure>", _update_scrollregion)
        # Mouse-wheel support (Mac/Win/Linux)
        self.legs_canvas.bind_all("<MouseWheel>", self._on_legs_mousewheel, add=True)
        self.legs_canvas.bind_all("<Button-4>", self._on_legs_mousewheel, add=True)  # Linux up
        self.legs_canvas.bind_all("<Button-5>", self._on_legs_mousewheel, add=True)  # Linux down
        # --- Controls row (below the scroll area)
        controls = ttk.Frame(outer)
        controls.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8,0))
        controls.columnconfigure(0, weight=1)
        btns = ttk.Frame(controls)
        btns.grid(row=0, column=0)
        self.add_leg_btn = ttk.Button(btns, text="Add leg", style="Accent.TButton", command=self._add_leg)
        self.add_leg_btn.grid(row=0, column=0, padx=(0,8))
        self.dup_leg_btn = ttk.Button(btns, text="Duplicate leg", style="Accent.TButton", command=self._duplicate_last_leg)
        self.dup_leg_btn.grid(row=0, column=1, padx=(0,8))
        self.del_leg_btn = ttk.Button(btns, text="Delete leg", style="Danger.TButton", command=self._delete_leg)
        self.del_leg_btn.grid(row=0, column=2)
        # Data structures & first leg
        self.legs: List[LegFrame] = []
        self._add_leg()
        self._update_delete_button_state()
        self._update_add_leg_button_state()
        self._update_duplicate_button_state()
    def _add_leg(self):
        # if self.legs and not self.legs[-1].is_complete():
        #     messagebox.showwarning("Incomplete", "Fill out the current leg before adding a new one.")
        #     return
        idx = len(self.legs) + 1
        leg = LegFrame(
            self.legs_inner,
            index=idx,
            get_mode=lambda: self.mode.get(),
            get_spot=lambda: self.eq_price_var.get(),
            get_strikes=lambda maturity, cp_label: self._get_strikes_for(maturity, cp_label),
            get_roots=lambda maturity, cp_label, strike: self._get_roots_for(maturity, cp_label, strike),
            on_change=self._on_leg_change
        )
        leg.grid(sticky="ew", pady=(0,10))
        try:
            leg.set_maturities(self.current_maturities)
        except Exception:
            pass
        self.legs.append(leg)
        self._renumber_legs()
        self._apply_mode_to_legs()
        self._update_delete_button_state()
        self._update_add_leg_button_state()
        self._update_legs_scrollregion()
        self._update_duplicate_button_state()
    def _delete_leg(self):
        if len(self.legs) <= 1:
            return
        leg = self.legs.pop()
        leg.destroy()
        self._renumber_legs()
        self._update_delete_button_state()
        self._update_add_leg_button_state()
        self._update_legs_scrollregion()
        self._update_duplicate_button_state()
    def _duplicate_last_leg(self):
        if not self.legs:
            return
        src = self.legs[-1]
        if not src.is_complete():
            messagebox.showwarning("Incomplete", "Complete the current leg before duplicating.")
            return
        # Capture from source
        d = src.to_dict()
        cp = d.get("type", "Call")
        maturity = d.get("maturity", "")
        qty = d.get("qty", "")
        price = d.get("price", "")
        strike_mode = d.get("strike_mode", "Strike")
        strike = d.get("strike", "")
        pct_otm = d.get("pct_otm", "")
        resolved = d.get("resolved_strike", "")
        vol_shock_leg = d.get("vol_shock_leg", "")
        # Add new leg and set values
        self._add_leg()
        tgt = self.legs[-1]
 
        # Capture source qty early (string form to preserve sign/format)
        try:
            qty_src = src.qty_var.get()
        except Exception:
            qty_src = str(d.get("qty", ""))
 
        # Populate all other fields (qty may be overridden by leg defaults later)
        tgt.set_values(
            cp=cp,
            maturity=maturity,
            strike=strike,
            qty=qty,  # keep for compatibility; we will enforce qty_src below
            price=price,
            strike_mode=strike_mode,
            pct_otm=pct_otm,
            resolved_strike=resolved,
            vol_shock_leg=vol_shock_leg,
        )
 
        # Robustly apply the exact contract size from the source leg.
        def _apply_qty_and_refresh():
            try:
                tgt.qty_var.set(qty_src)
                print(f"qty: {qty_src}")
            except Exception:
                print(f"_apply_qty_and_refresh failed (1) with qty: {qty_src}")
                pass
            try:
                self._on_leg_change()
            except Exception:
                print(f"_apply_qty_and_refresh failed (2) with qty: {qty_src}")
                pass
 
        # Apply immediately and once more after idle to win any late widget updates
        _apply_qty_and_refresh()
        try:
            self.after_idle(_apply_qty_and_refresh)
            self._on_leg_change()
        except Exception:
            pass
        self._update_add_leg_button_state()
        self._update_summary()
    def _renumber_legs(self):
        for i, leg in enumerate(self.legs, start=1):
            leg.set_index(i)
    def _update_delete_button_state(self):
        state = tk.NORMAL if len(self.legs) > 1 else tk.DISABLED
        self.del_leg_btn.configure(state=state)
    def _update_add_leg_button_state(self):
        pass
        # ok = True if not self.legs else self.legs[-1].is_complete()
        # self.add_leg_btn.configure(state=(tk.NORMAL if ok else tk.DISABLED))
    def _update_duplicate_button_state(self):
        ok = True if (self.legs and self.legs[-1].is_complete()) else False
        self.dup_leg_btn.configure(state=(tk.NORMAL if ok else tk.DISABLED))
    def _update_legs_scrollregion(self):
        # Safely recompute the scrollable region
        try:
            self.legs_canvas.configure(scrollregion=self.legs_canvas.bbox("all"))
        except Exception:
            pass
    def _on_legs_mousewheel(self, event):
        # Cross-platform scrolling
        if getattr(event, 'num', None) == 4:
            delta = 1
        elif getattr(event, 'num', None) == 5:
            delta = -1
        else:
            # On Mac/Win this is usually ±120 per “tick”; trackpads vary
            delta = int(event.delta / 120) if event.delta else 0
        try:
            self.legs_canvas.yview_scroll(-delta, "units")
        except Exception:
            pass
    def _apply_mode_to_legs(self):
        mode = self.mode.get()
        for leg in self.legs:
            leg.apply_mode(mode)
        # Enable Update Data only in NEW mode; disable in LOAD mode
        try:
            if mode == "LOAD":
                self.update_btn.configure(state=tk.DISABLED)
            else:
                self.update_btn.configure(state=tk.NORMAL)
        except Exception:
            pass
        self._update_mode_label()
    def _on_leg_change(self):
        # if not getattr(self, "_ui_ready", False):
        #     return
        # Try to auto-select a strike for any leg that has a maturity but no strike yet.
        try:
            for lf in getattr(self, 'legs', []):
                self._maybe_autoselect_strike(lf)
        except Exception:
            pass
        self._update_add_leg_button_state()
        self._update_duplicate_button_state()
        # Do not recompute chart on every keystroke; require Update Data
        self._mark_dirty_and_show_update_placeholder()
        self._update_summary()
   
    # ----------------------
    # Summary Strip
    # ----------------------
   
    def _build_summary_strip(self):
        # Row right before the chart (chart is row=6; summary in row=5)
        wrap = ttk.Frame(self)
        # wrap.grid(row=5, column=0, sticky="ew", padx=20, pady=(0,8))
        wrap.columnconfigure(0, weight=1)
        card = ttk.Frame(wrap, style="Card.TFrame", padding=10)
        card.grid(row=0, column=0, sticky="ew")
        for c in range(10):
            card.columnconfigure(c, weight=1)
        # ttk.Label(card, text="Summary:", style="LegTitle.TLabel").grid(row=0, column=0, sticky="w")
        # ttk.Label(card, text="Total Premium:", style="OnCard.TLabel").grid(row=0, column=1, sticky="w")
        self.sum_premium_var = tk.StringVar(value="-")
        # ttk.Label(card, textvariable=self.sum_premium_var, style="OnCard.TLabel").grid(row=0, column=2, sticky="w")
        # ttk.Label(card, text="Equity Exposure:", style="OnCard.TLabel").grid(row=0, column=3, sticky="w")
        self.sum_equity_var = tk.StringVar(value="-")
        # ttk.Label(card, textvariable=self.sum_equity_var, style="OnCard.TLabel").grid(row=0, column=4, sticky="w")
        # ttk.Label(card, text="# Legs:", style="OnCard.TLabel").grid(row=0, column=5, sticky="w")
        self.sum_legs_var = tk.StringVar(value="0")
        # ttk.Label(card, textvariable=self.sum_legs_var, style="OnCard.TLabel").grid(row=0, column=6, sticky="w")
        # # Add new summary metrics: Total Delta Trade and Total Delta Notional
        # ttk.Label(card, text="Delta Trade:", style="OnCard.TLabel").grid(row=0, column=7, sticky="w")
        self.sum_delta_trade_var = tk.StringVar(value="-")
        # ttk.Label(card, textvariable=self.sum_delta_trade_var, style="OnCard.TLabel").grid(row=0, column=8, sticky="w")
        # ttk.Label(card, text="Delta Notional:", style="OnCard.TLabel").grid(row=0, column=9, sticky="w")
        self.sum_delta_notional_var = tk.StringVar(value="-")
        # ttk.Label(card, textvariable=self.sum_delta_notional_var, style="OnCard.TLabel").grid(row=0, column=10, sticky="w")
        self._update_summary()
    def _on_strategy_change(self, *_):
        self._update_summary()
        self._mark_dirty_and_show_update_placeholder()
    def _update_summary(self):
        if not getattr(self, "_ui_ready", False):
            return
        data = self._collect_data()
        legs = data.get("legs", [])
        # Total premium (sum of leg qty * price)
        total_premium = 0.0
        for leg in legs:
            try:
                q = float(leg.get("qty", "0") or 0)
                p = float(leg.get("price", "0") or 0)
                total_premium += q * p * 100
            except Exception:
                pass
        # Apply Total Premium Override for display, if provided
        try:
            ov_txt = (self.total_prem_override_var.get() if hasattr(self, 'total_prem_override_var') else '').strip()
            if ov_txt:
                total_premium = float(ov_txt)
        except Exception:
            pass
        # Equity exposure = equity price * equity qty
        try:
            eq_val = float(data.get("price", "0") or 0) * float(data.get("qty", "0") or 0)
        except Exception:
            eq_val = 0.0
        # New: aggregate Delta Trade and Delta Notional across completed legs
        total_delta_trade = 0.0
        total_delta_notional = 0.0
        try:
            eq_price_float = float((self.eq_price_var.get() or "0").strip())
        except Exception:
            eq_price_float = 0.0
        for lf in getattr(self, 'legs', []):
            if not lf.is_complete():
                continue
            # Prefer snapshot delta if present; fallback to any delta_var if available
            delta_val = 0.0
            snap = getattr(lf, 'get_snapshot', lambda: None)()
            if isinstance(snap, dict):
                try:
                    dv = snap.get("DELTA_MID_RT")
                    if dv is not None:
                        delta_val = float(dv)
                except Exception:
                    delta_val = 0.0
            if delta_val == 0.0 and hasattr(lf, 'delta_var'):
                try:
                    delta_val = float(lf.delta_var.get())
                except Exception:
                    pass
            # qty
            try:
                qty_val = float(lf.qty_var.get())
            except Exception:
                qty_val = 0.0
            # per-leg delta trade and notional
            d_trade = delta_val * qty_val * 100.0
            d_notional = d_trade * eq_price_float
            total_delta_trade += d_trade
            total_delta_notional += d_notional
        self.sum_premium_var.set(f"{total_premium:,.2f}")
        self.sum_equity_var.set(f"{eq_val:,.2f}")
        self.sum_legs_var.set(str(len(legs)))
        # Set new summary numbers
        if hasattr(self, 'sum_delta_trade_var'):
            self.sum_delta_trade_var.set(f"{total_delta_trade:,.2f}")
        if hasattr(self, 'sum_delta_notional_var'):
            self.sum_delta_notional_var.set(f"{total_delta_notional:,.2f}")
  
    # ----------------------
    # Graph placeholder
    # ----------------------
   
    def _build_graph_placeholder(self):
        """Open the chart in a pop-out window instead of embedding at the bottom."""
        self._ensure_chart_window()
    def _export_pnl_to_excel(self):
        if not getattr(self, "chart_widget", None):
            self._ensure_chart_window()
        try:
            strategy = self._collect_data()
            dates = strategy.get("dates", [])
            result = self.compute_pnl(strategy, dates)
            if not result:
                messagebox.showwarning("Export to Excel", "Nothing to export — add legs and dates, then Refresh Chart.")
                return
            x_pct, totals = result
            try:
                spot = float((self.eq_price_var.get() or "0").strip())
            except Exception:
                spot = 0.0
            x_under = [spot * (1.0 + (xpct / 100.0)) for xpct in x_pct] if spot else x_pct
            self.chart_widget.set_data(x_under, totals)
            self.chart_widget.export_to_excel()
        except Exception as e:
            messagebox.showerror("Export to Excel", f"Failed to export:\n{e}")
    def _copy_pnl_table_to_clipboard(self):
        if not getattr(self, "chart_widget", None):
            self._ensure_chart_window()
        try:
            strategy = self._collect_data()
            dates = strategy.get("dates", [])
            result = self.compute_pnl(strategy, dates)
            if not result:
                messagebox.showwarning("Copy P&L Table", "Nothing to copy — add legs and dates, then Refresh Chart.")
                return
            x_pct, totals = result
            try:
                spot = float((self.eq_price_var.get() or "0").strip())
            except Exception:
                spot = 0.0
            x_under = [spot * (1.0 + (xpct / 100.0)) for xpct in x_pct] if spot else x_pct
            # Push into widget and let it format/copy
            self.chart_widget.set_data(x_under, totals)
            self.chart_widget.copy_table_to_clipboard()
        except Exception as e:
            messagebox.showerror("Copy P&L Table", f"Unexpected error:\n{e}")
    def _copy_chart_to_clipboard(self):
        if not getattr(self, "chart_widget", None):
            self._ensure_chart_window()
        try:
            self.chart_widget.copy_chart_to_clipboard()
        except Exception as e:
            messagebox.showerror("Copy Chart", str(e))
    def _draw_placeholder(self):
        if not getattr(self, "_chart_ready", False) or not hasattr(self, "chart_widget"):
            return
        try:
            # Use the live UI to determine if any leg rows exist, because
            # the serialized strategy may omit incomplete legs.
            strategy = self._collect_data() if hasattr(self, "_collect_data") else {}
            has_dates = bool(strategy.get("dates", []))
            has_legs_ui = bool(getattr(self, "legs", []))
 
            if not has_dates and not has_legs_ui:
                msg = "Fill in leg(s) and scenario date(s)"
            elif not has_dates:
                msg = "Fill in at least one date to compute P&L"
            elif not has_legs_ui:
                msg = "Add at least one leg to compute P&L"
            else:
                # Fallback text if we land here with no plottable data for other reasons
                msg = "Fill in a ticker (ALL CAPS) and hit Update Data"
            self.chart_widget._draw_placeholder(msg)
        except Exception as e:
            print(f"[DBG] _draw_placeholder failed: {e}")
 
    def _get_earliest_maturity_from_legs(self) -> Optional[str]:
        """Return 'YYYY-MM-DD' for the earliest maturity among complete legs; None if not found."""
        earliest = None
        for lf in getattr(self, 'legs', []):
            try:
                exp = (lf.maturity.get() or "").strip()
                if not exp:
                    continue
                dt = datetime.strptime(exp, "%Y-%m-%d")
                if earliest is None or dt < datetime.strptime(earliest, "%Y-%m-%d"):
                    earliest = exp
            except Exception:
                continue
        return earliest
 
    def _refresh_chart(self):
        # Skip any chart work if we are in the middle of a bulk update
        if getattr(self, "_suspend_chart", False):
            return
        try:
            self._ensure_chart_window()
        except Exception:
            pass
        # Skip if chart not initialized yet
        if not getattr(self, "_chart_ready", False):
            return
        # If inputs changed since last update, show placeholder instead of recomputing
        if getattr(self, "_dirty", False):
            self._draw_placeholder()
            return
        try:
            strategy = self._collect_data()
            dates = list(strategy.get("dates", []) or [])
 
            # Optionally add earliest maturity to the dates used for the chart
            if self.show_earliest_curve_var.get():
                em = self._get_earliest_maturity_from_legs()
                if em and em not in dates:
                    dates.append(em)
 
            result = self.compute_pnl(strategy, dates)
            if not result:
                self._draw_placeholder()
                return
            x, totals = result
            try:
                spot = float((self.eq_price_var.get() or "0").strip())
            except Exception:
                spot = 0.0
            x_under = [spot * (1.0 + (xpct / 100.0)) for xpct in x] if spot else x
            # Update options from current controls
            try:
                g = int((self.granularity_var.get() or "5").strip())
            except Exception:
                g = 5
            g = max(2, min(g, 25))
            self.chart_widget.update_options({
                "x_ticks": g,
                "show_grid": bool(self.chart_opts.get("show_grid", True)),
                "show_legend": bool(self.chart_opts.get("show_legend", True)),
                "y_commas": bool(self.chart_opts.get("y_commas", True)),
                "ref_line": bool(self.chart_opts.get("spot_line", True)) and bool(spot),
                "ref_x": spot if spot else None,
                "ref_style": str(self.chart_opts.get("spot_line_style", "-.") or "-."),
                "ref_width": float(self.chart_opts.get("spot_line_width", 1.25) or 1.25),
                "ref_alpha": float(self.chart_opts.get("spot_line_alpha", 0.9) or 0.9),
                "title": f"P&L vs. {(' ' + (self.ticker_var.get() or '').strip()) if self.ticker_var.get() else ''}",
                "xlabel": "Underlying price ($)",
                "ylabel": "P&L ($)",
                "extra_bottom_pad" : 0.2,
                "label_ref_line": "Spot Price",
                "label_show_line_stats": "Show PnL statistics",
                "label_show_max_in_summary": "Display max PnL in summary",
                "show_custom_message": True,
                "label_show_custom_message": "Show Option Leg Data on Graph",
                "custom_message": self._format_portfolio_summary_message(strategy),
                "max_statistic_label" : "Max PnL",
                "label_x_cross" : "Breakeven",
            })
            self.chart_widget.set_data(x_under, totals).refresh()
        except Exception:
            self._draw_placeholder()
 
    def _ensure_chart_window(self):
        """Create (or re-show) the chart in a side pop-out window."""
        # Re-entrancy / singleton guard
        if getattr(self, "_chart_creating", False):
            try:
                win = self.nametowidget(".chart_win")
                if win and win.winfo_exists():
                    win.deiconify(); win.lift(); win.focus_force()
                    self._chart_win = win
                    return win
            except Exception:
                pass
            return
 
        # Try to reuse an already-named Toplevel
        try:
            win = self.nametowidget(".chart_win")
            if win and win.winfo_exists():
                win.deiconify(); win.lift(); win.focus_force()
                self._chart_win = win
                return win
        except Exception:
            pass
 
        self._chart_creating = True
        try:
            # NOTE: give the Toplevel a fixed name so we can always find it
            win = tk.Toplevel(self, name="chart_win")
            self._chart_win = win
            win.title("P&L Chart")
            win.minsize(900, 500)
 
            def _on_close_popout():
                self._chart_ready = False
                try:
                    if hasattr(self, "chart_widget"):
                        self.chart_widget.destroy()
                except Exception:
                    pass
                try:
                    win.destroy()
                finally:
                    self._chart_win = None
 
            win.protocol("WM_DELETE_WINDOW", _on_close_popout)
 
            # Place to the right of the main window
            try:
                self.update_idletasks()
                rx, ry = self.winfo_rootx(), self.winfo_rooty()
                rw = self.winfo_width()
                win.geometry(f"+{rx + rw + 30}+{ry + 40}")
            except Exception:
                pass
 
            container = ttk.Frame(win, style="Card.TFrame")
            container.pack(fill="both", expand=True)
 
            # (Re)create widget
            try:
                if hasattr(self, "chart_widget"):
                    self.chart_widget.destroy()
            except Exception:
                pass
 
            # Prepare initial opts...
            try:
                spot = float((self.eq_price_var.get() or "0").strip())
            except Exception:
                spot = 0.0
            try:
                g = int((getattr(self, "granularity_var", tk.StringVar(value="5")).get() or "5").strip())
            except Exception:
                g = 5
            g = max(2, min(g, 25))
 
            opts = {
                "show_grid": bool(self.chart_opts.get("show_grid", True)),
                "show_legend": bool(self.chart_opts.get("show_legend", True)),
                "y_commas": bool(self.chart_opts.get("y_commas", True)),
                "ref_line": bool(self.chart_opts.get("spot_line", True)) and bool(spot),
                "ref_x": spot if spot else None,
                "ref_style": str(self.chart_opts.get("spot_line_style", "-.") or "-."),
                "ref_width": float(self.chart_opts.get("spot_line_width", 1.25) or 1.25),
                "ref_alpha": float(self.chart_opts.get("spot_line_alpha", 0.9) or 0.9),
                "x_ticks": g,
                "title": f"P&L vs. {(' ' + (self.ticker_var.get() or '').strip()) if self.ticker_var.get() else ''}",
                "xlabel": "Underlying price ($)",
                "ylabel": "P&L ($)",
            }
 
            self.chart_widget = ChartWidget(container, options=opts)
            self.chart_widget.pack(fill="both", expand=True)
            self.chart_widget._draw_placeholder("Fill in leg(s) and scenario date(s)")

            # After creating or showing the chart window, widen it (chart popout only)
            try:
                self.after_idle(self._widen_chart_popout)
            except Exception:
                pass
 
            self._chart_ready = True
            return win
        finally:
            self._chart_creating = False
   
    # ----------------------
    # Menubar commands
    # ----------------------
   
    def _menu_new(self):
        self.mode.set("NEW")
        self._apply_mode_to_legs()
        # Optional: clear inputs here if desired
        # self.ticker_var.set(""); self.max_var.set(""); self.min_var.set("")
        # Normalize any prefilled Max/Min to percent display
        self._format_percent_var(self.max_var)
        self._format_percent_var(self.min_var)
    def _menu_load(self):
        path = filedialog.askopenfilename(filetypes=[("JSON files", "*.json")])
        if not path:
            return
        try:
            with open(path, "r") as f:
                data = json.load(f)
            # Validate strictly before mutating UI
            self._validate_full_strategy(data)
        except Exception as e:
            messagebox.showerror("Load Error", f"Invalid or unreadable file:\n{e}")
            return
        try:
            self._load_from_data(data)
            self.mode.set("LOAD")
            self._apply_mode_to_legs()
            self._dirty = False
            self._refresh_chart()
        except Exception as e:
            messagebox.showerror("Load Error", f"Failed to load strategy:\n{e}")
    def _menu_save(self):
        data = self._collect_data()
        # Require Min/Max before saving
        if not (self.max_var.get() or "").strip() or not (self.min_var.get() or "").strip():
            messagebox.showwarning(
                "Missing Min/Max",
                "Please enter both 'Equity Scenerio Max' and 'Equity Scenerio Min' before saving."
            )
            return
        # Block save if there are no complete legs
        if not data.get("legs"):
            messagebox.showwarning("Nothing to save", "Please complete at least one leg before saving.")
            return
    
        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON files", "*.json")])
        if not path:
            return
        try:
            with open(path, "w") as f:
                json.dump(data, f, indent=2)
            messagebox.showinfo("Saved", f"Strategy saved to:\n{path}")
        except Exception as e:
            messagebox.showerror("Save Error", f"Could not save file:\n{e}")
    def _menu_quit(self):
        self._on_close()
    def _menu_clear_dates(self):
        while self.date_entries:
            self._remove_last_date_box()
        self._add_date_box("")
        self._update_date_buttons_state()
    def _menu_reset_legs(self):
        while len(self.legs) > 1:
            self._delete_leg()
        # clear remaining leg
        leg = self.legs[0]
        leg.set_values(cp="Call", maturity="", strike="", qty="", price="")
        self._update_add_leg_button_state()
        self._update_duplicate_button_state()
    def _menu_set_intervals(self):
        """Prompt for the number of grid intervals used in compute_pnl()."""
        try:
            current = int(getattr(self, "intervals", 50))
        except Exception:
            current = 50
        val = simpledialog.askinteger(
            "Set Computation Intervals",
            f"Enter number of grid intervals for P&L computation (x-axis resolution).\n\nCurrent value: {current}",
            initialvalue=current,
            minvalue=5,
            maxvalue=2000,
            parent=self,
        )
        if val is None:
            return
        self.intervals = int(val)
        # reflect in header label if present
        if hasattr(self, "intervals_label_var"):
            self.intervals_label_var.set(f"Computation Intervals: {self.intervals}")
        # refresh chart so new spacing is used
        self._refresh_chart()
    # ----------------------
    # Diagnostics / Exception hook
    # ----------------------
 
    def _tk_exception_hook(self, exc, val, tb):
        """Show callback exceptions instead of freezing the UI."""
        try:
            import traceback as _tb
            msg = "\n".join(_tb.format_exception(exc, val, tb))
            print("[EXC]", msg)
            messagebox.showerror("Unhandled error", msg)
        except Exception:
            # Fall back to printing if messagebox fails
            print("[EXC]", exc, val)
    def _menu_diag_env_info(self):
        import tkinter as _tk
        try:
            import tkcalendar as _tkcal
            tkcal_ver = getattr(_tkcal, "__version__", "?")
        except Exception:
            tkcal_ver = "not importable"
        try:
            import matplotlib as _mpl
            mpl_ver = getattr(_mpl, "__version__", "?")
        except Exception:
            mpl_ver = "not importable"
        info = []
        info.append(f"Python: {sys.version.split()[0]} ({sys.version.split()[1] if len(sys.version.split())>1 else ''})")
        info.append(f"Executable: {sys.executable}")
        info.append(f"OS: {platform.platform()}")
        info.append(f"Tkinter: {_tk.TkVersion}")
        try:
            info.append(f"Tcl: {self.tk.call('info', 'patchlevel')}")
        except Exception:
            pass
        info.append(f"ttk theme: {ttk.Style().theme_use()}")
        info.append(f"tkcalendar: {tkcal_ver}")
        info.append(f"matplotlib: {mpl_ver}")
        info.append(f"CONDA_PREFIX: {os.environ.get('CONDA_PREFIX','')}\nPYTHONPATH: {os.environ.get('PYTHONPATH','')}")
        messagebox.showinfo("Environment Info", "\n".join(info))
    def _menu_diag_calendar_window(self):
        top = tk.Toplevel(self)
        top.title("Calendar Sanity Test")
        frm = ttk.Frame(top, padding=12)
        frm.pack(fill="both", expand=True)
        lbl = ttk.Label(frm, text="Pick a date (this window is isolated from main UI):")
        lbl.pack(anchor="w")
        from tkcalendar import DateEntry as _DE
        v = tk.StringVar()
        de = _DE(
            frm,
            textvariable=v,
            state="readonly",
            date_pattern="yyyy-mm-dd",
            showweeknumbers=False,
            headersbackground=THEME_ACCENT,
            headersforeground="#ffffff",
            background="#ffffff",
            foreground="#000000",
            selectbackground=THEME_ACCENT,
            selectforeground="#ffffff",
        )
        de.pack(fill="x", pady=6)
        de.bind("<<DateEntrySelected>>", lambda e: print("[DBG] sanity DateEntry selected:", getattr(e.widget, "get_date", lambda: v.get())()))
        ttk.Button(frm, text="Close", command=top.destroy).pack(anchor="e", pady=(8,0))
    def _menu_diag_print_dates(self):
        vals = [v.get() for v in getattr(self, 'date_vars', [])]
        print("[DBG] Current dates:", vals)
        messagebox.showinfo("Current Dates", "\n".join(vals) if vals else "(no dates)")
   
    # ----------------------
    # Data helpers & validation
    # ----------------------
 
    # This is called when any input changes that would affect the chart.
    # It marks the strategy as dirty and shows a placeholder instead of refreshing the chart.
    # The user must explicitly click "Update Data" to recompute and refresh the chart.
    def _mark_dirty_and_show_update_placeholder(self, msg: str = "Press 'Update Data' to recompute and refresh chart"):
        """Mark the strategy as dirty and show an update-required placeholder instead of refreshing the chart."""
        self._dirty = True
        if getattr(self, "_chart_ready", False) and hasattr(self, "chart_widget"):
            try:
                self.chart_widget._draw_placeholder(msg)
            except Exception:
                pass
 
    def _format_portfolio_summary_message(self, strategy: Dict[str, Any]) -> str:
        """
        Build a multi-line string:
        <ticker>: <eq_price>
        <SIDE>\t<ticker>\t<qty>\t<expiration>\t<strike>\t<cp>\t@<price>
        ...
        Net Price: <total premium / sum_qty>
        Delta: <sum(delta*qty)/sum_qty> \t Delta Notional: <Delta * eq_price>
        Gamma: <sum(gamma*qty)/sum_qty> \t Gamma Notional: <Gamma * eq_price>
        Theta: <sum(theta*qty)/sum_qty> \t Vega: <sum(vega*qty)/sum_qty>
 
        Notes:
        - Greks are pulled from each leg's snapshot (if present).
        - Weighted averages are computed by sum(greek * qty) / sum(qty).
        - sum_qty uses the SIGNED qty (matches your spec). If 0, we guard to avoid division by zero.
        """
        try:
            ticker = (strategy.get("ticker", "") or "").strip()
            try:
                eq_price = float((self.eq_price_var.get() or "0").strip())
            except Exception:
                eq_price = 0.0
 
            lines = []
            header = f"{ticker}: {eq_price:.2f}" if ticker else f"{eq_price:.2f}"
            lines.append(header)
 
            # Get the earliest maturity across all legs for Net Payout label
            self.earliest_maturity = None
 
            # Per-leg line items
            legs = strategy.get("legs", []) or []
            for i, leg in enumerate(legs):
                try:
                    # side from signed qty
                    qtxt = str(leg.get("qty", "")).strip()
                    qval = float(qtxt) if qtxt != "" else 0.0
                    side = "SELL" if qval < 0 else "BUY"
 
                    exp   = (leg.get("maturity", "") or "").strip()
                    strike = (leg.get("strike", "") or leg.get("resolved_strike", "") or "")
                    cp    = (leg.get("type", "") or "").strip()  # "Call" / "Put"
                    px    = (leg.get("price", "") or "").strip()
 
                    # Get earliest maturity
                    if self.earliest_maturity is None and exp:
                        self.earliest_maturity = exp
                    elif self.earliest_maturity and exp:
                        try:
                            d1 = datetime.strptime(self.earliest_maturity, "%Y-%m-%d")
                            d2 = datetime.strptime(exp, "%Y-%m-%d")
                            if d2 < d1:
                                self.earliest_maturity = exp
                        except Exception:
                            print(f"[DBG] _format_portfolio_summary_message: failed to parse maturity dates:  {self.earliest_maturity}\t{exp}")
                            pass
 
                    # fallbacks for formatting
                    strike_str = f"{float(strike):.2f}" if str(strike).strip() not in ("", None) else ""
                    px_str     = f"{float(px):.2f}" if str(px).strip() not in ("", None) else ""
 
                    # Safely format quantity as absolute if numeric; otherwise leave text as-is
                    try:
                        qty_abs_txt = f"{abs(float(qtxt)):.0f}"
                    except Exception:
                        qty_abs_txt = qtxt
 
                    lines.append(f"{side} {ticker} {qty_abs_txt} {exp} {strike_str} {cp} @{px_str}")
                except Exception:
                    print(f"[DBG] _format_portfolio_summary_message: failed to format leg {i+1}: {leg}")
                    continue
 
            # --- Aggregate across greeks (no averaging), and Net Price ---
            # Raw Net Price = sum(q * price) (signed), NO *100
            net_price_raw = 0.0
            qtys: list[float] = []
            try:
                for leg in legs:
                    try:
                        q = float(leg.get("qty", "0") or 0)
                    except Exception:
                        q = 0.0
                    try:
                        p = float(leg.get("price", "0") or 0)
                    except Exception:
                        p = 0.0
                    net_price_raw += q * p
                    qtys.append(q)
            except Exception:
                net_price_raw = 0.0
 
            # Normalize to the base combo by dividing quantities by their integer GCD (if applicable).
            # If any qty is non-integer-like or all zero, fall back to raw net price.
            from math import gcd
            def _near_int(x: float, tol: float = 1e-6) -> bool:
                return abs(x - round(x)) < tol
 
            mags: list[int] = []
            for q in qtys:
                if q == 0:
                    continue
                if not _near_int(q):
                    mags = []
                    break
                mags.append(int(abs(round(q))))
 
            gcd_factor = 0
            for m in mags:
                gcd_factor = m if gcd_factor == 0 else gcd(gcd_factor, m)
 
            net_price_base = net_price_raw
            if gcd_factor and gcd_factor > 1:
                try:
                    net_price_base = 0.0
                    for leg in legs:
                        try:
                            q = float(leg.get("qty", "0") or 0)
                        except Exception:
                            q = 0.0
                        try:
                            p = float(leg.get("price", "0") or 0)
                        except Exception:
                            p = 0.0
                        net_price_base += (q / float(gcd_factor)) * p
                except Exception:
                    net_price_base = net_price_raw
 
            # Net Premium (summary): allow UI override, else compute from legs
            try:
                ov = self._get_total_premium_override()
            except Exception:
                ov = None
            if ov is not None:
                net_premium = ov
                _np_overridden = True
            else:
                _np_overridden = False
                # Net Premium = sum(q * price * 100) (signed, contract multiplier)
                net_premium = 0.0
                try:
                    for leg in legs:
                        try:
                            q = float(leg.get("qty", "0") or 0)
                        except Exception:
                            q = 0.0
                        try:
                            p = float(leg.get("price", "0") or 0)
                        except Exception:
                            p = 0.0
                        net_premium += q * p * 100.0
                except Exception:
                    net_premium = 0.0
 
            # Greeks = sum( greek * qty * 100 )  (signed)
            sum_delta = 0.0
            sum_gamma = 0.0
            sum_theta = 0.0
            sum_vega  = 0.0
 
            for lf in getattr(self, 'legs', []):
                if not lf.is_complete():
                    continue
                # qty (SIGNED)
                try:
                    qv = float(lf.qty_var.get())
                except Exception:
                    qv = 0.0
 
                snap = getattr(lf, 'get_snapshot', lambda: None)()
                if not isinstance(snap, dict):
                    continue
 
                def _g(name: str, default: float = 0.0) -> float:
                    try:
                        v = snap.get(name, default)
                        return float(v) if v is not None else default
                    except Exception:
                        return default
 
                d = _g("DELTA_MID_RT", 0.0)
                g = _g("GAMMA_MID_RT", 0.0)
                t = _g("THETA_MID_RT", 0.0)
                v = _g("VEGA_MID_RT",  0.0)
 
                # multiply each greek by qty and by 100, then add
                sum_delta += d * qv * 100.0
                sum_gamma += g * qv * 100.0
                sum_theta += t * qv * 100.0
                sum_vega  += v * qv * 100.0
 
            # Notionals = greek * eq_price
            delta_notional = sum_delta * eq_price
            gamma_notional = sum_gamma * eq_price
 
            # ---- Net Payout (ratio) — compute off the maturity date ----
            max_pnl = None
            edge_unlimited = False
 
            # Use the maturity date for payout. If multiple legs, pick the earliest.
            maturity_date = getattr(self, "earliest_maturity", None)
            if not maturity_date:
                maturity_date = self._get_earliest_maturity_from_legs()
 
            try:
                # Ensure maturity date is included in the dates we pass to compute_pnl
                dates_for_pnl = list(strategy.get("dates", []) or [])
                if maturity_date and maturity_date not in dates_for_pnl:
                    dates_for_pnl.append(maturity_date)
 
                pnl_result = self.compute_pnl(strategy, dates_for_pnl)
                if pnl_result and isinstance(pnl_result, (tuple, list)) and len(pnl_result) == 2:
                    x_grid_pct, totals_by_date = pnl_result or ([], {})
 
                    arr = None
                    if maturity_date and maturity_date in (totals_by_date or {}):
                        arr = totals_by_date.get(maturity_date)
 
                    # Fallback: earliest available key, just in case
                    if arr is None:
                        keys = sorted((totals_by_date or {}).keys())
                        if keys:
                            maturity_date = keys[0]
                            arr = totals_by_date.get(maturity_date)
 
                    if arr:
                        max_pnl = max(arr)
                        if len(arr) >= 2:
                            idx = arr.index(max_pnl)
                            edge_unlimited = (idx == len(arr) - 1 and arr[-1] >= arr[-2])
            except Exception:
                max_pnl = None
                edge_unlimited = False
 
            # Show Net Premium (signed, $)
            lines.append(f"Net Premium: {net_premium:,.0f}" + (" (override)" if locals().get("_np_overridden") else ""))
 
            # Ratio formatting: (max_pnl - net_premium) / |net_premium|
            date_tag = f" ({maturity_date})" if maturity_date else ""
            if edge_unlimited:
                lines.append(f"Net Payout{date_tag}: Unlimited")
            else:
                denom = abs(net_premium) if net_premium not in (0.0, None) else None
                if (max_pnl is None) or (denom is None) or denom == 0:
                    lines.append(f"Net Payout{date_tag}: —")
                else:
                    raw_ratio = (max_pnl / net_premium)
                    print(f"max_pnl: {max_pnl}\tnet_premium: {net_premium}\tdenom: {denom}")
                    if abs(raw_ratio) < 1e-9:
                        raw_ratio = 0.0
                    if abs(raw_ratio - round(raw_ratio)) < 1e-6:
                        ratio_txt = f"{int(round(raw_ratio))}:1"
                    else:
                        if raw_ratio <= 0:
                            ratio_txt = f"NA"
                        else:
                            ratio_txt = f"{raw_ratio:.1f}:1"
                    lines.append(f"Net Payout{date_tag}: {ratio_txt}")
 
            lines.append(f"Net Price: {net_price_base:,.2f}\n")
            lines.append(f"Delta: {sum_delta:.0f}   Delta Notional: {delta_notional:,.0f}")
            lines.append(f"Gamma: {sum_gamma:.0f}   Gamma Notional: {gamma_notional:,.0f}")
            lines.append(f"Theta: {sum_theta:.0f}   Vega: {sum_vega:.0f}")
 
            return "\n".join(lines)
        except Exception:
            return ""
 
    def _percent_trace(self, var: tk.StringVar):
        """Ensure the entry shows as percent (e.g., '10%') but stores as decimal (0.1)."""
        txt = var.get().replace("%", "").strip()
        if txt == "":
            return
        try:
            # user typed in 10, convert to decimal 0.1
            val = float(txt) / 100.0
            # update UI to show "10%"
            var.set(f"{float(txt):.0f}%")
            # store decimal in a hidden attribute
            var.decimal_value = val
        except Exception:
            pass
 
    def _get_percent_decimal(self, s: str, default: float = 0.0) -> float:
        """Return decimal from a user-facing percent string ('10%' or '10') -> 0.10."""
        try:
            if s is None:
                return default
            raw = str(s).strip().replace("%", "")
            if raw == "":
                return default
            return float(raw) / 100.0
        except Exception:
            return default
 
    def _maybe_autoselect_strike(self, leg):
        """If maturity is set and strike is empty for this leg, pick the strike closest to spot.
        Requires an option chain to be loaded.
        """
        try:
            if self.chain_tree is None:
                return
            # Only act if no strike currently selected
            current_strike = (getattr(leg, 'strike_combo', None).get() if hasattr(leg, 'strike_combo') else "").strip()
            if current_strike:
                return
 
            maturity = (leg.maturity.get() or "").strip()
            if not maturity:
                return
 
            cp_label = leg.cp_var.get() if hasattr(leg, 'cp_var') else 'Call'
            strikes = self._get_strikes_for(maturity, cp_label) or []
 
            # parse spot
            try:
                spot = float((self.eq_price_var.get() or "0").strip())
            except Exception:
                spot = 0.0
            if not strikes:
                return
 
            # choose strike with min |strike - spot|
            best = None
            best_s = None
            for s in strikes:
                try:
                    fv = float(str(s).strip())
                    d = abs(fv - spot)
                    if best is None or d < best:
                        best = d
                        best_s = str(s)
                except Exception:
                    continue
 
            if best_s:
                # ensure strikes list is available to the combobox
                if hasattr(leg, 'set_strikes'):
                    try:
                        leg.set_strikes(strikes)
                    except Exception:
                        pass
                # set selection
                leg.strike_combo.set(best_s)
                # refresh roots if the leg provides it
                if hasattr(leg, '_refresh_roots'):
                    try:
                        leg._refresh_roots()
                    except Exception:
                        pass
        except Exception:
            pass
 
    def _validate_leg_warning(self) -> bool:
        """
        Staged validation with specific warnings:
        1) If no top-level ticker, do nothing (no warnings).
        2) For each leg (that exists), require:
            - maturity
            - strike (or resolved_strike)
            - qty != 0
        Returns True if all good, False if a warning was shown.
        """
        try:
            strategy = self._collect_data() if hasattr(self, "_collect_data") else {}
            ticker = (strategy.get("ticker", "") or "").strip()
 
            # If no ticker at all, don't warn here—let the Update Data flow handle that.
            if not ticker:
                print(f"no ticker")
                return True
 
            legs = strategy.get("legs", []) or []
            if not legs:
                print(f"no legs")
                return True  # nothing to validate
 
            for leg in legs:
                print(f"in legs")
                # 1) Maturity required
                maturity = (leg.get("maturity", "") or "").strip()
                if not maturity:
                    messagebox.showwarning(
                        "Missing Maturity",
                        "One or more legs are missing a maturity date. "
                        "Please select a maturity before continuing."
                    )
                    return False
 
                # 2) Strike required (accept either 'strike' or 'resolved_strike')
                strike_txt = (leg.get("strike") or leg.get("resolved_strike") or "")
                strike_txt = str(strike_txt).strip()
                if not strike_txt:
                    messagebox.showwarning(
                        "Missing Strike",
                        "One or more legs are missing a strike. "
                        "Please select a strike (or %OTM to resolve) before continuing."
                    )
                    return False
 
                # 3) Qty required and must be non-zero
                qtxt = str(leg.get("qty", "")).strip()
                try:
                    qval = float(qtxt) if qtxt != "" else 0.0
                except Exception:
                    qval = 0.0
                if qval == 0.0:
                    messagebox.showwarning(
                        "Missing Contracts",
                        "One or more legs have a contract quantity of 0. "
                        "Please enter a non-zero number of contracts."
                    )
                    return False
 
        except Exception as e:
            print(f"[WARN CHECK] Validation skipped due to error: {e}")
 
        print(f"[INFO] Passed Validation")
        return True
 
    def set_equity_price(self, px: str):
        """Safely update the (readonly) equity price field, e.g., after a Bloomberg fetch."""
        self.eq_price_entry.configure(state="normal")
        self.eq_price_var.set(px)
        self.eq_price_entry.configure(state="readonly")
    def _collect_data(self) -> Dict[str, Any]:
        """Collect current UI data. Only include fully-completed legs."""
        legs = [leg.to_dict() for leg in self.legs if leg.is_complete()]
       
        return {
            "mode": self.mode.get(),
            "ticker": self.ticker_var.get().strip(),
            "max": self.max_var.get().strip(),
            "min": self.min_var.get().strip(),
            "price": self.eq_price_var.get().strip(),
            "qty": self.eq_qty_var.get().strip(),
            "dates": [v.get().strip() for v in self.date_vars if v.get().strip()],
            "legs": legs,
            "total_premium_override": getattr(self, 'total_prem_override_var', tk.StringVar(value="")).get().strip() if hasattr(self, 'total_prem_override_var') else "",
            "vol_shock_term": (self.vol_shock_term_var.get() or "").strip(),
        }
    def _load_from_data(self, data: Dict[str, Any]):
        # primitives
        self.ticker_var.set(data.get("ticker", ""))
        self.max_var.set(data.get("max", ""))
        self.min_var.set(data.get("min", ""))
        # Ensure Max/Min show as N.N%
        self._format_percent_var(self.max_var)
        self._format_percent_var(self.min_var)
        self.eq_price_var.set(data.get("price", ""))
        self.eq_qty_var.set(data.get("qty", ""))
        # premium override
        try:
            ov = str(data.get("total_premium_override", ""))
            if hasattr(self, 'total_prem_override_var'):
                self.total_prem_override_var.set(ov)
        except Exception:
            pass
        # term volatility shock (global): store/show like Min/Max (percent string)
        try:
            v = data.get("vol_shock_term", "")
            self.vol_shock_term_var.set("" if v in ("", None) else str(v))
            # normalize display "10" -> "10%"
            self._format_percent_var(self.vol_shock_term_var)
            # propagate to legs & readonly states
            self._on_vol_shock_term_change()
        except Exception:
            print(f"[ERROR] Vol Shock Loading Failed")
            pass
        # dates
        while self.date_entries:
            self._remove_last_date_box()
        for d in data.get("dates", []) or [""]:
            self._add_date_box(d)
        self._update_date_buttons_state()
        # legs
        # remove down to one
        while len(self.legs) > 1:
            self._delete_leg()
        # reset the remaining leg
        self.legs[0].set_values(cp="Call", maturity="", strike="", qty="", price="")
       
        # --- Ensure leg vol shocks display as percent in the UI (post-population) ---
        try:
            legs_in = data.get("legs", []) or []
            # If a term shock exists, _on_vol_shock_term_change() already pushed it to legs.
            _term = data.get("vol_shock_term", "")
            has_term = (_term not in ("", None))
            if not has_term:
                for i, l in enumerate(legs_in):
                    try:
                        vls = l.get("vol_shock_leg", "")
                        if vls in ("", None):
                            continue
                        dv = float(vls)  # stored as decimal in file
                    except Exception:
                        continue
        except Exception:
            pass
       
        legs_in = data.get("legs", [])
        if legs_in:
            # set first then add the rest
            first = legs_in[0]
            self.legs[0].set_values(
                cp=first.get("type", "Call"),
                maturity=first.get("maturity", ""),
                strike=first.get("strike", ""),
                qty=first.get("qty", ""),
                price=first.get("price", ""),
                strike_mode=first.get("strike_mode", "Strike"),
                pct_otm=first.get("pct_otm", ""),
                resolved_strike=first.get("resolved_strike", ""),
                vol_shock_leg=first.get("vol_shock_leg", "")
            )
            # Reflect BUY/SELL UI from signed qty while keeping backend qty_var signed
            try:
                qtxt = str(first.get("qty", "")).strip()
                qval = float(qtxt) if qtxt != "" else 0.0
                side = "SELL" if qval < 0 else "BUY"
                self.legs[0].side_var.set(side)
                self.legs[0].display_qty_var.set(str(abs(qval)).rstrip('0').rstrip('.') if '.' in str(abs(qval)) else str(int(abs(qval))))
                # Ensure qty_var (backend) keeps the signed number
                self.legs[0].qty_var.set(str(qval))
            except Exception:
                pass
            # Ensure strike combobox can show the saved strike in LOAD mode (no chain fetched)
            try:
                strike_to_show = (first.get("strike") or first.get("resolved_strike") or "").strip()
                if strike_to_show:
                    self.legs[0].set_strikes([strike_to_show])  # populate values with the saved strike
                    self.legs[0].strike_combo.set(strike_to_show)
            except Exception:
                pass
            # restore root if present
            try:
                r0 = first.get("root", "")
                if r0:
                    self.legs[0].set_roots([r0])  # ensure it's selectable
                    self.legs[0].root_combo.set(r0)
            except Exception:
                pass
            # restore snapshot if present
            try:
                snap0 = first.get("snapshot")
                if isinstance(snap0, dict):
                    self.legs[0].set_snapshot(snap0)
                    self.legs[0].set_stats_from_snapshot(snap0)
                    # refresh label from stored price if any; otherwise compute from snapshot
                    price_text = first.get("price")
                    if not price_text:
                        px_mid = snap0.get("PX_MID") or 0
                        px_ask = snap0.get("PX_ASK") or 0
                        try:
                            price_text = f"{(float(px_mid)+float(px_ask))/2:.2f}"
                        except Exception:
                            price_text = ""
                    self.legs[0].set_option_price(price_text if price_text else None)
            except Exception:
                pass
            for l in legs_in[1:]:
                self._add_leg()
                lf = self.legs[-1]
                lf.set_values(
                    cp=l.get("type", "Call"),
                    maturity=l.get("maturity", ""),
                    strike=l.get("strike", ""),
                    qty=l.get("qty", ""),
                    price=l.get("price", ""),
                    strike_mode=l.get("strike_mode", "Strike"),
                    pct_otm=l.get("pct_otm", ""),
                    resolved_strike=l.get("resolved_strike", ""),
                    vol_shock_leg=l.get("vol_shock_leg", "")
                )
                # Show leg vol shock as percent in UI and cache decimal (first leg)
                try:
                    vls = first.get("vol_shock_leg", "")
                    if vls not in ("", None) and hasattr(self.legs[0], "vol_shock_leg_var"):
                        dv = float(vls)
                        self.legs[0].vol_shock_leg_var.set(f"{dv * 100:.0f}%")
                        self.legs[0].vol_shock_leg_var.decimal_value = dv
                except Exception:
                    pass
               
                # Reflect BUY/SELL for this leg from its signed qty
                try:
                    qtxt = str(l.get("qty", "")).strip()
                    qval = float(qtxt) if qtxt != "" else 0.0
                    side = "SELL" if qval < 0 else "BUY"
                    lf.side_var.set(side)
                    lf.display_qty_var.set(str(abs(qval)).rstrip('0').rstrip('.') if '.' in str(abs(qval)) else str(int(abs(qval))))
                    lf.qty_var.set(str(qval))
                except Exception:
                    pass
                # Ensure strike combobox can show the saved strike for this leg
                try:
                    strike_to_show = (l.get("strike") or l.get("resolved_strike") or "").strip()
                    if strike_to_show:
                        lf.set_strikes([strike_to_show])
                        lf.strike_combo.set(strike_to_show)
                except Exception:
                    pass
                # restore root if present
                try:
                    r = l.get("root", "")
                    if r:
                        lf.set_roots([r])
                        lf.root_combo.set(r)
                except Exception:
                    pass
                # restore snapshot if present
                try:
                    snap = l.get("snapshot")
                    if isinstance(snap, dict):
                        lf.set_snapshot(snap)
                        lf.set_stats_from_snapshot(snap)
                        price_text = l.get("price")
                        if not price_text:
                            px_mid = snap.get("PX_MID") or 0
                            px_ask = snap.get("PX_ASK") or 0
                            try:
                                price_text = f"{(float(px_mid)+float(px_ask))/2:.2f}"
                            except Exception:
                                price_text = ""
                        lf.set_option_price(price_text if price_text else None)
                except Exception:
                    pass
        self._update_add_leg_button_state()
        self._update_summary()
        self._update_duplicate_button_state()
    def _validate_full_strategy(self, data: Dict[str, Any]) -> None:
        def require(cond: bool, msg: str):
            if not cond:
                raise ValueError(msg)
        # Basic fields
        require(isinstance(data, dict), "Top-level JSON must be an object")
        for k in ("ticker", "max", "min", "price"):
            require(k in data and isinstance(data[k], str) and data[k].strip() != "", f"Missing or empty '{k}'")
        # Dates
        require("dates" in data and isinstance(data["dates"], list) and len(data["dates"]) > 0, "'dates' must be a non-empty list")
        for d in data["dates"]:
            require(isinstance(d, str) and d.strip() != "", "All dates must be non-empty strings")
            try:
                datetime.strptime(d, "%Y-%m-%d")
            except ValueError:
                raise ValueError(f"Invalid date format: {d} (expected YYYY-MM-DD)")
        # Legs
        require("legs" in data and isinstance(data["legs"], list) and len(data["legs"]) > 0, "'legs' must be a non-empty list")
        for i, leg in enumerate(data["legs"], start=1):
            require(isinstance(leg, dict), f"Leg {i} must be an object")
            require(leg.get("type") in ("Call", "Put"), f"Leg {i}: 'type' must be 'Call' or 'Put'")
            for field in ("maturity", "qty", "price"):
                require(field in leg and isinstance(leg[field], str) and leg[field].strip() != "", f"Leg {i}: missing or empty '{field}'")
            mode = leg.get("strike_mode")
            require(mode in ("Strike", "%OTM"), f"Leg {i}: invalid 'strike_mode'")
            if mode == "Strike":
                require("strike" in leg and isinstance(leg["strike"], str) and leg["strike"].strip() != "", f"Leg {i}: missing or empty 'strike'")
            else:
                require("pct_otm" in leg and isinstance(leg["pct_otm"], str) and leg["pct_otm"].strip() != "", f"Leg {i}: missing or empty 'pct_otm'")
                # Optionally:
                # require("resolved_strike" in leg and str(leg["resolved_strike"]).strip() != "", f"Leg {i}: missing resolved_strike")
   
    # ----------------------
    # Compute P&L stub — this was long
    # ----------------------
 
    def compute_pnl(self, strategy: Dict[str, Any], dates: List[str]) -> Optional[Tuple[List[float], Dict[str, List[float]]]]:
        """Return (x_pct, totals_by_date) where totals_by_date maps scenario date -> PnL curve."""
        if not dates:
            return None
        # Parse MIN / MAX from UI (formatted like '12.3%'); choose a default grid density
        min_dec = self._parse_percent_to_decimal(self.min_var.get(), default=-0.5)
        max_dec = self._parse_percent_to_decimal(self.max_var.get(), default=0.5)
        intervals = int(getattr(self, 'intervals', 50))
        # Spot (cash equity price)
        try:
            spot = float((self.eq_price_var.get() or "0").strip())
        except Exception:
            spot = 0.0
        if spot == 0.0:
            return None
        term_raw = (strategy.get("vol_shock_term", "") or "").strip()
        has_term_shock = (term_raw != "")
        term_shock = self._parse_percent_to_decimal(term_raw, 0.0) if has_term_shock else 0.0
        data_legs = []
        for leg in getattr(self, 'legs', []):
            if not leg.is_complete():
                continue
            # Resolve full option description and find a snapshot
            desc = self._resolve_leg_description(leg)
            if not desc:
                # Fall back to leg snapshot even if we can't resolve description, if present
                snap = getattr(leg, 'get_snapshot', lambda: None)()
                if not isinstance(snap, dict):
                    continue
            else:
                # Prefer leg's own snapshot if present, else fall back to cached dict
                snap = getattr(leg, 'get_snapshot', lambda: None)()
                if not isinstance(snap, dict):
                    snap = self.opt_snapshots.get(desc)
                if not isinstance(snap, dict):
                    continue
 
            # Pull leg basics
            cp_label = leg.cp_var.get()
            option_type = 'C' if cp_label == 'Call' else 'P'
            maturity = (leg.maturity.get() or "").strip()
            try:
                strike = float((leg.strike_combo.get() or "").strip())
            except Exception:
                strike = self._parse_float_safe(getattr(leg, 'strike_combo', None).get() if hasattr(leg, 'strike_combo') else "0", 0.0)
            qty = self._parse_float_safe(leg.qty_var.get(), 0.0)
           
            # # --- Work on a copy so we don't mutate caches/UI state ---
            # try:
            #     snap = dict(snap)
            # except Exception:
            #     pass
 
            # ---- Determine effective vol shock for this leg ----
            term_raw = (strategy.get("vol_shock_term", "") or "").strip()
            has_term_shock = (term_raw != "")
            if has_term_shock:
                leg_shock_val = term_shock
            else:
                try:
                    leg_txt = getattr(leg, "vol_shock_leg_var", tk.StringVar(value="")).get()
                    leg_shock_val = self._parse_percent_to_decimal(leg_txt, 0.0)
                except Exception:
                    leg_shock_val = 0.0
 
            # Snapshot numeric fields (default to 0.0 if missing) — helper must be defined before use
            def _gfloat(name: str, default: float = 0.0) -> float:
                try:
                    v = snap.get(name, default)
                    return float(v) if v is not None else default
                except Exception:
                    return default
 
            # Read originals and set adjusted defaults (avoid NameError if adjustment fails)
            orig_ivol_rt = _gfloat("IVOL_MID_RT")
            orig_vega_rt = _gfloat("VEGA_MID_RT")
            orig_vega    = _gfloat("VEGA")
            adj_ivol_rt = orig_ivol_rt
            adj_vega_rt = orig_vega_rt
            adj_vega    = orig_vega
 
            # ---- Apply shock to VOL fields on the local snapshot copy ----
            try:
                # figure out leg_shock_val (term overrides leg)
                if has_term_shock:
                    leg_shock_val = term_shock
                else:
                    leg_txt = getattr(leg, "vol_shock_leg_var", tk.StringVar(value="")).get()
                    leg_shock_val = self._parse_percent_to_decimal(leg_txt, 0.0)
 
                factor = 1.0 + float(leg_shock_val)
 
                # compute adjusted values locally (orig_ * were read above)
                adj_ivol_rt = orig_ivol_rt * factor
                adj_vega_rt = orig_vega_rt * factor
                adj_vega    = orig_vega * factor
            except Exception as e:
                print(f"[ERROR] Could not Apply shock to VOL fields on the local snapshot copy \n{e} ")
                pass
 
            leg_dict = {
                "SPOT": spot,
                "STRIKE": strike,
                "OPTION_TYPE": option_type,
                "MATURITY": maturity,
                "QTY": qty,
                "MULTIPLIER": 100,
                "OPT_FINANCE_RT": _gfloat("OPT_FINANCE_RT"),
                "OPT_DIV_YIELD": _gfloat("OPT_DIV_YIELD"),
                "DELTA_MID_RT": _gfloat("DELTA_MID_RT"),
                "GAMMA_MID_RT": _gfloat("GAMMA_MID_RT"),
                "VEGA_MID_RT": adj_vega_rt,          # instead of _gfloat("VEGA_MID_RT")
                "IVOL_MID_RT": adj_ivol_rt,          # instead of _gfloat("IVOL_MID_RT")
                "THETA_MID_RT": _gfloat("THETA_MID_RT"),
                "PX_MID": _gfloat("PX_MID"),
                "PX_ASK": _gfloat("PX_ASK"),
                # scenario controls
                "SCENARIO_DATE": dates[0],   # portfolio helper overrides this per loop
                "PRICE_MOVEMENT": 0.0,       # set per grid point
                "BETA": 1.0,
                "MIN": min_dec,
                "MAX": max_dec,
                "INTERVALS": intervals,
            }
            data_legs.append(leg_dict)
        if not data_legs:
            return None
        moves, totals, _ = portfolio_profit_curves(data_legs, dates)
        x_pct = [m * 100.0 for m in moves]
        # Compute the current (computed) total premium = sum(qty * price * 100)
        computed_total = 0.0
        try:
            for leg in strategy.get("legs", []):
                q = float(leg.get("qty", "0") or 0)
                p = float(leg.get("price", "0") or 0)
                computed_total += q * p * 100.0
        except Exception:
            pass
        # --- Add cash equity position P&L to the totals ---
        # Equity is a cash position with delta = 1 per share (100 delta convention for options is handled
        # inside option legs which use a MULTIPLIER of 100). For cash equity, profit per move is:
        #   profit = qty * (price_after_movement - spot)
        # where price_after_movement = spot * (1 + move * beta). We use beta=1.0 for direct underlying moves.
        try:
            eq_qty = float((strategy.get("qty", "0") or 0))
        except Exception:
            eq_qty = 0.0
        try:
            # Only add equity P&L if a non-zero quantity is provided
            if eq_qty != 0.0:
                for dt, arr in list(totals.items()):
                    # arr is a list of totals for each grid point; we add equity profit pointwise
                    new_arr = []
                    for i, mv in enumerate(moves):
                        # price movement grid 'mv' is a decimal (e.g., 0.10 for +10%)
                        price_after = spot * (1.0 + mv * 1.0)
                        eq_profit = (price_after - spot) * eq_qty
                        new_arr.append(arr[i] + eq_profit)
                    totals[dt] = new_arr
        except Exception:
            pass
        # If an override is given, shift all P&L series by (computed_total - override)
        try:
            ov_txt = (self.total_prem_override_var.get() if hasattr(self, 'total_prem_override_var') else '').strip()
            if ov_txt:
                ov_val = float(ov_txt)
                shift = computed_total - ov_val
                for dt, arr in totals.items():
                    totals[dt] = [(v + shift) for v in arr]
                print(f"[PnL] Applied Total Premium Override: override={ov_val:.2f}, computed={computed_total:.2f}, shift={shift:.2f}")
        except Exception:
            pass
        return x_pct, totals
