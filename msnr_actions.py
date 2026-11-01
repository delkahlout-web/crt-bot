# -*- coding: utf-8 -*-
"""
MSNR — نظام موحَّد داخل حلقة بوت SH (منفصل عن CRT):
  • مستويات MSNR Key Levels v4 (msnr_v4): قرب ← رفض مؤكَّد (نوع T1–T4 + منطقة الدخول) ← إعادة اختبار (لحظية عند لمس السعر الحي).
  • صفقات «Session plan» (msnr_plan): عند فتح شمعة 4H، دخول عند إغلاق رفض على مستوى 30M (3 نجوم)، وقف 60 وهدف 120 نقطة.
  • رسالة واحدة لكل مرحلة لكل مستوى (ولو تقاطع أكثر من فريم)، وكل شيء يُعالَج لحظة إغلاق شمعة 5 دقائق (بعد ثوانٍ لا بعد دورة كاملة).
تاريخ الشموع: بذرة MT5 (msnr_seed.json.gz) + تمديد Yahoo، والشموع الأحدث تُبنى من سعر الذهب الفوري مباشرة (بلا تأخير Yahoo).
"""
import datetime as dt
import gzip
import json
import os
import time

import msnr_msgs3 as MG3
import msnr_plan as PL
import msnr_v4 as V4M

HERE = os.path.dirname(os.path.abspath(__file__))
SEED_PATH = os.path.join(HERE, "msnr_seed.json.gz")
STATE_PATH = os.path.join(HERE, "msnr_state.json")
CFG_PATH = os.path.join(HERE, "msnr_config.json")
BANNER = "🟧 <b>MSNR Key Levels</b>"
LINE = "━━━━━━━━━━━━━━"
SAME_LEVEL = 1.2                       # مستويان بينهما أقل من هذا (دولار) = نفس المستوى

DEF = dict(alertPts=50.0, rearmPts=100.0, cooldownMin=30, maxAlertsPerDay=15, snapshotHours=0, enabled=True,
           v4={}, plan={}, levelAlerts=True, planAlerts=True)


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
    tmp = STATE_PATH + ".tmp"
    json.dump(st, open(tmp, "w", encoding="utf-8"), ensure_ascii=False)
    os.replace(tmp, STATE_PATH)


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
    why = c.get("why", "")
    parts = []
    if "A" in why:
        parts.append("A مفعَّل من مستوى سابق")
    if "B" in why:
        parts.append("B كسر آخر نقطة معاكسة")
    if "L" in why:
        parts.append(f"L سيولة مخفية {c['hl']} نقطة" if c.get("hl") else "L سيولة مخفية")
    desc = f"{'+'.join(c['tags'])} · {c.get('kind', '')} {'★' * len(why)}".strip() + (f" ({' · '.join(parts)})" if parts else "") + (" ⚡" if c.get("af") else "")
    return icon, side, desc, d


def snapshot_text(levels, cur, tz, P):
    if not levels:
        return f"{BANNER}\n📋 لا مستويات ضمن {P['maxDist']:g} نقطة من السعر الآن."
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
    move = "يقترب من الأعلى" if d > 0 else "يقترب من الأسفل"
    return (f"{BANNER}\n⚠️ <b>قرب من {side}</b>\n{icon} المستوى: <b>{c['price']:.2f}</b>\n{LINE}\n"
            f"📍 السعر الآن: <b>{cur:.2f}</b> ({move})\n📏 المسافة: {abs(d):.2f}$ ({pts:.0f} نقطة)\n"
            f"💪 القوة والنوع: {desc}\n{LINE}\n🕒 {fmt_time(time.time(), tz)}")


# تصميم الرسائل الموحَّد (msnr_msgs3) يحلّ محلّ الدوال أعلاه
snapshot_text = MG3.snapshot_text
alert_text = MG3.alert_text


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
        self.v4 = V4M.V4(P=self.cfg.get("v4"), S=self.st.get("v4"))
        self.plan = PL.Plan(P=self.cfg.get("plan"), S=self.st.get("plan"))
        self.warmed = False
        self.dirty = False
        self.P = self.v4.P
        log(f"جاهز: 1H={len(self.h1)} 30M={len(self.m30)} 15M={len(self.m15)} | مستويات v4 + خطة الجلسة | alertPts={self.cfg['alertPts']:g} rearmPts={self.cfg['rearmPts']:g}")

    # ───────────── إرسال ─────────────
    def _send(self, tg, text, at):
        if tg.send(text):
            return 1
        self.st.setdefault("outbox", []).append(dict(t=at, text=text))
        return 0

    def _persist(self):
        self.st["v4"] = self.v4.S; self.st["plan"] = self.plan.S
        self.st["v4eng"] = self.v4.dump(); self.st["planeng"] = self.plan.dump()

    # ───────────── معالجة الشموع ─────────────
    def _prepare(self, chart5):
        r4 = rp = False
        if not self.warmed:                                   # استعادة حالة المحرّكات المحفوظة (وإلا إعادة بنائها من الشموع)
            r4 = self.v4.restore(self.st.get("v4eng")) if self.v4.S["last"] else False
            rp = self.plan.restore(self.st.get("planeng")) if self.plan.S["last"] else False
        self.v4.set_candles(self.h1, self.m30, self.m15, chart5)
        self.plan.set_candles(self.v4.cl[3], self.v4.cl[4], self.v4.cl[2], chart5)
        if not self.warmed:
            if self.v4.S["last"] and not r4:
                self.v4.warm(self.v4.S["last"] + 300)
            if self.plan.S["last"] and not rp:
                self.plan.warm(self.plan.S["last"])
            self.warmed = True

    def _run_bars(self, chart5, now):
        """يعالج شموع 5د المغلقة الجديدة في محرك المستويات وخطة الجلسة ويعيد (أحداث المستويات، أحداث الصفقات)."""
        v4, plan = self.v4, self.plan
        b4 = [b for b in chart5 if b["time"] > v4.S["last"] and b["time"] + 300 <= now]
        bp = [b for b in chart5 if b["time"] > plan.S["last"] and b["time"] + 300 <= now]
        if not self.warmed or b4 or bp:
            self._prepare(chart5)
        cold4 = not v4.S["last"]; coldp = not plan.S["last"]
        ev4 = []; evp = []
        for b in b4:
            v4.live = (not cold4) or b["time"] >= now - 1800
            v4.events = []; v4.step(b); ev4 += v4.events
        v4.events = []
        for b in bp:
            plan.live = (not coldp) or b["time"] >= now - 900
            plan.events = []; plan.step(b); evp += plan.events
        plan.events = []
        return ev4, evp

    def fast_bar(self, tg, bars, now, tz):
        """عند إغلاق شمعة 5د مباشرة (بعد ثوانٍ): يعالج الشمعة الجديدة ويرسل الرفض/إعادة الاختبار/الصفقة فوراً."""
        if not self.cfg.get("enabled", True) or not self.warmed:
            return 0
        c5 = self.v4.chart5
        last = max(c5[-1]["time"] if c5 else 0, self.v4.S["last"], self.plan.S["last"])
        new = [b for b in bars if b["time"] > last and b["time"] + 300 <= now]
        if not new:
            return 0
        chart5 = list(c5) + new
        ev4, evp = self._run_bars(chart5, now)
        sent = self._emit(tg, ev4, evp, tz, now)
        self._persist(); save_state(self.st)
        if sent:
            self.dirty = True
        return sent

    def fast(self, tg, cur, now, tz):
        """السعر الحي (كل ~4 ثوانٍ): إعادة اختبار لحظية بعد رفض مؤكَّد + وقف/هدف الصفقة المفتوحة فوراً."""
        if not self.cfg.get("enabled", True) or not self.warmed:
            return 0
        c5 = self.v4.chart5
        if not (c5 and now - (c5[-1]["time"] + 300) <= 1200):
            return 0                                   # السوق مغلق
        ev4 = self.v4.fast(cur, now) if self.cfg.get("levelAlerts", True) else []
        evp = self.plan.fast(cur, now) if self.cfg.get("planAlerts", True) else []
        if not ev4 and not evp:
            return 0
        sent = self._emit(tg, ev4, evp, tz, now)
        self._persist(); save_state(self.st)
        if sent:
            self.dirty = True
        return sent

    def _emit(self, tg, ev4, evp, tz, now):
        sent = 0
        if self.cfg.get("levelAlerts", True):
            for e in ev4:
                sent += self._send(tg, MG3.v4_text(e, tz, self.v4.P), e["at"])
                log(f"{e['kind']} {e['tag']} @ {e['p']:.2f} | السعر {e['cur']:.2f}")
        if self.cfg.get("planAlerts", True):
            for e in evp:
                sent += self._send(tg, MG3.plan_text(e, tz, self.plan.P), e["at"])
                log(f"خطة الجلسة: {e['kind']} {e.get('res', '')} {'شراء' if e['dir'] == 1 else 'بيع'} @ {e['entry']:.2f}")
        return sent

    def levels(self, chart5, cur, now, force=False):
        return self.v4.shown(cur, now)

    # ───────────── الدورة الكاملة (~كل 20 ثانية) ─────────────
    def tick(self, tg, chart5, cur, now, yahoo_h1, basis, tz):
        """يعيد عدد الرسائل المرسلة. لا يرفع استثناءً لخارج الحلقة إلا لتعالجه (إصلاح ذاتي في sh_actions)."""
        if not self.cfg.get("enabled", True) or not self.h1:
            return 0
        sent = 0
        yd = yahoo_h1 if isinstance(yahoo_h1, dict) else {"h1": yahoo_h1}
        extend_store(self.h1, self.st["h1"], yd.get("h1", []), basis, now, 3600)
        extend_store(self.m30, self.st["m30"], yd.get("m30", []), basis, now, 1800)
        extend_store(self.m15, self.st["m15"], yd.get("m15", []), basis, now, 900)
        P = self.v4.P
        mkt = bool(chart5) and now - (chart5[-1]["time"] + 300) <= 1200          # السوق مفتوح: آخر شمعة 5د حديثة
        ev4, evp = self._run_bars(chart5, now)
        if mkt and chart5:
            lag = max(chart5[-1]["time"] - self.v4.S["last"], chart5[-1]["time"] - self.plan.S["last"])
            if lag > 900:                                                         # المحرّكات متخلفة عن الشموع أكثر من 15 دقيقة: إصلاح ذاتي بإعادة التهيئة
                raise RuntimeError(f"تخلّف معالجة الشموع {lag // 60} دقيقة")
        if not mkt:
            ev4 = []; evp = []                                                    # لا رسائل بسعر قديم والسوق مغلق
        sent += self._emit(tg, ev4, evp, tz, now)
        # إعادة إرسال ما فشل (صندوق صادر) خلال 3 ساعات
        keep = []
        for m in self.st.setdefault("outbox", []):
            if now - m["t"] > 3 * 3600:
                continue
            if not keep and tg.send(m["text"]):
                sent += 1
            else:
                keep.append(m)
        self.st["outbox"] = keep[-20:]
        self._persist()
        if not mkt:
            save_state(self.st)
            return sent
        lv = self.levels(chart5, cur, now)
        day = dt.datetime.fromtimestamp(now, dt.timezone.utc).strftime("%Y-%m-%d")
        if self.st.get("day") != day:
            self.st["day"] = day; self.st["dayN"] = 0
        hrs = self.cfg["snapshotHours"]                                           # 0 = مرة واحدة فقط (أول تشغيل)
        if self.cfg.get("levelAlerts", True) and (not self.st.get("snap") or (hrs > 0 and now - self.st["snap"] >= hrs * 3600)):
            if tg.send(snapshot_text(lv, cur, tz, P), silent=bool(self.st.get("snap"))):
                self.st["snap"] = now; sent += 1
        # تنبيهات القرب: مرة لكل مستوى حتى يبتعد السعر (rearmPts) أو تمضي مدة التهدئة
        near = self.cfg["alertPts"] * P["pipSize"]; rearm = self.cfg["rearmPts"] * P["pipSize"]
        al = self.st["alerts"]
        for k in [k for k, v in al.items() if now - v["t"] > 3 * 86400]:
            del al[k]
        for c in lv if self.cfg.get("levelAlerts", True) else []:
            if (c["role"] == "support") != (c["price"] < cur):                    # مستوى تجاوزه السعر لا يُنبَّه عليه
                continue
            rec = next((v for v in al.values() if v["role"] == c["role"] and abs(v["p"] - c["price"]) <= SAME_LEVEL), None)
            dist = abs(c["price"] - cur)
            if rec is not None and dist > rearm:
                rec["armed"] = True
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
                log(f"قرب: {c['role']} {c['price']:.2f} | السعر {cur:.2f}")
        save_state(self.st)
        return sent
