#!/usr/bin/env python3
"""
Vantage report builder.

Reads tickers.json, pulls free data from Yahoo Finance (via the yfinance library),
computes the checklist metrics in code, scores each one with simple thresholds,
and writes data/reports.json for the website to display.

No paid APIs and no AI calls. Every number is calculated here, not guessed.
Note: yfinance is an unofficial library. It is fine for personal research, but it can
break when Yahoo changes things, and it is not meant for commercial products.
"""
import json
import math
import time
import datetime as dt
from pathlib import Path

import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parent.parent
TICKERS_FILE = ROOT / "tickers.json"
OUT_FILE = ROOT / "data" / "reports.json"

# ---------------------------------------------------------------------------
# Thresholds. (good, bad, higher_is_better, plain-English rule)
# Edit these numbers to change how items are scored. They are shown on the
# site's Assumptions section so you can always see why something was rated.
# ---------------------------------------------------------------------------
T = {
    "rev_cagr":       (0.08, 0.0,   True,  "Revenue growth per year: 8% or more is strong, below 0% is a concern"),
    "gm_change":      (0.01, -0.03, True,  "Gross margin change over the period: up 1 point or more is strong, down 3 points or more is a concern"),
    "op_margin":      (0.15, 0.0,   True,  "Operating margin: 15% or more is strong, below 0% is a concern"),
    "net_margin":     (0.10, 0.0,   True,  "Net margin: 10% or more is strong, below 0% is a concern"),
    "fcf_margin":     (0.10, 0.0,   True,  "Free cash flow margin: 10% or more is strong, below 0% is a concern"),
    "roe":            (0.15, 0.05,  True,  "Return on equity: 15% or more is strong, below 5% is a concern"),
    "debt_equity":    (1.0,  2.0,   False, "Debt to equity: 1.0 or lower is strong, above 2.0 is a concern"),
    "interest_cov":   (6.0,  2.0,   True,  "Interest coverage (operating profit / interest): 6x or more is strong, below 2x is a concern"),
    "current_ratio":  (1.5,  1.0,   True,  "Current ratio: 1.5 or more is strong, below 1.0 is a concern"),
    "pe":             (20,   40,    False, "P/E: 20 or lower is strong, above 40 is a concern (negative earnings are flagged)"),
    "ps":             (3,    10,    False, "Price to sales: 3 or lower is strong, above 10 is a concern"),
    "ev_ebitda":      (12,   25,    False, "EV/EBITDA: 12 or lower is strong, above 25 is a concern"),
    "peg":            (1.5,  3.0,   False, "PEG ratio: 1.5 or lower is strong, above 3 is a concern"),
    "p_fcf":          (20,   50,    False, "Price to free cash flow: 20 or lower is strong, above 50 is a concern"),
    "share_change":   (0.005, 0.04, False, "Share count growth per year: under 0.5% is strong, above 4% is a concern (dilution)"),
    "sbc_pct":        (0.03, 0.10,  False, "Stock-based pay as a share of revenue: under 3% is strong, above 10% is a concern"),
    "cash_conv":      (1.0,  0.5,   True,  "Operating cash flow / net income: 1.0 or more is strong, below 0.5 is a concern"),
    "insider_ratio":  (2.0,  10.0,  False, "Insider sales per purchase in recent filings: 2 or fewer is strong, more than 10 is a concern"),
    "beta":           (1.0,  1.8,   False, "Beta (swings vs the market): 1.0 or lower is strong, above 1.8 is a concern"),
    "dollar_volume":  (5e6,  5e5,   True,  "Average daily dollar volume: $5M or more is strong, below $500K is a concern (hard to trade)"),
    "short_pct":      (0.05, 0.15,  False, "Short interest as share of float: under 5% is strong, above 15% is a concern"),
    "inst_pct":       (0.40, 0.10,  True,  "Institutional ownership: 40% or more is strong, below 10% is a concern"),
    "vs_200d":        (0.0, -0.15,  True,  "Price vs 200-day average: at or above is strong, more than 15% below is a concern"),
}


def rate(key, value):
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "na"
    good, bad, higher, _ = T[key]
    if higher:
        return "good" if value >= good else "bad" if value < bad else "warn"
    return "good" if value <= good else "bad" if value > bad else "warn"


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------
def pct(x, digits=1):
    return "n/a" if x is None else f"{x * 100:.{digits}f}%"


def mult(x, digits=1):
    return "n/a" if x is None else f"{x:.{digits}f}x"


def money(x):
    if x is None:
        return "n/a"
    sign = "-" if x < 0 else ""
    x = abs(x)
    for limit, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if x >= limit:
            return f"{sign}{x / limit:.2f}{suffix}"
    return f"{sign}{x:.0f}"


def clean(x):
    """Return a float or None (handles NaN, strings, missing)."""
    try:
        v = float(x)
        return None if math.isnan(v) or math.isinf(v) else v
    except (TypeError, ValueError):
        return None


def get_row(df, *names):
    """First matching row of a yfinance statement, oldest to newest, NaNs dropped."""
    if df is None or getattr(df, "empty", True):
        return None
    for n in names:
        if n in df.index:
            s = df.loc[n].dropna()
            if len(s):
                return s.sort_index()
    return None


def last(s):
    return None if s is None or len(s) == 0 else clean(s.iloc[-1])


def item(label, value, status, note="", source="Yahoo Finance"):
    return {"label": label, "value": value, "status": status, "note": note, "source": source}


def safe_div(a, b):
    a, b = clean(a), clean(b)
    if a is None or b is None or b == 0:
        return None
    return a / b


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------
def business_section(info):
    return {
        "id": "business",
        "title": "Business",
        "items": [
            item("Sector and industry", f"{info.get('sector', 'n/a')} / {info.get('industry', 'n/a')}", "info",
                 "Read the business summary below and confirm you can explain how it makes money in one sentence."),
            item("Market cap", money(clean(info.get("marketCap"))), "info", "Company size on the market."),
            item("Employees", f"{int(info['fullTimeEmployees']):,}" if info.get("fullTimeEmployees") else "n/a", "info"),
        ],
    }


def growth_section(inc):
    items = []
    rev = get_row(inc, "Total Revenue", "Operating Revenue")
    if rev is not None and len(rev) >= 2:
        yoy = safe_div(rev.iloc[-1], rev.iloc[-2])
        yoy = None if yoy is None else yoy - 1
        years = len(rev) - 1
        cagr = None
        if rev.iloc[0] and rev.iloc[0] > 0 and rev.iloc[-1] > 0:
            cagr = (rev.iloc[-1] / rev.iloc[0]) ** (1 / years) - 1
        items.append(item("Revenue growth, latest year", pct(yoy), rate("rev_cagr", yoy),
                          "Compared with the prior fiscal year.", "Annual income statement"))
        items.append(item(f"Revenue growth per year ({years}-year)", pct(cagr), rate("rev_cagr", cagr),
                          "Compound annual growth across the years available.", "Annual income statement"))
    else:
        items.append(item("Revenue growth", "n/a", "na", "Not enough annual data found."))

    gp = get_row(inc, "Gross Profit")
    if rev is not None and gp is not None and len(gp) >= 2:
        margins = (gp / rev).dropna()
        if len(margins) >= 2:
            change = margins.iloc[-1] - margins.iloc[0]
            items.append(item("Gross margin trend", f"{pct(margins.iloc[-1])} (change {change * 100:+.1f} pts)",
                              rate("gm_change", change), "Rising margins can signal pricing power or scale.",
                              "Annual income statement"))
    return {"id": "growth", "title": "Growth drivers", "items": items}


def profitability_section(inc, cf, bal):
    items = []
    rev = get_row(inc, "Total Revenue", "Operating Revenue")
    op = get_row(inc, "Operating Income")
    ni = get_row(inc, "Net Income", "Net Income Common Stockholders")
    fcf = get_row(cf, "Free Cash Flow")
    eq = get_row(bal, "Stockholders Equity", "Common Stock Equity")

    om = safe_div(last(op), last(rev))
    nm = safe_div(last(ni), last(rev))
    fm = safe_div(last(fcf), last(rev))
    roe = safe_div(last(ni), last(eq))

    items.append(item("Operating margin", pct(om), rate("op_margin", om), "Profit from operations as a share of sales.", "Annual income statement"))
    items.append(item("Net margin", pct(nm), rate("net_margin", nm), "Bottom-line profit as a share of sales.", "Annual income statement"))
    items.append(item("Free cash flow margin", pct(fm), rate("fcf_margin", fm), f"Free cash flow: {money(last(fcf))}.", "Annual cash flow statement"))
    items.append(item("Return on equity", pct(roe), rate("roe", roe), "How much profit is earned on shareholders' money.", "Annual statements"))
    if last(ni) is not None and last(ni) < 0:
        items.append(item("Profitability", "Net loss", "bad", "The company lost money last year. Check its cash runway and path to profit in the filings.", "Annual income statement"))
    return {"id": "profitability", "title": "Profitability and cash", "items": items}


def balance_section(inc, bal):
    items = []
    debt = last(get_row(bal, "Total Debt"))
    cash = last(get_row(bal, "Cash Cash Equivalents And Short Term Investments", "Cash And Cash Equivalents"))
    eq = last(get_row(bal, "Stockholders Equity", "Common Stock Equity"))
    de = safe_div(debt, eq)
    items.append(item("Debt to equity", mult(de, 2), rate("debt_equity", de), f"Total debt {money(debt)} vs equity {money(eq)}.", "Annual balance sheet"))

    if debt is not None and cash is not None:
        net = debt - cash
        items.append(item("Net debt", money(net), "good" if net <= 0 else "info",
                          "Negative means more cash than debt. Check debt maturity dates in the 10-K.", "Annual balance sheet"))

    ebit = last(get_row(inc, "EBIT", "Operating Income"))
    interest = last(get_row(inc, "Interest Expense", "Interest Expense Non Operating"))
    cov = safe_div(ebit, abs(interest)) if interest else None
    items.append(item("Interest coverage", mult(cov), rate("interest_cov", cov),
                      "Operating profit divided by interest cost." if cov is not None else "No interest expense found, or not reported.",
                      "Annual statements"))

    cr = safe_div(last(get_row(bal, "Current Assets")), last(get_row(bal, "Current Liabilities")))
    items.append(item("Current ratio", mult(cr, 2), rate("current_ratio", cr), "Can it cover bills due within a year?", "Annual balance sheet"))
    return {"id": "balance", "title": "Balance sheet", "items": items}


def valuation_section(info, cf, price):
    items = []
    trailing = clean(info.get("trailingPE"))
    if trailing is None and clean(info.get("trailingEps")) is not None and clean(info.get("trailingEps")) <= 0:
        items.append(item("P/E (trailing)", "Negative earnings", "bad", "No P/E because the company is not profitable.", "Yahoo Finance"))
    else:
        items.append(item("P/E (trailing)", mult(trailing), rate("pe", trailing), "Compare with competitors and the company's own history.", "Yahoo Finance"))
    fwd = clean(info.get("forwardPE"))
    items.append(item("P/E (forward)", mult(fwd), rate("pe", fwd), "Based on analyst earnings estimates.", "Yahoo Finance"))
    ps = clean(info.get("priceToSalesTrailing12Months"))
    items.append(item("Price to sales", mult(ps), rate("ps", ps), "", "Yahoo Finance"))
    ev = clean(info.get("enterpriseToEbitda"))
    items.append(item("EV/EBITDA", mult(ev), rate("ev_ebitda", ev), "", "Yahoo Finance"))
    peg = clean(info.get("trailingPegRatio")) or clean(info.get("pegRatio"))
    items.append(item("PEG ratio", mult(peg, 2), rate("peg", peg), "P/E relative to expected growth.", "Yahoo Finance"))
    fcf = last(get_row(cf, "Free Cash Flow"))
    mcap = clean(info.get("marketCap"))
    pfcf = safe_div(mcap, fcf) if fcf and fcf > 0 else None
    items.append(item("Price to free cash flow", mult(pfcf), rate("p_fcf", pfcf),
                      "Not meaningful while free cash flow is negative." if fcf is not None and fcf <= 0 else "", "Yahoo Finance and cash flow statement"))
    return {"id": "valuation", "title": "Valuation", "items": items}


def trust_section(inc, cf, bal, tk):
    items = []
    # Dilution
    shares = get_row(bal, "Ordinary Shares Number", "Share Issued")
    if shares is not None and len(shares) >= 2 and shares.iloc[0] > 0:
        years = len(shares) - 1
        change = (shares.iloc[-1] / shares.iloc[0]) ** (1 / years) - 1
        items.append(item(f"Share count change per year ({years}-year)", pct(change, 2), rate("share_change", change),
                          "Rising share counts dilute existing owners. Falling counts mean buybacks.", "Annual balance sheet"))
    else:
        items.append(item("Share count change", "n/a", "na", "Share history not found."))

    rev = last(get_row(inc, "Total Revenue", "Operating Revenue"))
    sbc = last(get_row(cf, "Stock Based Compensation"))
    sbc_pct = safe_div(sbc, rev)
    items.append(item("Stock-based pay vs revenue", pct(sbc_pct), rate("sbc_pct", sbc_pct), "Heavy stock pay is a hidden cost to shareholders.", "Annual cash flow statement"))

    ocf = last(get_row(cf, "Operating Cash Flow", "Cash Flow From Continuing Operating Activities"))
    ni = last(get_row(inc, "Net Income", "Net Income Common Stockholders"))
    conv = safe_div(ocf, ni) if ni and ni > 0 else None
    items.append(item("Cash conversion", mult(conv, 2), rate("cash_conv", conv),
                      "Profit that does not turn into cash can point to aggressive accounting." if conv is not None else "Not meaningful without positive net income.",
                      "Annual statements"))

    # Insider activity (best effort, Yahoo data is limited)
    try:
        tx = tk.insider_transactions
        buys = sells = 0
        if tx is not None and not tx.empty:
            text_col = "Text" if "Text" in tx.columns else None
            for _, row in tx.iterrows():
                text = str(row.get(text_col, "")) if text_col else ""
                tl = text.lower()
                if "purchase" in tl or "buy" in tl:
                    buys += 1
                elif "sale" in tl or "sold" in tl:
                    sells += 1
        if buys + sells == 0:
            items.append(item("Insider buying and selling", "No clear data", "na", "Check Form 4 filings on SEC EDGAR (link below).", "Yahoo Finance"))
        else:
            ratio = sells / max(buys, 1)
            items.append(item("Insider buying and selling", f"{buys} purchases, {sells} sales", rate("insider_ratio", ratio),
                              "Sales are common for pay reasons. Open-market purchases are the stronger signal.", "Yahoo Finance"))
    except Exception:
        items.append(item("Insider buying and selling", "n/a", "na", "Could not load insider data."))
    return {"id": "trust", "title": "Trust and red flags", "items": items}


def risk_section(info):
    beta = clean(info.get("beta"))
    return {
        "id": "risks",
        "title": "Risks and competition",
        "items": [
            item("Beta", mult(beta, 2), rate("beta", beta), "How much the stock tends to swing compared with the market.", "Yahoo Finance"),
            item("Competitors, threats, legal issues", "Manual check", "info", "See the manual checks below. Code cannot judge these reliably.", "You"),
        ],
    }


def market_section(info, hist, tk):
    items = []
    price = clean(info.get("currentPrice")) or clean(info.get("regularMarketPrice"))
    avg_vol = clean(info.get("averageVolume"))
    dollar = avg_vol * price if avg_vol and price else None
    items.append(item("Average daily dollar volume", money(dollar), rate("dollar_volume", dollar), "Low trading volume makes it harder to buy or sell at a fair price.", "Yahoo Finance"))
    sp = clean(info.get("shortPercentOfFloat"))
    items.append(item("Short interest (share of float)", pct(sp), rate("short_pct", sp), "High short interest means many investors are betting against it.", "Yahoo Finance"))
    inst = clean(info.get("heldPercentInstitutions"))
    items.append(item("Institutional ownership", pct(inst), rate("inst_pct", inst), "", "Yahoo Finance"))
    avg200 = clean(info.get("twoHundredDayAverage"))
    v200 = safe_div(price, avg200)
    v200 = None if v200 is None else v200 - 1
    items.append(item("Price vs 200-day average", pct(v200), rate("vs_200d", v200), "Shows the longer-term trend.", "Yahoo Finance"))
    lo, hi = clean(info.get("fiftyTwoWeekLow")), clean(info.get("fiftyTwoWeekHigh"))
    if lo is not None and hi is not None and price is not None:
        items.append(item("52-week range", f"{lo:.2f} to {hi:.2f}", "info", f"Current price {price:.2f}. Be careful buying right after a spike.", "Yahoo Finance"))
    try:
        cal = tk.calendar
        ed = cal.get("Earnings Date") if isinstance(cal, dict) else None
        if ed:
            ed = ed[0] if isinstance(ed, (list, tuple)) else ed
            items.append(item("Next earnings date", str(ed), "info", "Prices often move sharply on earnings day.", "Yahoo Finance"))
    except Exception:
        pass
    return {"id": "market", "title": "Market behavior", "items": items}


def build_report(symbol):
    tk = yf.Ticker(symbol)
    info = tk.info or {}
    inc, bal, cf = tk.income_stmt, tk.balance_sheet, tk.cashflow
    price = clean(info.get("currentPrice")) or clean(info.get("regularMarketPrice"))
    prev = clean(info.get("previousClose")) or clean(info.get("regularMarketPreviousClose"))
    change = None if price is None or not prev else (price / prev - 1)

    sections = [
        business_section(info),
        growth_section(inc),
        profitability_section(inc, cf, bal),
        balance_section(inc, bal),
        valuation_section(info, cf, price),
        trust_section(inc, cf, bal, tk),
        risk_section(info),
        market_section(info, None, tk),
    ]
    short = symbol.split(".")[0]
    return {
        "name": info.get("longName") or info.get("shortName") or symbol,
        "currency": info.get("currency", ""),
        "exchange": info.get("exchange", ""),
        "price": price,
        "change_pct": change,
        "summary": (info.get("longBusinessSummary") or "")[:600],
        "as_of": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"),
        "sections": sections,
        "manual": [
            {"q": "Can you explain in one sentence how this company makes money, and who its biggest customers are?",
             "link": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={short}&type=10-K", "link_label": "Latest annual report (SEC EDGAR)"},
            {"q": "Does it have a real moat: brand, switching costs, network effects, or a cost advantage?", "link": f"https://finance.yahoo.com/quote/{symbol}/profile", "link_label": "Company profile"},
            {"q": "Who are the top three competitors, and is this company gaining or losing share?", "link": f"https://finance.yahoo.com/quote/{symbol}", "link_label": "Quote page"},
            {"q": "Any lawsuits, regulatory probes, auditor changes, restatements, or CFO departures?", "link": f"https://finance.yahoo.com/quote/{symbol}/news", "link_label": "Recent news"},
            {"q": "Has management hit its past guidance? Read the last two earnings calls.", "link": f"https://finance.yahoo.com/quote/{symbol}/analysis", "link_label": "Analyst estimates"},
            {"q": "Insider purchases and sales (Form 4 filings).", "link": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={short}&type=4", "link_label": "Form 4 filings (SEC EDGAR)"},
        ],
    }


def main():
    tickers = json.loads(TICKERS_FILE.read_text())
    reports, errors = {}, {}
    for symbol in tickers:
        symbol = symbol.strip().upper()
        try:
            reports[symbol] = build_report(symbol)
            print(f"ok   {symbol}")
        except Exception as exc:  # keep going if one ticker fails
            errors[symbol] = str(exc)
            print(f"FAIL {symbol}: {exc}")
        time.sleep(1.5)  # be polite to the data source

    if not reports:
        raise SystemExit("No reports built. Keeping the previous data file unchanged.")

    out = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"),
        "sample": False,
        "assumptions": [v[3] for v in T.values()],
        "errors": errors,
        "reports": reports,
    }
    OUT_FILE.parent.mkdir(exist_ok=True)
    OUT_FILE.write_text(json.dumps(out, indent=2))
    print(f"Wrote {OUT_FILE} with {len(reports)} reports.")


if __name__ == "__main__":
    main()
