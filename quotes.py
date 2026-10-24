"""ราคาล่าสุดแบบเบาของทุกสัญลักษณ์ใน data.json -> quotes.json
รันทุก ~10 นาทีตอนตลาดสหรัฐเปิด (ดู .github/workflows/quotes.yml) ไม่แตะงบ ข่าว หรือตัวชี้วัด
ส่วนต่างคำนวณจากราคาปิดวันก่อนหน้าใน data.json ถ้าราคาไม่เปลี่ยนจากรอบก่อน จะไม่เขียนไฟล์ (ไม่เกิด commit)"""
import datetime as dt
import json

import yfinance as yf


def main():
    try:
        data = json.load(open("data.json", encoding="utf-8"))
    except Exception as e:
        print("อ่าน data.json ไม่ได้:", e)
        return
    items = {i["symbol"]: i for g in data["groups"] for i in g["items"]}
    try:
        close = yf.download(list(items), period="5d", interval="5m", progress=False, auto_adjust=True)["Close"]
    except Exception as e:
        print("ดึงราคาไม่สำเร็จ:", e)
        return
    out = {}
    for sym, it in items.items():
        if sym not in close:
            continue
        s = close[sym].dropna()
        if s.empty:
            continue
        ts = s.index[-1]
        ts = ts.tz_convert("UTC") if ts.tzinfo else ts.tz_localize("UTC")
        last = float(s.iloc[-1])
        # วันใหม่กว่า data.json: ฐานคือราคาปิดใน data.json / วันเดียวกัน: ฐานคือราคาปิดก่อนหน้านั้น
        base = it["price"] if ts.strftime("%Y-%m-%d") > it["date"] else it["price"] - it["change"]
        if not base:
            continue
        out[sym] = {"price": round(last, 2), "change": round(last - base, 2),
                    "pct": round((last / base - 1) * 100, 2), "t": ts.strftime("%Y-%m-%dT%H:%M:%SZ")}
    if not out:
        print("ไม่มีราคาใหม่")
        return
    try:
        old = json.load(open("quotes.json", encoding="utf-8")).get("q")
    except Exception:
        old = None
    if old == out:
        print("ราคาไม่เปลี่ยน ไม่เขียนไฟล์")
        return
    with open("quotes.json", "w", encoding="utf-8") as f:
        json.dump({"updated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "q": out},
                  f, ensure_ascii=False, separators=(",", ":"))
    print(f"เขียน quotes.json ({len(out)} ตัว)")


if __name__ == "__main__":
    main()
