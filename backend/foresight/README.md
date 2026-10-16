# foresight (vendored)

Pure-Python demand & pricing forecaster (no Streamlit, no matplotlib). Vendored from the Foresight module.
Local changes vs. upstream: `store.py` opens SQLite with a 30 s timeout + WAL and rolls back on error; `charts.py` (matplotlib) was dropped because the web UI draws its own SVG charts from the JSON API.
