# -*- coding: utf-8 -*-
"""
MSNR Session Plan — ترجمة لقسم «Session plan (signals)» في مؤشر MSNR v2 Signals، مع الإعدادات الأفضل بعد الاختبار على 10 أشهر (5 فترات متتالية كلها رابحة):
  • عند فتح شمعة 4H (الساعات 3,7,11,15,19 بتوقيت GMT+3) تُفتح نافذة 240 دقيقة.
  • داخل النافذة: أقرب مستوى 30M (3 نجوم) يلمسه السعر ثم تُغلق الشمعة في الجهة الصحيحة (إغلاق رفض) ← دخول بسعر الإغلاق.
  • وقف 60 نقطة (6$) وهدف 120 نقطة (12$) — صفقة واحدة لكل نافذة.
المحرّك المستعمل للمستويات: Eng3 (محرّك B2 v2 بلا مرشّح النوع، كما في المؤشر).
"""
import datetime as dt

import msnr_pro as MP
import msnr_v3 as V3

DEFP = dict(sessH=[3, 7, 11, 15, 19], dirMode="both", planTf="30M", entry="rej", slPts=60.0, tpPts=120.0, tol=1.0, minDelay=0,
            winMin=240, planStars=3, planFresh=True, revOn=False, revDelay=30, pipSize=0.1, tzOff=3)
TFNAME = {3: "1H", 4: "30M"}


def fresh_state():
    return dict(last=0, hr=-1, st=0, dir=0, win=0, cnt=0, slT=0, en=None, sl=None, tp=None, d0=0, ebar=0, tid=0, w=0, l=0, tag="", lv=None, bi=0, muted=False, et=0)


class Plan:
    def __init__(self, P=None, S=None):
        self.P = {**DEFP, **(P or {})}
        self.P3 = {**V3.DEF, "nPer": 2, "minStars": 1, "pipSize": self.P["pipSize"]}
        self.S = S if S else fresh_state()
        for k, v in fresh_state().items():
            self.S.setdefault(k, v)
        self.E = {3: V3.Eng3(), 4: V3.Eng3()}
        self.cl = {3: [], 4: []}; self.ptr = {3: 0, 4: 0}; self.fed = {3: 0, 4: 0}
        self.c4end = {}; self.chart5 = []
        self.events = []; self.live = True

    def dump(self):
        return dict(fed=dict(self.fed), E={str(k): dict(lv=e.lv, hist=e.hist, n=e.n, sh=e.lastSH, sl=e.lastSL) for k, e in self.E.items()})

    def restore(self, d):
        try:
            if not d:
                return False
            for k, e in self.E.items():
                x = d["E"][str(k)]
                e.lv = x["lv"]; e.hist = x["hist"]; e.n = x["n"]; e.lastSH = x["sh"]; e.lastSL = x["sl"]
            self.fed = {int(k): v for k, v in d["fed"].items()}
            return True
        except Exception:
            return False

    def set_candles(self, cl3, cl4, cl4h, chart5):
        self.cl = {3: cl3, 4: cl4}
        for k in (3, 4):
            lst = self.cl[k]; i = 0
            while i < len(lst) and lst[i]["time"] <= self.fed[k]:
                i += 1
            self.ptr[k] = i
        self.c4end = {c["end"]: c for c in cl4h}
        self.chart5 = chart5

    def feed_until(self, T):
        for k in (3, 4):
            lst = self.cl[k]
            while self.ptr[k] < len(lst):
                c = lst[self.ptr[k]]
                if c["end"] > T:
                    break
                self.ptr[k] += 1
                self.E[k].feed(c, self.P3); self.fed[k] = c["time"]

    def warm(self, T):
        self.feed_until(T)

    def hour(self, T):
        return (dt.datetime.fromtimestamp(T, dt.timezone.utc) + dt.timedelta(hours=self.P["tzOff"])).hour

    def levels(self, cur):
        P = self.P; out = []
        for k in (3, 4):
            if (P["planTf"] == "30M" and k != 4) or (P["planTf"] == "1H" and k != 3):
                continue
            for x in self.E[k].select(cur, self.P3, kf=False):
                out.append((k, x))
        return out

    def step(self, bar):
        S = self.S; P = self.P; pip = P["pipSize"]
        T = int(bar["time"]); self.feed_until(T)
        S["bi"] += 1; bi = S["bi"]
        hr = self.hour(T); new_hour = S["hr"] != -1 and hr != S["hr"]; S["hr"] = hr
        if new_hour and S["st"] != 2 and hr in P["sessH"]:
            p4 = self.c4end.get(MP.bucket(T, "4H")[0])
            ok = P["dirMode"] == "both" or (p4 is not None and p4["close"] != p4["open"])
            S["st"] = 1 if ok else 0; S["win"] = T; S["cnt"] = 0
            S["dir"] = 0 if P["dirMode"] == "both" else ((1 if p4["close"] > p4["open"] else -1) if p4 else 0)
        if S["st"] == 1:
            if T >= S["win"] + P["winMin"] * 60:
                S["st"] = 0
            elif T >= S["win"] + P["minDelay"] * 60:
                sel = self.levels(bar["close"])
                for d in (1, -1):
                    if S["st"] == 1 and (S["dir"] == 0 or S["dir"] == d):
                        best = None
                        for k, x in sel:
                            if x["r"] == d and ((x["p"] < bar["open"]) if d == 1 else (x["p"] > bar["open"])):
                                if best is None or ((x["p"] > best[0]["p"]) if d == 1 else (x["p"] < best[0]["p"])):
                                    best = (x, k)
                        if best and ((not P["planFresh"]) or best[0]["ts"] == 0) and best[0]["stc"] >= P["planStars"]:
                            x, k = best; lv = x["p"]
                            touch = (bar["low"] <= lv + P["tol"] * pip) if d == 1 else (bar["high"] >= lv - P["tol"] * pip)
                            conf = P["entry"] == "touch" or ((bar["close"] > lv) if d == 1 else (bar["close"] < lv))
                            rev_ok = S["cnt"] == 0 or T >= S["slT"] + P["revDelay"] * 60
                            if touch and conf and rev_ok:
                                S["dir"] = d; S["d0"] = d
                                S["en"] = lv if P["entry"] == "touch" else bar["close"]
                                S["sl"] = S["en"] - P["slPts"] * pip if d == 1 else S["en"] + P["slPts"] * pip
                                S["tp"] = S["en"] + P["tpPts"] * pip if d == 1 else S["en"] - P["tpPts"] * pip
                                S["st"] = 2; S["cnt"] += 1; S["ebar"] = bi; S["lv"] = lv
                                S["tag"] = f"{TFNAME[k]} {V3.kind_short(x['kd'], x['r'])} " + "★" * x["stc"]
                                S["tid"] += 1; S["muted"] = not self.live; S["et"] = T + 300
                                if self.live:
                                    self.events.append(dict(kind="plan", tid=S["tid"], dir=d, entry=S["en"], sl=S["sl"], tp=S["tp"], lv=lv, tag=S["tag"],
                                                            at=T + 300, win=S["win"], winMin=P["winMin"], pts_sl=P["slPts"], pts_tp=P["tpPts"], entry_mode=P["entry"]))
        elif S["st"] == 2 and bi > S["ebar"]:
            d = S["d0"]
            hs = (bar["low"] <= S["sl"]) if d == 1 else (bar["high"] >= S["sl"])
            ht = (bar["high"] >= S["tp"]) if d == 1 else (bar["low"] <= S["tp"])
            if hs or ht:
                self.close(ht and not hs, T + 300)
        S["last"] = T

    def close(self, win, at):
        S = self.S; P = self.P
        if win:
            S["w"] += 1
        else:
            S["l"] += 1
        if self.live and not S["muted"]:
            self.events.append(dict(kind="result", tid=S["tid"], dir=S["d0"], entry=S["en"], sl=S["sl"], tp=S["tp"], lv=S["lv"], tag=S["tag"], res="TP" if win else "SL",
                                    pts=P["tpPts"] if win else -P["slPts"], at=at, w=S["w"], l=S["l"]))
        S["st"] = 0; S["slT"] = at

    def fast(self, cur, now):
        """متابعة الصفقة المفتوحة بالسعر الحي: وقف/هدف لحظياً (الأولوية للوقف كالمؤشر)."""
        S = self.S; self.events = []
        if S["st"] == 2 and not S["muted"] and now >= S["et"]:
            d = S["d0"]
            hs = (cur <= S["sl"]) if d == 1 else (cur >= S["sl"])
            ht = (cur >= S["tp"]) if d == 1 else (cur <= S["tp"])
            if hs or ht:
                self.close(ht and not hs, now)
        out = self.events; self.events = []
        return out
