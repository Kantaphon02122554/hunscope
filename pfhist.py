"""ประวัติราคารายสัปดาห์ 5 ปี (ปรับปันผลแล้ว) สำหรับพอร์ตจำลองบนหน้าเว็บ"""
import pandas as pd
import yfinance as yf


def collect(symbols, period="5y"):
    syms = list(dict.fromkeys(symbols))
    try:
        df = yf.download(syms, period=period, interval="1wk", progress=False, auto_adjust=True)
        c = (df["Close"] if isinstance(df.columns, pd.MultiIndex) else df).dropna(axis=1, how="all").dropna(how="all")
    except Exception as e:
        print("ข้ามประวัติราคา:", e)
        return None
    if c.empty:
        return None
    c = c[~c.index.duplicated()]
    return {"dates": [d.strftime("%Y-%m-%d") for d in c.index],
            "series": {s: [None if pd.isna(v) else round(float(v), 2) for v in c[s]] for s in c.columns}}
