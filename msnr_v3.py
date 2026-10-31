# -*- coding: utf-8 -*-
"""
MSNR Key Levels v3 — ترجمة حرفية لمؤشر «MSNR-B2 v3» (محرك المستويات + حالة المستويات الملموسة + تصنيف الرفض 1–4).
  • محرك المستويات eng(): نفس منطق المؤشر (إغلاقان للكسر، السيولة المخفية، نجوم التفعيل/الكسر، rt = لمس عند الكسر، af = تفعيل من مستوى فريش).
  • حالة كل مستوى ملموس: TOUCH ← REJ (نوع T1–T4 + منطقة الدخول) ← RETEST / BEHIND.
  • فوق المؤشر: أحداث لحظية (⚡) من السعر الحي: لمس المستوى، رفض مبدئي، لمس إعادة الاختبار — بلا انتظار إغلاق شمعة التأكيد.
  • تأكيد الرفض/الاختبار يُعالَج لحظة إغلاق شمعة التأكيد نفسها (لا بعد 5 دقائق كما في TradingView).
الأسعار بالدولار؛ pipSize=0.1 يعني أن «النقطة» = 0.1$.
"""
import msnr_pro as MP

TFN = ["W", "D", "4H", "1H", "30M", "15M"]
RANK = [4, 3, 2, 1, 0, 0]
SECS = [604800, 86400, 14400, 3600, 1800, 900, 300]
CONF = [1, 2, 3, 4, 5, 6]                       # فريم تأكيد كل فريم: W→D, D→4H, 4H→1H, 1H→30M, 30M→15M, 15M→5M(الشارت)
CONFN = ["D", "4H", "1H", "30M", "15M", "5M"]

DEF = dict(
    tfOn=[True, True, True, True, True, False], classicMode=0,
    kClassic=True, kGap=False, kFlip=True, kQML=True, brkN=2, minStars=1, liqPips=30.0, keepT=False,
    nPer=1, mergeGap=20.0, minAge=0, maxDist=500.0, confOnly=False, pipSize=0.1,
    retestC=2, retLife=40, flipFromBreak=True, refineOn=True, refineMax=50.0, rejOn=True, farPts=30.0, strongPts=30.0, chkHide=True,
    earlyRejPts=15.0, retTolPts=5.0, touchLive=True, msgMaxG=3, msgNear=150.0, msgTouch=False, earlyRej=False, dedupeH=3.0,
)
TYPE_TXT = {
    1: "ذيل ضعيف + إغلاق قريب: يُتوقَّع سحب سيولة قمة الذيل أولاً — لا تدخل فوراً، ابحث عن Refine عند/فوق الذيل",
    2: "ذيل ضعيف + إغلاق بعيد: قد يكتفي السعر باللمس — الدخول داخل الصندوق بين الإغلاق والمستوى (50% أو Refine)",
    3: "ذيل قوي + إغلاق قريب: يُتوقَّع رجوع لإعادة الاختبار — الدخول من 50% الذيل أو Refine بفريم أصغر",
    4: "ذيل قوي + إغلاق بعيد (مهم جداً): يرجع غالباً لـ50% الذيل أو للمستوى — Refine على 5M حتى 1M",
}


def kind_name(kd, role):
    return "Classic V" if kd == 1 and role == 1 else "Classic A" if kd == 1 else "OC" if kd == 2 else ("RBS" if role == 1 else "SBR") if kd == 3 else "QML"


def kind_short(kd, role):
    return "CL" if kd == 1 else "OC" if kd == 2 else ("RBS" if role == 1 else "SBR") if kd == 3 else "QM"


class Eng3:
    """نسخة تراكمية من eng() للمؤشر: تُغذّى بشمعة فريم مكتملة واحدة كل مرة."""

    def __init__(self):
        self.lv = []; self.hist = []; self.n = 0; self.lastSH = self.lastSL = None

    def feed(self, bar, P):
        pip = P["pipSize"]; liq = P["liqPips"]; cfm = int(P["brkN"]); keepI = 1 if P["keepT"] else 0; cMode = P["classicMode"]
        self.hist.append(bar); self.hist = self.hist[-6:]; self.n += 1; b = self.n
        H = self.hist

        def g(k, f):
            j = len(H) - k
            return H[j][f] if j >= 0 else None
        o1, h1, l1, c1, t1 = g(1, "open"), g(1, "high"), g(1, "low"), g(1, "close"), g(1, "time")
        o2, c2, l2, h2, t2 = g(2, "open"), g(2, "close"), g(2, "low"), g(2, "high"), g(2, "time")
        c3 = g(3, "close"); c4 = g(4, "close"); c5 = g(5, "close")
        lv = self.lv
        if lv:
            for i in range(len(lv) - 1, -1, -1):
                L = lv[i]; p = L["p"]; r = L["r"]; gone = False
                if t1 > L["tm"] and L["lb"] < t1:
                    L["lb"] = t1
                    beyond = (c1 < p) if r == 1 else (c1 > p)
                    nb = L["bk"]

                    def flip():
                        L["r"] = -r; L["kd"] = 3 if nb == 0 else 4; L["bk"] = nb + 1; L["tm"] = t1
                        L["ts"] = 0; L["ac"] = 1; L["br"] = 1; L["lq"] = 0; L["wt"] = 0
                        L["rt"] = 1 if ((l1 <= p) if -r == 1 else (h1 >= p)) else 0; L["af"] = 0
                    if L["pd"] == 1:
                        L["pd"] = 0
                        if beyond:
                            if nb < 2:
                                flip()
                            else:
                                gone = True
                        elif keepI == 0:
                            gone = True
                        else:
                            L["ts"] += 1
                    else:
                        touched = (l1 <= p) if r == 1 else (h1 >= p)
                        if touched:
                            if beyond and cfm == 1:
                                if nb < 2:
                                    flip()
                                else:
                                    gone = True
                            elif beyond:
                                L["pd"] = 1
                            elif keepI == 0:
                                gone = True
                            else:
                                L["ts"] += 1
                        else:
                            near_fail = (l1 > p and l1 - p <= liq * pip) if r == 1 else (h1 < p and p - h1 <= liq * pip)
                            if near_fail:
                                L["lq"] += 1
                                dw = (l1 - p) if r == 1 else (p - h1)
                                L["wt"] = dw if L["wt"] == 0 else min(L["wt"], dw)
                            ox = L["op"]
                            if L["br"] == 0 and ox is not None and ((c1 > ox) if r == 1 else (c1 < ox)):
                                L["br"] = 1
                if gone:
                    del lv[i]
        if c5 is not None:
            if c3 > c4 and c3 > c5 and c3 > c2 and c3 > c1:
                self.lastSH = c3
            if c3 < c4 and c3 < c5 and c3 < c2 and c3 < c1:
                self.lastSL = c3
        lp = None; role = 0; kind = 0; ot = None
        if c3 is not None:
            if cMode == 0:
                cA = c2 > c3 and c2 > c1; cV = c2 < c3 and c2 < c1
            else:
                cA = c2 > o2 and c1 < o1 and l1 < l2; cV = c2 < o2 and c1 > o1 and h1 > h2
            if cA:
                lp, role, kind, ot = c2, -1, 1, t2
            elif cV:
                lp, role, kind, ot = c2, 1, 1, t2
            elif c2 > o2 and c1 > o1:
                lp, role, kind, ot = c2, 1, 2, t2
            elif c2 < o2 and c1 < o1:
                lp, role, kind, ot = c2, -1, 2, t2
        if lp is not None:
            dup = False; act = False; actF = False
            tolA = 10 * pip; lo = min(l1, l2); hi = max(h1, h2)
            for L in lv:
                if L["r"] == role and abs(L["p"] - lp) <= pip:
                    dup = True
                if L["tm"] < t2 and ((L["p"] >= lo - tolA and L["p"] <= lp + tolA) if role == 1 else (L["p"] <= hi + tolA and L["p"] >= lp - tolA)):
                    act = True
                    if L["ts"] == 0 and L["bk"] == 0:
                        actF = True
            if not dup:
                oppP = None
                if role == 1:
                    if self.lastSH is not None and self.lastSH > c1:
                        oppP = self.lastSH
                else:
                    if self.lastSL is not None and self.lastSL < c1:
                        oppP = self.lastSL
                lv.append(dict(p=lp, r=role, kd=kind, tm=t1, bk=0, og=ot, ob=b, ts=0, pd=0, lb=0, ac=1 if act else 0, op=oppP, br=0, lq=0, wt=0, rt=0, af=1 if actF else 0))
                if len(lv) > 60:
                    lv.pop(0)

    def select(self, cur, P, kf=True):
        """أقرب مستويات فوق السعر وتحته (حتى nPer لكل جهة) بعد مرشّح النوع والنجوم والعمر."""
        pip = P["pipSize"]; out = []
        kon = {1: P["kClassic"], 2: P["kGap"], 3: P["kFlip"], 4: P["kQML"]}
        for side in (0, 1):
            used = set()
            for _ in range(P["nPer"]):
                best = -1; bd = 0.0
                for i, L in enumerate(self.lv):
                    if i in used or L["pd"] != 0 or self.n - L["ob"] < P["minAge"] or (kf and not kon[L["kd"]]):
                        continue
                    if L["ac"] + L["br"] + (1 if L["lq"] > 0 else 0) < P["minStars"]:
                        continue
                    d = L["p"] - cur
                    if (d > 0) if side == 0 else (d < 0):
                        ad = abs(d)
                        if best == -1 or ad < bd:
                            best, bd = i, ad
                if best >= 0:
                    used.add(best); L = self.lv[best]
                    out.append(dict(p=L["p"], r=L["r"], kd=L["kd"], ts=min(L["ts"], 9), stc=L["ac"] + L["br"] + (1 if L["lq"] > 0 else 0),
                                    hl=int(min(round(L["wt"] / pip), 999)), rt=L["rt"], af=L["af"],
                                    o=(L["tm"] if (P["flipFromBreak"] and L["kd"] >= 3) else L["og"])))
        return out


def fresh_state():
    return dict(last=0, st=[], bi=0)


class V3:
    def __init__(self, P=None, S=None):
        self.P = {**DEF, **(P or {})}
        self.S = S if S else fresh_state()
        for k, v in fresh_state().items():
            self.S.setdefault(k, v)
        self.E = [Eng3() for _ in range(6)]
        self.cl = [[] for _ in range(6)]
        self.ptr = [0] * 6; self.fed = [0] * 6
        self.chart5 = []
        self.sel = [[] for _ in range(6)]
        self.events = []; self.live = True
        self.ready = False

    # ───────────── البيانات ─────────────
    def set_candles(self, h1, m30, m15, chart5):
        def ext(base, size):
            last = base[-1]["time"] if base else 0
            return [dict(b, end=b["time"] + size) for b in base] + MP.derive(chart5, size, last + size - 1 if base else 0)
        a1 = ext(h1, 3600)
        self.cl = [MP.agg(a1, "W"), MP.agg(a1, "D"), MP.agg(a1, "4H"), a1, ext(m30, 1800), ext(m15, 900)]
        for k in range(6):
            lst = self.cl[k]; i = 0
            while i < len(lst) and lst[i]["time"] <= self.fed[k]:
                i += 1
            self.ptr[k] = i
        self.chart5 = chart5

    def feed_until(self, T):
        """يغذّي المحرّكات بكل شمعة فريم نهايتها ≤ T؛ يعيد {فهرس: الشمعة المغلقة الجديدة}."""
        new = {}
        for k in range(6):
            lst = self.cl[k]
            while self.ptr[k] < len(lst):
                c = lst[self.ptr[k]]
                if c["end"] > T:
                    break
                self.ptr[k] += 1
                self.E[k].feed(c, self.P); self.fed[k] = c["time"]; new[k] = c
        return new

    def warm(self, T):
        self.feed_until(T)

    # ───────────── مساعدات ─────────────
    def forming_extremes(self, g, T, cur):
        """أدنى/أعلى الشمعة المتكوّنة الحالية للفريم g من شموع الشارت 5د (+ السعر الحي)."""
        t0 = self.htf_open(g, T)
        lo = hi = None
        for b in reversed(self.chart5):
            if b["time"] < t0:
                break
            if b["time"] > T:
                continue
            lo = b["low"] if lo is None else min(lo, b["low"]); hi = b["high"] if hi is None else max(hi, b["high"])
        if cur is not None:
            lo = cur if lo is None else min(lo, cur); hi = cur if hi is None else max(hi, cur)
        return lo, hi

    @staticmethod
    def htf_open(g, T):
        if g == 0:
            return MP.bucket(T, "W")[0]
        if g == 1:
            return MP.bucket(T, "D")[0]
        if g == 2:
            return MP.bucket(T, "4H")[0]
        return int(T) // SECS[g] * SECS[g]

    def tag_of(self, g, kd, role, stc):
        return f"{TFN[g]} {kind_short(kd, role)}" + (" " + "★" * stc if stc else "")

    # ───────────── معالجة شمعة شارت 5د مغلقة ─────────────
    def step(self, bar):
        S = self.S; P = self.P; pip = P["pipSize"]
        T = int(bar["time"]); end = T + 300
        new = self.feed_until(end)
        S["bi"] += 1
        cur = bar["close"]
        for g in range(6):
            self.sel[g] = self.E[g].select(cur, P) if P["tfOn"][g] else []
        st = S["st"]
        for g in range(6):
            if not P["tfOn"][g]:
                continue
            lo, hi = self.forming_extremes(g, T, None)
            for L in self.sel[g]:
                p = L["p"]; r = L["r"]
                used0 = (lo is not None) and ((lo <= p) if r == 1 else (hi >= p))
                kon = {1: P["kClassic"], 2: P["kGap"], 3: P["kFlip"], 4: P["kQML"]}[L["kd"]]
                if not kon:
                    continue
                f = next((x for x in st if x["g"] == g and x["r"] == r and abs(x["p"] - p) <= 2 * pip), None)
                if f is not None:
                    f["seen"] = True; f["kd"] = L["kd"]; f["stc"] = L["stc"]
                elif not used0:
                    st.append(dict(p=p, r=r, g=g, kd=L["kd"], stc=L["stc"], o=L["o"], s=1 if L["rt"] else 0, T=T if L["rt"] else 0, n=0, m=0,
                                   x=0, w=None, c=None, seen=True, e1=0, e2=0, e3=0, rt=L["rt"], af=L["af"]))
        # لمس بالشمعة (low/high) + انتقالات التأكيد
        for x in st:
            sup = x["r"] == 1; p = x["p"]
            if x["s"] == 0 and ((bar["low"] <= p) if sup else (bar["high"] >= p)):
                x["s"] = 1; x["T"] = T
                if not x["e1"]:
                    x["e1"] = 1; self.ev("touch", x, T, at=T, cur=cur)
            ci = CONF[x["g"]]
            cc = bar if ci == 6 else new.get(ci)
            if cc is None or x["s"] not in (1, 2, 3, 5):
                continue
            cend = cc["time"] + SECS[ci] if ci != 6 else end
            yh, yl, yc = cc["high"], cc["low"], cc["close"]
            ok_side = yc > p if sup else yc < p
            touch_c = (yl <= p) if sup else (yh >= p)
            s2 = x["s"]
            if s2 == 1:
                if x["T"] < cend:
                    if ok_side:
                        x["s"] = 2; x["n"] = 0; x["m"] = 0
                        self.classify(x, yh, yl, yc)
                        self.ev("rej", x, T, at=cend, cur=cur)
                    else:
                        x["s"] = 3
            elif s2 == 2:
                x["n"] += 1
                if not ok_side:
                    x["s"] = 3
                elif touch_c and x["n"] <= P["retestC"]:
                    x["s"] = 5; x["m"] = 0
                    self.ev("ret", x, T, at=cend, cur=cur)
                elif x["n"] > P["retestC"]:
                    x["s"] = 9
            elif s2 == 3:
                if ok_side:
                    x["s"] = 2; x["n"] = 0; x["m"] = 1
                    self.classify(x, yh, yl, yc)                     # عودة بعد «كسر 1/2»: لا رسالة (يعرضها المؤشر FAKE? بلا تنبيه)
                else:
                    x["s"] = 9
            elif s2 == 5:
                x["m"] += 1
                if not ok_side:
                    x["s"] = 3
                elif x["m"] >= P["retLife"]:
                    x["s"] = 9
        S["st"] = [x for x in st if (x.pop("seen", False) or x["s"] in (1, 2, 3, 5)) and len(st) < 400]
        S["st"] = S["st"][-150:]
        S["last"] = T

    def classify(self, x, yh, yl, yc):
        if not self.P["rejOn"]:
            return
        pip = self.P["pipSize"]; p = x["p"]; sup = x["r"] == 1
        dpt = max(p - yl, 0) if sup else max(yh - p, 0)
        far = abs(yc - p) >= self.P["farPts"] * pip
        strong = dpt >= self.P["strongPts"] * pip
        x["x"] = 4 if (strong and far) else 3 if strong else 2 if far else 1
        x["w"] = yl if sup else yh; x["c"] = yc

    # ───────────── أحداث ─────────────
    def zone(self, x):
        t = x.get("x") or 0; p = x["p"]; w = x.get("w"); c = x.get("c")
        if not t or w is None:
            return None
        if t == 1:
            return (w, w)
        a, b = (c, p) if t == 2 else (p, w)
        return (min(a, b), max(a, b))

    def refine_of(self, x):
        P = self.P; pip = P["pipSize"]
        if not P["refineOn"]:
            return None
        best = None
        for g in range(x["g"] + 1, 5):
            for L in self.sel[g]:
                if L["r"] != x["r"]:
                    continue
                dd = (x["p"] - L["p"]) if x["r"] == 1 else (L["p"] - x["p"])
                if 0.02 < dd <= P["refineMax"] * pip and (best is None or dd < best[0]):
                    best = (dd, L["p"], self.tag_of(g, L["kd"], L["r"], 0))
        return None if best is None else (best[1], best[2])

    def cluster_tag(self, x):
        """وسوم كل المستويات المتتبَّعة عند نفس السعر (نفس الجهة) في رسالة واحدة، الأكبر فريماً أولاً."""
        pip = self.P["pipSize"]; mg = self.P["mergeGap"] * pip
        mem = sorted([y for y in self.S["st"] if y["r"] == x["r"] and abs(y["p"] - x["p"]) <= mg and y["g"] <= self.P["msgMaxG"] and y["s"] in (0, 1, 2, 3, 5)], key=lambda y: y["g"])
        if x not in mem:
            mem.append(x)
        return " + ".join(self.tag_of(y["g"], y["kd"], y["r"], y["stc"]) for y in mem[:4])

    def allowed(self, kind, x, at):
        """رسالة واحدة لكل مرحلة لكل مستوى (ولو تكرر على أكثر من فريم): قرب ← رفض ← إعادة اختبار، ولا إعادة اختبار قبل رفض."""
        P = self.P; sent = self.S.setdefault("sent", [])
        stage = "ret" if kind in ("ret", "retE") else "rej" if kind in ("rej", "rejE") else "touch"
        tol = P["mergeGap"] * P["pipSize"]; hh = P["dedupeH"] * 3600
        self.S["sent"] = sent = [m for m in sent if at - m["t"] < 12 * 3600]
        near = [m for m in sent if m["r"] == x["r"] and abs(m["p"] - x["p"]) <= tol]
        if any(m["stage"] == stage and at - m["t"] < hh for m in near):
            return False
        if stage == "ret" and not any(m["stage"] == "rej" for m in near):
            return False
        if stage == "rej" and any(m["stage"] == "ret" and at - m["t"] < hh for m in near):
            return False
        sent.append(dict(r=x["r"], p=x["p"], stage=stage, t=at))
        return True

    def ev(self, kind, x, T, at, cur, fake=False, live=False):
        if (not self.live and not live) or x["g"] > self.P["msgMaxG"]:        # الرسائل لمستويات 1H فما فوق افتراضياً (msgMaxG=4 يضيف 30M)
            return
        if kind == "touch" and not self.P["msgTouch"]:
            return
        if kind == "ret" and x.get("e3"):                           # أُرسلت إعادة الاختبار لحظياً: لا رسالة ثانية
            return
        if kind in ("rej", "ret") and not x.get("e1") and abs(cur - x["p"]) > self.P["msgNear"] * self.P["pipSize"]:
            return                                    # مستوى مقلوب بعيد عن السعر لم يُلمس فعلياً: لا رسالة (الحالة تتقدّم بصمت)
        if not self.allowed(kind, x, at):
            return
        z = self.zone(x)
        self.events.append(dict(kind=kind, p=x["p"], role=x["r"], tag=self.cluster_tag(x), g=x["g"], cf=CONFN[x["g"]], cur=cur,
                                x=x.get("x", 0), w=x.get("w"), c=x.get("c"), zone=z, mid=(None if z is None else (z[0] + z[1]) / 2), refine=self.refine_of(x),
                                at=at, fake=fake, rt=x.get("rt"), af=x.get("af")))

    # ───────────── لحظي: السعر الحي ─────────────
    def fast(self, cur, now):
        """يُستدعى كل بضع ثوانٍ بالسعر الحي. يعيد أحداثاً لحظية (لمس / رفض مبدئي / لمس إعادة اختبار)."""
        S = self.S; P = self.P; pip = P["pipSize"]; out = []
        if not P["touchLive"]:
            return out
        for x in S["st"]:
            sup = x["r"] == 1; p = x["p"]; msg = x["g"] <= P["msgMaxG"]
            if x["s"] == 0 and ((cur <= p) if sup else (cur >= p)):
                x["s"] = 1; x["T"] = int(now) // 300 * 300; x["e1"] = 1
                if msg and P["msgTouch"] and self.allowed("touch", x, now):
                    out.append(self._lev("touch", x, now, cur))
            elif x["s"] == 1 and not x["e2"] and x["e1"]:
                far = P["earlyRejPts"] * pip
                if (sup and cur >= p + far) or ((not sup) and cur <= p - far):
                    x["e2"] = 1
                    if msg and P["earlyRej"] and self.allowed("rejE", x, now):
                        out.append(self._lev("rejE", x, now, cur))
            elif x["s"] == 2 and not x["e3"] and x["n"] <= P["retestC"]:
                tol = P["retTolPts"] * pip
                if (sup and p - 2 * tol <= cur <= p + tol) or ((not sup) and p - tol <= cur <= p + 2 * tol):
                    x["e3"] = 1
                    if msg and self.allowed("retE", x, now):
                        out.append(self._lev("retE", x, now, cur))
        return out

    def _lev(self, kind, x, now, cur):
        z = self.zone(x)
        return dict(kind=kind, p=x["p"], role=x["r"], tag=self.cluster_tag(x), g=x["g"], cf=CONFN[x["g"]], cur=cur,
                    x=x.get("x", 0), w=x.get("w"), c=x.get("c"), zone=z, mid=(None if z is None else (z[0] + z[1]) / 2), refine=self.refine_of(x),
                    at=now, fake=False, rt=x.get("rt"), af=x.get("af"), live=True)

    # ───────────── المستويات المعروضة (للقطة وتنبيهات الاقتراب) ─────────────
    def shown(self, cur, now=None):
        P = self.P; pip = P["pipSize"]; T = int(now or 0) or (self.S["last"] + 300)
        cl = []
        for g in range(6):
            if not P["tfOn"][g]:
                continue
            sel = self.E[g].select(cur, P)
            lo, hi = self.forming_extremes(g, T, cur)
            for L in sel:
                p = L["p"]; r = L["r"]
                near = P["maxDist"] <= 0 or abs(cur - p) / pip <= P["maxDist"]
                used0 = (lo is not None) and ((lo <= p) if r == 1 else (hi >= p))
                wrong = (p > cur) if r == 1 else (p < cur)
                if not near or used0 or (P["chkHide"] and wrong):
                    continue
                hit = next((c for c in cl if abs(c["price"] - p) <= P["mergeGap"] * pip and (c["role"] == "support") == (r == 1)), None)
                tag = TFN[g]
                if hit:
                    hit["tags"].append(tag)
                else:
                    cl.append(dict(price=p, role="support" if r == 1 else "resistance", tags=[tag], kd=L["kd"], kind=kind_name(L["kd"], r),
                                   marks=("★" * L["stc"]) + ("$" if L["hl"] else ""), hl=L["hl"], stars=L["stc"], tests=L["ts"], rt=L["rt"], af=L["af"], tf=g))
        if P["confOnly"]:
            cl = [c for c in cl if len(c["tags"]) > 1]
        cl.sort(key=lambda c: abs(c["price"] - cur))
        return cl
