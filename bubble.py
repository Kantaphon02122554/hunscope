"""ตัวเฝ้าระวังความร้อนแรงของ AI (AI bubble watch)
รวมสัญญาณที่วัดได้: มูลค่า ราคาเทียบเส้นเฉลี่ย ราคาเทียบรายได้ ความแคบของตลาด VIX และจำนวนพาดหัวที่พูดถึงฟองสบู่
เกณฑ์เป็นดุลยพินิจทั่วไป ไม่ใช่ค่าที่พิสูจน์ได้ และไม่ใช่เครื่องมือทำนายเวลาที่ตลาดจะกลับตัว"""
import json
import re
import statistics

import pandas as pd
import yfinance as yf

import fund

# หุ้น AI หลักที่ใช้คำนวณ (เอาเฉพาะตัวที่อยู่ในรายการติดตาม) แก้ได้
AI_BASKET = ["NVDA", "MSFT", "GOOGL", "AMZN", "META", "AVGO", "AMD", "TSM", "ASML", "MU"]
BUBBLE_RE = re.compile(r"bubble|froth|overvalu|euphori|mania|overbuil|circular (?:financ|deal)|ai trade|spending (?:spree|binge)|capex", re.I)


def med(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def ind(name, value, f, warm, hot, rule, note, hi=True):
    if value is None:
        return None
    lvl = (2 if value >= hot else 1 if value >= warm else 0) if hi else (2 if value <= hot else 1 if value <= warm else 0)
    return {"name": name, "value": f.format(value), "level": lvl, "rule": rule, "note": note}


def spread():
    """ผลตอบแทน 1 ปีของ S&P 500 ถ่วงน้ำหนักมูลค่าตลาด (SPY) เทียบถ่วงน้ำหนักเท่ากัน (RSP)"""
    try:
        c = yf.download(["SPY", "RSP"], period="1y", interval="1d", progress=False, auto_adjust=True)["Close"].dropna()
        ret = (c.iloc[-1] / c.iloc[0] - 1) * 100
        return float(ret["SPY"] - ret["RSP"])
    except Exception as e:
        print("ข้ามความแคบของตลาด:", e)
        return None


def collect(idx, news):
    """idx = {สัญลักษณ์: ข้อมูลหุ้นจาก data.json}  news = รายการข่าวที่รวมแล้ว"""
    basket = [idx[s] for s in AI_BASKET if s in idx]
    if len(basket) < 3:
        return None
    kpi = lambda i, k: ((i.get("fund") or {}).get("kpi") or {}).get(k)
    ext = [(i["price"] / i["sma200"] - 1) * 100 for i in basket if i.get("sma200") and i.get("price")]
    rsis = [i["rsi"] for i in basket if i.get("rsi") is not None]
    ret1y, rev = med([i.get("ret1y") for i in basket]), med([kpi(i, "rev_yoy") for i in basket])
    hits = [n for n in news if BUBBLE_RE.search(n["title"])]
    rows = [
        ind("P/E คาดการณ์ (มัธยฐาน)", med([kpi(i, "fpe") for i in basket]), "{:.1f}x", 25, 35,
            "ตึงตัวเมื่อ ≥ 25 ร้อนแรงเมื่อ ≥ 35", "ยิ่งสูง ราคายิ่งพึ่งการเติบโตในอนาคตมาก"),
        ind("P/S (มัธยฐาน)", med([kpi(i, "ps") for i in basket]), "{:.1f}x", 6, 12,
            "ตึงตัวเมื่อ ≥ 6 ร้อนแรงเมื่อ ≥ 12", "ราคาต่อยอดขาย 12 เดือนล่าสุด"),
        ind("ราคาเหนือเส้นเฉลี่ย 200 วัน (มัธยฐาน)", med(ext), "{:+.1f}%", 15, 30,
            "ตึงตัวเมื่อ ≥ 15% ร้อนแรงเมื่อ ≥ 30%", "ราคาห่างจากแนวโน้มระยะยาวมาก มักปรับฐานง่ายขึ้น"),
        ind("สัดส่วนหุ้นที่ RSI สูงกว่า 70", (sum(1 for x in rsis if x > 70) / len(rsis) * 100) if rsis else None, "{:.0f}%", 30, 60,
            "ตึงตัวเมื่อ ≥ 30% ร้อนแรงเมื่อ ≥ 60%", "หุ้นที่ซื้อมากเกินไปพร้อมกันหลายตัว"),
        ind("ผลตอบแทน 1 ปี (มัธยฐาน)", ret1y, "{:+.0f}%", 40, 80,
            "ตึงตัวเมื่อ ≥ 40% ร้อนแรงเมื่อ ≥ 80%", "ผลตอบแทนที่ผ่านมาสูงไม่ได้แปลว่าจะต่อเนื่อง แต่ยิ่งสูงยิ่งคาดหวังสูง"),
        ind("ราคาวิ่งนำรายได้", None if ret1y is None or rev is None else ret1y - rev, "{:+.0f} จุด", 15, 40,
            "ตึงตัวเมื่อ ≥ 15 ร้อนแรงเมื่อ ≥ 40", "ผลตอบแทน 1 ปีลบด้วยรายได้โต YoY ล่าสุด (ค่ามัธยฐาน)"),
        ind("ตลาดแคบ (SPY − RSP, 1 ปี)", spread(), "{:+.1f} จุด", 4, 8,
            "ตึงตัวเมื่อ ≥ 4 ร้อนแรงเมื่อ ≥ 8", "ถ้าหุ้นใหญ่ชนะหุ้นถ่วงเท่ากันมาก แปลว่าตลาดพึ่งหุ้นไม่กี่ตัว"),
        ind("VIX (ความชะล่าใจ)", (idx.get("^VIX") or {}).get("price"), "{:.1f}", 17, 14,
            "ตึงตัวเมื่อ ≤ 17 ร้อนแรงเมื่อ ≤ 14", "VIX ต่ำมากแปลว่านักลงทุนกังวลน้อย", hi=False),
        ind("พาดหัวที่พูดถึงฟองสบู่/ความร้อนแรง", float(len(hits)), "{:.0f} ข่าว", 3, 8,
            "ตึงตัวเมื่อ ≥ 3 ร้อนแรงเมื่อ ≥ 8", "นับจากคำเช่น bubble, froth, overvalued, capex ในพาดหัวล่าสุด"),
    ]
    rows = [x for x in rows if x]
    if not rows:
        return None
    score = sum(x["level"] for x in rows) / (2 * len(rows))
    label = "ยังไม่ร้อนแรง" if score < 0.34 else "เริ่มตึงตัว" if score < 0.67 else "ร้อนแรง"
    return {"score": round(score, 2), "label": label, "indicators": rows, "basket": [i["symbol"] for i in basket],
            "headlines": [{k: n.get(k) for k in ("title", "title_th", "url", "source", "time")} for n in hits[:8]]}


def review(bb, key):
    """ให้ Claude สรุปภาพรวมจากตัวชี้วัดและพาดหัวที่ให้เท่านั้น"""
    if not key or not bb:
        return
    prompt = ("ต่อไปนี้คือตัวชี้วัดความร้อนแรงของหุ้น AI (JSON, level 0=ปกติ 1=ตึงตัว 2=ร้อนแรง เกณฑ์เป็นดุลยพินิจทั่วไป) และพาดหัวข่าวที่พูดถึงฟองสบู่ "
              "ช่วยสรุปเป็นภาษาไทย ตอบ JSON ล้วน ไม่มีข้อความอื่น รูปแบบ "
              '{"summary":"ภาพรวม 3-4 ประโยค","hot":["สัญญาณที่ร้อน"],"ok":["สัญญาณที่ยังรับได้"],"watch":["สิ่งที่ควรติดตามต่อ"]} '
              "กติกา: ใช้เฉพาะข้อมูลที่ให้มา ห้ามทำนายว่าตลาดจะแตกเมื่อไร ห้ามแนะนำซื้อขาย ต้องบอกว่าคะแนนรวมเป็นภาพคร่าวๆ และเป็นกลาง "
              "ไม่เอนเอียงไปทางกลัวหรือมั่นใจเกินไป hot/ok/watch ข้อละไม่เกิน 3 รายการ\n\nข้อมูล: "
              + json.dumps({k: bb[k] for k in ("score", "label", "indicators", "headlines")}, ensure_ascii=False))
    try:
        res = fund._claude_json(prompt, key, 2500)
    except Exception as e:
        print("Claude สรุปความร้อนแรง AI ไม่สำเร็จ ข้ามส่วนนี้:", e)
        return
    lst = lambda k: [str(x)[:200] for x in res.get(k, [])[:3]]
    bb["ai"] = {"summary": str(res.get("summary", ""))[:900], "hot": lst("hot"), "ok": lst("ok"), "watch": lst("watch")}
