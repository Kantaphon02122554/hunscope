"""งบรายไตรมาสจาก SEC EDGAR (XBRL) สำหรับบริษัทสหรัฐ ออกเร็วกว่าตารางงบของ Yahoo มาก
ต้องตั้งตัวแปร SEC_CONTACT (อีเมลของคุณ) ตามข้อกำหนดการเข้าถึงของ SEC ถ้าไม่ตั้งจะข้ามส่วนนี้ (ใช้ข้อมูลจาก Yahoo ตามเดิม)
บริษัทต่างประเทศ (เช่น TSM, ASML) ไม่มีข้อมูลรูปแบบนี้ จะข้ามไปเอง"""
import datetime as dt
import json
import os
import time
import urllib.error
import urllib.request

TAGS = {
    "rev": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
            "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueNet"],
    "ni": ["NetIncomeLoss", "ProfitLoss"],
    "gp": ["GrossProfit"],
    "op": ["OperatingIncomeLoss"],
}
EPS_TAGS = ["EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted", "EarningsPerShareBasic"]
_state = {"map": None, "warned": False}


def _get(url, ua):
    time.sleep(0.12)  # SEC อนุญาตไม่เกิน 10 คำขอต่อวินาที
    req = urllib.request.Request(url, headers={"User-Agent": ua})
    return json.loads(urllib.request.urlopen(req, timeout=30).read())


def _days(a, b):
    return (dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days


def series(facts, tags, unit="USD", derive_q4=True):
    """คืน {วันสิ้นไตรมาส: ค่า} ของไตรมาส (ช่วง 3 เดือน) และไตรมาส 4 ที่คำนวณจาก ปีเต็ม − 9 เดือน"""
    best = None
    for tag in tags:
        rows = (facts.get("us-gaap", {}).get(tag) or {}).get("units", {}).get(unit) or []
        rows = [r for r in rows if "start" in r and "end" in r]
        if rows and (best is None or max(r["end"] for r in rows) > best[0]):
            best = (max(r["end"] for r in rows), rows)
    if best is None:
        return {}
    uniq = {}
    for r in best[1]:  # ช่วงเวลาเดียวกันที่ถูกแก้ไขย้อนหลัง ใช้รายการที่ยื่นล่าสุด
        k = (r["start"], r["end"])
        if k not in uniq or r.get("filed", "") > uniq[k].get("filed", ""):
            uniq[k] = r
    q, ytd9, fy = {}, {}, {}
    for (s, e), r in uniq.items():
        d = _days(s, e)
        if 80 <= d <= 100:
            q[e] = r["val"]
        elif 260 <= d <= 285:
            ytd9[e] = r["val"]
        elif 350 <= d <= 380:
            fy[e] = r["val"]
    if derive_q4:
        for e, v in fy.items():
            for e9, v9 in ytd9.items():
                if e not in q and 80 <= _days(e9, e) <= 100:
                    q[e] = v - v9
    return q


def build_quarters(facts):
    rev = series(facts, TAGS["rev"])
    if not rev:
        return []
    ni, gp, op = (series(facts, TAGS[k]) for k in ("ni", "gp", "op"))
    eps = series(facts, EPS_TAGS, "USD/shares", derive_q4=False)
    out = []
    for e in sorted(rev, reverse=True)[:4]:
        r0 = rev[e]
        prior = [k for k in rev if 350 <= _days(k, e) <= 380]
        r4 = rev[prior[0]] if prior else None
        pct = lambda x: round(x / r0 * 100, 1) if x is not None and r0 else None
        out.append({"date": e, "rev": round(r0 / 1e9, 2),
                    "rev_yoy": round((r0 / r4 - 1) * 100, 1) if r4 and r4 > 0 else None,
                    "ni": round(ni[e] / 1e9, 2) if e in ni else None, "nm": pct(ni.get(e)),
                    "gm": pct(gp.get(e)), "om": pct(op.get(e)), "eps": round(eps[e], 2) if e in eps else None})
    return out


def overlay(symbol, yahoo_qs):
    """คืนงบรายไตรมาสจาก SEC ถ้ามีไตรมาสที่ใหม่กว่าของ Yahoo ไม่งั้นคืน None (ให้ใช้ของ Yahoo)"""
    contact = os.environ.get("SEC_CONTACT", "").strip()
    if not contact:
        if not _state["warned"]:
            print("ไม่ได้ตั้ง SEC_CONTACT จึงใช้ข้อมูลงบจาก Yahoo อย่างเดียว (ตั้งอีเมลเพื่อให้ดึงงบล่าสุดจาก SEC ได้)")
            _state["warned"] = True
        return None
    ua = f"Hunscope/1.0 ({contact})"
    try:
        if _state["map"] is None:
            raw = _get("https://www.sec.gov/files/company_tickers.json", ua)
            _state["map"] = {v["ticker"].upper(): int(v["cik_str"]) for v in raw.values()}
        cik = _state["map"].get(symbol.upper())
        if not cik:
            return None
        sec = build_quarters(_get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json", ua).get("facts", {}))
    except urllib.error.HTTPError as e:
        if e.code != 404:  # 404 = ไม่มีข้อมูลรูปแบบนี้ (เช่น บริษัทต่างประเทศ) ไม่ต้องแจ้ง
            print(f"ข้าม SEC {symbol}: HTTP {e.code}")
        return None
    except Exception as e:
        print(f"ข้าม SEC {symbol}: {e}")
        return None
    if not sec or (yahoo_qs and sec[0]["date"] <= yahoo_qs[0]["date"]):
        return None
    return sec
