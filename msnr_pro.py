# -*- coding: utf-8 -*-
"""
MSNR Trader Pro — ترجمة حرفية لمؤشر TradingView «MSNR Trader Pro / Levels Pro» (نسخة المستويات + اللمس REJ/RET/BO + آلة الصفقات).
المحرّكات: D / 4H / 2H / 1H / 30M (مستويات كاملة) و15M (تأكيد فقط). كل شمعة فريم تُغذّى عند إغلاقها، ثم تُعالَج شمعة الشارت (5 دقائق)
المغلقة بنفس ترتيب البايين: تغذية المحرّكات ← Story ← ذاكرة المرشّحين (عند إغلاق 1H) ← تتبّع اللمس ← آلة الصفقة.
الأسعار بالدولار؛ pipSize=0.1 يعني أن «النقطة» = 0.1$.
"""
import datetime as dt
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")

DEF = dict(
    dOn=True, h4On=True, h2On=True, h1On=True, m30On=True,
    classicMode=0, kClassic=True, kGap=True, kFlip=True, kQM=True, brkN=2, momK=0.0,
    liqTol=30.0, actTol=5.0, confTol=20.0, qMin=1,
    lb=[40, 60, 60, 80, 100, 100],
    perTf=1, maxDist=500.0, mergeGap=20.0, confOnly=False, pipSize=0.1,
    retMax=2, retTol=5.0, trkLife=40, markMinIdx=3,
    tradeOn=True, tQMin=3, mainMinIdx=3, armDist=150.0, ctOnly=True, useCt=True, boWait=10,
    entryModel="refined", refineMax=50.0, orderWin=120, slBuf=3.0, minSL=10.0, maxSL=50.0, minRR=5.0,
    tpMinIdx=3, tpBuf=3.0, maxPerDay=6, corrRule=True, corrWin=30,
)
SECS = [86400, 14400, 7200, 3600, 1800, 900]
TFN = ["D", "4H", "2H", "1H", "30M", "15M"]
KIND_CODE = {1: "CL", 2: "OC", 3: "SBR/RBS", 4: "QM"}


def kind_txt(kd, side):
    return "CL" if kd == 1 else "OC" if kd == 2 else ("SBR" if side == -1 else "RBS") if kd == 3 else "QM"


def cf_of(k):
    return 3 if k <= 2 else 4 if k == 3 else 5


def rf_of(k):
    return 4 if k <= 3 else 5


def bucket(t, tf):
    """(بداية، نهاية) الشمعة الكبيرة التي تحوي ساعة تبدأ عند t؛ اليوم يبدأ 17:00 نيويورك."""
    loc = dt.datetime.fromtimestamp(t, dt.timezone.utc).astimezone(NY).replace(tzinfo=None) + dt.timedelta(hours=7)
    if tf == "D":
        fl, sec = loc.replace(hour=0, minute=0, second=0, microsecond=0), 86400
    elif tf == "4H":
        fl, sec = loc.replace(hour=loc.hour // 4 * 4, minute=0, second=0, microsecond=0), 14400
    else:
        fl, sec = loc.replace(hour=loc.hour // 2 * 2, minute=0, second=0, microsecond=0), 7200
    s = t - int((loc - fl).total_seconds())
    return s, s + sec


def agg(h1, tf):
    out = []; cur = None; ck = None
    for b in h1:
        s, e = bucket(b["time"], tf)
        if s != ck:
            if cur: out.append(cur)
            cur = dict(time=s, end=e, open=b["open"], high=b["high"], low=b["low"], close=b["close"]); ck = s
        else:
            cur["high"] = max(cur["high"], b["high"]); cur["low"] = min(cur["low"], b["low"]); cur["close"] = b["close"]
    if cur: out.append(cur)
    return out


def derive(chart5, size, after_t):
    """شموع بحجم size ثانية مبنية من شموع الشارت 5 دقائق، للحاويات المكتملة التي تبدأ بعد after_t."""
    out = []; cur = None; ck = None
    last_end = chart5[-1]["time"] + 300 if chart5 else 0
    for b in chart5:
        s = b["time"] // size * size
        if s <= after_t:
            continue
        if s != ck:
            if cur: out.append(cur)
            cur = dict(time=s, end=s + size, open=b["open"], high=b["high"], low=b["low"], close=b["close"], first=b["time"]); ck = s
        else:
            cur["high"] = max(cur["high"], b["high"]); cur["low"] = min(cur["low"], b["low"]); cur["close"] = b["close"]
    if cur: out.append(cur)
    return [c for c in out if c["end"] <= last_end and c["first"] <= c["time"] + 300]


class Lvl:
    __slots__ = ("p", "side", "kind", "flips", "touched", "beyond", "born", "active", "bo", "opp", "liq", "liqPx", "dead", "tborn")

    def __init__(s, p, side, kind, born, active, opp, liq, liqPx, tborn):
        s.p = p; s.side = side; s.kind = kind; s.flips = 0; s.touched = False; s.beyond = 0; s.born = born; s.active = active
        s.bo = False; s.opp = opp; s.liq = liq; s.liqPx = liqPx; s.dead = False; s.tborn = tborn


class Eng:
    def __init__(s, secs):
        s.secs = secs; s.lv = []
        s.o1 = s.h1 = s.l1 = s.c1 = s.c2 = s.swH = s.swL = s.atr = None
        s.n = 0; s.lastT = 0


def feed(e, o, h, l, c, t, P):
    pip = P["pipSize"]; cm = P["classicMode"]; bn = P["brkN"]; mk = P["momK"]; liqT = P["liqTol"] * pip; actT = P["actTol"] * pip
    pc = o if e.c1 is None else e.c1
    trg = max(h - l, abs(h - pc), abs(l - pc))
    e.atr = trg if e.atr is None else (e.atr * 13 + trg) / 14
    i = e.n
    for L in e.lv:
        if not L.dead and i > L.born:
            sup = L.side == 1
            pierced = (l <= L.p) if sup else (h >= L.p)
            bey = (c < L.p) if sup else (c > L.p)
            if pierced:
                L.touched = True
            elif not L.touched:
                ext = l if sup else h
                gp = (ext - L.p) if sup else (L.p - ext)
                if 0 < gp <= liqT:
                    L.liq += 1
                    if L.liqPx is None or (sup and ext < L.liqPx) or (not sup and ext > L.liqPx):
                        L.liqPx = ext
            if L.active and not L.bo and L.opp is not None and not L.touched:
                if (sup and c > L.opp) or (not sup and c < L.opp):
                    L.bo = True
            L.beyond = L.beyond + 1 if bey else 0
            body_ok = mk <= 0 or abs(c - o) >= mk * (e.atr or 0) or L.beyond > bn
            if L.beyond >= bn and body_ok:
                L.flips += 1
                if L.flips >= 3:
                    L.dead = True
                else:
                    L.side = -L.side; L.kind = 3 if L.flips == 1 else 4; L.touched = False; L.beyond = 0
                    L.born = i; L.tborn = t; L.liq = 0; L.liqPx = None; L.active = True; L.opp = None
                    sw = e.swH if L.side == 1 else e.swL
                    L.bo = sw is not None and ((L.side == -1 and c < sw) or (L.side == 1 and c > sw))
    if e.c2 is not None and e.c1 is not None:
        if e.c1 > e.c2 and e.c1 > c:
            e.swH = e.c1
        if e.c1 < e.c2 and e.c1 < c:
            e.swL = e.c1
    if e.c1 is not None and e.c2 is not None:
        bull1 = e.c1 > e.o1; bear1 = e.c1 < e.o1; bull2 = c > o; bear2 = c < o
        Pp = e.c1; sd = 0; kd = 0
        isA = (e.c1 > e.c2 and e.c1 > c) if cm == 0 else (bull1 and bear2)
        isV = (e.c1 < e.c2 and e.c1 < c) if cm == 0 else (bear1 and bull2)
        if isA:
            sd, kd = -1, 1
        elif isV:
            sd, kd = 1, 1
        elif bull1 and bull2:
            sd, kd = 1, 2
        elif bear1 and bear2:
            sd, kd = -1, 2
        if sd != 0:
            dupe = any((not X.dead) and X.side == sd and abs(X.p - Pp) < 0.05 for X in e.lv)
            if not dupe:
                sup2 = sd == 1
                wick1 = e.l1 if sup2 else e.h1
                swept = (l <= wick1) if sup2 else (h >= wick1)
                lq = 0; lpx = None
                wd = abs(wick1 - Pp)
                if not swept and wd > 0.05 and wd <= liqT:
                    lq = 1; lpx = wick1
                hi2 = max(e.h1, h); lo2 = min(e.l1, l)
                act = False
                for K in e.lv:
                    if K.born < i - 1 and not K.dead:
                        if sd == -1 and K.p >= Pp - actT and K.p <= hi2 + actT:
                            act = True
                        if sd == 1 and K.p <= Pp + actT and K.p >= lo2 - actT:
                            act = True
                opp = e.swH if sd == 1 else e.swL
                e.lv.append(Lvl(Pp, sd, kd, i, act, opp, lq, lpx, t))
    e.lv = [X for X in e.lv if not (X.dead or i - X.born > 150)]
    e.c2 = e.c1; e.o1 = o; e.h1 = h; e.l1 = l; e.c1 = c; e.lastT = t; e.n += 1


def feed_lite(e, o, h, l, c, t):
    if e.c2 is not None and e.c1 is not None:
        if e.c1 > e.c2 and e.c1 > c:
            e.swH = e.c1
        if e.c1 < e.c2 and e.c1 < c:
            e.swL = e.c1
    e.c2 = e.c1; e.o1 = o; e.h1 = h; e.l1 = l; e.c1 = c; e.lastT = t; e.n += 1


def fresh_state():
    return dict(
        last=0, bi=0, pc=None, day="", dayCnt=0, tid=0, muted=False,
        tk=[], st=0, pDir=0, pK=None, pTag="", pMain=0, pCf=3, pRf=4, pCt=False, pPh=0, pCnt=0, pBey=0, pExt=None, pSw=None, pRejT=0,
        pEntry=None, pSL=None, pTP=None, pRisk=None, pTpTag="", orderBar=0, entryBar=0, usedL=None, usedBar=0,
        nStart=0, nTO=0, nBrk=0, nNoTgt=0, nBig=0, nWin=0, nLoss=0, nBE=0,
        cands=[], slLvl=None, slSide=0, slStat=0, slCause=None, slDec=None, slBey=0, slTag="", lastTr=0, corrFlag=False, corrBias=0, lastDT=0,
    )


class Pro:
    def __init__(self, P=None, S=None):
        self.P = {**DEF, **(P or {})}
        self.S = S if S else fresh_state()
        for k, v in fresh_state().items():
            self.S.setdefault(k, v)
        self.tfOn = [self.P["dOn"], self.P["h4On"], self.P["h2On"], self.P["h1On"], self.P["m30On"], True]
        self.E = [Eng(s) for s in SECS]
        self.cl = [[] for _ in range(6)]                  # شموع كل فريم (مرتبة بالفتح)
        self.fed = [0] * 6                                # وقت فتح آخر شمعة مُغذّاة
        self.ptr = [0] * 6
        self.c4h = []; self.hA = self.hB = self.lA = self.lB = None; self.trn = 0
        self.events = []
        self.live = True

    # ───────────── البيانات ─────────────
    def set_candles(self, h1, m30, m15, chart5):
        """h1/m30/m15: مخازن (بذرة + ممتدة)؛ الشموع الأحدث تُشتق من شموع الشارت 5 دقائق (لحظية) بدل انتظار Yahoo."""
        def ext(base, size):
            last = base[-1]["time"] if base else 0
            return [dict(b, end=b["time"] + size) for b in base] + derive(chart5, size, last + size - 1 if base else 0)
        a1 = ext(h1, 3600)
        self.cl = [agg(a1, "D"), agg(a1, "4H"), agg(a1, "2H"), a1, ext(m30, 1800), ext(m15, 900)]
        for k in range(6):
            lst = self.cl[k]; i = 0
            while i < len(lst) and lst[i]["time"] <= self.fed[k]:
                i += 1
            self.ptr[k] = i

    def feed_until(self, T):
        """يغذّي كل شموع الفريمات التي انتهت (نهايتها ≤ T) ولم تُغذَّ بعد؛ يعيد أعلام «شمعة جديدة» لكل فريم."""
        fl = [False] * 6
        for k in range(6):
            lst = self.cl[k]; e = self.E[k]
            while self.ptr[k] < len(lst):
                c = lst[self.ptr[k]]
                if c["end"] > T:
                    break
                self.ptr[k] += 1
                if k == 5:
                    feed_lite(e, c["open"], c["high"], c["low"], c["close"], c["time"])
                else:
                    feed(e, c["open"], c["high"], c["low"], c["close"], c["time"], self.P)
                self.fed[k] = c["time"]; fl[k] = True
                if k == 1:
                    self.trend_feed(c["close"])
        return fl

    def trend_feed(self, c):
        self.c4h.append(c); n = len(self.c4h)
        if n >= 5:
            j = n - 3; ctr = self.c4h[j]
            if ctr > max(self.c4h[j - 2:j]) and ctr > max(self.c4h[j + 1:j + 3]):
                self.hB, self.hA = self.hA, ctr
            if ctr < min(self.c4h[j - 2:j]) and ctr < min(self.c4h[j + 1:j + 3]):
                self.lB, self.lA = self.lA, ctr
        if self.hB is not None and self.lB is not None:
            if self.hA > self.hB and self.lA > self.lB:
                self.trn = 1
            elif self.hA < self.hB and self.lA < self.lB:
                self.trn = -1

    # ───────────── المرشّحون ─────────────
    def kind_on(self, kd):
        P = self.P
        return P["kClassic"] if kd == 1 else P["kGap"] if kd == 2 else P["kFlip"] if kd == 3 else P["kQM"]

    def conf_by(self, k, p, side):
        pip = self.P["pipSize"]
        for q in range(k):
            if self.tfOn[q]:
                e = self.E[q]
                for L in e.lv:
                    if (not L.dead) and (not L.touched) and L.side == side and e.n - L.born <= self.P["lb"][q] and abs(L.p - p) <= self.P["confTol"] * pip:
                        return True
        return False

    def scan(self, px, rng_pts, max_idx, full):
        P = self.P; pip = P["pipSize"]; cl = []
        for k in range(max_idx + 1):
            if not self.tfOn[k]:
                continue
            e = self.E[k]
            for L in e.lv:
                if (not L.dead) and (not L.touched) and self.kind_on(L.kind) and e.n - L.born <= P["lb"][k] and abs(L.p - px) <= rng_pts * pip:
                    s1 = 1 if (L.active and L.bo) else 0
                    l1 = 1 if L.liq > 0 else 0
                    if k == 0:
                        c1 = 1
                    elif full or s1 + l1 < P["qMin"]:
                        c1 = 1 if self.conf_by(k, L.p, L.side) else 0
                    else:
                        c1 = 0
                    self.add_cand(cl, L.p, L.side, k, L.kind, s1, l1, c1, L.tborn, TFN[k] + " " + kind_txt(L.kind, L.side), L.liqPx if L.liq > 0 else None)
        return cl

    def add_cand(self, cl, p, side, k, kd, st1, lq1, cf1, tb, tg, lx1):
        hit = None
        for c in cl:
            if c["sd"] == side and abs(c["p"] - p) <= self.P["mergeGap"] * self.P["pipSize"]:
                hit = c; break
        if hit is not None:
            hit["tg"] += "+" + tg
            hit["st"] = max(hit["st"], st1); hit["lq"] = max(hit["lq"], lq1); hit["cf"] = max(hit["cf"], cf1)
            if hit["lx"] is None:
                hit["lx"] = lx1
            if k < hit["tf"]:
                hit["tf"] = k; hit["p"] = p; hit["kd"] = kd; hit["tb"] = tb
        else:
            cl.append(dict(p=p, sd=side, tf=k, kd=kd, st=st1, lq=lq1, cf=cf1, tb=tb, lx=lx1, tg=tg))

    @staticmethod
    def q_of(c):
        return c["st"] + c["lq"] + c["cf"]

    def short_tag(self, c):
        parts = c["tg"].split("+")
        return parts[0] + (f" ×{len(parts)}" if len(parts) > 1 else "")

    def shown(self, cur):
        """المستويات المعروضة على الشارت (أقرب مستوى لكل فريم فوق السعر وتحته) بصيغة قريبة من collect() القديم."""
        P = self.P; pip = P["pipSize"]
        cl = self.scan(cur, P["maxDist"], 4, True)
        sh = [False] * len(cl)
        for k in range(5):
            if not self.tfOn[k]:
                continue
            for side in (0, 1):
                for _ in range(P["perTf"]):
                    best = -1; bd = 0.0
                    for i, c in enumerate(cl):
                        if not sh[i] and c["tf"] == k and self.q_of(c) >= P["qMin"]:
                            d = c["p"] - cur
                            if (d > 0) if side == 0 else (d < 0):
                                ad = abs(d)
                                if best == -1 or ad < bd:
                                    best, bd = i, ad
                    if best >= 0:
                        sh[best] = True
        out = []
        for i, c in enumerate(cl):
            if not sh[i]:
                continue
            tags = c["tg"].split("+")
            if P["confOnly"] and len(tags) < 2:
                continue
            marks = ("★" if c["st"] else "") + ("$" if c["lq"] else "") + ("✓" if c["cf"] else "")
            hl = int(round(abs(c["lx"] - c["p"]) / pip)) if c["lx"] is not None else 0
            out.append(dict(price=c["p"], role="support" if c["sd"] == 1 else "resistance", tags=tags, kd=c["kd"], tf=c["tf"], marks=marks,
                            kind=kind_txt(c["kd"], c["sd"]), stars=c["st"] + c["lq"] + c["cf"], tests=0, hl=hl))
        out.sort(key=lambda c: abs(c["price"] - cur))
        return out

    # ───────────── Story (خط القصة) ─────────────
    def story_step(self):
        S = self.S; P = self.P; e4 = self.E[1]; eD = self.E[0]
        for L in eD.lv:
            if (not L.dead) and e4.l1 is not None and e4.l1 <= L.p <= e4.h1:
                S["lastDT"] = e4.lastT
        tr = self.trn
        if tr != S["lastTr"] and tr != 0:
            if S["lastTr"] != 0:
                S["corrFlag"] = (e4.lastT - S["lastDT"]) > P["corrWin"] * e4.secs
                S["corrBias"] = S["lastTr"] if S["corrFlag"] else 0
            S["lastTr"] = tr
        if S["slStat"] == 1:
            sd = S["slSide"]
            brk = S["slCause"] is not None and ((sd == 1 and e4.c1 > S["slCause"]) or (sd == -1 and e4.c1 < S["slCause"]))
            bey = (sd == 1 and e4.c1 < S["slLvl"]) or (sd == -1 and e4.c1 > S["slLvl"])
            S["slBey"] = S["slBey"] + 1 if bey else 0
            if brk:
                S["slStat"] = 2; S["slDec"] = e4.swL if sd == 1 else e4.swH
            elif S["slBey"] >= 2:
                S["slStat"] = 4
        elif S["slStat"] == 2:
            sd = S["slSide"]
            S["slDec"] = e4.swL if sd == 1 else e4.swH
            if S["slDec"] is not None and ((sd == 1 and e4.c1 < S["slDec"]) or (sd == -1 and e4.c1 > S["slDec"])):
                S["slStat"] = 5
        for L in eD.lv:
            if (not L.dead) and (not L.touched) and (S["slLvl"] is None or abs(L.p - S["slLvl"]) > 0.01) and e4.c2 is not None:
                tch = (e4.l1 <= L.p and e4.c2 > L.p) if L.side == 1 else (e4.h1 >= L.p and e4.c2 < L.p)
                if tch and ((e4.swH is not None) if L.side == 1 else (e4.swL is not None)):
                    S["slLvl"] = L.p; S["slSide"] = L.side; S["slStat"] = 1
                    S["slCause"] = e4.swH if L.side == 1 else e4.swL
                    S["slBey"] = 0; S["slTag"] = "D " + kind_txt(L.kind, L.side)

    def bias(self):
        S = self.S
        if S["slStat"] == 2:
            return S["slSide"]
        if self.P["corrRule"] and S["corrFlag"] and S["corrBias"] != 0:
            return S["corrBias"]
        return self.trn

    # ───────────── إعادة البناء عند التشغيل ─────────────
    def warm(self, T_last):
        """يعيد المحرّكات إلى حالتها بعد معالجة شمعة الشارت T_last (للتشغيل الدافئ)."""
        self.feed_until(T_last)

    # ───────────── معالجة شمعة شارت مغلقة ─────────────
    def emit(self, kind, **kw):
        if self.live:
            self.events.append(dict(kind=kind, **kw))

    def step(self, bar):
        S = self.S; P = self.P; pip = P["pipSize"]
        T = int(bar["time"]); o, h, l, c = bar["open"], bar["high"], bar["low"], bar["close"]
        nw = self.feed_until(T)
        S["bi"] += 1; bi = S["bi"]
        prev_close = S["pc"] if S["pc"] is not None else c
        dk = (dt.datetime.fromtimestamp(T, dt.timezone.utc).astimezone(NY).replace(tzinfo=None) + dt.timedelta(hours=7)).strftime("%Y-%m-%d")
        if dk != S["day"]:
            S["day"] = dk; S["dayCnt"] = 0
        if nw[1]:
            self.story_step()
        bias = self.bias()
        if nw[3]:
            self.S["cands"] = self.scan(c, 250, max(3, P["markMinIdx"]), True)
        self.track(bar, prev_close, nw, bi)
        if P["tradeOn"]:
            self.trade(bar, nw, bi, bias)
        S["pc"] = c; S["last"] = T

    # ───────────── تتبّع اللمس TOUCH ← REJ ← RET / BO ─────────────
    def track(self, bar, prev_close, nw, bi):
        S = self.S; P = self.P; pip = P["pipSize"]; tk = S["tk"]
        l, h, T = bar["low"], bar["high"], int(bar["time"])
        for c in self.S["cands"]:
            pT = c["p"]; sd = c["sd"]
            tch = (l <= pT and prev_close > pT) if sd == 1 else (h >= pT and prev_close < pT)
            if tch and self.q_of(c) >= P["qMin"]:
                if not any(t["sd"] == sd and abs(t["p"] - pT) <= 2 * pip for t in tk):
                    tk.append(dict(p=pT, sd=sd, k=c["tf"], tg=self.short_tag(c), s=1, n=0, m=0, t0=T, tb=c["tb"], br=bi))
                    self.emit("touch", p=pT, sd=sd, tag=self.short_tag(c), time=T)
        for t in tk:
            s0 = t["s"]; cfI = cf_of(t["k"])
            if nw[cfI] and s0 != 9:
                ce = self.E[cfI]
                if ce.lastT + ce.secs > t["t0"]:
                    pk = t["p"]; sup = t["sd"] == 1
                    okS = ce.c1 > pk if sup else ce.c1 < pk
                    tchC = (ce.l1 <= pk + P["retTol"] * pip) if sup else (ce.h1 >= pk - P["retTol"] * pip)
                    if s0 == 1:
                        if okS:
                            t["s"] = 2; t["n"] = 0; t["m"] = 0
                            self.emit("rej", p=pk, sd=t["sd"], tag=t["tg"], time=T)
                        else:
                            t["s"] = 3
                    elif s0 == 2:
                        t["n"] += 1
                        if not okS:
                            t["s"] = 3
                        elif tchC and t["n"] <= P["retMax"]:
                            t["s"] = 5; t["m"] = 0
                            self.emit("ret", p=pk, sd=t["sd"], tag=t["tg"], time=T)
                        elif t["n"] > P["retMax"]:
                            t["s"] = 9
                    elif s0 == 3:
                        if okS:
                            t["s"] = 2; t["n"] = 0; t["m"] = 1
                        else:
                            t["s"] = 9
                            self.emit("bo", p=pk, sd=t["sd"], tag=t["tg"], time=T)
                    elif s0 == 5:
                        t["m"] += 1
                        if not okS:
                            t["s"] = 3
                        elif t["m"] >= P["trkLife"]:
                            t["s"] = 9
        S["tk"] = [t for t in tk if bi - t["br"] <= 600]

    # ───────────── آلة الصفقة ─────────────
    def find_refine(self, idx, d, pk):
        pip = self.P["pipSize"]; best = None
        for L in self.E[idx].lv:
            if (not L.dead) and (not L.touched) and L.side == d:
                dd = (L.p - pk) * d
                if 0.02 < dd <= self.P["refineMax"] * pip:
                    if best is None or dd < (best - pk) * d:
                        best = L.p
        return best

    def find_new_kl(self, idx, d, pk, since_t):
        pip = self.P["pipSize"]; best = None; bt = 0
        for L in self.E[idx].lv:
            if (not L.dead) and (not L.touched) and L.side == d and L.tborn >= since_t:
                dd = (L.p - pk) * d
                if dd > -0.02 and dd <= self.P["refineMax"] * pip * 2:
                    if L.tborn > bt:
                        bt = L.tborn; best = L.p
        return best

    def trade(self, bar, nw, bi, bias):
        S = self.S; P = self.P; pip = P["pipSize"]
        T = int(bar["time"]); o, h, l, c = bar["open"], bar["high"], bar["low"], bar["close"]
        arm = 0
        if S["st"] == 0:
            if (nw[3] or nw[4] or nw[5]) and S["dayCnt"] < P["maxPerDay"]:
                bj = None; bs = -1.0
                for j in self.S["cands"]:
                    k = j["tf"]; cf = cf_of(k); ce = self.E[cf]; p = j["p"]; sd = j["sd"]
                    qual = self.q_of(j) >= P["tQMin"] and k <= P["mainMinIdx"] and abs(p - c) <= P["armDist"] * pip
                    if ce.c2 is None:
                        continue
                    tch = (ce.l1 <= p and ce.c2 > p) if sd == 1 else (ce.h1 >= p and ce.c2 < p)
                    used = S["usedL"] is not None and abs(p - S["usedL"]) <= 5 * pip and bi - S["usedBar"] < 300
                    ctb = P["ctOnly"] and bias != 0 and sd != bias
                    if nw[cf] and qual and tch and not used and not ctb:
                        sc = (6 - k) * 10 + self.q_of(j) * 3 - abs(p - c) / pip / 100
                        if sc > bs:
                            bs = sc; bj = j
                if bj is not None:
                    k = bj["tf"]; cf = cf_of(k); ce = self.E[cf]
                    S["pDir"] = bj["sd"]; S["pK"] = bj["p"]
                    S["pTag"] = bj["tg"] + (" ✓" if bj["cf"] == 1 else "") + (" $" if bj["lq"] == 1 else "")
                    S["pMain"] = k; S["pCf"] = cf; S["pRf"] = rf_of(k)
                    S["pCt"] = bias != 0 and S["pDir"] != bias
                    S["usedL"] = S["pK"]; S["usedBar"] = bi; S["st"] = 1
                    S["nStart"] += 1; S["dayCnt"] += 1; S["pBey"] = 0; S["pCnt"] = 1; S["pRejT"] = ce.lastT
                    d = S["pDir"]; pk = S["pK"]
                    rej_ok = ce.c1 > pk if d == 1 else ce.c1 < pk
                    S["pExt"] = ce.l1 if d == 1 else ce.h1
                    S["pSw"] = ce.swH if d == 1 else ce.swL
                    if rej_ok:
                        S["pPh"] = 1
                        if S["pCt"] and P["useCt"]:
                            S["pPh"] = 2; S["pCnt"] = 0
                    else:
                        S["pPh"] = 3; S["pBey"] = 1
        elif S["st"] == 1:
            ce = self.E[S["pCf"]]; d = S["pDir"]; pk = S["pK"]
            if nw[S["pCf"]]:
                bey_now = ce.c1 < pk if d == 1 else ce.c1 > pk
                if S["pPh"] != 3:
                    S["pBey"] = S["pBey"] + 1 if bey_now else 0
                S["pCnt"] += 1
                if S["pPh"] in (1, 2):
                    S["pExt"] = min(S["pExt"], ce.l1) if d == 1 else max(S["pExt"], ce.h1)
                if S["pBey"] >= 2 and S["pPh"] != 3:
                    S["nBrk"] += 1; S["st"] = 0
                elif S["pPh"] == 3:
                    if bey_now:
                        S["nBrk"] += 1; S["st"] = 0
                    else:
                        S["pPh"] = 2; S["pCnt"] = 0
                        S["pExt"] = min(S["pExt"], ce.l1) if d == 1 else max(S["pExt"], ce.h1)
                elif S["pPh"] == 1:
                    tch = (ce.l1 <= pk + P["retTol"] * pip) if d == 1 else (ce.h1 >= pk - P["retTol"] * pip)
                    good = ce.c1 > pk if d == 1 else ce.c1 < pk
                    if S["pCnt"] <= P["retMax"] + 1 and tch and good:
                        arm = 1
                    elif S["pCnt"] >= P["retMax"] + 1:
                        arm = 3
                elif S["pPh"] == 2:
                    bo = S["pSw"] is not None and (ce.c1 > S["pSw"] if d == 1 else ce.c1 < S["pSw"])
                    if bo:
                        arm = 2
                    elif S["pCnt"] > P["boWait"]:
                        S["nTO"] += 1; S["st"] = 0
        elif S["st"] == 2:
            d = S["pDir"]; pk = S["pK"]
            beyond = c < pk if d == 1 else c > pk
            S["pBey"] = S["pBey"] + 1 if beyond else 0
            tp_first = (h >= S["pTP"] and l > S["pEntry"]) if d == 1 else (l <= S["pTP"] and h < S["pEntry"])
            filled = (l <= S["pEntry"]) if d == 1 else (h >= S["pEntry"])
            if S["pBey"] >= 2 or bi - S["orderBar"] > P["orderWin"] or tp_first:
                reason = "وصل السعر للهدف دون أن يلمس الأمر" if tp_first else ("كُسر المستوى بإغلاقين" if S["pBey"] >= 2 else "انتهت مدة الأمر دون لمسه")
                self.emit_trade("cancel", T, reason=reason)
                S["st"] = 0
            elif filled and bi > S["orderBar"]:
                S["entryBar"] = bi - 1; S["st"] = 3
                self.emit_trade("fill", T)
        if S["st"] == 3 and bi > S["entryBar"]:
            d = S["pDir"]
            hit_sl = (l <= S["pSL"]) if d == 1 else (h >= S["pSL"])
            hit_tp = (h >= S["pTP"]) if d == 1 else (l <= S["pTP"])
            if hit_sl:
                pts = (S["pSL"] - S["pEntry"]) * d / pip
                if abs(pts) < 3:
                    S["nBE"] += 1
                else:
                    S["nLoss"] += 1
                self.emit_trade("result", T, res="BE" if abs(pts) < 3 else "SL", pts=pts)
                S["st"] = 0
            elif hit_tp:
                pts = (S["pTP"] - S["pEntry"]) * d / pip
                S["nWin"] += 1
                self.emit_trade("result", T, res="TP", pts=pts)
                S["st"] = 0
        if arm > 0 and S["st"] == 1:
            self.build_plan(arm, c, T, bi)

    def build_plan(self, arm, close, T, bi):
        S = self.S; P = self.P; pip = P["pipSize"]
        d = S["pDir"]; pk = S["pK"]
        rf = self.find_refine(S["pRf"], d, pk)
        klp = self.find_new_kl(S["pRf"], d, pk, S["pRejT"]) if arm == 3 or (arm == 2 and S["pCt"]) else None
        base = pk; how = "LIMIT"
        if klp is not None:
            base = klp; how = "KL AFTER REJ"
        elif arm == 3:
            base = None
        elif P["entryModel"] == "refined" and rf is not None:
            base = rf; how = "REFINED"
        elif P["entryModel"] == "half" and rf is not None:
            base = (pk + rf) / 2; how = "50%"
        elif P["entryModel"] == "market":
            base = close; how = "ENTRY HERE"
        entry = sl = tgt = None; tgt_tag = ""; big = False; mkt = False
        if base is not None:
            entry = min(base, close) if d == 1 else max(base, close)
            mkt = entry == close
            sl = S["pExt"] - P["slBuf"] * pip if d == 1 else S["pExt"] + P["slBuf"] * pip
            sl = min(sl, entry - P["minSL"] * pip) if d == 1 else max(sl, entry + P["minSL"] * pip)
            dist = abs(entry - sl)
            if dist > P["maxSL"] * pip:
                big = True
            else:
                for cd in self.scan(entry, 3000, P["tpMinIdx"], False):
                    pp = cd["p"]
                    if (pp > entry) if d == 1 else (pp < entry):
                        tpx = pp - P["tpBuf"] * pip if d == 1 else pp + P["tpBuf"] * pip
                        rr = abs(tpx - entry) / dist
                        if rr >= P["minRR"] and (tgt is None or abs(tpx - entry) < abs(tgt - entry)):
                            tgt = tpx; tgt_tag = cd["tg"]
        if not big and base is not None:
            self.S["cands"] = self.scan(close, 250, max(3, P["markMinIdx"]), True)
        if entry is None or big or tgt is None:
            if big:
                S["nBig"] += 1
            else:
                S["nNoTgt"] += 1
            S["st"] = 0
            return
        dist = abs(entry - sl)
        S["pEntry"] = entry; S["pSL"] = sl; S["pTP"] = tgt; S["pRisk"] = dist / pip; S["pTpTag"] = tgt_tag
        S["orderBar"] = bi; S["entryBar"] = bi; S["pBey"] = 0
        S["st"] = 3 if mkt else 2
        S["tid"] += 1; S["muted"] = not self.live
        self.emit_trade("plan", T, how=how, mkt=mkt, rr=abs(tgt - entry) / dist)

    def emit_trade(self, what, T, **kw):
        S = self.S
        if not self.live or (S["muted"] and what != "plan"):
            return
        self.events.append(dict(kind=what, time=T, tid=S["tid"], dir=S["pDir"], entry=S["pEntry"], sl=S["pSL"], tp=S["pTP"], risk=S["pRisk"],
                                pK=S["pK"], tag=S["pTag"], tpTag=S["pTpTag"], ct=S["pCt"], **kw))
