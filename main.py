import os
import time
import random
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timezone

# ---------- Config ----------
TICKERS = [
    "MSN","SAB","VNM","GVR","MWG","DGW","FRT","PNJ","IMP","DHG",
    "MBB","VCB","BID","FOX","FPT","HPG","DGC","CTR","VCG","PC1",
    "GMD","POW","QTP",
    "VIC","VHM","DXG","DIG","KDH","KDC","KBC","DPM","PDR","STB",
    "SHB","SSI","HUT","VCI","VJC","GEX","EIB","PLX","VRE","VIX",
    "VND","MCH","VPL","TCX","NVL"
]

REPORT_FACTOR = 0.9
BARGAIN_FACTOR = 0.8
LOOKBACK_YEARS = 1
PAGE_SIZE = 50
MAX_PAGES = 50

# ---------- API endpoints ----------
REPORT_LIST_URL = "https://api2.simplize.vn/api/company/analysis-report/list"
QUOTE_URL_TMPL = "https://api2.simplize.vn/api/historical/quote/{ticker}"

HEADERS = {
    "user-agent": "Mozilla/5.0",
    "accept": "application/json, text/plain, */*",
    "origin": "https://simplize.vn",
}

# Optional: gentle pacing to avoid looking like a bot
MIN_DELAY_S = 0.1
MAX_DELAY_S = 0.4

# ---------- Functions ----------
def fetch_current_price(ticker: str) -> float:
    url = QUOTE_URL_TMPL.format(ticker=ticker)
    h = {**HEADERS, "referer": f"https://simplize.vn/co-phieu/{ticker}"}
    r = requests.get(url, headers=h, timeout=30)
    r.raise_for_status()
    js = r.json()
    return float(js["data"]["priceClose"])

def fetch_reports_page(ticker: str, page: int = 0, size: int = 10, isWL: str = "false") -> dict:
    params = {"ticker": ticker, "isWL": isWL, "page": page, "size": size}
    h = {**HEADERS, "referer": f"https://simplize.vn/co-phieu/{ticker}/bao-cao"}
    r = requests.get(REPORT_LIST_URL, params=params, headers=h, timeout=30)
    r.raise_for_status()
    return r.json()

def fetch_all_reports(ticker: str, size: int = 10, max_pages: int = 200, page_start: int = 0) -> list:
    all_rows = []
    for page in range(page_start, page_start + max_pages):
        js = fetch_reports_page(ticker=ticker, page=page, size=size)
        rows = js.get("data") or js.get("items") or js.get("result") or []
        if not rows:
            break
        all_rows.extend(rows)
        if len(rows) < size:
            break
        time.sleep(random.uniform(MIN_DELAY_S, MAX_DELAY_S))
    return all_rows

def build_one_year_report_stats(raw_rows: list, lookback_years: int = 1):
    if not raw_rows:
        return None, 0, 0

    df = pd.DataFrame(raw_rows)
    if "issueDate" not in df.columns:
        return None, 0, 0

    df["issueDate_dt"] = pd.to_datetime(df["issueDate"], format="%d/%m/%Y", errors="coerce")
    cutoff = pd.Timestamp.today().normalize() - pd.DateOffset(years=lookback_years)
    df_1y = df[df["issueDate_dt"].notna() & (df["issueDate_dt"] >= cutoff)].copy()

    if df_1y.empty:
        return None, 0, 0

    df_1y["targetPrice"] = pd.to_numeric(df_1y.get("targetPrice"), errors="coerce")
    avg_target = df_1y["targetPrice"].mean()
    diversity = int(df_1y["source"].dropna().nunique()) if "source" in df_1y.columns else 0
    n_reports = int(len(df_1y))

    if pd.isna(avg_target):
        avg_target = None
    else:
        avg_target = float(avg_target)

    return avg_target, diversity, n_reports

def safe_ratio(current_price, report_eval):
    if current_price is None or report_eval in (None, 0) or (isinstance(report_eval, float) and np.isnan(report_eval)):
        return None
    return float(current_price) / float(report_eval)

def fmt_int_commas(x):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return ""
    try:
        return f"{int(round(float(x))):,}"
    except Exception:
        return ""

def fmt_ratio(x):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return ""
    return f"{float(x):.3f}"

def row_color_by_ratio(r):
    # strong
    if r is not None and not np.isnan(r) and r <= 0.8:
        return "#6E0080"
    # medium
    if r is not None and not np.isnan(r) and (r > 0.8) and (r < 0.9):
        return "#00803E"
    return ""

def build_html(df_display: pd.DataFrame, generated_at_str: str) -> str:
    # basic searchable table (no external libs)
    table_rows = []
    for _, row in df_display.iterrows():
        bg = row.get("_bg", "")
        style = f' style="background:{bg};font-weight:700;"' if bg else ""
        tds = "".join([f"<td>{row[c]}</td>" for c in df_display.columns if c != "_bg"])
        table_rows.append(f"<tr{style}>{tds}</tr>")

    cols = [c for c in df_display.columns if c != "_bg"]
    ths = "".join([f"<th>{c}</th>" for c in cols])

    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Simplize Portfolio Daily</title>
  <style>
    body {{ font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial; padding: 16px; }}
    .meta {{ color: #555; margin-bottom: 12px; }}
    input {{ padding: 8px; width: 320px; max-width: 100%; }}
    table {{ border-collapse: collapse; width: 100%; margin-top: 12px; }}
    th, td {{ border: 1px solid #ddd; padding: 8px; font-size: 14px; }}
    th {{ position: sticky; top: 0; background: #f7f7f7; }}
    tr:hover {{ outline: 2px solid #ccc; }}
    .hint {{ margin-top: 8px; color: #666; font-size: 13px; }}
  </style>
</head>
<body>
  <h2>Simplize Portfolio Daily</h2>
  <div class="meta">Generated at: <b>{generated_at_str}</b> (UTC)</div>

  <input id="q" placeholder="Search ticker (e.g., VNM)..." oninput="filterTable()" />
  <div class="hint">Highlight: Purple (Ratio ≤ 0.8) • Green (0.8 &lt; Ratio &lt; 0.9)</div>

  <table id="t">
    <thead><tr>{ths}</tr></thead>
    <tbody>
      {''.join(table_rows)}
    </tbody>
  </table>

<script>
function filterTable() {{
  const q = document.getElementById('q').value.toLowerCase();
  const rows = document.querySelectorAll('#t tbody tr');
  rows.forEach(r => {{
    const text = r.innerText.toLowerCase();
    r.style.display = text.includes(q) ? '' : 'none';
  }});
}}
</script>
</body>
</html>
"""

def main():
    rows_out = []

    for ticker in TICKERS:
        row = {
            "Stock Code": ticker,
            "Current Price": None,
            "Report Evaluation": None,
            "Diversity of Report Source": 0,
            "Acceptable Purchase Price": None,
            "Ratio": None,
            "Reports (1Y)": 0,
            "Errors": ""
        }

        # price
        try:
            row["Current Price"] = fetch_current_price(ticker)
        except Exception as e:
            row["Errors"] += f"price_err:{type(e).__name__}; "

        time.sleep(random.uniform(MIN_DELAY_S, MAX_DELAY_S))

        # reports
        try:
            raw_reports = fetch_all_reports(ticker, size=PAGE_SIZE, max_pages=MAX_PAGES, page_start=0)
            avg_target_1y, diversity, n_reports_1y = build_one_year_report_stats(raw_reports, lookback_years=LOOKBACK_YEARS)

            row["Diversity of Report Source"] = diversity
            row["Reports (1Y)"] = n_reports_1y

            if avg_target_1y is not None:
                report_eval = avg_target_1y * REPORT_FACTOR
                acceptable = report_eval * BARGAIN_FACTOR
                row["Report Evaluation"] = report_eval
                row["Acceptable Purchase Price"] = acceptable
                row["Ratio"] = safe_ratio(row["Current Price"], report_eval)
            else:
                row["Errors"] += "no_1y_reports_or_no_targetPrice; "

        except Exception as e:
            row["Errors"] += f"report_err:{type(e).__name__}; "

        rows_out.append(row)

    df_out = pd.DataFrame(rows_out, columns=[
        "Stock Code","Current Price","Report Evaluation","Diversity of Report Source",
        "Acceptable Purchase Price","Ratio","Reports (1Y)","Errors"
    ])

    # Save CSV (raw numeric)
    os.makedirs("docs", exist_ok=True)
    df_out.to_csv("docs/data.csv", index=False)

    # Build display df for HTML
    df_display = df_out.copy()
    for col in ["Current Price", "Report Evaluation", "Acceptable Purchase Price", "Ratio"]:
        df_display[col] = pd.to_numeric(df_display[col], errors="coerce")

    ratio_num = pd.to_numeric(df_out["Ratio"], errors="coerce")

    df_display["Current Price"] = df_display["Current Price"].apply(fmt_int_commas)
    df_display["Report Evaluation"] = df_display["Report Evaluation"].apply(fmt_int_commas)
    df_display["Acceptable Purchase Price"] = df_display["Acceptable Purchase Price"].apply(fmt_int_commas)
    df_display["Ratio"] = df_display["Ratio"].apply(fmt_ratio)

    # add background flag per row
    bgs = []
    for r in ratio_num.tolist():
        if pd.isna(r):
            bgs.append("")
        else:
            bgs.append(row_color_by_ratio(float(r)))
    df_display["_bg"] = bgs

    generated_at_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    html = build_html(df_display, generated_at_utc)
    with open("docs/index.html", "w", encoding="utf-8") as f:
        f.write(html)

if __name__ == "__main__":
    main()
