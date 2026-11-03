from __future__ import annotations

from datetime import datetime
from io import BytesIO
from itertools import product
import re
import time

import numpy as np
import pandas as pd
import requests
import streamlit as st
import yfinance as yf

st.set_page_config(
    page_title="Fuzzy Global Stock Screener",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

APP_NAME = "Fuzzy Global Stock Screener"
CACHE_SECONDS = 6 * 60 * 60
USER_AGENT = "Mozilla/5.0 (compatible; FuzzyGlobalStockScreener/1.0)"
GRID = np.linspace(0.0, 1.0, 101)
RULES = list(product(range(3), repeat=5))
METRICS = ["trailingPE", "priceToBook", "dividendYield", "returnOnAssets", "returnOnEquity"]


# ----------------------------- Data universe -----------------------------

def _find_column(columns, keywords):
    normalized = {c: re.sub(r"[^a-z0-9ก-๙]", "", str(c).lower()) for c in columns}
    for keyword in keywords:
        key = re.sub(r"[^a-z0-9ก-๙]", "", keyword.lower())
        for col, value in normalized.items():
            if key == value or key in value:
                return col
    return None


@st.cache_data(ttl=24 * 60 * 60, show_spinner=False)
def load_us_universe():
    sources = [
        ("https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt", "Symbol"),
        ("https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt", "ACT Symbol"),
    ]
    frames = []
    for url, symbol_col in sources:
        response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=25)
        response.raise_for_status()
        raw = pd.read_csv(BytesIO(response.content), sep="|", dtype=str, on_bad_lines="skip")
        if symbol_col not in raw.columns:
            continue
        raw = raw[~raw[symbol_col].fillna("").str.contains("File Creation Time", case=False)]
        if "Test Issue" in raw:
            raw = raw[raw["Test Issue"].fillna("N").str.upper().ne("Y")]
        if "ETF" in raw:
            raw = raw[raw["ETF"].fillna("N").str.upper().ne("Y")]
        name_col = "Security Name" if "Security Name" in raw.columns else None
        if name_col:
            non_common = r"\b(warrant|rights?|units?|preferred|depositary receipt|notes?|bonds?|debentures?)\b"
            raw = raw[~raw[name_col].fillna("").str.contains(non_common, case=False, regex=True)]
        tickers = raw[symbol_col].fillna("").astype(str).str.strip().str.upper().str.replace(".", "-", regex=False)
        valid = tickers.str.match(r"^[A-Z0-9-]{1,15}$")
        raw = raw.loc[valid].copy()
        tickers = tickers.loc[valid]
        frames.append(pd.DataFrame({
            "ticker": tickers.values,
            "market": "US",
            "company": raw[name_col].fillna("Unknown").astype(str).values if name_col else "Unknown",
            "sector": "Unknown",
            "asset_id": "US|" + tickers.values,
        }))
    if not frames:
        return pd.DataFrame(columns=["ticker", "market", "company", "sector", "asset_id"])
    return pd.concat(frames, ignore_index=True).drop_duplicates("asset_id").reset_index(drop=True)


@st.cache_data(ttl=24 * 60 * 60, show_spinner=False)
def load_th_universe():
    urls = [
        "https://www.set.or.th/dat/eod/listedcompany/static/listedCompanies_en_US.xls",
        "https://www.set.or.th/dat/eod/listedcompany/static/listedCompanies_th_TH.xls",
    ]
    last_error = None
    for url in urls:
        try:
            response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=25)
            response.raise_for_status()
            raw = pd.read_excel(BytesIO(response.content), engine="xlrd")
            symbol_col = _find_column(raw.columns, ["symbol", "ชื่อย่อหลักทรัพย์"])
            if symbol_col is None:
                continue
            name_col = _find_column(raw.columns, ["company name", "company", "ชื่อบริษัท", "ชื่อเต็มหลักทรัพย์"])
            market_col = _find_column(raw.columns, ["market", "ตลาด"])
            sector_col = _find_column(raw.columns, ["sector", "industry group", "หมวดธุรกิจ", "กลุ่มอุตสาหกรรม"])
            type_col = _find_column(raw.columns, ["security type", "ประเภทหลักทรัพย์"])
            work = raw.copy()
            if market_col:
                mask = work[market_col].fillna("").astype(str).str.contains(r"SET|mai", case=False, regex=True)
                if mask.any():
                    work = work.loc[mask].copy()
            if type_col:
                types = work[type_col].fillna("").astype(str)
                common = types.str.contains(r"common stock|common share|หุ้นสามัญ", case=False, regex=True)
                if common.any():
                    work = work.loc[common].copy()
            symbols = work[symbol_col].fillna("").astype(str).str.strip().str.upper()
            symbols = symbols.str.replace(r"\.BK$", "", regex=True)
            valid = symbols.str.match(r"^[A-Z0-9&-]{1,20}$")
            work = work.loc[valid].copy()
            symbols = symbols.loc[valid]
            out = pd.DataFrame({
                "ticker": (symbols + ".BK").values,
                "market": "TH",
                "company": work[name_col].fillna("Unknown").astype(str).values if name_col else "Unknown",
                "sector": work[sector_col].fillna("Unknown").astype(str).values if sector_col else "Unknown",
            })
            out["asset_id"] = out["market"] + "|" + out["ticker"]
            if not out.empty:
                return out.drop_duplicates("asset_id").reset_index(drop=True)
        except Exception as exc:
            last_error = str(exc)
    raise RuntimeError(f"SET/mai directory could not be loaded: {last_error or 'unknown error'}")


def infer_market(ticker):
    suffixes = {
        ".BK": "TH", ".T": "JP", ".HK": "HK", ".NS": "IN", ".BO": "IN",
        ".L": "UK", ".DE": "DE", ".PA": "FR", ".AX": "AU", ".TO": "CA",
        ".SI": "SG", ".JK": "ID", ".KS": "KR", ".TW": "TW", ".SS": "CN", ".SZ": "CN",
    }
    return next((market for suffix, market in suffixes.items() if ticker.endswith(suffix)), "US")


def parse_custom_tickers(text):
    rows = []
    for raw in re.split(r"[\n,;]+", text or ""):
        value = raw.strip().upper()
        if not value:
            continue
        if "|" in value:
            market, ticker = [x.strip() for x in value.split("|", 1)]
        else:
            ticker = value
            market = infer_market(ticker)
        rows.append({
            "ticker": ticker, "market": market, "company": "Unknown",
            "sector": "Unknown", "asset_id": f"{market}|{ticker}",
        })
    if not rows:
        return pd.DataFrame(columns=["ticker", "market", "company", "sector", "asset_id"])
    return pd.DataFrame(rows).drop_duplicates("asset_id").reset_index(drop=True)


# ----------------------------- Fundamentals -----------------------------

@st.cache_data(ttl=CACHE_SECONDS, show_spinner=False)
def fetch_fundamental(ticker, market, company_hint="", sector_hint=""):
    info = yf.Ticker(ticker).get_info()
    if not info:
        raise ValueError("Yahoo Finance returned an empty response")

    def number(key):
        try:
            value = float(info.get(key))
            return value if np.isfinite(value) else np.nan
        except (TypeError, ValueError):
            return np.nan

    dividend = info.get("dividendYield")
    if dividend is None and info.get("dividendRate") == 0:
        dividend = 0.0
    try:
        dividend = float(dividend) if dividend is not None else np.nan
    except (TypeError, ValueError):
        dividend = np.nan

    return {
        "asset_id": f"{market}|{ticker}",
        "ticker": ticker,
        "market": market,
        "company": info.get("longName") or info.get("shortName") or company_hint or ticker,
        "sector": info.get("sector") or sector_hint or "Unknown",
        "industry": info.get("industry") or "Unknown",
        "currency": info.get("currency") or "",
        "quoteType": info.get("quoteType") or "",
        "marketCap": number("marketCap"),
        "trailingPE": number("trailingPE"),
        "priceToBook": number("priceToBook"),
        "dividendYield": dividend,
        "returnOnAssets": number("returnOnAssets"),
        "returnOnEquity": number("returnOnEquity"),
        "profitMargins": number("profitMargins"),
        "revenueGrowth": number("revenueGrowth"),
        "debtToEquity": number("debtToEquity"),
        "fetch_status": "OK",
        "fetch_error": "",
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
    }


# ----------------------------- Fuzzy model -----------------------------

def membership_lmh(value):
    x = float(np.clip(value, 0.0, 1.0))
    return np.array([
        np.clip((0.5 - x) / 0.5, 0, 1),
        np.clip(1.0 - abs(x - 0.5) / 0.5, 0, 1),
        np.clip((x - 0.5) / 0.5, 0, 1),
    ])


def triangle(x, a, b, c):
    left = np.clip((x - a) / (b - a), 0, 1)
    right = np.clip((c - x) / (c - b), 0, 1)
    return np.minimum(left, right)


OUTPUT_SETS = [
    np.clip((0.25 - GRID) / 0.25, 0, 1),
    triangle(GRID, 0.0, 0.25, 0.50),
    triangle(GRID, 0.25, 0.50, 0.75),
    triangle(GRID, 0.50, 0.75, 1.0),
    np.clip((GRID - 0.75) / 0.25, 0, 1),
]


def rule_output(rule):
    average = float(np.mean(rule)) / 2.0
    if average < 0.20:
        return 0
    if average < 0.40:
        return 1
    if average <= 0.60:
        return 2
    if average <= 0.80:
        return 3
    return 4


RULE_OUTPUTS = [rule_output(rule) for rule in RULES]


def fuzzy_cog(values):
    values = np.asarray(values, dtype=float)
    if values.shape != (5,) or not np.isfinite(values).all():
        return np.nan
    memberships = [membership_lmh(v) for v in values]
    aggregate = np.zeros_like(GRID)
    for rule, output_idx in zip(RULES, RULE_OUTPUTS):
        strength = min(memberships[i][rule[i]] for i in range(5))
        if strength > 0:
            aggregate = np.maximum(aggregate, np.minimum(strength, OUTPUT_SETS[output_idx]))
    denominator = aggregate.sum()
    return float(np.sum(GRID * aggregate) / denominator) if denominator > 0 else np.nan


# ----------------------------- Screening -----------------------------

def screen_stocks(raw, pass_threshold, watch_threshold, min_sector_peers, min_market_peers):
    if raw.empty:
        return pd.DataFrame()
    if watch_threshold > pass_threshold:
        raise ValueError("WATCH threshold must not exceed PASS threshold")

    data = raw.copy()
    for col in METRICS:
        data[col] = pd.to_numeric(data[col], errors="coerce")

    def issue(row):
        if row.get("fetch_status") != "OK":
            return row.get("fetch_error") or "Fundamental data unavailable"
        quote_type = str(row.get("quoteType", "")).upper()
        if quote_type and quote_type != "EQUITY":
            return f"Unsupported asset type: {quote_type}"
        reasons = [f"Missing {m}" for m in METRICS if pd.isna(row.get(m))]
        if pd.notna(row.get("trailingPE")) and row["trailingPE"] <= 0:
            reasons.append("Non-positive P/E")
        if pd.notna(row.get("priceToBook")) and row["priceToBook"] <= 0:
            reasons.append("Non-positive P/BV")
        if pd.notna(row.get("dividendYield")) and row["dividendYield"] < 0:
            reasons.append("Negative Dividend Yield")
        return "; ".join(reasons)

    data["DataIssue"] = data.apply(issue, axis=1)
    valid = data[data["DataIssue"].eq("")].copy()
    data["ScreenStatus"] = "DATA ISSUE"
    for col in ["FuzzyWeight", "FuzzyScore100", "RankPeer", "RankMarket", "PeerBasis", "PeerCount"]:
        data[col] = np.nan

    if valid.empty:
        return data

    valid["market"] = valid["market"].fillna("Unknown").astype(str)
    valid["sector"] = valid["sector"].fillna("Unknown").replace("", "Unknown").astype(str)
    sector_counts = valid.groupby(["market", "sector"])["ticker"].transform("count")
    market_counts = valid.groupby("market")["ticker"].transform("count")
    sector_ok = sector_counts.ge(min_sector_peers) & valid["sector"].ne("Unknown")
    market_ok = market_counts.ge(min_market_peers)
    valid["peer_group"] = np.where(
        sector_ok,
        valid["market"] + "|" + valid["sector"],
        np.where(market_ok, valid["market"] + "|ALL", None),
    )
    valid["PeerBasis"] = np.where(sector_ok, "Sector", np.where(market_ok, "Market", "Insufficient"))
    valid = valid[valid["peer_group"].notna()].copy()
    if valid.empty:
        data["ScreenStatus"] = "DATA ISSUE / INSUFFICIENT PEERS"
        return data

    # Lower P/E and P/BV are better; higher dividend yield, ROA and ROE are better.
    valid["pe_quality"] = valid.groupby("peer_group")["trailingPE"].rank(ascending=False, pct=True)
    valid["pb_quality"] = valid.groupby("peer_group")["priceToBook"].rank(ascending=False, pct=True)
    valid["div_quality"] = valid.groupby("peer_group")["dividendYield"].rank(ascending=True, pct=True)
    valid["roa_quality"] = valid.groupby("peer_group")["returnOnAssets"].rank(ascending=True, pct=True)
    valid["roe_quality"] = valid.groupby("peer_group")["returnOnEquity"].rank(ascending=True, pct=True)

    quality_cols = ["pe_quality", "pb_quality", "div_quality", "roa_quality", "roe_quality"]
    valid["FuzzyWeight"] = valid[quality_cols].apply(lambda row: fuzzy_cog(row.to_numpy()), axis=1)
    valid["FuzzyScore100"] = valid["FuzzyWeight"] * 100
    valid["PeerCount"] = valid.groupby("peer_group")["ticker"].transform("count")
    valid["RankPeer"] = valid.groupby("peer_group")["FuzzyWeight"].rank(ascending=False, method="min")
    valid["RankMarket"] = valid.groupby("market")["FuzzyWeight"].rank(ascending=False, method="min")

    def classify(row):
        score = row["FuzzyWeight"]
        if pd.isna(score):
            return "DATA ISSUE"
        if score >= pass_threshold and row["returnOnAssets"] > 0 and row["returnOnEquity"] > 0:
            return "PASS"
        if score >= watch_threshold:
            return "WATCH"
        return "LOW PRIORITY"

    valid["ScreenStatus"] = valid.apply(classify, axis=1)
    scored = valid[[
        "asset_id", "ScreenStatus", "FuzzyWeight", "FuzzyScore100",
        "RankPeer", "RankMarket", "PeerBasis", "PeerCount",
    ]]
    data = data.drop(columns=["ScreenStatus", "FuzzyWeight", "FuzzyScore100", "RankPeer", "RankMarket", "PeerBasis", "PeerCount"])
    data = data.merge(scored, on="asset_id", how="left")
    data["ScreenStatus"] = data["ScreenStatus"].fillna(
        np.where(data["DataIssue"].eq(""), "DATA ISSUE / INSUFFICIENT PEERS", "DATA ISSUE")
    )
    data["DividendYield_pct"] = data["dividendYield"] * 100
    data["ROA_pct"] = data["returnOnAssets"] * 100
    data["ROE_pct"] = data["returnOnEquity"] * 100
    data["ProfitMargin_pct"] = data["profitMargins"] * 100
    data["RevenueGrowth_pct"] = data["revenueGrowth"] * 100
    return data.sort_values("FuzzyWeight", ascending=False, na_position="last").reset_index(drop=True)


# ----------------------------- Excel report -----------------------------

def excel_report(result, pass_threshold, watch_threshold):
    output = BytesIO()
    passed = result[result["ScreenStatus"].eq("PASS")]
    watch = result[result["ScreenStatus"].eq("WATCH")]
    low = result[result["ScreenStatus"].eq("LOW PRIORITY")]
    issues = result[result["ScreenStatus"].astype(str).str.contains("DATA ISSUE", case=False, na=False)]
    summary = pd.DataFrame({
        "Metric": ["Generated at", "Scanned stocks", "PASS", "WATCH", "LOW PRIORITY", "DATA ISSUES", "PASS threshold", "WATCH threshold"],
        "Value": [datetime.now().strftime("%Y-%m-%d %H:%M:%S"), len(result), len(passed), len(watch), len(low), len(issues), pass_threshold, watch_threshold],
    })
    methodology = pd.DataFrame({
        "Item": ["Model", "Method", "Factors", "Fuzzy inference", "Rule count", "Defuzzification", "Peer comparison", "Data provider", "Limitation"],
        "Description": [
            APP_NAME, "Adapted Mamdani fuzzy ranking", "P/E, P/BV, Dividend Yield, ROA, ROE",
            "Mamdani min implication / max aggregation", "243 generated rules", "Center of Gravity",
            "Sector percentile with market fallback", "Yahoo Finance via yfinance; SET/Nasdaq public directories",
            "Current fundamentals and scanned-peer ranks are not a historical backtest or return forecast.",
        ],
    })
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        summary.to_excel(writer, sheet_name="Overview", index=False)
        result.to_excel(writer, sheet_name="All Stocks", index=False)
        passed.to_excel(writer, sheet_name="PASS", index=False)
        watch.to_excel(writer, sheet_name="WATCH", index=False)
        low.to_excel(writer, sheet_name="Low Priority", index=False)
        issues.to_excel(writer, sheet_name="Data Issues", index=False)
        methodology.to_excel(writer, sheet_name="Methodology", index=False)
    output.seek(0)
    return output.getvalue()


# ----------------------------- Streamlit UI -----------------------------

def init_state():
    defaults = {
        "candidates": [], "cursor": 0, "records": [],
        "results": pd.DataFrame(), "universe_ready": False,
        "universe_warnings": [],
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


init_state()

st.title("📊 Fuzzy Global Stock Screener")
st.caption("Fundamental quality screening • Adapted Mamdani fuzzy ranking • Mobile-friendly dashboard")
st.info(
    "เครื่องมือนี้ใช้คัดกรองคุณภาพพื้นฐานของบริษัท ไม่ใช่สัญญาณซื้อขาย "
    "และไม่รับประกันผลตอบแทน คะแนนเป็นการเปรียบเทียบกับหุ้นที่สแกนในรอบเดียวกัน"
)

with st.sidebar:
    st.header("ตั้งค่าการคัดกรอง")
    universe_choice = st.selectbox(
        "ตลาด / Universe",
        ["Starter Watchlist", "Thailand (SET/mai)", "United States", "Custom Tickers"],
        index=0,
    )
    max_symbols = st.slider("จำนวนหุ้นสูงสุด", 5, 200, 30, step=5)
    batch_size = st.select_slider("หุ้นต่อรอบ", options=[5, 10, 20, 30, 50], value=10)
    pass_threshold = st.slider("เกณฑ์ PASS", 0.40, 0.90, 0.60, step=0.05)
    watch_threshold = st.slider("เกณฑ์ WATCH", 0.30, 0.85, 0.50, step=0.05)
    min_sector_peers = st.slider("จำนวนหุ้นขั้นต่ำในกลุ่มอุตสาหกรรม", 3, 20, 8)
    min_market_peers = st.slider("จำนวนหุ้นขั้นต่ำในตลาด", 3, 20, 5)
    custom_text = st.text_area(
        "Ticker เอง (หนึ่งตัวต่อบรรทัด)",
        placeholder="ADVANC.BK\nPTT.BK\nAAPL\nNVDA\nJP|7203.T",
        height=120,
        disabled=universe_choice != "Custom Tickers",
    )

starter = [
    ("TH", "ADVANC.BK"), ("TH", "AOT.BK"), ("TH", "BDMS.BK"), ("TH", "CPALL.BK"),
    ("TH", "GULF.BK"), ("TH", "KBANK.BK"), ("TH", "PTT.BK"), ("TH", "SCB.BK"),
    ("TH", "TRUE.BK"), ("TH", "TISCO.BK"), ("US", "AAPL"), ("US", "AMZN"),
    ("US", "AVGO"), ("US", "GOOGL"), ("US", "JPM"), ("US", "META"),
    ("US", "MSFT"), ("US", "NVDA"), ("US", "TSLA"), ("US", "WMT"),
]
starter_df = pd.DataFrame([
    {"market": m, "ticker": t, "company": t, "sector": "Unknown", "asset_id": f"{m}|{t}"}
    for m, t in starter
])

col1, col2 = st.columns(2)
with col1:
    prepare_clicked = st.button("1. เตรียมรายชื่อหุ้น", type="primary", use_container_width=True)
with col2:
    clear_clicked = st.button("ล้างผลลัพธ์", use_container_width=True)

if clear_clicked:
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.rerun()

if prepare_clicked:
    try:
        warnings_list = []
        with st.spinner("กำลังโหลดรายชื่อหลักทรัพย์..."):
            if universe_choice == "Starter Watchlist":
                candidates = starter_df.copy()
            elif universe_choice == "Custom Tickers":
                candidates = parse_custom_tickers(custom_text)
            elif universe_choice == "Thailand (SET/mai)":
                candidates = load_th_universe()
            else:
                candidates = load_us_universe()
        if candidates.empty:
            st.error("ไม่พบรายชื่อหุ้น กรุณาลองใหม่หรือใช้ Custom Tickers")
        else:
            candidates = candidates.head(max_symbols).reset_index(drop=True)
            st.session_state.candidates = candidates.to_dict("records")
            st.session_state.cursor = 0
            st.session_state.records = []
            st.session_state.results = pd.DataFrame()
            st.session_state.universe_ready = True
            st.session_state.universe_warnings = warnings_list
            st.success(f"เตรียมรายชื่อสำเร็จ {len(candidates):,} หุ้น")
            st.dataframe(candidates[["ticker", "market", "company"]], use_container_width=True, hide_index=True)
    except Exception as exc:
        st.error(f"โหลด Universe ไม่สำเร็จ: {exc}")

if st.session_state.universe_ready:
    candidates = st.session_state.candidates
    total = len(candidates)
    cursor = st.session_state.cursor
    remaining = max(total - cursor, 0)
    st.progress(cursor / total if total else 0.0, text=f"สแกนแล้ว {cursor:,}/{total:,} หุ้น • เหลือ {remaining:,} หุ้น")
    scan_clicked = st.button(
        f"2. สแกนหุ้นรอบถัดไป ({min(batch_size, remaining)} ตัว)",
        disabled=remaining == 0,
        use_container_width=True,
    )
    if scan_clicked:
        start = cursor
        end = min(start + batch_size, total)
        batch = candidates[start:end]
        progress = st.progress(0.0, text="เริ่มดึงข้อมูล Fundamental...")
        new_records = []
        for index, row in enumerate(batch, start=1):
            ticker = row["ticker"]
            progress.progress(index / len(batch), text=f"กำลังดึงข้อมูล {ticker} ({start + index}/{total})")
            try:
                record = fetch_fundamental(
                    str(ticker), str(row.get("market", "US")),
                    str(row.get("company", "")), str(row.get("sector", "Unknown")),
                )
            except Exception as exc:
                record = {
                    "asset_id": row["asset_id"], "ticker": ticker,
                    "market": row.get("market", "US"), "company": row.get("company", ticker),
                    "sector": row.get("sector", "Unknown"), "fetch_status": "ERROR",
                    "fetch_error": str(exc)[:250], "fetched_at": datetime.now().isoformat(timespec="seconds"),
                }
            new_records.append(record)
            time.sleep(0.2)
        st.session_state.records.extend(new_records)
        st.session_state.cursor = end
        st.rerun()

    if st.session_state.records:
        st.caption(f"ดึงข้อมูลแล้ว {len(st.session_state.records):,} / {total:,} หุ้น")
        if st.button("3. คำนวณคะแนนและจัดอันดับ", type="primary", use_container_width=True):
            with st.spinner("กำลังคำนวณ Peer Percentile และ Fuzzy Score..."):
                raw = pd.DataFrame(st.session_state.records)
                st.session_state.results = screen_stocks(
                    raw, pass_threshold, watch_threshold,
                    min_sector_peers, min_market_peers,
                )

if not st.session_state.results.empty:
    result = st.session_state.results
    st.divider()
    st.header("ผลการคัดกรองหุ้น")
    passed = result[result["ScreenStatus"].eq("PASS")]
    watched = result[result["ScreenStatus"].eq("WATCH")]
    low = result[result["ScreenStatus"].eq("LOW PRIORITY")]
    issues = result[result["ScreenStatus"].astype(str).str.contains("DATA ISSUE", case=False, na=False)]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("สแกนทั้งหมด", f"{len(result):,}")
    c2.metric("PASS", f"{len(passed):,}")
    c3.metric("WATCH", f"{len(watched):,}")
    c4.metric("ข้อมูลไม่ครบ", f"{len(issues):,}")

    display_cols = [
        "ticker", "company", "market", "sector", "currency", "trailingPE",
        "priceToBook", "DividendYield_pct", "ROA_pct", "ROE_pct",
        "FuzzyScore100", "RankPeer", "RankMarket", "PeerBasis",
        "PeerCount", "ScreenStatus", "DataIssue",
    ]
    tabs = st.tabs(["ภาพรวม", "PASS", "WATCH", "LOW PRIORITY", "ข้อมูลไม่ครบ", "ทั้งหมด"])
    with tabs[0]:
        top = result[result["FuzzyScore100"].notna()].head(20)
        if not top.empty:
            st.subheader("Top 20 Fuzzy Score")
            st.bar_chart(top.set_index("ticker")[["FuzzyScore100"]])
        st.dataframe(result[[c for c in display_cols if c in result.columns]].head(20), use_container_width=True, hide_index=True)
    with tabs[1]:
        st.dataframe(passed[[c for c in display_cols if c in passed.columns]], use_container_width=True, hide_index=True)
    with tabs[2]:
        st.dataframe(watched[[c for c in display_cols if c in watched.columns]], use_container_width=True, hide_index=True)
    with tabs[3]:
        st.dataframe(low[[c for c in display_cols if c in low.columns]], use_container_width=True, hide_index=True)
    with tabs[4]:
        st.dataframe(issues[[c for c in display_cols if c in issues.columns]], use_container_width=True, hide_index=True)
    with tabs[5]:
        st.dataframe(result[[c for c in display_cols if c in result.columns]], use_container_width=True, hide_index=True)

    try:
        workbook = excel_report(result, pass_threshold, watch_threshold)
        st.download_button(
            "⬇️ ดาวน์โหลดผลลัพธ์ Excel",
            data=workbook,
            file_name=f"Fuzzy_Global_Stock_Screening_{datetime.now():%Y%m%d_%H%M}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
        st.caption("ไฟล์ Excel ถูกสร้างในหน่วยความจำและดาวน์โหลดผ่านเบราว์เซอร์ ไม่บันทึกลง Google Drive")
    except Exception as exc:
        st.error(f"สร้าง Excel ไม่สำเร็จ: {exc}")

with st.expander("วิธีอ่านคะแนนและข้อจำกัด"):
    st.markdown(
        """
        **5 ปัจจัยหลัก:** P/E, P/BV, Dividend Yield, ROA และ ROE

        - P/E และ P/BV ต่ำกว่าเมื่อเทียบกับกลุ่ม จะได้ quality percentile สูงกว่า
        - Dividend Yield, ROA และ ROE สูงกว่าเมื่อเทียบกับกลุ่ม จะได้ quality percentile สูงกว่า
        - คะแนนใช้ Adapted Mamdani Fuzzy Inference: 243 rules, MIN implication, MAX aggregation และ Center of Gravity
        - PASS/WATCH เป็นเกณฑ์ที่ผู้ใช้ตั้งค่าได้ ไม่ใช่คำแนะนำซื้อขาย

        **ข้อจำกัด:** ข้อมูล Fundamental เป็นข้อมูลปัจจุบันจาก Yahoo Finance ผ่าน yfinance และอาจขาดหายหรือถูกจำกัดการเรียกข้อมูล คะแนนเปรียบเทียบเฉพาะหุ้นที่สแกนใน Session นั้น ไม่ใช่ Backtest แบบ Historical Point-in-Time โมเดล Fuzzy นี้ดัดแปลงจากแนวคิดงานวิจัย ไม่ใช่การทำซ้ำสมการและกฎต้นฉบับทั้งหมด ETF และกองทุนไม่เหมาะกับปัจจัย Fundamental ของบริษัทชุดนี้
        """
    )
