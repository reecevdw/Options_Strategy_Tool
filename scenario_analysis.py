from datetime import date
from typing import Dict
import math
from copy import deepcopy

class ScenarioRunner:
    def _sf(self, v):
        """Safe float: return float(v) if numeric and finite, else None."""
        try:
            f = float(v)
        except Exception:
            return None
        # NaN/inf guard
        try:
            if not math.isfinite(f):
                return None
        except Exception:
            if f != f:  # NaN
                return None
        return f

    def entry_price_from_snapshot(self) -> float:
        """
        Compute the original unit price using BUY/SELL-aware rules to mirror the UI:
          - BUY (qty > 0): price = (MID + ASK) / 2
              * If BID was missing but ASK exists: set BID := 0, recompute MID := (BID + ASK)/2, then price := (MID + ASK)/2
              * If MID missing but BID & ASK exist: recompute MID := (BID + ASK)/2
              * If ASK missing but BID & MID exist: infer ASK := max(0, 2*MID - BID)
          - SELL (qty < 0): price = (BID + MID) / 2
              * If MID missing but BID & ASK exist: recompute MID := (BID + ASK)/2
              * If BID missing but MID & ASK exist: infer BID := max(0, 2*MID - ASK)
        If all three of BID/MID/ASK are missing, raise ValueError.
        """
        b = self._sf(self.data.get("PX_BID"))
        m = self._sf(self.data.get("PX_MID"))
        a = self._sf(self.data.get("PX_ASK"))

        logs = []
        b0, m0, a0 = b, m, a
        EPS = 1e-9

        if b is None and m is None and a is None:
            raise ValueError("Missing option price: need at least one of PX_BID, PX_MID, PX_ASK.")

        qty = int(self.data.get("QTY", 1))

        if qty > 0:
            # BUY path
            # If BID is missing and ASK exists, only ignore/override MID when MID == ASK.
            # If MID is None: assume BID=0 and synthesize MID from BID/ASK.
            # If MID present and MID == ASK: ignore reported MID per rule (assume BID=0, recompute MID).
            # If MID present and MID != ASK: treat MID as true; infer BID = max(0, 2*MID - ASK).
            if b is None and a is not None:
                if m is None:
                    b = 0.0
                    m = (b + a) / 2.0
                    logs.append(f"[EntryPrice][BUY] BID missing & MID missing → assume BID=0.0; MID=(BID+ASK)/2={m}")
                else:
                    if abs(m - a) <= EPS:
                        b = 0.0
                        m = (b + a) / 2.0
                        logs.append(f"[EntryPrice][BUY] BID missing & MID==ASK ({a}) → ignore MID; assume BID=0.0; MID=(BID+ASK)/2={m}")
                    else:
                        inferred_bid = max(0.0, 2.0 * m - a)
                        b = inferred_bid
                        logs.append(f"[EntryPrice][BUY] BID missing & MID({m})!=ASK({a}) → infer BID=max(0,2*MID-ASK)={b}")
            # If MID missing but have BID & ASK -> recompute MID
            if m is None and (b is not None) and (a is not None):
                m = (b + a) / 2.0
                logs.append(f"[EntryPrice][BUY] MID missing → recompute MID=(BID+ASK)/2={(b + a)/2.0}")
            # If ASK missing but have BID & MID -> infer ASK
            if a is None and (m is not None) and (b is not None):
                a = max(0.0, 2.0 * m - b)
                logs.append(f"[EntryPrice][BUY] ASK missing → infer ASK=max(0, 2*MID−BID)={a}")
            # Compute price
            if (m is not None) and (a is not None):
                logs.append(f"[EntryPrice][BUY] price=(MID+ASK)/2={(m + a)/2.0} using BID={b}, MID={m}, ASK={a}")
                if logs:
                    for _line in logs:
                        print(_line)
                return (m + a) / 2.0
            # Fallbacks
            if m is not None:
                logs.append(f"[EntryPrice][BUY] fallback price=MID={m} (ASK/BID unavailable)")
                if logs:
                    for _line in logs:
                        print(_line)
                return float(m)
            if a is not None:
                logs.append(f"[EntryPrice][BUY] fallback price=ASK={a} (MID/BID unavailable)")
                if logs:
                    for _line in logs:
                        print(_line)
                return float(a)
            if b is not None:
                logs.append(f"[EntryPrice][BUY] fallback price=BID={b} (MID/ASK unavailable)")
                if logs:
                    for _line in logs:
                        print(_line)
                return float(b)
            # Should not reach here due to earlier check
            raise ValueError("Unable to compute BUY entry price.")
        else:
            # SELL path (qty <= 0)
            # If MID missing but have BID & ASK -> recompute MID
            if m is None and (b is not None) and (a is not None):
                m = (b + a) / 2.0
                logs.append(f"[EntryPrice][SELL] MID missing → recompute MID=(BID+ASK)/2={(b + a)/2.0}")
            # If BID missing but have MID & ASK -> infer BID
            if b is None and (m is not None) and (a is not None):
                b = max(0.0, 2.0 * m - a)
                logs.append(f"[EntryPrice][SELL] BID missing → infer BID=max(0, 2*MID−ASK)={b}")
            # Compute price
            if (b is not None) and (m is not None):
                logs.append(f"[EntryPrice][SELL] price=(BID+MID)/2={(b + m)/2.0} using BID={b}, MID={m}, ASK={a}")
                if logs:
                    for _line in logs:
                        print(_line)
                return (b + m) / 2.0
            # Fallbacks
            if m is not None:
                logs.append(f"[EntryPrice][SELL] fallback price=MID={m} (BID/ASK unavailable)")
                if logs:
                    for _line in logs:
                        print(_line)
                return float(m)
            if b is not None:
                logs.append(f"[EntryPrice][SELL] fallback price=BID={b} (MID/ASK unavailable)")
                if logs:
                    for _line in logs:
                        print(_line)
                return float(b)
            if a is not None:
                logs.append(f"[EntryPrice][SELL] fallback price=ASK={a} (BID/MID unavailable)")
                if logs:
                    for _line in logs:
                        print(_line)
                return float(a)
            raise ValueError("Unable to compute SELL entry price.")

    def __init__(self, data: Dict):
        """
        data should at least include the keys:
          - "MATURITY":    "YYYY-MM-DD"
          - "SCENARIO_DATE": "YYYY-MM-DD"
        """
        self.data = data

    @staticmethod
    def _to_date(s: str) -> date:
        y, m, d = map(int, s.strip().split("-"))
        return date(y, m, d)

    def time_to_maturity(self, maturity: str, scenario_date: str) -> float:
        """
        Return ACT/365 year fraction between scenario_date and maturity.
        """
        d_maturity = self._to_date(maturity)
        d_scn = self._to_date(scenario_date)
        days = (d_maturity - d_scn).days
        if days <= 0:
            return 0.0
        return days / 365.0

    def forward_price(self) -> float:
        spot = self.data["SPOT"]
        price_move = self.data["PRICE_MOVEMENT"]
        beta = self.data["BETA"]
        r = self.data["OPT_FINANCE_RT"] / 100.0   # assuming % input
        q = self.data["OPT_DIV_YIELD"] / 100.0    # assuming % input
        maturity = self.data["MATURITY"]
        scenario_date = self.data["SCENARIO_DATE"]

        # Step 1: Apply price movement shock
        price_after_movement = spot * (1 + price_move * beta)
        # print(f"Price after movement: {price_after_movement:.4f}")

        # Step 2: Calculate forward price
        t = self.time_to_maturity(maturity, scenario_date)
        # print(f"Time to maturity: {t:.4f} years")
        fwd_price = price_after_movement * math.exp((r - q) * t)
        return fwd_price

    def _vol_decimal(self) -> float:
        """Return IVOL_MID_RT as a decimal (assumes percent if > 1)."""
        v = float(self.data["IVOL_MID_RT"])  # required upstream
        return v / 100.0 if v > 1.0 else v

    def compute_d1(self):
        """Compute Black-Scholes d1 using forward, strike, vol, and time to maturity.
        d1 = (ln(F/K) + 0.5 * sigma^2 * T) / (sigma * sqrt(T))
        Stores result on self.d1 and returns it.
        Also stores self.neg_d1 = -self.d1 and returns both.
        """
        F = float(self.forward_price())
        K = float(self.data["STRIKE"])  # expects strike under key "STRIKE"
        sigma = float(self._vol_decimal())
        T = float(self.time_to_maturity(self.data["MATURITY"], self.data["SCENARIO_DATE"]))

        if T <= 0.0 or sigma <= 0.0 or F <= 0.0 or K <= 0.0:
            self.d1 = float("nan")
            self.neg_d1 = float("nan")
            return self.d1, self.neg_d1

        sqrtT = math.sqrt(T)
        self.d1 = (math.log(F / K) + 0.5 * sigma * sigma * T) / (sigma * sqrtT)
        self.neg_d1 = -self.d1
        # print(f"Computed d1: {self.d1:.6f}")
        return self.d1, self.neg_d1
    
    def compute_d2(self):
        """Compute Black-Scholes d2 using d1, vol, and time to maturity.
        d2 = d1 - sigma * sqrt(T)
        Stores result on self.d2 and returns it.
        Also stores self.neg_d2 = -self.d2 and returns both.
        """
        sigma = self._vol_decimal()
        T = self.time_to_maturity(self.data["MATURITY"], self.data["SCENARIO_DATE"])
        # Ensure d1 is computed and valid
        d1 = getattr(self, "d1", float("nan"))
        if not hasattr(self, "d1") or d1 != d1:  # d1 is not set or is NaN
            # compute_d1 now returns (d1, neg_d1)
            d1, _ = self.compute_d1()
        self.d2 = d1 - sigma * math.sqrt(T)
        self.neg_d2 = -self.d2
        # print(f"Computed d2: {self.d2:.6f}")
        return self.d2, self.neg_d2
     
    def compute_normals(self):
        """
        Compute the CDF (standard normal cumulative distribution) for d1 and d2.
        Uses math.erf for the calculation:
        N(x) = 0.5 * (1 + math.erf(x / sqrt(2)))
        Stores results on self.nd1 and self.nd2 and returns them as a tuple.
        Prints debug statements for both.
        """
        # Ensure d1 and d2 are computed and valid; handle tuple returns
        d1_val = getattr(self, "d1", None)
        if d1_val is None or (isinstance(d1_val, float) and d1_val != d1_val):
            d1_val, _ = self.compute_d1()  # returns (d1, neg_d1)
        d2_val = getattr(self, "d2", None)
        if d2_val is None or (isinstance(d2_val, float) and d2_val != d2_val):
            d2_val, _ = self.compute_d2()  # returns (d2, neg_d2)

        # Compute standard normal CDFs
        self.Norm_d1 = 0.5 * (1 + math.erf(d1_val / math.sqrt(2)))
        self.Norm_d2 = 0.5 * (1 + math.erf(d2_val / math.sqrt(2)))
        self.Norm_neg_d1 = 0.5 * (1 + math.erf((-d1_val) / math.sqrt(2)))
        self.Norm_neg_d2 = 0.5 * (1 + math.erf((-d2_val) / math.sqrt(2)))
        # print(f"Computed N(d1): {self.Norm_d1:.6f}")
        # print(f"Computed N(d2): {self.Norm_d2:.6f}")
        # print(f"Computed N(-d1): {self.Norm_neg_d1:.6f}")
        # print(f"Computed N(-d2): {self.Norm_neg_d2:.6f}")
        return self.Norm_d1, self.Norm_d2, self.Norm_neg_d1, self.Norm_neg_d2
    
    def compute_option_prices(self):
        """
        Compute Black-Scholes call and put prices using current scenario data.
        Ensures d1, d2, and their normal CDFs are computed.
        Stores results in self.call_price and self.put_price, and returns them as a tuple.
        Prints debug statements for both.
        """
        # Ensure required values are computed
        self.compute_d1()
        self.compute_d2()
        self.compute_normals()

        # Gather required parameters
        OPT_FINANCE_RT = self.data["OPT_FINANCE_RT"] / 100.0  # assume percent input
        time_to_maturity = self.time_to_maturity(self.data["MATURITY"], self.data["SCENARIO_DATE"])
        forward_price = self.forward_price()
        STRIKE = self.data["STRIKE"]
        Norm_d1 = self.Norm_d1
        Norm_d2 = self.Norm_d2
        Norm_neg_d1 = self.Norm_neg_d1
        Norm_neg_d2 = self.Norm_neg_d2

        # Black-Scholes price formulas
        call_price = math.exp(-OPT_FINANCE_RT * time_to_maturity) * (
            forward_price * Norm_d1 - STRIKE * Norm_d2
        )
        put_price = math.exp(-OPT_FINANCE_RT * time_to_maturity) * (
            STRIKE * Norm_neg_d2 - forward_price * Norm_neg_d1
        )
        self.call_price = call_price
        self.put_price = put_price
        # print(f"Computed call price: {call_price:.6f}")
        # print(f"Computed put price: {put_price:.6f}")
        return self.call_price, self.put_price

    def market_value_after_move(self) -> float:
        """
        Return the market value of the option after the specified price movement.

        Logic:
          - If SCENARIO_DATE > MATURITY: return 0.0
          - If SCENARIO_DATE == MATURITY: return intrinsic value per option * QTY
              * Call: max(PriceAfterMove - STRIKE, 0)
              * Put:  max(STRIKE - PriceAfterMove, 0)
          - If SCENARIO_DATE < MATURITY: compute option price (call/put) and multiply by QTY
        """
        maturity = self._to_date(self.data["MATURITY"])
        scenario_date = self._to_date(self.data["SCENARIO_DATE"])
        qty = int(self.data.get("QTY", 1))
        opt_type = str(self.data["OPTION_TYPE"]).upper()

        # spot after movement (no carry)
        spot = float(self.data["SPOT"]) 
        price_move = float(self.data["PRICE_MOVEMENT"]) 
        beta = float(self.data["BETA"]) 
        price_after_movement = spot * (1.0 + price_move * beta)

        # If scenario after maturity -> worthless
        if scenario_date > maturity:
            print("[MV] Scenario date is after maturity; value = 0.0")
            return 0.0

        # If on maturity -> intrinsic value per option * qty
        if scenario_date == maturity:
            K = float(self.data["STRIKE"]) 
            if opt_type.startswith("C"):
                intrinsic = max(price_after_movement - K, 0.0)
            else:
                intrinsic = max(K - price_after_movement, 0.0)
            mv = intrinsic * qty * 100
            # print(f"[MV] At maturity, intrinsic per option={intrinsic:.6f}, qty={qty}, MV={mv:.6f}")
            return mv

        # Otherwise before maturity -> BS price per option times qty
        self.compute_option_prices()
        if opt_type.startswith("C"):
            mv = float(self.call_price) * qty * 100
        else:
            mv = float(self.put_price) * qty * 100
        # print(f"[MV] Before maturity, option price per option={(self.call_price if opt_type.startswith('C') else self.put_price):.6f}, qty={qty}, MV={mv:.6f}")
        return mv

    def profit_from_move(self) -> float:
        """
        Calculate the profit on the option from the price movement.
        Profit = Market Value after move - Original Value
        Original Value is calculated as average of PX_MID and PX_ASK times quantity times 100.
        """
        orig_price = self.entry_price_from_snapshot()
        qty = int(self.data.get("QTY", 1))
        opt_type = str(self.data["OPTION_TYPE"]).upper()
        mv_after = self.market_value_after_move()
        original_value = orig_price * qty * 100
        profit = mv_after - original_value
        # print(f"[Profit] Original Value: {original_value:.6f}, Market Value After Move: {mv_after:.6f}, Profit: {profit:.6f}")
        return profit

    def deltas_after_move(self):
        """
        Return a dict with delta metrics after the price movement.

        DELTA_MID_POST = N(d1) if OPTION_TYPE == 'C' else -N(-d1)
        DELTA_NOTIONAL_POST = price_after_movement * QTY * MULTIPLIER * DELTA_MID_POST
        """
        # Ensure normals are computed based on the shocked forward/spot
        self.compute_normals()

        opt_type = str(self.data["OPTION_TYPE"]).upper()
        qty = int(self.data.get("QTY", 1))
        multiplier = int(self.data.get("MULTIPLIER", 100))

        # spot after movement (no carry)
        spot = float(self.data["SPOT"]) 
        price_move = float(self.data["PRICE_MOVEMENT"]) 
        beta = float(self.data["BETA"]) 
        price_after_movement = spot * (1.0 + price_move * beta)

        # Compute delta mid post move
        if opt_type.startswith("C"):
            delta_mid_post = float(self.Norm_d1)
        else:  # Put
            delta_mid_post = -float(self.Norm_neg_d1)

        delta_notional_post = price_after_movement * qty * multiplier * delta_mid_post

        # print(f"[Delta] Post-move delta: {delta_mid_post:.6f}, Notional: {delta_notional_post:.6f}")
        return {
            "DELTA_MID_POST": delta_mid_post,
            "DELTA_NOTIONAL_POST": delta_notional_post,
        }
    
    def generate_percent_range(self):
        min_val = self.data["MIN"]
        max_val = self.data["MAX"]
        intervals = self.data["INTERVALS"]
        return [min_val + i * (max_val - min_val) / (intervals - 1) for i in range(intervals)]
    
    def generate_profit_curve(self):
        profits = []
        for move in self.generate_percent_range():
            self.data["PRICE_MOVEMENT"] = move
            profits.append(self.profit_from_move())
        return profits

    def generate_profit_curves_for_dates(self, scenario_dates):
        """
        Given an iterable of scenario date strings ("YYYY-MM-DD"), compute a profit curve
        (list of profits from MIN..MAX with INTERVALS steps) for each date.

        Returns a dict: { scenario_date_str: [profit_at_each_PRICE_MOVEMENT,...] }
        The PRICE_MOVEMENT grid is taken from generate_percent_range().
        """
        # Preserve original scenario date
        original_date = self.data.get("SCENARIO_DATE")
        movements = self.generate_percent_range()
        curves = {}

        for dt in scenario_dates:
            self.data["SCENARIO_DATE"] = dt
            profits = []
            for move in movements:
                self.data["PRICE_MOVEMENT"] = move
                profits.append(self.profit_from_move())
            curves[dt] = profits

        # Restore original scenario date
        if original_date is not None:
            self.data["SCENARIO_DATE"] = original_date

        return curves
    
def portfolio_profit_curves(data_legs, scenario_dates):
    """
    Build portfolio profit curves by summing leg PnL across a shared PRICE_MOVEMENT grid.

    Parameters
    ----------
    data_legs : list[dict]
        Each dict is a fully-formed leg input for ScenarioRunner.
        Assumes MIN, MAX, INTERVALS are aligned across legs (we use grid from the first leg).
    scenario_dates : iterable[str]
        Iterable of scenario date strings "YYYY-MM-DD".

    Returns
    -------
    moves : list[float]
        The shared PRICE_MOVEMENT grid from MIN..MAX inclusive.
    totals : dict[str, list[float]]
        For each scenario date, the portfolio total PnL curve over `moves`.
    per_leg : dict[str, list[list[float]]]
        For each scenario date, a list of per-leg curves (one list per leg).
    """
    if not data_legs:
        return [], {}, {}

    # Instantiate runners on copies to avoid mutating caller's dicts
    runners = [ScenarioRunner(deepcopy(d)) for d in data_legs]

    # Shared grid from the first leg
    moves = runners[0].generate_percent_range()

    totals = {}
    per_leg = {}

    for dt in scenario_dates:
        leg_curves = []

        for r in runners:
            # Preserve and set scenario date
            original_date = r.data.get("SCENARIO_DATE")
            r.data["SCENARIO_DATE"] = dt

            # Build curve for this leg on the shared grid
            curve = []
            for mv in moves:
                r.data["PRICE_MOVEMENT"] = mv
                curve.append(r.profit_from_move())
            leg_curves.append(curve)

            # Restore original date (if any)
            if original_date is not None:
                r.data["SCENARIO_DATE"] = original_date

        # Sum across legs point-by-point
        totals[dt] = [sum(vals) for vals in zip(*leg_curves)]
        per_leg[dt] = leg_curves

    return moves, totals, per_leg