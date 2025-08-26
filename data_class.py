
from __future__ import annotations
import json
import os
import re
from datetime import date
from typing import Any, Dict, List, Optional
 
HOST = "127.0.0.1"
PORT = 8194
REFDATA_SVC = "//blp/refdata"
 
try:
    import blpapi  # type: ignore
except Exception:
    blpapi = None
 
_DEF_RX = re.compile(
        r"""
        ^\s*
        (?P<under>[A-Z0-9]+)         # Underlying root (e.g., VXX, VXX2)
        \s+[A-Z]{2}\s+               # Country code (e.g., US)
        (?P<mdy>\d{2}/\d{2}/\d{2,4}) # Expiry date MM/DD/YY or MM/DD/YYYY
        \s+(?P<right>[CP])\s*        # Right (C or P)
        (?P<strike>\d+(?:\.\d+)?)    # Strike (int or decimal)
        \b
        """,
        re.VERBOSE
    )
 
# -----------------------------
# Bloomberg client class
# -----------------------------
class BloombergClient:
    def __init__(self, host: str = HOST, port: int = PORT):
        if blpapi is None:
            raise RuntimeError("blpapi not installed")
        opts = blpapi.SessionOptions()
        opts.setServerHost(host)
        opts.setServerPort(port)
        opts.setServiceCheckTimeout(5000)
        self._session = blpapi.Session(opts)
        if not self._session.start():
            raise RuntimeError("Failed to start Bloomberg session. Is the Terminal running?")
        if not self._session.openService(REFDATA_SVC):
            raise RuntimeError(f"Could not open {REFDATA_SVC}")
        self._svc = self._session.getService(REFDATA_SVC)
 
    # Context-manager support (optional)
    def __enter__(self) -> "BloombergClient":
        return self
 
    def __exit__(self, exc_type, exc, tb):
        self.close()
 
    def close(self):
        try:
            self._session.stop()
        except Exception:
            pass
 
    # --------------
    # Internals
    # --------------
    @staticmethod
    def _ensure_equity_ticker(t: str) -> str:
        """If no asset-class suffix present, assume 'US Equity'."""
        t = (t or "").strip()
        if "<" in t or t.upper().endswith("EQUITY"):
            return t
        parts = t.split()
        return f"{t} US Equity" if len(parts) == 1 else t
 
    @staticmethod
    def _wait(session: "blpapi.Session", cid: "blpapi.CorrelationId"):
        msgs = []
        while True:
            ev = session.nextEvent(10000)
            et = ev.eventType()
            if et in (blpapi.Event.PARTIAL_RESPONSE, blpapi.Event.RESPONSE):
                for msg in ev:
                    if msg.correlationIds() and cid in msg.correlationIds():
                        msgs.append(msg)
                if et == blpapi.Event.RESPONSE:
                    break
            elif et == blpapi.Event.SESSION_STATUS:
                for msg in ev:
                    if msg.messageType() == blpapi.Name("SessionTermination"):
                        raise RuntimeError("Session terminated while waiting for response")
        return msgs
 
    def _refdata(self, securities: List[str], fields: List[str], overrides: Optional[Dict[str, Any]] = None) -> List["blpapi.Message"]:
        req = self._svc.createRequest("ReferenceDataRequest")
        sec_el = req.getElement("securities")
        for s in securities:
            sec_el.appendValue(s)
        fld_el = req.getElement("fields")
        for f in fields:
            fld_el.appendValue(f)
        if overrides:
            ovrs = req.getElement("overrides")
            for k, v in overrides.items():
                o = ovrs.appendElement()
                o.setElement("fieldId", k)
                o.setElement("value", str(v))
        cid = blpapi.CorrelationId()
        self._session.sendRequest(req, correlationId=cid)
        return self._wait(self._session, cid)
   
    # -----------------------------
    # Regex + parser for OPT_CHAIN
    # -----------------------------
 
    def _normalize_mdy(self, mdy: str) -> str:
        mm, dd, yy = mdy.split("/")
        y = int(yy)
        if len(yy) == 2:
            y = 2000 + y if y <= 79 else 1900 + y
        return f"{int(y):04d}-{int(mm):02d}-{int(dd):02d}"
 
    def parse_opt_chain_descriptions(self, descriptions: List[str]) -> Dict[str, Dict[str, Dict[str, Dict[str, List[str]]]]]:
        """
        Returns nested dict:
        { YYYY-MM-DD: {
            'C': {
                '25': {
                'VXX': ['VXX US 08/15/25 C25 Equity', ...],
                'VXX2': [...],
                },
                ...
            },
            'P': { ... }
            },
            ...
        }
        """
        out: Dict[str, Dict[str, Dict[str, Dict[str, List[str]]]]] = {}
        # Build with sets to dedupe, convert to list at end
        tmp: Dict[str, Dict[str, Dict[str, Dict[str, set]]]] = {}
        for s in descriptions:
            m = _DEF_RX.search(s)
            if not m:
                continue
            under = m.group("under")
            mdy   = m.group("mdy")
            right = m.group("right")
            raw_strike = m.group("strike")
            strike_str = raw_strike.rstrip("0").rstrip(".") if "." in raw_strike else raw_strike
            ymd = self._normalize_mdy(mdy)
 
            tmp.setdefault(ymd, {}).setdefault(right, {}).setdefault(strike_str, {}).setdefault(under, set()).add(s)
 
        # Convert sets → sorted lists; also ensure 'C' and 'P' keys exist
        for ymd, rights in tmp.items():
            out[ymd] = {'C': {}, 'P': {}}
            for right, strikes in rights.items():
                for strike, under_map in strikes.items():
                    out[ymd][right].setdefault(strike, {})
                    for under, desc_set in under_map.items():
                        out[ymd][right][strike][under] = sorted(desc_set)
        return out
 
    # --------------
    # Public API
    # --------------
 
    def get_equity_px_mid(self, full_equity: str) -> float:
        """
        Given a full equity name (e.g., 'AAPL US Equity'), return PX_MID as an int.
        NOTE: Returns a Float. For Jia or future reference, replace `int(px)` with `round(px)` if preferred.
        """
        sec = self._ensure_equity_ticker(full_equity)
        msgs = self._refdata([sec], ["PX_MID"])
        for msg in msgs:
            if not msg.hasElement("securityData"):
                continue
            arr = msg.getElement("securityData")
            for i in range(arr.numValues()):
                sec_block = arr.getValueAsElement(i)
                if sec_block.hasElement("securityError"):
                    raise RuntimeError(sec_block.getElement("securityError").toString())
                if not sec_block.hasElement("fieldData"):
                    continue
                fdata = sec_block.getElement("fieldData")
                if fdata.hasElement("PX_MID"):
                    px = fdata.getElementAsFloat("PX_MID")
                    return px  # truncate; change to round(px) if you want rounding
        raise RuntimeError(f"PX_MID not returned for '{full_equity}'")
 
    def get_option_snapshot(self, full_option: str) -> Dict[str, Optional[float]]:
        """
        Given a full option security name (e.g., 'VXX US 08/15/25 C25 Equity'),
        return a dict of the requested fields.
        Missing fields will appear with value None.
        """
        fields = [
            "OPT_FINANCE_RT",
            "OPT_DIV_YIELD",
            "PX_BID",
            "PX_MID",
            "PX_ASK",
            "DELTA_MID_RT",
            "GAMMA_MID_RT",
            "VEGA_MID_RT",
            "IVOL_MID_RT",
            "THETA_MID_RT",
        ]
        # Do not alter full option string; users pass the full name already.
        msgs = self._refdata([full_option], fields)
        out: Dict[str, Optional[float]] = {f: None for f in fields}
        for msg in msgs:
            if not msg.hasElement("securityData"):
                continue
            arr = msg.getElement("securityData")
            for i in range(arr.numValues()):
                sec_block = arr.getValueAsElement(i)
                if sec_block.hasElement("securityError"):
                    raise RuntimeError(sec_block.getElement("securityError").toString())
                if not sec_block.hasElement("fieldData"):
                    continue
                fdata = sec_block.getElement("fieldData")
                # Try retrieving as float; fall back to string then None
                for f in fields:
                    if fdata.hasElement(f):
                        try:
                            out[f] = fdata.getElementAsFloat(f)
                        except Exception:
                            try:
                                # sometimes returned as string/enum; you can store as string if you prefer
                                out[f] = float(fdata.getElementAsString(f))
                            except Exception:
                                out[f] = None
        return out
 
    def get_opt_chain_descriptions(self, underlying_equity: str, option_chain_override: Optional[str] = "A") -> List[str]:
        """
        Return the Bloomberg bulk OPT_CHAIN 'Security Description' list for an underlying equity.
        If `option_chain_override` is provided (e.g., "W/M"), it is sent as the
        Bloomberg override field `OPTION_CHAIN_OVERRIDE` on the OPT_CHAIN request.
        Pass None to skip the override.        
        """
        sec = self._ensure_equity_ticker(underlying_equity)
        overrides = {"OPTION_CHAIN_OVERRIDE": option_chain_override} if option_chain_override else None
        msgs = self._refdata([sec], ["OPT_CHAIN"], overrides=overrides)
        out: List[str] = []
        for msg in msgs:
            if not msg.hasElement("securityData"):
                continue
            arr = msg.getElement("securityData")
            for i in range(arr.numValues()):
                sec_block = arr.getValueAsElement(i)
                if sec_block.hasElement("securityError"):
                    raise RuntimeError(sec_block.getElement("securityError").toString())
                if not sec_block.hasElement("fieldData"):
                    continue
                fdata = sec_block.getElement("fieldData")
                if not fdata.hasElement("OPT_CHAIN"):
                    continue
                bulk = fdata.getElement("OPT_CHAIN")  # array of sequence rows
                for j in range(bulk.numValues()):
                    row = bulk.getValueAsElement(j)
                    if row.hasElement("Security Description"):
                        out.append(row.getElementAsString("Security Description"))
        return out
 
    # --------------
    # Chain Search Helpers
    # --------------
 
    def list_maturities(self, tree: dict) -> list[str]:
        """Return all maturity dates (YYYY-MM-DD) sorted ascending."""
        return sorted(tree.keys())
 
    def list_rights_for_date(self, tree: dict, ymd: str) -> list[str]:
        if ymd not in tree:
            return []
        return [r for r in ("C","P") if tree[ymd].get(r)]
 
    def list_strikes(self, tree: dict, ymd: str, right: str) -> list[str]:
        r = tree.get(ymd, {}).get(right.upper(), {})
        return sorted(r.keys(), key=lambda x: float(x))
 
    def list_underlyings(self, tree: dict, ymd: str, right: str, strike: str) -> list[str]:
        return sorted(tree.get(ymd, {}).get(right.upper(), {}).get(strike, {}).keys())
 
    def get_descriptions(self, tree: dict, ymd: str, right: str, strike: str, underlying: str) -> str:
        """Return the string of full Security Description strings for this node."""
        return tree.get(ymd, {}).get(right.upper(), {}).get(strike, {}).get(underlying, [])[0]
 


