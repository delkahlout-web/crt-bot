# -*- coding: utf-8 -*-
"""
MSNR Key Levels v4 — ترجمة حرفية لمؤشر «MSNR-B2 v4».
  • كل مستوى يحمل حالته داخل محرّك فريمه نفسه: طازج ← رفض REJ (نوع T1–T4) ← إعادة اختبار RET / خلف المستوى (BEHIND).
    الرفض = شمعة فريم المستوى نفسها لمست المستوى وأغلقت في الجهة الصحيحة؛ إعادة الاختبار = شمعة لاحقة (حتى retestC) لمسته وأغلقت صحيحة.
  • histDepth: المحرّك يبني المستويات من آخر N شمعة لكل فريم فقط (فتتطابق على أي فريم شارت).
  • الرسائل: قرب (من لقطة المستويات الحية) ← رفض مؤكَّد ← إعادة اختبار (لحظية عند لمس السعر الحي بعد الرفض).
الأسعار بالدولار؛ pipSize=0.1 يعني أن «النقطة» = 0.1$.
"""
import msnr_pro as MP

TFN = ["W", "D", "4H", "1H", "30M", "15M"]
SECS = [604800, 86400, 14400, 3600, 1800, 900]
DEF = dict(
    tfOn=[True, True, True, True, True, False], classicMode=0,
    kClassic=True, kGap=False, kFlip=True, kQML=True, brkN=2, minStars=1, liqPips=30.0, keepT=False, histDepth=500,
    nPer=1, maxPerSide=3, mergeGap=20.0, minAge=0, maxDist=500.0, confOnly=False, pipSize=0.1,
    retestC=2, retLife=40, refineOn=True, refineMax=50.0, rejOn=True, farPts=30.0, strongPts=30.0, chkHide=True,
    retTolPts=5.0, msgMaxG=3, dedupeH=3.0, touchLive=True,
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


def why_of(L):
    """A = تشكّل عند مستوى أقدم (تفعيل) · B = كسر آخر نقطة معاكسة · L = سيولة مخفية."""
    return ("A" if L["ac"] else "") + ("B" if L["br"] else "") + ("L" if L["lq"] > 0 else "")


class Eng4:
    """نسخة تراكمية من eng() للمؤشر v4: تُغذّى بشمعة فريم مكتملة واحدة كل مرة وتعيد انتقالات الحالة (رفض/إعادة اختبار)."""

    def __init__(self):
        self.lv = []; self.hist = []; self.n = 0; self.lastSH = self.lastSL = None

    def feed(self, bar, P):
        pip = P["pipSize"]; liq = P["liqPips"]; cfm = int(P["brkN"]); keepI = 1 if P["keepT"] else 0; cMode = P["classicMode"]
        minStars = P["minStars"]; retestC = P["retestC"]; retLife = P["retLife"]
        farP = P["farPts"] * pip; strP = P["strongPts"] * pip
        self.hist.append(bar); self.hist = self.hist[-6:]; self.n += 1; b = self.n
        H = self.hist; trans = []

        def g(k, f):
            j = len(H) - k
            return H[j][f] if j >= 0 else None
        o1, h1, l1, c1, t1 = g(1, "open"), g(1, "high"), g(1, "low"), g(1, "close"), g(1, "time")
        o2, c2, l2, h2, t2 = g(2, "open"), g(2, "close"), g(2, "low"), g(2, "high"), g(2, "time")
        c3 = g(3, "close"); c4 = g(4, "close"); c5 = g(5, "close")
        lv = self.lv
        flipOn = P["kFlip"]; qmlOn = P["kQML"]
        if lv:
            for i in range(len(lv) - 1, -1, -1):
                L = lv[i]; p = L["p"]; r = L["r"]; gone = False
                if t1 > L["tm"] and L["lb"] < t1:
                    L["lb"] = t1
                    beyond = (c1 < p) if r == 1 else (c1 > p)
                    touchedB = (l1 <= p) if r == 1 else (h1 >= p)
                    nb = L["bk"]
                    canFlip = (nb == 0 and flipOn) or (nb == 1 and qmlOn)
                    stN = L["ac"] + L["br"] + (1 if L["lq"] > 0 else 0)
                    s0 = L["us"]

                    def flip():
                        L["r"] = -r; L["kd"] = 3 if nb == 0 else 4; L["bk"] = nb + 1; L["tm"] = t1
                        L["ts"] = 0; L["ac"] = 1; L["br"] = 1; L["lq"] = 0; L["wt"] = 0; L["af"] = 0
                        L["us"] = 0; L["um"] = 0; L["un"] = 0; L["ut"] = 0; L["e3"] = 0

                    def reject(um):
                        L["us"] = 2
                        dpx = max(p - l1, 0) if r == 1 else max(h1 - p, 0)
                        L["ux"] = (4 if abs(c1 - p) >= farP else 3) if dpx >= strP else (2 if abs(c1 - p) >= farP else 1)
                        L["uw"] = l1 if r == 1 else h1; L["uq"] = c1
                        L["um"] = um; L["un"] = 0; L["ut"] = 0; L["e3"] = 0
                        trans.append(("rej", dict(L), bar))
                    if s0 == 0:
                        if L["pd"] == 1:
                            L["pd"] = 0
                            if beyond:
                                if canFlip:
                                    flip()
                                else:
                                    gone = True
                            elif keepI == 0:
                                if stN >= minStars:
                                    reject(1)
                                else:
                                    gone = True
                            else:
                                L["ts"] += 1
                        else:
                            if touchedB:
                                if beyond and cfm == 1:
                                    if canFlip:
                                        flip()
                                    else:
                                        gone = True
                                elif beyond:
                                    L["pd"] = 1
                                elif keepI == 0:
                                    if stN >= minStars:
                                        reject(0)
                                    else:
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
                    elif s0 == 2:
                        L["un"] += 1
                        if beyond:
                            L["us"] = 3; L["ut"] = 0
                        elif touchedB and L["un"] <= retestC:
                            L["us"] = 5; L["ut"] = 0
                            trans.append(("ret", dict(L), bar))
                        elif L["un"] > retestC:
                            gone = True
                    elif s0 == 5:
                        L["ut"] += 1
                        if beyond:
                            L["us"] = 3; L["ut"] = 0
                        elif L["ut"] >= retLife:
                            gone = True
                    elif s0 == 3:
                        if not beyond:
                            reject(1)
                        else:
                            gone = True
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
                if L["us"] == 0 and L["r"] == role and abs(L["p"] - lp) <= pip:
                    dup = True
                if L["us"] == 0 and L["tm"] < t2 and ((L["p"] >= lo - tolA and L["p"] <= lp + tolA) if role == 1 else (L["p"] <= hi + tolA and L["p"] >= lp - tolA)):
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
                lv.append(dict(p=lp, r=role, kd=kind, tm=t1, bk=0, og=ot, ob=b, ts=0, pd=0, lb=0, ac=1 if act else 0, op=oppP, br=0, lq=0, wt=0,
                               us=0, um=0, un=0, ut=0, af=1 if actF else 0, ux=0, uw=None, uq=None, e3=0))
                if len(lv) > 60:
                    ev = next((k for k, L in enumerate(lv) if L["us"] > 0), 0)
                    lv.pop(ev)
        return trans


def fresh_state():
    return dict(last=0, bi=0, sent=[])


class V4:
    def __init__(self, P=None, S=None):
        self.P = {**DEF, **(P or {})}
        self.S = S if S else fresh_state()
        for k, v in fresh_state().items():
            self.S.setdefault(k, v)
        self.E = [Eng4() for _ in range(6)]
        self.cl = [[] for _ in range(6)]
        self.ptr = [0] * 6; self.fed = [0] * 6
        self.chart5 = []
        self.events = []; self.live = True

    # ───────────── حفظ/استعادة حالة المحرّكات (تشغيل متقطع = نفس النتيجة تماماً) ─────────────
    def dump(self):
        return dict(fed=list(self.fed), E=[dict(lv=e.lv, hist=e.hist, n=e.n, sh=e.lastSH, sl=e.lastSL) for e in self.E])

    def restore(self, d):
        try:
            if not d or len(d["E"]) != 6:
                return False
            for e, x in zip(self.E, d["E"]):
                e.lv = x["lv"]; e.hist = x["hist"]; e.n = x["n"]; e.lastSH = x["sh"]; e.lastSL = x["sl"]
            self.fed = list(d["fed"])
            return True
        except Exception:
            return False

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

    def feed_until(self, T, silent=False):
        """يغذّي كل شمعة فريم نهايتها ≤ T؛ عند أول تغذية لفريم يبدأ من آخر histDepth شمعة فقط (كالمؤشر). يعيد قائمة انتقالات (g, kind, snap, candle)."""
        out = []
        depth = self.P["histDepth"]
        for k in range(6):
            lst = self.cl[k]
            if self.fed[k] == 0:
                j = self.ptr[k]
                while j < len(lst) and lst[j]["end"] <= T:
                    j += 1
                self.ptr[k] = max(self.ptr[k], j - depth)
            while self.ptr[k] < len(lst):
                c = lst[self.ptr[k]]
                if c["end"] > T:
                    break
                self.ptr[k] += 1
                tr = self.E[k].feed(c, self.P); self.fed[k] = c["time"]
                if not silent:
                    out += [(k, kd, snap, c) for kd, snap, _ in tr]
        return out

    def warm(self, T):
        self.feed_until(T, silent=True)

    # ───────────── مساعدات ─────────────
    @staticmethod
    def htf_open(g, T):
        if g == 0:
            return MP.bucket(T, "W")[0]
        if g == 1:
            return MP.bucket(T, "D")[0]
        if g == 2:
            return MP.bucket(T, "4H")[0]
        return int(T) // SECS[g] * SECS[g]

    def forming_extremes(self, g, T, cur):
        t0 = self.htf_open(g, T); lo = hi = None
        for b in reversed(self.chart5):
            if b["time"] < t0:
                break
            if b["time"] > T:
                continue
            lo = b["low"] if lo is None else min(lo, b["low"]); hi = b["high"] if hi is None else max(hi, b["high"])
        if cur is not None:
            lo = cur if lo is None else min(lo, cur); hi = cur if hi is None else max(hi, cur)
        return lo, hi

    def tag_of(self, g, L):
        w = why_of(L)
        return f"{TFN[g]} {kind_short(L['kd'], L['r'])}" + (" " + "★" * len(w) + f" [{w}]" if w else "")

    def zone(self, L):
        t = L.get("ux") or 0; p = L["p"]; w = L.get("uw"); c = L.get("uq")
        if not t or w is None:
            return None
        if t == 1:
            return (w, w)
        a, b = (c, p) if t == 2 else (p, w)
        return (min(a, b), max(a, b))

    def cluster_tag(self, g, L):
        """وسوم كل المستويات في حالة رفض/اختبار عند نفس السعر (نفس الجهة) في رسالة واحدة، الأكبر فريماً أولاً."""
        mg = self.P["mergeGap"] * self.P["pipSize"]; mem = [(g, L)]
        for k in range(6):
            if not self.P["tfOn"][k] or k > self.P["msgMaxG"]:
                continue
            for M in self.E[k].lv:
                if M["us"] in (2, 5) and M["r"] == L["r"] and abs(M["p"] - L["p"]) <= mg and not (k == g and abs(M["p"] - L["p"]) < 1e-9):
                    mem.append((k, M))
        mem.sort(key=lambda x: x[0])
        return " + ".join(self.tag_of(k, M) for k, M in mem[:4])

    def refine_of(self, g, L, cur):
        P = self.P; pip = P["pipSize"]
        if not P["refineOn"]:
            return None
        best = None
        for k in range(g + 1, 5):
            if not P["tfOn"][k]:
                continue
            for F in self.select(k, cur, None):
                if F["r"] != L["r"]:
                    continue
                dd = (L["p"] - F["p"]) if L["r"] == 1 else (F["p"] - L["p"])
                if 0.02 < dd <= P["refineMax"] * pip and (best is None or dd < best[0]):
                    best = (dd, F["p"], f"{TFN[k]} {kind_short(F['kd'], F['r'])}")
        return None if best is None else (best[1], best[2])

    def allowed(self, kind, L, at):
        """رسالة واحدة لكل مرحلة لكل مستوى (ولو تكرر على أكثر من فريم): رفض ← إعادة اختبار، ولا إعادة اختبار قبل رفض."""
        P = self.P; sent = self.S.setdefault("sent", [])
        stage = "ret" if kind in ("ret", "retE") else "rej"
        tol = P["mergeGap"] * P["pipSize"]; hh = P["dedupeH"] * 3600
        self.S["sent"] = sent = [m for m in sent if at - m["t"] < 12 * 3600]
        near = [m for m in sent if m["r"] == L["r"] and abs(m["p"] - L["p"]) <= tol]
        if any(m["stage"] == stage and at - m["t"] < hh for m in near):
            return False
        if stage == "ret" and not any(m["stage"] == "rej" for m in near):
            return False
        sent.append(dict(r=L["r"], p=L["p"], stage=stage, t=at))
        return True

    def make_event(self, kind, g, L, at, cur, live=False):
        z = self.zone(L)
        return dict(kind=kind, p=L["p"], role=L["r"], tag=self.cluster_tag(g, L), g=g, cf=TFN[g], cur=cur, x=L.get("ux", 0), w=L.get("uw"), c=L.get("uq"),
                    zone=z, mid=(None if z is None else (z[0] + z[1]) / 2), refine=self.refine_of(g, L, cur), at=at, fake=bool(L.get("um")), af=L.get("af"), live=live)

    # ───────────── معالجة شمعة شارت 5د مغلقة ─────────────
    def step(self, bar):
        S = self.S; T = int(bar["time"]); end = T + 300; cur = bar["close"]
        for g, kind, snap, c in self.feed_until(end):
            if not self.live or g > self.P["msgMaxG"] or not self.P["tfOn"][g]:
                continue
            at = c["end"]
            if kind == "ret":
                # إعادة الاختبار أُرسلت لحظياً (السعر الحي لمس المستوى) أو مسجَّلة: لا تُكرَّر
                pass
            if self.allowed(kind, snap, at):
                self.events.append(self.make_event(kind, g, snap, at, cur))
        S["bi"] += 1; S["last"] = T

    # ───────────── لحظي: السعر الحي ─────────────
    def fast(self, cur, now):
        """بعد رفض مؤكَّد: حين يلمس السعر الحي المستوى مجدداً (إعادة اختبار) نرسل فوراً بلا انتظار إغلاق الشمعة."""
        P = self.P; pip = P["pipSize"]; out = []
        if not P["touchLive"]:
            return out
        tol = P["retTolPts"] * pip
        for g in range(P["msgMaxG"] + 1):
            if not P["tfOn"][g]:
                continue
            for L in self.E[g].lv:
                if L["us"] == 2 and not L["e3"] and L["un"] < P["retestC"] + 1:
                    sup = L["r"] == 1; p = L["p"]
                    if (sup and p - 2 * tol <= cur <= p + tol) or ((not sup) and p - tol <= cur <= p + 2 * tol):
                        L["e3"] = 1
                        if self.allowed("retE", L, now):
                            out.append(self.make_event("retE", g, L, now, cur, live=True))
        return out

    # ───────────── المستويات الطازجة (للقطة وتنبيهات القرب) ─────────────
    def select(self, g, cur, T):
        """أقرب مستويات طازجة (us==0) فوق السعر وتحته لفريم g؛ T=None يعني تجاهل شرط «لُمس بالشمعة الحالية»."""
        P = self.P; pip = P["pipSize"]; E = self.E[g]; out = []
        kon = {1: P["kClassic"], 2: P["kGap"], 3: P["kFlip"], 4: P["kQML"]}
        lo = hi = None
        if T is not None:
            lo, hi = self.forming_extremes(g, T, cur)
        for side in (0, 1):
            used = set()
            for _ in range(P["nPer"]):
                best = -1; bd = 0.0
                for i, L in enumerate(E.lv):
                    if i in used or L["us"] != 0 or L["pd"] != 0 or E.n - L["ob"] < P["minAge"] or not kon[L["kd"]]:
                        continue
                    if L["ac"] + L["br"] + (1 if L["lq"] > 0 else 0) < P["minStars"]:
                        continue
                    if lo is not None and ((lo <= L["p"]) if L["r"] == 1 else (hi >= L["p"])):
                        continue
                    d = L["p"] - cur
                    if (d > 0) if side == 0 else (d < 0):
                        ad = abs(d)
                        if best == -1 or ad < bd:
                            best, bd = i, ad
                if best >= 0:
                    used.add(best); L = E.lv[best]
                    out.append(dict(p=L["p"], r=L["r"], kd=L["kd"], ts=min(L["ts"], 9), ac=L["ac"], br=L["br"], lq=L["lq"], hl=int(min(round(L["wt"] / pip), 999)),
                                    af=L["af"], o=(L["tm"] if L["kd"] >= 3 else L["og"])))
        return out

    def shown(self, cur, now=None):
        P = self.P; pip = P["pipSize"]; T = int(now or 0) or (self.S["last"] + 300)
        cl = []
        for g in range(6):
            if not P["tfOn"][g]:
                continue
            for L in self.select(g, cur, T):
                p = L["p"]; r = L["r"]
                near = P["maxDist"] <= 0 or abs(cur - p) / pip <= P["maxDist"]
                wrong = (p > cur) if r == 1 else (p < cur)
                if not near or (P["chkHide"] and wrong):
                    continue
                hit = next((c for c in cl if abs(c["price"] - p) <= P["mergeGap"] * pip and (c["role"] == "support") == (r == 1)), None)
                if hit:
                    hit["tags"].append(TFN[g])
                else:
                    w = ("A" if L["ac"] else "") + ("B" if L["br"] else "") + ("L" if L["lq"] > 0 else "")
                    cl.append(dict(price=p, role="support" if r == 1 else "resistance", tags=[TFN[g]], kd=L["kd"], kind=kind_name(L["kd"], r),
                                   marks=("★" * len(w)), why=w, hl=L["hl"], stars=len(w), tests=L["ts"], af=L["af"], tf=g))
        if P["confOnly"]:
            cl = [c for c in cl if len(c["tags"]) > 1]
        cl.sort(key=lambda c: abs(c["price"] - cur))
        if P["maxPerSide"] > 0:
            keep = []
            for role in ("support", "resistance"):
                keep += [c for c in cl if c["role"] == role][:P["maxPerSide"]]
            cl = sorted(keep, key=lambda c: abs(c["price"] - cur))
        return cl
