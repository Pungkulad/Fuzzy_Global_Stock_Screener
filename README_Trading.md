# Fuzzy Global Stock Screener & Research Trading Dashboard

A Streamlit research application with two separate stages:

1. **Stage 1 — Fundamental stock screening** (`app.py`): an adapted Mamdani fuzzy ranking model using P/E, P/BV, Dividend Yield, ROA and ROE.
2. **Stage 2 — Technical trading research** (`pages/2_Trading_Dashboard.py`): standard MACD, research-based MACDP, MACDP + fuzzy trading weight, risk controls, backtesting, chronological validation and paper trading.

Stage 1 remains in the original `app.py`. Stage 2 is stored as a versioned ZIP source bundle represented by 24 Base64 text parts in `trading_module_bundle_parts/`. The Streamlit page verifies the combined archive's SHA-256 checksum, reconstructs it in a temporary directory, then imports the Python package directly from the ZIP using Python's zip importer. No source-code download or manual extraction is required at runtime.

The trading module does not submit live orders and does not connect to a brokerage account.

## Deploy to Streamlit Community Cloud

1. Sign in to https://share.streamlit.io/ with GitHub.
2. Create an app or open the existing app's settings.
3. Repository: `Pungkulad/Fuzzy_Global_Stock_Screener`.
4. Branch: `main`.
5. Main file path: `app.py`.
6. Deploy. The Stage 2 page should appear in Streamlit's multipage navigation.

## Run locally

```bash
python -m venv .venv
# Activate the environment, then:
pip install -r requirements.txt
streamlit run app.py
```

The Stage 2 source, tests and research notes are inside the compressed package represented by the 24 `.b64` text files. To reconstruct and unpack it for local development:

```bash
python -c "import base64,pathlib; p=pathlib.Path('trading_module_bundle_parts'); b=''.join(x.read_text().strip() for x in sorted(p.glob('part_*.b64'))); pathlib.Path('trading_module_bundle.zip').write_bytes(base64.b64decode(b, validate=True))"
python -m zipfile -e trading_module_bundle.zip .
pip install -r requirements-dev.txt
python -m pytest tests
```

The dashboard UI test uses `streamlit.testing.v1.AppTest`; run it in an environment where the main requirements, including Streamlit, are installed. The core deterministic unit tests can also be run separately:

```bash
python -m pytest tests --ignore=tests/test_dashboard.py
```

## Stage 1 — Fundamental stock screening

- SET/mai, US listings, starter watchlist and custom ticker input.
- Fundamental factors: P/E, P/BV, Dividend Yield, ROA and ROE.
- Peer-relative scoring and an adapted Mamdani fuzzy model.
- PASS, WATCH, LOW PRIORITY, DATA ISSUE and INSUFFICIENT PEERS.
- Excel report generated in memory and downloaded by the user.

**Research limitation:** Stage 1 is an adapted model, not an exact reproduction of every equation, membership function and rule in the original 2019 paper. Current Yahoo Finance fundamentals are not historical point-in-time data. Universe-relative scores depend on the scanned sample.

## Stage 2 — Technical trading research

- Receives PASS stocks from the current screener session, imports screener Excel, or accepts manual tickers. WATCH requires explicit opt-in.
- Strategy A: standard MACD (12/26/9).
- Strategy B: modified MACD signal line (MACDP), based on Boonprasurt, Sampaokit & Witayakiattilerd (2022).
- Strategy C: MACDP plus fuzzy trading confidence / trading weight.
- Simulated orders execute no earlier than the next session open.
- Supports configurable fees, slippage, lot sizes, portfolio limits and optional protective stops.
- Includes Buy & Hold benchmark, backtesting, chronological development/validation/out-of-sample split, parameter sensitivity and walk-forward analysis.
- Paper trading only. Live brokerage orders are disabled.

### Source and research notes

The Stage 2 source bundle contains:

- `trading/` — indicator, strategy, fuzzy, risk, portfolio, backtest, validation and paper-trading modules.
- `trading/dashboard_page.py` — Stage 2 Streamlit page.
- `tests/` — deterministic unit and regression tests.
- `docs/research_methodology.md`
- `docs/strategy_specification.md`
- `docs/backtesting_limitations.md`
- `scripts/mock_comparison.py`

Primary trading research:

Boonprasurt, P., Sampaokit, P., & Witayakiattilerd, W. (2022). *MACD Indicator with the Modified Signal Line and Trading Weight Inference in Fuzzy Environment*. Thailand Statistician, 20(1), 98–123. [PDF](https://ph02.tci-thaijo.org/index.php/thaistat/article/download/245852/166747/868056).

The implementation distinguishes formulas visually verified in the paper from documented engineering assumptions and experimental alternatives. See `docs/research_methodology.md`.

## Data and validation limitations

- Yahoo Finance via `yfinance` is an unofficial source and may be delayed, revised, incomplete or rate-limited.
- Backtests use the current selected stock universe. This introduces selection and survivorship bias; it is not a point-in-time end-to-end test of the historical screener + trading process.
- Adjusted OHLC is a proxy series. Historical fills and cash accounting do not fully reconstruct every cash dividend and corporate action.
- Fees and slippage are user assumptions; enter values suitable for the broker and exchange being studied.
- Unit tests use deterministic synthetic data. A passing test suite verifies implementation behavior, not future profitability.
- The paper's reported MACDP experiment used SET100 stocks in a short 5 July–28 November 2013 window, no transaction costs, and signal-day-price execution. This project uses next-session-open simulation with configurable costs and therefore is not directly comparable to the paper's reported results.
- The fuzzy worked example has a documented numerical centroid discrepancy; see `docs/research_methodology.md`.
- Streamlit Cloud deployment and live Yahoo Finance retrieval must be verified in the target environment separately from deterministic unit tests.

**Research and education only. Not investment advice. No returns are guaranteed. Do not use paper-trading output as proof of live-trading performance.**
