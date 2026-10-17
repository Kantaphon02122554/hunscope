"""รวบรวมข่าวจากหลายแหล่ง วิเคราะห์ความรู้สึกของพาดหัว
และให้ Claude สรุป/แปลเป็นไทยถ้ามี ANTHROPIC_API_KEY (ไม่มีก็ใช้การนับคำสำคัญแทน)"""
import datetime as dt
import json
import os
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from email.utils import parsedate_to_datetime

UA = {"User-Agent": "Mozilla/5.0 (stock-dashboard)"}
MAX_AGE_DAYS = 4


def gnews(q):
    return "https://news.google.com/rss/search?q=" + urllib.parse.quote(q) + "&hl=en-US&gl=US&ceid=US:en"


# (หมวด, ชื่อแหล่ง (None = ใช้ชื่อสื่อจากตัวข่าว), URL ฟีด RSS) เพิ่ม/ลบได้ตามต้องการ
FEEDS = [
    ("ตลาดและเศรษฐกิจ", "CNBC", "https://www.cnbc.com/id/15839069/device/rss/rss.html"),
    ("ตลาดและเศรษฐกิจ", "CNBC", "https://www.cnbc.com/id/20910258/device/rss/rss.html"),
    ("ตลาดและเศรษฐกิจ", "MarketWatch", "https://feeds.content.dowjones.io/public/rss/mw_topstories"),
    ("ตลาดและเศรษฐกิจ", "BBC Business", "http://feeds.bbci.co.uk/news/business/rss.xml"),
    ("เทคโนโลยี", "CNBC Tech", "https://www.cnbc.com/id/19854910/device/rss/rss.html"),
    ("ธนาคารกลาง", "Federal Reserve", "https://www.federalreserve.gov/feeds/press_all.xml"),
    ("ธนาคารและนักวิเคราะห์", None, gnews('("Goldman Sachs" OR JPMorgan OR "Morgan Stanley" OR "Bank of America" OR Citi OR UBS) (Nvidia OR Microsoft OR Apple OR chip OR "AI stocks") when:3d')),
    ("ธนาคารและนักวิเคราะห์", None, gnews("Wall Street analyst upgrade OR downgrade tech stock when:2d")),
]

COMPANIES = [(r"\bNvidia\b", "NVDA"), (r"\bMicrosoft\b", "MSFT"), (r"\bApple\b", "AAPL"),
             (r"\b(Alphabet|Google)\b", "GOOGL"), (r"\b(Meta|Facebook)\b", "META"), (r"\bBroadcom\b", "AVGO"),
             (r"\bAMD\b", "AMD"), (r"\b(TSMC|Taiwan Semiconductor)\b", "TSM"), (r"\bMicron\b", "MU"),
             (r"\bAmazon\b", "AMZN"), (r"\bASML\b", "ASML"), (r"\bOklo\b", "OKLO"), (r"\bSpaceX\b", "SPCX"), (r"\bTelomir\b", "TELO")]
TOPICS = {
    "AI": r"\bAI\b|artificial intelligence|OpenAI|chatbot",
    "ชิป": r"\bchips?\b|semiconductor|Nvidia|TSMC|\bAMD\b|Micron|Broadcom|ASML",
    "น้ำมัน": r"\boil\b|crude|Brent|OPEC",
    "เฟดและดอกเบี้ย": r"\bFed\b|Federal Reserve|interest rate|rate cut|rate hike|Powell|yield",
    "เงินเฟ้อ": r"inflation|\bCPI\b|\bPPI\b",
    "ภาษีและการค้า": r"tariff|trade war|export control|sanction",
    "ผลประกอบการ": r"earnings|revenue|profit|guidance",
}
POS = ["surge", "soar", "jump", "rall", "beat", "record", "gain", "rise", "climb", "upgrade", "raises", "bullish", "strong", "boost", "outperform", "optimis", "tops"]
NEG = ["fall", "drop", "plunge", "slump", "miss", "cut", "downgrade", "warn", "bearish", "weak", "probe", "lawsuit", "ban", "tariff", "sell-off", "selloff", "fear", "risk", "concern", "decline", "slide", "tumble", "crash", "layoff", "slow"]
_pos = re.compile(r"\b(?:" + "|".join(POS) + ")", re.I)
_neg = re.compile(r"\b(?:" + "|".join(NEG) + ")", re.I)


def to_iso(s):
    if not s:
        return ""
    try:
        t = parsedate_to_datetime(s)
    except Exception:
        try:
            t = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:
            return ""
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.timezone.utc)
    return t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def annotate(n, symbols=None):
    t = n["title"]
    p, g = len(_pos.findall(t)), len(_neg.findall(t))
    n["sent"] = 1 if p > g else -1 if g > p else 0
    n["topics"] = [k for k, rx in TOPICS.items() if re.search(rx, t, re.I)]
    n["symbols"] = sorted(set(symbols or []) | {s for rx, s in COMPANIES if re.search(rx, t)})
    return n


def prepare(items, category, symbols=None):
    return [annotate({**n, "category": category}, symbols) for n in items if n.get("title") and n.get("url")]


def read_feed(source, url, n=8):
    try:
        raw = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20).read()
        root = ET.fromstring(raw)
    except Exception as e:
        print(f"ข้ามฟีด {url[:70]}: {e}")
        return []
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=MAX_AGE_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        src = source or (it.findtext("source") or "").strip() or "Google News"
        if source is None and title.endswith(" - " + src):
            title = title[: -len(src) - 3]
        t = to_iso(it.findtext("pubDate") or "")
        if title and link and t >= cutoff:
            out.append({"title": title, "url": link, "source": src, "time": t})
    return out[:n]


def collect():
    out = []
    for category, source, url in FEEDS:
        out += prepare(read_feed(source, url), category)
    return out


def ask_claude(items, key):
    lines = "\n".join(f"{i}. [{n['category']}] {n['title']} ({n['source']})" for i, n in enumerate(items[:40]))
    prompt = f"""ด้านล่างคือพาดหัวข่าวตลาดหุ้นสหรัฐล่าสุด (ภาษาอังกฤษ) ช่วยวิเคราะห์เป็นภาษาไทย
ตอบเป็น JSON ล้วนๆ ไม่มีข้อความอื่น รูปแบบ:
{{"summary":"สรุปภาพรวมข่าวและบรรยากาศตลาด 3-4 ประโยค","themes":[{{"title":"ประเด็น","detail":"อธิบายสั้นๆ"}}],"watch":["สิ่งที่ควรจับตา"],"items":[{{"i":0,"th":"พาดหัวแปลเป็นไทย","sentiment":"บวก|กลาง|ลบ","reason":"เหตุผลสั้นๆ ไม่เกิน 1 ประโยค"}}]}}
กติกา: ใช้เฉพาะข้อมูลจากพาดหัวด้านล่าง ห้ามเดาเนื้อหาที่ไม่ได้ระบุ ไม่ให้คำแนะนำซื้อขาย
sentiment คือผลของข่าวต่อบรรยากาศตลาดหรือราคาหุ้นที่เกี่ยวข้อง themes 3-4 ข้อ watch 2-3 ข้อ

พาดหัว:
{lines}"""
    body = json.dumps({"model": os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5"), "max_tokens": 6000,
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body, headers={
        "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    resp = json.loads(urllib.request.urlopen(req, timeout=120).read())
    text = "".join(b.get("text", "") for b in resp["content"] if b.get("type") == "text")
    return json.loads(text[text.index("{"): text.rindex("}") + 1])


def analyze(items, symbols):
    a = {"method": "keywords"}
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if key and items:
        try:
            res = ask_claude(items, key)
            smap = {"บวก": 1, "กลาง": 0, "ลบ": -1}
            for it in res.get("items", []):
                i = it.get("i")
                if isinstance(i, int) and 0 <= i < min(40, len(items)):
                    n = items[i]
                    if it.get("th"):
                        n["title_th"] = str(it["th"])[:300]
                    if it.get("sentiment") in smap:
                        n["sent"] = smap[it["sentiment"]]
                    if it.get("reason"):
                        n["reason"] = str(it["reason"])[:300]
            a.update(method="claude", summary=str(res.get("summary", ""))[:1500],
                     themes=[{"title": str(t.get("title", ""))[:80], "detail": str(t.get("detail", ""))[:300]}
                             for t in res.get("themes", [])[:5] if isinstance(t, dict)],
                     watch=[str(x)[:200] for x in res.get("watch", [])[:4]])
        except Exception as e:
            print("Claude วิเคราะห์ไม่สำเร็จ ใช้การนับคำแทน:", e)
    a["counts"] = {"pos": sum(n["sent"] > 0 for n in items), "neu": sum(n["sent"] == 0 for n in items),
                   "neg": sum(n["sent"] < 0 for n in items)}
    a["topics"] = [{"name": k, "count": v} for k, v in Counter(t for n in items for t in n["topics"]).most_common(6)]
    by = {s: sum(n["sent"] for n in items if s in n["symbols"]) for s in symbols if any(s in n["symbols"] for n in items)}
    a["by_symbol"] = by
    return a
