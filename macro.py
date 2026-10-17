"""วิเคราะห์สถานการณ์มหภาค
- ความอ่อนไหวของหุ้นต่อน้ำมัน Brent และผลตอบแทนพันธบัตรสหรัฐ 10 ปี (ถดถอยจากผลตอบแทนรายวันย้อนหลัง 1 ปี)
- ดอกเบี้ยเฟดและ CPI จาก FRED (ถ้าเข้าถึงได้)
- ถ้ามี ANTHROPIC_API_KEY ให้ Claude สรุปสถานการณ์ปัจจุบันของแต่ละปัจจัยจากข้อมูลและพาดหัวข่าว"""
import csv
import io
import json
import urllib.request

import numpy as np
import pandas as pd
import yfinance as yf

import fund

UA = {"User-Agent": "Mozilla/5.0 (stock-dashboard)"}


def r(x, n=2):
    return None if x is None or pd.isna(x) else round(float(x), n)


def fred(series):
    try:
        raw = urllib.request.urlopen(urllib.request.Request(
            f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}", headers=UA), timeout=20).read().decode()
        return [(d, float(v)) for d, v in list(csv.reader(io.StringIO(raw)))[1:] if v not in ("", ".")]
    except Exception as e:
        print(f"ข้าม FRED {series}: {e}")
        return []


def yoy(rows):
    return (rows[-1][1] / rows[-13][1] - 1) * 100 if len(rows) >= 13 else None


def context(px):
    c = {}
    oil, y10 = px["BZ=F"], px["^TNX"]
    if len(oil) > 22:
        c["brent"] = {"price": r(oil.iloc[-1]), "chg1m": r((oil.iloc[-1] / oil.iloc[-22] - 1) * 100, 1)}
    if len(y10) > 22:
        c["y10"] = {"level": r(y10.iloc[-1]), "chg1m_bp": r((y10.iloc[-1] - y10.iloc[-22]) * 100, 0)}
    ff = fred("DFF")
    if ff:
        c["fedfunds"] = {"rate": r(ff[-1][1]), "date": ff[-1][0]}
    cpi, core = fred("CPIAUCSL"), fred("CPILFESL")
    if yoy(cpi) is not None:
        c["cpi"] = {"yoy": r(yoy(cpi), 1), "core_yoy": r(yoy(core), 1), "month": cpi[-1][0][:7]}
    return c


def collect(names):
    """names = {สัญลักษณ์: ชื่อที่แสดง} ของหุ้น/ดัชนีที่จะวิเคราะห์"""
    syms = list(names)
    try:
        df = yf.download(syms + ["BZ=F", "^TNX"], period="1y", interval="1d", progress=False, auto_adjust=True)
        px = (df["Close"] if isinstance(df.columns, pd.MultiIndex) else df).dropna(axis=1, how="all").ffill().copy()
    except Exception as e:
        print("ข้ามการวิเคราะห์สถานการณ์:", e)
        return None
    if px.empty or "BZ=F" not in px or "^TNX" not in px:
        return None
    px = px.dropna(subset=["BZ=F", "^TNX"])
    if px.empty:
        return None
    if px["^TNX"].iloc[-1] > 20:  # บางช่วง Yahoo ส่งค่าเป็น yield x10
        px["^TNX"] = px["^TNX"] / 10
    X = pd.concat([(px["BZ=F"].pct_change() * 100).rename("oil"), (px["^TNX"].diff() * 100).rename("dy")], axis=1)
    sens = []
    for s in [s for s in syms if s in px]:
        d = pd.concat([(px[s].pct_change() * 100).rename("y"), X], axis=1).dropna()
        if len(d) < 60:
            continue
        A = np.column_stack([np.ones(len(d)), d["oil"].values, d["dy"].values])
        coef = np.linalg.lstsq(A, d["y"].values, rcond=None)[0]
        res = d["y"].values - A @ coef
        se = np.sqrt(np.diag(res @ res / (len(d) - 3) * np.linalg.pinv(A.T @ A)))
        tot = ((d["y"] - d["y"].mean()) ** 2).sum()
        sens.append({"symbol": s, "name": names[s], "b_oil": r(coef[1], 3), "t_oil": r(coef[1] / se[1], 1),
                     "b_y": r(coef[2], 3), "t_y": r(coef[2] / se[2], 1), "r2": r(1 - res @ res / tot, 3), "n": int(len(d))})
    return {"context": context(px), "sens": sens}


def review(m, news, key):
    """ให้ Claude สรุป 'สถานการณ์ตอนนี้' ของแต่ละปัจจัยจากข้อมูลและพาดหัวข่าวที่ให้เท่านั้น"""
    if not key or not m:
        return
    topics = {"น้ำมัน", "เฟดและดอกเบี้ย", "เงินเฟ้อ", "ภาษีและการค้า"}
    heads = [f'[{n["source"]}] {n["title"]}' for n in news if topics & set(n.get("topics", []))][:16]
    prompt = ("ต่อไปนี้คือข้อมูลมหภาคล่าสุด (JSON) และพาดหัวข่าวที่เกี่ยวข้อง (ภาษาอังกฤษ) ช่วยสรุปเป็นภาษาไทยว่าแต่ละปัจจัยตอนนี้เป็นอย่างไร "
              'ตอบ JSON ล้วน ไม่มีข้อความอื่น รูปแบบ {"oil":{"now":"2 ประโยค","watch":["สิ่งที่ตลาดกำลังจับตา"]},"rates":{...},"inflation":{...},"trade":{...}} '
              "กติกา: ใช้เฉพาะข้อมูลและพาดหัวที่ให้มา ห้ามคาดการณ์ตัวเลขหรือวันที่ที่ไม่มีในข้อมูล ห้ามแนะนำซื้อขาย "
              "watch มี 2-3 ข้อ ถ้าข้อมูลของปัจจัยไหนไม่พอให้บอกตรงๆ\n\nข้อมูล: "
              + json.dumps(m["context"], ensure_ascii=False) + "\n\nพาดหัว:\n" + "\n".join(heads))
    try:
        res = fund._claude_json(prompt, key, 3000)
    except Exception as e:
        print("Claude สรุปสถานการณ์ไม่สำเร็จ ข้ามส่วนนี้:", e)
        return
    ai = {}
    for k in ("oil", "rates", "inflation", "trade"):
        v = res.get(k)
        if isinstance(v, dict):
            ai[k] = {"now": str(v.get("now", ""))[:500], "watch": [str(x)[:200] for x in v.get("watch", [])[:3]]}
    m["ai"] = ai
