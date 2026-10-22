# -*- coding: utf-8 -*-
"""
MSNR Key Levels — ترجمة حرفية لمؤشر TradingView «MSNR Key Levels» إلى بايثون.
كل فريم (W / D / 4H / 1H) يُعالَج بنفس دالة eng() خطوة بخطوة على الشموع المكتملة (الشمعة الحالية المتكوّنة تُستعمل لسعر الإغلاق الحالي فقط)،
ثم collect() يجمع المستويات ويدمج المتقاربة ويستبعد المستخدَم. الأسعار بالدولار؛ pipSize=0.1 يعني أن «النقطة» = 0.1$.
"""
import datetime as dt
import math
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
NAN = float("nan")

DEFAULTS = dict(
    tfs={"W": True, "D": True, "4H": True, "1H": True, "30M": True, "15M": False}, story=True, confOnly=False,
    classicMode=0,                        # 0 = Line chart pivot، 1 = Strict
    kClassic=True, kGap=False, kFlip=True, kQML=True, breakCl=2,
    minStars=1, liqPips=30.0, keepT=False,
    nPer=1, mergeGap=20.0, minAge=0, maxDist=500.0, pipSize=0.1,
)
RANK = {"W": 4, "D": 3, "4H": 2, "1H": 1, "30M": 0, "15M": 0}


def isnan(x):
    return x is None or (isinstance(x, float) and math.isnan(x))


# ───────────────────────── تجميع الفريمات من شموع الساعة (حدود اليوم 17:00 نيويورك كـ OANDA) ─────────────────────────
def _key(t, tf):
    """مفتاح الشمعة الكبيرة لشمعة ساعة تبدأ عند t (epoch UTC)."""
    loc = dt.datetime.fromtimestamp(t, dt.timezone.utc).astimezone(NY).replace(tzinfo=None) + dt.timedelta(hours=7)   # 17:00 نيويورك = 00:00
    if tf == "1H":
        return t
    if tf == "4H":
        return loc.replace(hour=loc.hour // 4 * 4, minute=0, second=0, microsecond=0)
    if tf == "D":
        return loc.date()
    if tf == "W":
        back = (loc.weekday() + 1) % 7                      # الأسبوع يبدأ الأحد 17:00 نيويورك
        return (loc - dt.timedelta(days=back)).date()
    raise ValueError(tf)


def aggregate(h1, tf):
    """h1: شموع ساعة مرتبة [dict(time, open, high, low, close)] ← شموع tf (time = وقت فتح أول ساعة فيها)."""
    if tf == "1H":
        return [dict(b) for b in h1]
    out = []; cur = None; ck = None
    for b in h1:
        k = _key(b["time"], tf)
        if k != ck:
            if cur: out.append(cur)
            cur = dict(time=b["time"], open=b["open"], high=b["high"], low=b["low"], close=b["close"]); ck = k
        else:
            cur["high"] = max(cur["high"], b["high"]); cur["low"] = min(cur["low"], b["low"]); cur["close"] = b["close"]
    if cur: out.append(cur)
    return out


# ───────────────────────── المحرك eng() ─────────────────────────
def eng(bars, cur, P):
    """bars: شموع الفريم المكتملة (الأخيرة قد تكون الشمعة المتكوّنة حالياً وتُعامل كشمعة متكوّنة).
    ترجع {"above": [...], "below": [...]} مستويات مختارة، كل مستوى dict(p, role, kd, tc, stc, origin)."""
    P = {**DEFAULTS, **P}
    pipS = P["pipSize"]; liq = P["liqPips"]; keepI = 1 if P["keepT"] else 0; cMode = P["classicMode"]; cfm = int(P["breakCl"])
    lv = []                               # كل مستوى: p r kd tm bk og ob ts pd lb ac op br lq
    lastSH = lastSL = NAN
    N = len(bars)
    for b in range(0, N + 1):             # b == N ← الشمعة المتكوّنة (لا نملك أرقامها؛ نستعمل cur كإغلاق)
        def g(k, f):
            j = b - k
            return bars[j][f] if 0 <= j < N else NAN
        o1, h1, l1, c1, t1 = g(1, "open"), g(1, "high"), g(1, "low"), g(1, "close"), g(1, "time")
        o2, h2, l2, c2, t2 = g(2, "open"), g(2, "high"), g(2, "low"), g(2, "close"), g(2, "time")
        o3, h3, l3, c3, t3 = g(3, "open"), g(3, "high"), g(3, "low"), g(3, "close"), g(3, "time")
        c4, c5 = g(4, "close"), g(5, "close")

        # (1) تحديث المستويات الحالية بالشمعة [1]
        if lv and not isnan(c1):
            for i in range(len(lv) - 1, -1, -1):
                L = lv[i]; p = L["p"]; r = L["r"]; gone = False
                if t1 > L["tm"] and L["lb"] < t1:
                    L["lb"] = t1
                    beyond = (c1 < p) if r == 1 else (c1 > p)
                    nb = L["bk"]
                    if L["pd"] == 1:
                        L["pd"] = 0
                        if beyond:
                            if nb < 2:
                                L["r"] = -r; L["kd"] = 3 if nb == 0 else 4; L["bk"] = nb + 1; L["tm"] = t1
                                L["ts"] = 0; L["ac"] = 1; L["br"] = 1; L["lq"] = 0; L["wt"] = 0
                            else:
                                gone = True
                        elif keepI == 0:
                            gone = True
                        else:
                            L["ts"] += 1
                    else:
                        touched = (l1 <= p) if r == 1 else (h1 >= p)
                        if touched:
                            if beyond and cfm == 1:                       # إغلاق واحد يكفي للكسر
                                if nb < 2:
                                    L["r"] = -r; L["kd"] = 3 if nb == 0 else 4; L["bk"] = nb + 1; L["tm"] = t1
                                    L["ts"] = 0; L["ac"] = 1; L["br"] = 1; L["lq"] = 0; L["wt"] = 0
                                else:
                                    gone = True
                            elif beyond:
                                L["pd"] = 1
                            elif keepI == 0:
                                gone = True
                            else:
                                L["ts"] += 1
                        else:
                            nearFail = (l1 > p and l1 - p <= liq * pipS) if r == 1 else (h1 < p and p - h1 <= liq * pipS)
                            if nearFail:
                                L["lq"] += 1
                                dw = (l1 - p) if r == 1 else (p - h1)            # بُعد الذيل عن المستوى (السيولة المخفية)
                                L["wt"] = dw if L["wt"] == 0 else min(L["wt"], dw)
                            ox = L["op"]
                            if L["br"] == 0 and not isnan(ox) and ((c1 > ox) if r == 1 else (c1 < ox)):
                                L["br"] = 1
                if gone:
                    del lv[i]

        # (2) آخر قمة/قاع (إغلاقات)
        if not isnan(c5):
            if c3 > c4 and c3 > c5 and c3 > c2 and c3 > c1:
                lastSH = c3
            if c3 < c4 and c3 < c5 and c3 < c2 and c3 < c1:
                lastSL = c3

        # (3) اكتشاف مستوى جديد
        lp = NAN; role = 0; kind = 0; ot = NAN
        if not isnan(c3):
            if cMode == 0:
                cA = c2 > c3 and c2 > c1
                cV = c2 < c3 and c2 < c1
            else:
                cA = c2 > o2 and c1 < o1 and l1 < l2
                cV = c2 < o2 and c1 > o1 and h1 > h2
            if cA:
                lp, role, kind, ot = c2, -1, 1, t2
            elif cV:
                lp, role, kind, ot = c2, 1, 1, t2
            elif c2 > o2 and c1 > o1:
                lp, role, kind, ot = c2, 1, 2, t2
            elif c2 < o2 and c1 < o1:
                lp, role, kind, ot = c2, -1, 2, t2
        if not isnan(lp):
            dup = False; act = False
            tolA = 10 * pipS; lo = min(l1, l2); hi = max(h1, h2)
            for L in lv:
                if L["r"] == role and abs(L["p"] - lp) <= pipS:
                    dup = True
                if L["tm"] < t2 and ((L["p"] >= lo - tolA and L["p"] <= lp + tolA) if role == 1 else (L["p"] <= hi + tolA and L["p"] >= lp - tolA)):
                    act = True
            if not dup:
                oppP = NAN
                if role == 1:
                    if not isnan(lastSH) and lastSH > c1:
                        oppP = lastSH
                else:
                    if not isnan(lastSL) and lastSL < c1:
                        oppP = lastSL
                lv.append(dict(p=lp, r=role, kd=kind, tm=t1, bk=0, og=ot, ob=b, ts=0, pd=0, lb=0, ac=1 if act else 0, op=oppP, br=0, lq=0, wt=0))
                if len(lv) > 60:
                    lv.pop(0)

    # (4) الاختيار عند السعر الحالي: الأقرب فوق السعر وتحته (حتى 5 لكل جهة، ونأخذ nPer)
    res = {"above": [], "below": []}
    for side, key in ((0, "above"), (1, "below")):
        used = set()
        for k in range(5):
            best = -1; bd = 0.0
            for i, L in enumerate(lv):
                if i in used or L["pd"] != 0 or N - L["ob"] < P["minAge"]:
                    continue
                stars = L["ac"] + L["br"] + (1 if L["lq"] > 0 else 0)
                if stars < P["minStars"]:
                    continue
                d = L["p"] - cur
                if (d > 0) if side == 0 else (d < 0):
                    ad = abs(d)
                    if best == -1 or ad < bd:
                        best, bd = i, ad
            if best >= 0:
                used.add(best); L = lv[best]
                stB = L["ac"] + L["br"] + (1 if L["lq"] > 0 else 0)
                res[key].append(dict(p=L["p"], role=L["r"], kd=L["kd"], tc=min(L["ts"], 9), stc=stB, origin=L["og"], hl=int(min(round(L["wt"] / pipS), 999))))
    return res


def story(bars4h, cur):
    """خط «Story»: اتجاه 4H من آخر قمتين وقاعين (إغلاقات، pivot 2/2) ومستوى القرار."""
    c = [b["close"] for b in bars4h] + [cur]
    hA = hB = lA = lB = NAN; tr = 0
    for i in range(len(c)):
        j = i - 2                                                      # الشمعة المرشّحة للقمة/القاع، تتأكد بعد شمعتين
        if j >= 2:
            if c[j] > max(c[j - 2:j]) and c[j] > max(c[j + 1:j + 3]):
                hB, hA = hA, c[j]
            if c[j] < min(c[j - 2:j]) and c[j] < min(c[j + 1:j + 3]):
                lB, lA = lA, c[j]
        if not isnan(hB) and not isnan(lB):
            if hA > hB and lA > lB:
                tr = 1
            elif hA < hB and lA < lB:
                tr = -1
    dec = lA if tr == 1 else hA if tr == -1 else NAN
    return tr, dec


# ───────────────────────── collect(): من كل الفريمات إلى قائمة مستويات نهائية ─────────────────────────
KIND = {1: ("Classic V", "Classic A"), 2: ("OC", "OC"), 3: ("RBS", "SBR"), 4: ("QML", "QML")}


def kind_on(kd, P):
    return {1: P["kClassic"], 2: P["kGap"], 3: P["kFlip"], 4: P["kQML"]}[kd]


def htf_open(t_now, tf):
    """وقت فتح الشمعة الكبيرة الحالية (epoch UTC) = أول ساعة تنتمي لنفس مفتاح الشمعة."""
    if tf == "30M":
        return int(t_now) // 1800 * 1800
    if tf == "15M":
        return int(t_now) // 900 * 900
    h = int(t_now) // 3600 * 3600
    k = _key(h, tf)
    while _key(h - 3600, tf) == k:
        h -= 3600
    return h


def collect(stores, chart5, cur, t_now, P):
    """stores: dict(h1=[...], m30=[...], m15=[...]) أو قائمة شموع ساعة فقط؛ chart5: شموع الشارت 5 دقائق (للتحقق من «المستخدَم»).
    ترجع قائمة مستويات مرتبة بالقرب: dict(price, role('support'|'resistance'), tags, kind, stars, tests, hl)."""
    P = {**DEFAULTS, **P}
    if isinstance(stores, list):
        stores = dict(h1=stores)
    h1 = stores.get("h1") or []
    cl = []; pipS = P["pipSize"]
    for tf in ("W", "D", "4H", "1H", "30M", "15M"):
        if not P["tfs"].get(tf, False):
            continue
        if tf == "30M":
            bars = list(stores.get("m30") or [])
        elif tf == "15M":
            bars = list(stores.get("m15") or [])
        else:
            bars = aggregate(h1, tf)
        if not bars:
            continue
        t0 = htf_open(t_now, tf)
        if bars and bars[-1]["time"] >= t0:                    # الشمعة الحالية المتكوّنة ليست «مكتملة» للمحرك
            bars = bars[:-1]
        sel = eng(bars, cur, P)
        recent = [b for b in chart5 if b["time"] >= t0]
        for key in ("above", "below"):
            for s, L in enumerate(sel[key][:P["nPer"]]):
                p = L["p"]; role = L["role"]
                if kind_on(L["kd"], P) and (P["maxDist"] <= 0 or abs(cur - p) / pipS <= P["maxDist"]):
                    used0 = any((b["low"] <= p) if role == 1 else (b["high"] >= p) for b in recent) or ((cur <= p) if role == 1 else (cur >= p))
                    if used0:
                        continue
                    hit = next((c for c in cl if abs(c["price"] - p) <= P["mergeGap"] * pipS), None)
                    if hit:
                        hit["tags"].append(tf)
                    else:
                        cl.append(dict(price=p, role="support" if role == 1 else "resistance", tags=[tf], kind=KIND[L["kd"]][0 if role == 1 else 1],
                                       kd=L["kd"], stars=L["stc"], tests=L["tc"], rank=RANK[tf], hl=L["hl"]))
    if P["story"]:
        b4 = aggregate(h1, "4H")
        if b4 and b4[-1]["time"] >= htf_open(t_now, "4H"):
            b4 = b4[:-1]
        tr, dec = story(b4, cur)
        if tr != 0 and not isnan(dec) and (P["maxDist"] <= 0 or abs(cur - dec) / pipS <= P["maxDist"]):
            cl.append(dict(price=dec, role="support" if dec < cur else "resistance", tags=["Story"], kind="Story " + ("Up" if tr == 1 else "Down") + " decision",
                           kd=0, stars=0, tests=0, rank=0, hl=0))
    if P["confOnly"]:
        cl = [c for c in cl if len(c["tags"]) > 1 or c["tags"] == ["Story"]]
    cl.sort(key=lambda c: abs(c["price"] - cur))
    return cl
