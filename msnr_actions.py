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

HERE = os.path.dirname(os.path.abspath(__file__))
SEED_PATH = os.path.join(HERE, "msnr_seed.json.gz")
STATE_PATH = os.path.join(HERE, "msnr_state.json")
CFG_PATH = os.path.join(HERE, "msnr_config.json")
BANNER = "🟧 <b>MSNR Key Levels</b>"
LINE = "━━━━━━━━━━━━━━"

DEF = dict(alertPts=50.0, rearmPts=100.0, cooldownMin=30, maxAlertsPerDay=15, snapshotHours=24, enabled=True,
           engine={})


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
    return {"h1": [], "alerts": {}, "snap": 0, "day": "", "dayN": 0}


def save_state(st):
    st["h1"] = st["h1"][-3000:]
    json.dump(st, open(STATE_PATH, "w", encoding="utf-8"), ensure_ascii=False)


def load_seed():
    if not os.path.exists(SEED_PATH):
        return []
    rows = json.loads(gzip.open(SEED_PATH, "rt", encoding="utf-8").read())
    return [dict(time=int(r[0]), open=r[1], high=r[2], low=r[3], close=r[4]) for r in rows]


def build_h1(seed, st):
    d = {b["time"]: b for b in seed}
    for r in st["h1"]:
        d.setdefault(int(r[0]), dict(time=int(r[0]), open=r[1], high=r[2], low=r[3], close=r[4]))
    return [d[k] for k in sorted(d)]


def extend_h1(h1, st, yahoo_h1, basis, now):
    """يضيف ساعات Yahoo المكتملة (مضى عليها 20 دقيقة على الأقل) الأحدث من آخر ساعة مخزّنة، بعد طرح الفرق (آجل − فوري)."""
    if basis is None or not h1:
        return 0
    last = h1[-1]["time"]; n = 0
    for b in yahoo_h1:
        if b["time"] > last and b["time"] + 3600 <= now - 1200:
            nb = dict(time=b["time"], open=b["open"] - basis, high=b["high"] - basis, low=b["low"] - basis, close=b["close"] - basis)
            h1.append(nb); st["h1"].append([nb["time"], round(nb["open"], 2), round(nb["high"], 2), round(nb["low"], 2), round(nb["close"], 2)]); n += 1
    return n


def level_text(c, cur):
    d = c["price"] - cur
    side = "مستوى بيع (مقاومة)" if c["role"] == "resistance" else "مستوى شراء (دعم)"
    icon = "🔴" if c["role"] == "resistance" else "🟢"
    stars = ("★" * c["stars"]) if c["stars"] else ""
    tf = "+".join(c["tags"])
    kind = c["kind"]
    tests = f" (اختُبر {c['tests']}x)" if c["tests"] else ""
    hl = f" · 💧 سيولة مخفية {c['hl']} نقطة" if c.get("hl") else ""
    return icon, side, f"{tf} · {kind} {stars}{tests}{hl}".strip(), d


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
        self.cache = ([], 0)                      # (مستويات، وقت الحساب)
        self.h1 = build_h1(self.seed, self.st)
        log(f"جاهز: {len(self.h1)} ساعة (بذرة {len(self.seed)} + ممتدة {len(self.st['h1'])}) | إعداد: alertPts={self.cfg['alertPts']:g} rearmPts={self.cfg['rearmPts']:g}")

    def levels(self, chart5, cur, now, force=False):
        if not force and now - self.cache[1] < 120:
            return self.cache[0]
        P = {**M.DEFAULTS, **self.cfg.get("engine", {})}
        lv = M.collect(self.h1, chart5, cur, now, P)
        self.cache = (lv, now)
        return lv

    def tick(self, tg, chart5, cur, now, yahoo_h1, basis, tz):
        """يُستدعى كل دقيقة. يعيد عدد الرسائل المرسلة. لا يرفع استثناءً لخارج (يُسجَّل فقط)."""
        if not self.cfg.get("enabled", True) or not self.h1:
            return 0
        sent = 0
        n = extend_h1(self.h1, self.st, yahoo_h1, basis, now)
        P = {**M.DEFAULTS, **self.cfg.get("engine", {})}
        lv = self.levels(chart5, cur, now, force=bool(n))
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
            rec = next((v for v in al.values() if v["role"] == c["role"] and abs(v["p"] - c["price"]) <= 3.0), None)
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
                for k2 in [k2 for k2, v in al.items() if v["role"] == c["role"] and abs(v["p"] - c["price"]) <= 3.0]:
                    del al[k2]
                al[key] = dict(p=c["price"], role=c["role"], t=now, armed=False)
                self.st["dayN"] += 1; sent += 1
                log(f"تنبيه: {c['role']} {c['price']:.2f} | السعر {cur:.2f}")
        save_state(self.st)
        return sent
