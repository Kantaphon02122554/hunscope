"""พื้นฐานบริษัท รายงานไตรมาส และสกอร์การ์ดตามกฎง่ายๆ จาก Yahoo Finance
ถ้ามี ANTHROPIC_API_KEY จะให้ Claude เขียนสรุปภาษาไทยจากตัวเลขเหล่านี้ด้วย (ไม่มีก็ข้ามส่วนนั้น)"""
import json
import os
import urllib.request

import pandas as pd
import yfinance as yf


def num(x, n=2):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(x) else round(x, n)


def row(df, *names):
    for n in names:
        if n in df.index:
            return df.loc[n]
    return None


def quarters(t):
    try:
        q = t.quarterly_income_stmt
    except Exception:
        return []
    if q is None or q.empty:
        return []
    q = q.sort_index(axis=1, ascending=False)  # ใหม่สุดก่อน
    rev = row(q, "Total Revenue", "Operating Revenue")
    ni = row(q, "Net Income", "Net Income Common Stockholders")
    eps = row(q, "Diluted EPS", "Basic EPS")
    gp = row(q, "Gross Profit")
    op = row(q, "Operating Income")
    val = lambda s, i: None if s is None or i >= len(s) else num(s.iloc[i], 4)
    out = []
    for i, c in enumerate(list(q.columns)[:4]):
        r0, r4 = val(rev, i), val(rev, i + 4)
        n0 = val(ni, i)
        pct = lambda a: round(a / r0 * 100, 1) if a is not None and r0 else None
        out.append({
            "date": pd.Timestamp(c).strftime("%Y-%m-%d"),
            "rev": None if r0 is None else round(r0 / 1e9, 2),
            "rev_yoy": round((r0 / r4 - 1) * 100, 1) if r0 and r4 and r4 > 0 else None,
            "ni": None if n0 is None else round(n0 / 1e9, 2),
            "nm": pct(n0), "gm": pct(val(gp, i)), "om": pct(val(op, i)),
            "eps": num(val(eps, i)),
        })
    return out


def surprises(t):
    try:
        h = t.earnings_history
    except Exception:
        return []
    if h is None or len(h) == 0:
        return []
    out = []
    for idx, r in h.sort_index(ascending=False).head(4).iterrows():
        est, act = num(r.get("epsEstimate")), num(r.get("epsActual"))
        out.append({"date": pd.Timestamp(idx).strftime("%Y-%m-%d"), "estimate": est, "actual": act,
                    "surprise": round((act - est) / abs(est) * 100, 1) if est and act is not None else None})
    return out


def next_earnings(t):
    try:
        ed = t.calendar.get("Earnings Date")
        if ed:
            return pd.Timestamp(ed[0] if isinstance(ed, (list, tuple)) else ed).strftime("%Y-%m-%d")
    except Exception:
        pass
    return None


def collect(symbol):
    t = yf.Ticker(symbol)
    try:
        info = t.info or {}
    except Exception:
        info = {}
    cur = info.get("financialCurrency") or info.get("currency") or ""
    qs = quarters(t)
    pc = lambda k: None if num(info.get(k)) is None else num(info.get(k)) * 100
    pos = lambda x: x if x is not None and x > 0 else None
    rev_yoy = qs[0]["rev_yoy"] if qs and qs[0]["rev_yoy"] is not None else pc("revenueGrowth")
    nm = qs[0]["nm"] if qs and qs[0]["nm"] is not None else pc("profitMargins")
    roe = pc("returnOnEquity")
    de = num(info.get("debtToEquity"))
    de = None if de is None else de / 100
    fcf = num(info.get("freeCashflow"))
    fcf = None if fcf is None else fcf / 1e9
    fpe = pos(num(info.get("forwardPE")))
    ps = pos(num(info.get("priceToSalesTrailing12Months")))
    price = num(info.get("currentPrice") or info.get("regularMarketPrice"))
    target = num(info.get("targetMeanPrice"))
    up = (target / price - 1) * 100 if price and target else None

    # (กลุ่ม, ชื่อ, ค่า, รูปแบบ, เกณฑ์ดี, เกณฑ์แย่, ยิ่งสูงยิ่งดี?, (ข้อความดี, กลาง, แย่))
    rules = [
        ("growth", "รายได้โต YoY", rev_yoy, "{:.1f}%", 15, 0, True, ("โตเร็ว", "โตช้า", "รายได้หดตัว")),
        ("growth", "กำไรโต YoY", pc("earningsGrowth"), "{:.1f}%", 15, 0, True, ("กำไรโตเร็ว", "กำไรโตช้า", "กำไรลดลง")),
        ("profit", "อัตรากำไรขั้นต้น", pc("grossMargins"), "{:.1f}%", 40, 20, True, ("สูง", "ปานกลาง", "ต่ำ")),
        ("profit", "อัตรากำไรจากการดำเนินงาน", pc("operatingMargins"), "{:.1f}%", 20, 8, True, ("สูง", "ปานกลาง", "ต่ำ")),
        ("profit", "ROE", roe, "{:.1f}%", 15, 8, True, ("ผลตอบแทนต่อผู้ถือหุ้นสูง", "พอใช้", "ต่ำ")),
        ("health", "หนี้สินต่อทุน", de, "{:.2f}x", 1.0, 2.0, False, ("หนี้ต่ำ", "หนี้ปานกลาง", "หนี้สูง")),
        ("health", "อัตราส่วนสภาพคล่อง", num(info.get("currentRatio")), "{:.2f}", 1.5, 1.0, True, ("สภาพคล่องดี", "พอใช้", "สภาพคล่องตึง")),
        ("health", "กระแสเงินสดอิสระ (พันล้าน)", fcf, "{:.1f}", 0.0001, 0, True, ("เป็นบวก", "ใกล้ศูนย์", "ติดลบ")),
        ("value", "P/E คาดการณ์", fpe, "{:.1f}", 20, 35, False, ("ไม่แพง", "พอเหมาะ", "ค่อนข้างแพง")),
        ("value", "PEG", pos(num(info.get("trailingPegRatio") or info.get("pegRatio"))), "{:.2f}", 1.5, 2.5, False, ("ไม่แพงเทียบการเติบโต", "พอเหมาะ", "แพงเทียบการเติบโต")),
        ("value", "P/S", ps, "{:.1f}", 6, 15, False, ("ไม่แพง", "พอเหมาะ", "ค่อนข้างแพง")),
        ("analyst", "ส่วนต่างถึงราคาเป้าหมายเฉลี่ย", up, "{:+.1f}%", 15, 0, True, ("เป้าหมายสูงกว่าราคาพอสมควร", "ใกล้ราคาปัจจุบัน", "ราคาเกินเป้าหมายเฉลี่ย")),
    ]
    metrics = []
    for g, name, x, f, good, bad, hi, texts in rules:
        if x is None:
            continue
        s = (1 if x >= good else -1 if x < bad else 0) if hi else (1 if x <= good else -1 if x > bad else 0)
        metrics.append({"group": g, "name": name, "value": f.format(x), "text": texts[0 if s > 0 else 2 if s < 0 else 1], "score": s})
    rk = info.get("recommendationKey")
    rec = {"strong_buy": ("ซื้อแรง", 1), "buy": ("ซื้อ", 1), "hold": ("ถือ", 0), "underperform": ("ต่ำกว่าตลาด", -1),
           "sell": ("ขาย", -1), "strong_sell": ("ขายแรง", -1)}.get(rk)
    if rec:
        metrics.append({"group": "analyst", "name": "ความเห็นนักวิเคราะห์ส่วนใหญ่", "value": rec[0], "text": "", "score": rec[1]})

    avg = lambda gs: (lambda l: sum(l) / len(l) if l else None)([m["score"] for m in metrics if m["group"] in gs])
    qa, va = avg(("growth", "profit", "health")), avg(("value",))
    quality = "ข้อมูลไม่พอ" if qa is None else "คุณภาพดี" if qa >= 0.4 else "คุณภาพอ่อน" if qa <= -0.2 else "คุณภาพปานกลาง"
    valuation = "ข้อมูลไม่พอ" if va is None else "ราคาไม่แพง" if va >= 0.3 else "ราคาค่อนข้างแพง" if va <= -0.3 else "ราคาพอเหมาะ"
    return {"currency": cur, "quality": quality, "valuation": valuation, "metrics": metrics, "quarters": qs,
            "surprises": surprises(t), "next_earnings": next_earnings(t),
            "kpi": {"rev_yoy": rev_yoy, "nm": nm, "roe": roe, "de": de, "fpe": fpe, "ps": ps}}


def _claude_json(prompt, key, max_tokens=5000):
    body = json.dumps({"model": os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5"), "max_tokens": max_tokens,
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body, headers={
        "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    resp = json.loads(urllib.request.urlopen(req, timeout=120).read())
    text = "".join(b.get("text", "") for b in resp["content"] if b.get("type") == "text")
    return json.loads(text[text.index("{"): text.rindex("}") + 1])


def review(items, key):
    """ให้ Claude สรุปพื้นฐานรายตัวเป็นภาษาไทย จากตัวเลขที่เราส่งให้เท่านั้น"""
    if not key:
        return
    data = {i["symbol"]: {"name": i["name"], "currency": i["fund"]["currency"], "quality": i["fund"]["quality"],
                          "valuation": i["fund"]["valuation"],
                          "metrics": [f'{m["name"]} {m["value"]} {m["text"]}'.strip() for m in i["fund"]["metrics"]],
                          "quarters": i["fund"]["quarters"], "surprises": i["fund"]["surprises"]}
            for i in items if i.get("fund")}
    if not data:
        return
    prompt = ("ต่อไปนี้คือข้อมูลพื้นฐานและงบไตรมาสล่าสุดของหุ้นเทคสหรัฐ (JSON, งบเป็นหน่วยพันล้านของสกุลเงินที่ระบุ) "
              "ช่วยสรุปเป็นภาษาไทยทีละตัว ตอบเป็น JSON ล้วน ไม่มีข้อความอื่น รูปแบบ "
              '{"SYMBOL":{"summary":"ภาพรวมคุณภาพธุรกิจและความถูกแพง 2-3 ประโยค","strengths":["จุดแข็ง"],"risks":["ความเสี่ยงหรือข้อสังเกต"],"quarter":"สรุปไตรมาสล่าสุดและผลเทียบประมาณการ 1-2 ประโยค"}} '
              "กติกา: ใช้เฉพาะตัวเลขที่ให้มา ห้ามอ้างข้อมูลอื่นหรือคาดการณ์อนาคต ห้ามแนะนำซื้อขาย "
              "ถ้าข้อมูลขาดให้บอกว่าข้อมูลไม่พอ และไม่เทียบตัวเลขข้ามสกุลเงิน\n\n" + json.dumps(data, ensure_ascii=False))
    try:
        res = _claude_json(prompt, key)
    except Exception as e:
        print("Claude สรุปพื้นฐานไม่สำเร็จ ข้ามส่วนนี้:", e)
        return
    for i in items:
        r = res.get(i["symbol"])
        if isinstance(r, dict) and i.get("fund"):
            i["fund"]["ai"] = {"summary": str(r.get("summary", ""))[:700],
                               "strengths": [str(x)[:160] for x in r.get("strengths", [])[:3]],
                               "risks": [str(x)[:160] for x in r.get("risks", [])[:3]],
                               "quarter": str(r.get("quarter", ""))[:400]}
