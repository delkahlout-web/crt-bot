# -*- coding: utf-8 -*-
"""
MSNR Key Levels — تنبيهات الاقتراب من المستويات (نظام ثالث منفصل عن CRT وSH، لكنه يعمل داخل نفس حلقة بوت SH).
  • تاريخ الساعة: بذرة من MT5 (msnr_seed.json.gz، بجودة الذهب الفوري) + تمديد من Yahoo 1h بعد تصحيح الفرق (آجل − فوري) الحي.
  • كل دقيقة: يحسب المستويات (W/D/4H/1H + Story) بمحرك msnr_engine ويقارنها بالسعر الحالي.
  • عند اقتراب السعر من مستوى (alertPts) يرسل رسالة، ولا يكرّرها حتى يبتعد السعر (rearmPts) أو تمضي مدة التهدئة.
"""
import datetime as dt
import gzip
import json
import os
import time
from zoneinfo import ZoneInfo

import msnr_engine as M
import msnr_pro as MP
import msnr_msgs as MG

HERE = os.path.dirname(os.path.abspath(__file__))
SEED_PATH = os.path.join(HERE, "msnr_seed.json.gz")
STATE_PATH = os.path.join(HERE, "msnr_state.json")
CFG_PATH = os.path.join(HERE, "msnr_config.json")
BANNER = "🟧 <b>MSNR Key Levels</b>"
LINE = "━━━━━━━━━━━━━━"
SAME_LEVEL = 1.2                       # مستويان بينهما أقل من هذا (دولار) = نفس المستوى (إزاحة الأسعار الطفيفة)

DEF = dict(alertPts=50.0, rearmPts=100.0, cooldownMin=30, maxAlertsPerDay=15, snapshotHours=24, enabled=True,
           engine={}, pro={}, tradeAlerts=True, stageAlerts=False)


def log(msg):
    print(f"[{dt.datetime.now():%Y-%m-%d %H:%M:%S}] MSNR {msg}", flush=True)


def load_cfg():
    c = dict(DEF)
    if os.path.exists(CFG_PATH):
        c.update(json.load(open(CFG_PATH, encoding="utf-8")))
    return c


def load_state():
    if os.path.exists(STATE_PATH):
        try:
            return json.load(open(STATE_PATH, encoding="utf-8"))
        except Exception:
            pass
    return {"h1": [], "m30": [], "m15": [], "alerts": {}, "snap": 0, "day": "", "dayN": 0}


def save_state(st):
    st["h1"] = st["h1"][-3000:]; st["m30"] = st.get("m30", [])[-3000:]; st["m15"] = st.get("m15", [])[-3000:]
    json.dump(st, open(STATE_PATH, "w", encoding="utf-8"), ensure_ascii=False)


def _rows(rows):
    return [dict(time=int(r[0]), open=r[1], high=r[2], low=r[3], close=r[4]) for r in rows]


def load_seed():
    """يعيد dict(h1=[...], m30=[...], m15=[...]) — الملف قد يكون قائمة ساعات فقط (قديم) أو dict."""
    if not os.path.exists(SEED_PATH):
        return {"h1": [], "m30": [], "m15": []}
    raw = json.loads(gzip.open(SEED_PATH, "rt", encoding="utf-8").read())
    if isinstance(raw, list):
        return {"h1": _rows(raw), "m30": [], "m15": []}
    return {k: _rows(raw.get(k, [])) for k in ("h1", "m30", "m15")}


def build_store(seed_rows, st_rows):
    d = {b["time"]: b for b in seed_rows}
    for r in st_rows:
        d.setdefault(int(r[0]), dict(time=int(r[0]), open=r[1], high=r[2], low=r[3], close=r[4]))
    return [d[k] for k in sorted(d)]


def extend_store(bars, st_rows, yahoo_bars, basis, now, sec):
    """يضيف شموع Yahoo المكتملة (مضى عليها 20 دقيقة على الأقل) الأحدث من آخر شمعة مخزّنة، بعد طرح الفرق (آجل − فوري)."""
    if basis is None or not bars:
        return 0
    last = bars[-1]["time"]; n = 0
    for b in yahoo_bars:
        if b["time"] > last and b["time"] + sec <= now - 1200:
            nb = dict(time=b["time"], open=b["open"] - basis, high=b["high"] - basis, low=b["low"] - basis, close=b["close"] - basis)
            bars.append(nb); st_rows.append([nb["time"], round(nb["open"], 2), round(nb["high"], 2), round(nb["low"], 2), round(nb["close"], 2)]); n += 1
    return n


def level_text(c, cur):
    d = c["price"] - cur
    side = "مستوى بيع (مقاومة)" if c["role"] == "resistance" else "مستوى شراء (دعم)"
    icon = "🔴" if c["role"] == "resistance" else "🟢"
    tf = "+".join(c["tags"])
    mk = c.get("marks", "")
    extra = (" ★ قوي" if "★" in mk else "") + ((f" · 💧 سيولة مخفية {c['hl']} نقطة" if c.get("hl") else " · 💧 سيولة") if "$" in mk else "") + (" · ✓ مؤكَّد بفريم أعلى" if "✓" in mk else "")
    return icon, side, f"{tf}{extra}".strip(), d


def snapshot_text(levels, cur, tz, P):
    if not levels:
        return f"{BANNER}\n📋 لا مستويات ضمن {P['maxDist']:g} نقطة من السعر الآن (المستويات المستخدَمة تُستبعد كما في المؤشر)."
    rows = []
    for c in levels:
        icon, side, desc, d = level_text(c, cur)
        rows.append(f"{icon} <b>{c['price']:.2f}</b> ({d:+.1f}$) — {side}\n    {desc}")
    from sh_messages import fmt_time
    return (f"{BANNER}\n📋 <b>المستويات الحالية</b> (للتحقق من شارتك)\n{LINE}\n" + "\n".join(rows) +
            f"\n{LINE}\nالسعر الآن: {cur:.2f}\n🕒 {fmt_time(time.time(), tz)}\n"
            "<i>الأسعار تقديرية بفرق نحو 1$ عن شارتك: اعتمد على القرب والنوع.</i>")


def alert_text(c, cur, tz, P):
    from sh_messages import fmt_time
    icon, side, desc, d = level_text(c, cur)
    pts = abs(d) / P["pipSize"]
    above = d > 0
    move = "يقترب من الأعلى" if above else "يقترب من الأسفل"
    return (f"{BANNER}\n⚠️ <b>السعر قرب من {side}</b>\n{icon} المستوى: <b>{c['price']:.2f}</b>\n{LINE}\n"
            f"📍 السعر الآن: <b>{cur:.2f}</b> ({move})\n📏 المسافة: {abs(d):.2f}$ ({pts:.0f} نقطة)\n"
            f"🏷️ النوع: {desc}\n{LINE}\n🕒 {fmt_time(time.time(), tz)}")


class Msnr:
    def __init__(self):
        self.cfg = load_cfg()
        self.seed = load_seed()
        self.st = load_state()
        for k in ("m30", "m15"):
            self.st.setdefault(k, [])
        self.h1 = build_store(self.seed["h1"], self.st["h1"])
        self.m30 = build_store(self.seed["m30"], self.st["m30"])
        self.m15 = build_store(self.seed["m15"], self.st["m15"])
        self.pro = MP.Pro(P=self.cfg.get("pro"), S=self.st.get("pro"))
        self.warmed = False
        self.pro.warmed_ok = False
        log(f"جاهز: 1H={len(self.h1)} 30M={len(self.m30)} 15M={len(self.m15)} (بذرة + ممتدة) | Trader Pro | إعداد: alertPts={self.cfg['alertPts']:g} rearmPts={self.cfg['rearmPts']:g}")

    def advance(self, chart5, now):
        """يعالج شموع الشارت 5د المغلقة الجديدة بآلة Trader Pro ويعيد أحداثها."""
        pro = self.pro; S = pro.S
        cold = not S["last"]
        bars = [b for b in chart5 if b["time"] > S["last"] and b["time"] + 300 <= now]
        if not self.warmed or bars:
            pro.set_candles(self.h1, self.m30, self.m15, chart5)
            if not self.warmed:
                if S["last"]:
                    pro.warm(S["last"])
                self.warmed = True; pro.warmed_ok = True
        out = []
        for b in bars:
            pro.live = (not cold) or b["time"] >= now - 1800     # التشغيل البارد: تُبنى الحالة صامتة ثم تُرسل أحداث آخر 30 دقيقة فقط
            pro.events = []
            pro.step(b)
            out += pro.events
        pro.events = []
        if S["muted"] and S["st"] in (2, 3):             # صفقة وُلدت أثناء إعادة البناء الصامتة ولم تُرسَل: تُهمل كي لا تحجب الصفقات الجديدة
            S["st"] = 0
        return out

    def levels(self, chart5, cur, now, force=False):
        return self.pro.shown(cur)

    def tick(self, tg, chart5, cur, now, yahoo_h1, basis, tz):
        """يُستدعى كل دقيقة. يعيد عدد الرسائل المرسلة. لا يرفع استثناءً لخارج (يُسجَّل فقط)."""
        if not self.cfg.get("enabled", True) or not self.h1:
            return 0
        sent = 0
        yd = yahoo_h1 if isinstance(yahoo_h1, dict) else {"h1": yahoo_h1}
        n = extend_store(self.h1, self.st["h1"], yd.get("h1", []), basis, now, 3600)
        n += extend_store(self.m30, self.st["m30"], yd.get("m30", []), basis, now, 1800)
        n += extend_store(self.m15, self.st["m15"], yd.get("m15", []), basis, now, 900)
        P = self.pro.P
        # آلة Trader Pro: شموع الشارت المغلقة الجديدة ← أحداث (صفقات/مراحل) ← صندوق صادر يُعاد إرساله عند فشل تلجرام
        mkt = bool(chart5) and now - (chart5[-1]["time"] + 300) <= 1200          # السوق مفتوح: آخر شمعة 5د حديثة
        ob = self.st.setdefault("outbox", [])
        for e in self.advance(chart5, now):
            if e["kind"] in ("plan", "fill", "cancel", "result") and self.cfg.get("tradeAlerts", True):
                ob.append(dict(t=e["time"], text=MG.trade_text(e, tz, P)))
            elif e["kind"] in self.cfg.get("stageKinds", ["rej", "ret", "early"]) and self.cfg.get("stageAlerts", False):
                ob.append(dict(t=e["time"], text=MG.stage_text(e, tz)))
        # تنبيه مبكر فوري: بعد REJ، حين يعود السعر الحي ويلمس المستوى (إعادة اختبار) نُرسل فوراً دون انتظار إغلاق شمعة التأكيد
        if mkt and self.cfg.get("stageAlerts", False) and "early" in self.cfg.get("stageKinds", ["rej", "ret", "early"]) and self.pro.warmed_ok:
            tol = P["retTol"] * P["pipSize"]
            for t in self.pro.S["tk"]:
                if t["s"] == 2 and not t.get("e") and t["n"] <= P["retMax"]:
                    p = t["p"]; sup = t["sd"] == 1
                    if (sup and p - 2 * tol <= cur <= p + tol) or ((not sup) and p - tol <= cur <= p + 2 * tol):
                        t["e"] = 1
                        ob.append(dict(t=now, text=MG.stage_text(dict(kind="early", p=p, sd=t["sd"], tag=t["tg"], cur=cur, cf=MP.TFN[MP.cf_of(t["k"])]), tz)))
        keep = []
        for m in ob:
            if now - m["t"] > 3 * 3600:
                continue
            if not keep and tg.send(m["text"]):
                sent += 1; log("رسالة صفقة أُرسلت")
            else:
                keep.append(m)
        self.st["outbox"] = keep[-20:]
        self.st["pro"] = self.pro.S
        if not mkt:                                                              # السوق مغلق: لا لقطة ولا تنبيهات اقتراب بسعر قديم
            save_state(self.st)
            return sent
        lv = self.levels(chart5, cur, now)
        day = dt.datetime.fromtimestamp(now, dt.timezone.utc).strftime("%Y-%m-%d")
        if self.st.get("day") != day:
            self.st["day"] = day; self.st["dayN"] = 0
        # لقطة المستويات (أول مرة، ثم كل snapshotHours)
        hrs = self.cfg["snapshotHours"]                                  # 0 = مرة واحدة فقط (أول تشغيل)
        if not self.st.get("snap") or (hrs > 0 and now - self.st["snap"] >= hrs * 3600):
            if tg.send(snapshot_text(lv, cur, tz, P), silent=bool(self.st.get("snap"))):
                self.st["snap"] = now; sent += 1
        # تنبيهات الاقتراب
        near = self.cfg["alertPts"] * P["pipSize"]; rearm = self.cfg["rearmPts"] * P["pipSize"]
        al = self.st["alerts"]
        for k in [k for k, v in al.items() if now - v["t"] > 3 * 86400]:        # تنظيف قديم
            del al[k]
        for c in lv:
            if (c["role"] == "support") != (c["price"] < cur):          # مستوى تجاوزه السعر (مستخدَم) لا يُنبَّه عليه
                continue
            rec = next((v for v in al.values() if v["role"] == c["role"] and abs(v["p"] - c["price"]) <= SAME_LEVEL), None)
            dist = abs(c["price"] - cur)
            if rec is not None and dist > rearm:
                rec["armed"] = True                                               # ابتعد كفاية: يُسلَّح من جديد
            if dist > near:
                continue
            if rec is not None and not rec.get("armed") and now - rec["t"] < 6 * 3600:
                continue
            if rec is not None and now - rec["t"] < self.cfg["cooldownMin"] * 60:
                continue
            if self.st["dayN"] >= self.cfg["maxAlertsPerDay"]:
                continue
            if tg.send(alert_text(c, cur, tz, P)):
                key = f"{c['role']}|{c['price']:.1f}"
                for k2 in [k2 for k2, v in al.items() if v["role"] == c["role"] and abs(v["p"] - c["price"]) <= SAME_LEVEL]:
                    del al[k2]
                al[key] = dict(p=c["price"], role=c["role"], t=now, armed=False)
                self.st["dayN"] += 1; sent += 1
                log(f"تنبيه: {c['role']} {c['price']:.2f} | السعر {cur:.2f}")
        save_state(self.st)
        return sent
