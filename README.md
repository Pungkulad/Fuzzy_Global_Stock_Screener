# Fuzzy Global Stock Screener

A mobile-friendly Streamlit dashboard for fundamental stock screening using an adapted Mamdani fuzzy ranking model.

## Deploy to Streamlit Community Cloud

1. Sign in to https://share.streamlit.io/ with GitHub.
2. Click **Create app**.
3. Choose repository: **Pungkulad/Fuzzy_Global_Stock_Screener**.
4. Choose branch: **main**.
5. Set the main file path to **app.py**.
6. Click **Deploy**.
7. After deployment, copy the generated `*.streamlit.app` URL and share it.

The app runs on Streamlit Cloud. Users only need a browser; they do not need Python, Colab, or GitHub access.

## Run locally (optional)

```bash
pip install -r requirements.txt
streamlit run app.py
```

## App features

- SET/mai, US listings, starter watchlist, and custom tickers in Yahoo Finance format.
- Batch fundamental-data collection.
- Five-factor score: P/E, P/BV, Dividend Yield, ROA, ROE.
- Peer-relative percentiles and an adapted Mamdani fuzzy model.
- PASS, WATCH, LOW PRIORITY and DATA ISSUE views.
- Excel report generated in memory and downloaded by the user.
- No Google Drive integration and no automatic CSV/Excel persistence.

## Research and data limitations

This is an **adapted** fuzzy ranking model, not an exact reproduction of the full 2019 research paper's rule base and membership functions. The generated 243-rule table is a transparent baseline. Yahoo Finance via yfinance is an unofficial data access route; data can be missing, revised, delayed, or rate-limited. Current fundamentals are not historical point-in-time fundamentals. Scores are relative to the symbols scanned in one session and are not a forecast, recommendation, or guarantee of returns. ETF/fund screening is not included in the company-fundamental model.
