"""ดึงราคา ตัวชี้วัด ปัจจัยพื้นฐาน และข่าวจาก Yahoo Finance แล้วเขียนลง data.json
รัน: pip install yfinance && python fetch_data.py
แก้รายการหุ้นที่ GROUPS (ค่าที่สามคือ True = คำนวณตัวประเมิน/ข่าวรายตัวด้วย)
"""
import json
import os
import re
import datetime as dt
import pandas as pd
import yfinance as yf

import bubble
import fund
import macro
import newsfeed
import pfhist

GROUPS = [
    ("ดัชนี", {"^IXIC": "Nasdaq", "^GSPC": "S&P 500", "^DJI": "Dow Jones", "^SOX": "เซมิคอนดักเตอร์ (SOX)"}, False),
    ("หุ้นเทค", {"NVDA": "Nvidia", "MSFT": "Microsoft", "AAPL": "Apple", "GOOGL": "Alphabet", "META": "Meta",
                 "AVGO": "Broadcom", "AMD": "AMD", "TSM": "TSMC", "MU": "Micron",
                 "AMZN": "Amazon", "ASML": "ASML", "OKLO": "Oklo", "SPCX": "SpaceX", "TELO": "Telomir (TELO)"}, True),
    ("น้ำมัน ดอกเบี้ย ความผันผวน", {"BZ=F": "น้ำมัน Brent", "CL=F": "น้ำมัน WTI",
                                   "^TNX": "พันธบัตรสหรัฐ 10 ปี (%)", "^VIX": "VIX ดัชนีความกลัว"}, False),
    ("ทองคำ", {"GC=F": "ทองคำ (ฟิวเจอร์ส USD/ออนซ์)", "GLD": "SPDR Gold Shares (GLD)"}, False),
]
POINTS = {"^TNX", "^VIX"}  # แสดงการเปลี่ยนแปลงเป็นจุด


def r(x, n=2):
    return None if x is None or pd.isna(x) else round(float(x), n)


def indicators(c):
    last = float(c.iloc[-1])
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean().iloc[-1]
    dn = (-d.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean().iloc[-1]
    rsi = 100.0 if dn == 0 else 100 - 100 / (1 + up / dn)
    macd = c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()
    hist = float((macd - macd.ewm(span=9, adjust=False).mean()).iloc[-1])
    sma50, sma200 = c.rolling(50).mean().iloc[-1], c.rolling(200).mean().iloc[-1]
    yr = c.tail(252)
    hi, lo = float(yr.max()), float(yr.min())
    ret = lambda n: r((last / float(c.iloc[-n - 1]) - 1) * 100) if len(c) > n else None

    sig = []
    if pd.notna(sma50):
        ok = last > sma50
        sig.append({"name": "แนวโน้มระยะกลาง", "text": "ราคาอยู่เหนือเส้นเฉลี่ย 50 วัน" if ok else "ราคาอยู่ต่ำกว่าเส้นเฉลี่ย 50 วัน", "score": 1 if ok else -1})
    if pd.notna(sma200):
        ok = last > sma200
        sig.append({"name": "แนวโน้มระยะยาว", "text": "ราคาอยู่เหนือเส้นเฉลี่ย 200 วัน" if ok else "ราคาอยู่ต่ำกว่าเส้นเฉลี่ย 200 วัน", "score": 1 if ok else -1})
    sig.append({"name": "โมเมนตัม (MACD)", "text": "MACD เหนือเส้นสัญญาณ แรงซื้อเด่น" if hist > 0 else "MACD ต่ำกว่าเส้นสัญญาณ แรงขายเด่น", "score": 1 if hist > 0 else -1})
    if rsi > 70:
        sig.append({"name": "RSI", "text": f"RSI {rsi:.0f} สูง เสี่ยงซื้อมากเกินไป", "score": -1})
    elif rsi < 30:
        sig.append({"name": "RSI", "text": f"RSI {rsi:.0f} ต่ำ ขายมากเกินไป อาจเด้งกลับ", "score": 1})
    else:
        sig.append({"name": "RSI", "text": f"RSI {rsi:.0f} อยู่ในช่วงปกติ", "score": 0})
    score = sum(s["score"] for s in sig)
    label = "ขาขึ้น" if score >= 2 else "ขาลง" if score <= -2 else "เป็นกลาง"
    return {
        "rsi": r(rsi, 1), "sma50": r(sma50), "sma200": r(sma200), "high52": r(hi), "low52": r(lo),
        "pos52": r((last - lo) / (hi - lo) * 100, 0) if hi > lo else None,
        "ret1m": ret(21), "ret3m": ret(63), "ret1y": r((last / float(c.iloc[0]) - 1) * 100), "signals": sig, "score": score, "label": label,
    }


def zones(h):
    """โซนรับทางเทคนิค: รวมระดับที่ซ้อนกัน (เส้นเฉลี่ย, Fibonacci ของช่วง 120 วัน, แนวรับเดิม) ใต้ราคาปัจจุบัน"""
    c = h["Close"]
    last = float(c.iloc[-1])
    tr = pd.concat([h["High"] - h["Low"], (h["High"] - c.shift()).abs(), (h["Low"] - c.shift()).abs()], axis=1).max(axis=1)
    atr = float(tr.rolling(14).mean().iloc[-1])
    win = h.tail(120)
    top, bot = float(win["High"].max()), float(win["Low"].min())
    cand = []
    for n, name in ((20, "SMA20"), (50, "SMA50"), (200, "SMA200")):
        v = c.rolling(n).mean().iloc[-1]
        if pd.notna(v):
            cand.append((float(v), name))
    for f, name in ((0.382, "Fib 38.2%"), (0.5, "Fib 50%"), (0.618, "Fib 61.8%")):
        cand.append((top - f * (top - bot), name))
    lows = win["Low"].reset_index(drop=True)
    for i in range(5, len(lows) - 5):
        if lows[i] == lows[i - 5:i + 6].min():
            cand.append((float(lows[i]), "แนวรับเดิม"))
    cand = sorted(x for x in cand if 0.75 * last <= x[0] < last)
    tol, pad = max(0.6 * atr, last * 0.01), 0.3 * atr
    clusters = []
    for lv, name in cand:
        if clusters and lv - clusters[-1][-1][0] <= tol:
            clusters[-1].append((lv, name))
        else:
            clusters.append([(lv, name)])
    zs = []
    for g in clusters:
        labels = sorted({n for _, n in g})
        low, high = g[0][0] - pad, g[-1][0] + pad
        zs.append({"low": r(low), "high": r(high), "labels": labels, "strength": len(labels),
                   "dist_pct": r((last - high) / last * 100, 1)})
    zs = sorted(zs, key=lambda z: z["high"], reverse=True)[:3]
    if not zs:
        return {"status": "none", "list": [], "atr": r(atr), "bars": int(len(h))}
    n = zs[0]
    status = "in" if n["dist_pct"] <= 0.5 else "near" if n["dist_pct"] <= 3 else "far"
    entry = last if status == "in" else (n["low"] + n["high"]) / 2
    brk = n["low"] - atr
    tgt = top if top > last * 1.01 else None
    rr = None
    if tgt and entry - brk > 0 and tgt - entry > 0:
        rr = r((tgt - entry) / (entry - brk), 1)
    return {"status": status, "list": zs, "atr": r(atr), "bars": int(len(h)), "break": r(brk), "target": r(tgt), "rr": rr}


def fundamentals(symbol):
    try:
        i = yf.Ticker(symbol).info
    except Exception:
        return {}
    out = {"pe": r(i.get("trailingPE")), "fpe": r(i.get("forwardPE")), "mcap": i.get("marketCap"),
           "target": r(i.get("targetMeanPrice")), "rec": i.get("recommendationKey")}
    return {k: v for k, v in out.items() if v is not None}


def news(symbol, n=5):
    try:
        raw = yf.Ticker(symbol).news or []
    except Exception:
        return []
    out = []
    for it in raw[:n]:
        c = it.get("content", it)
        url = ((c.get("canonicalUrl") or c.get("clickThroughUrl") or {}).get("url")) or c.get("link")
        title = c.get("title")
        t = c.get("pubDate") or ""
        if not t and it.get("providerPublishTime"):
            t = dt.datetime.fromtimestamp(it["providerPublishTime"], dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        src = (c.get("provider") or {}).get("displayName") or c.get("publisher") or ""
        if title and url:
            out.append({"title": title, "url": url, "source": src, "time": t})
    return out


def fetch(symbol, detail):
    h = yf.Ticker(symbol).history(period="1y", interval="1d").dropna(subset=["Close"])
    c = h["Close"]
    if len(c) < 2:
        return None
    last, prev = float(c.iloc[-1]), float(c.iloc[-2])
    d = {"price": r(last), "change": r(last - prev), "pct": r((last / prev - 1) * 100),
         "unit": "pt" if symbol in POINTS else "%", "date": c.index[-1].strftime("%Y-%m-%d"),
         "series": [r(x) for x in c.tail(90)]}
    if len(c) >= 30:
        d.update(indicators(c))
    if len(c) >= 60:
        d["zones"] = zones(h)
    if detail:
        d.update(fundamentals(symbol))
        try:
            d["fund"] = fund.collect(symbol)
        except Exception as e:
            print(f"ข้ามพื้นฐาน {symbol}: {e}")
        d["news"] = news(symbol)
    return d


def main():
    groups, feed = [], []
    for title, symbols, detail in GROUPS:
        items = []
        for symbol, name in symbols.items():
            try:
                d = fetch(symbol, detail)
            except Exception as e:  # ตัวใดตัวหนึ่งพังก็ไม่ให้ทั้งหน้าพัง
                print(f"ข้ามหุ้น {symbol}: {e}")
                continue
            if d:
                if detail:
                    d["news"] = newsfeed.prepare(d.get("news", []), "หุ้นรายตัว", [symbol])
                    feed += d["news"][:3]
                items.append({"symbol": symbol, "name": name, **d})
        groups.append({"title": title, "detail": detail, "items": items})
    feed += newsfeed.prepare(news("^GSPC", 6) or news("SPY", 6), "ตลาดและเศรษฐกิจ")
    feed += newsfeed.collect()
    seen, merged = set(), []
    for n in sorted(feed, key=lambda x: x["time"], reverse=True):
        key = re.sub(r"\W+", "", n["title"].lower())[:80]
        if n["url"] in seen or key in seen:
            continue
        seen.update((n["url"], key))
        merged.append(n)
    merged = merged[:60]
    stocks = [g for g in groups if g["detail"]]
    analysis = newsfeed.analyze(merged, [i["symbol"] for g in stocks for i in g["items"]])
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    fund.review([i for g in stocks for i in g["items"]], key)
    names = {i["symbol"]: i["name"] for g in stocks for i in g["items"]}
    mc = macro.collect({**names, "^IXIC": "Nasdaq", "^SOX": "เซมิคอนดักเตอร์ (SOX)"})
    macro.review(mc, merged, key)
    bb = bubble.collect({i["symbol"]: i for g in groups for i in g["items"]}, merged)
    bubble.review(bb, key)
    ph = pfhist.collect([i["symbol"] for g in stocks for i in g["items"]] + ["^IXIC", "^GSPC", "GLD"])
    for g in stocks:
        for i in g["items"]:
            i["news_score"] = sum(n["sent"] for n in i.get("news", []))
    out = {"updated": dt.datetime.now(dt.timezone.utc).isoformat(), "groups": groups, "news": merged, "analysis": analysis, "macro": mc, "bubble": bb, "hist": ph}
    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("เขียน data.json แล้ว")


if __name__ == "__main__":
    main()
