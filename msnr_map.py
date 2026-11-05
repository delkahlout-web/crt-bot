# -*- coding: utf-8 -*-
"""
خريطة المناطق (MSNR Levels Classic — «Level map»): أقوى المستويات على أي بُعد عن السعر، لا الأقرب فقط.
  • محرّك المؤشر الكلاسيكي (Eng3) بعمق 1500 شمعة لكل فريم وحتى 300 مستوى، يختار لكل فريم أقوى 5 فوق السعر وتحته (النجوم أولاً ثم القرب).
  • دمج المتقارب (≤ mergeGap) وترتيب عالمي: نجوم + تقاطع فريمات + رتبة الفريم، ثم القرب، وأعلى mapCount لكل جهة.
  • يُستخدم لرسالة «خريطة المناطق» (عند فتح كل جلسة 4H، وبالأمر /map).
"""
import msnr_v3 as V3

TFN = ["W", "D", "4H", "1H", "30M"]
RANK = [4, 3, 2, 1, 0]
PM = {**V3.DEF, "maxLv": 300, "nPer": 5, "minStars": 1, "mapCount": 6, "histDepth": 1500, "tsOnly": False, "erlIrl": True, "erlIrlTf": 4, "swingLen": 5, "fvgMin": 15.0}


class LevelMap:
    def __init__(self, P=None):
        self.P = {**PM, **(P or {})}
        self.E = [V3.Eng3() for _ in range(5)]
        self.cl = [[] for _ in range(5)]; self.ptr = [0] * 5; self.fed = [0] * 5

    def set_candles(self, cl):
        self.cl = [list(x) for x in cl[:5]]
        for k in range(5):
            lst = self.cl[k]; i = 0
            while i < len(lst) and lst[i]["time"] <= self.fed[k]:
                i += 1
            self.ptr[k] = i

    def feed_until(self, T):
        depth = self.P["histDepth"]
        for k in range(5):
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
                self.E[k].feed(c, self.P); self.fed[k] = c["time"]

    def levels(self, cur, forming):
        """forming(g) -> (low, high) للشمعة المتكوّنة الحالية للفريم g. يعيد قائمة مستويات مرتّبة بالقوة: {support:[...], resistance:[...]}."""
        P = self.P; pip = P["pipSize"]
        kon = {1: P["kClassic"], 2: P["kGap"], 3: P["kFlip"], 4: P["kQML"]}
        cl = []
        for g in range(5):
            if not P["tfOn"][g]:
                continue
            lo, hi = forming(g)
            for L in self.E[g].select(cur, P, kf=False, by_str=True):
                p = L["p"]; r = L["r"]
                used0 = lo is not None and ((lo <= p) if r == 1 else (hi >= p))
                wrong = (p > cur) if r == 1 else (p < cur)
                if not kon[L["kd"]] or used0 or (P["chkHide"] and wrong) or (P["tsOnly"] and L["kd"] == 1 and not L.get("vl")):
                    continue
                hit = next((c for c in cl if abs(c["price"] - p) <= P["mergeGap"] * pip and (c["role"] == "support") == (r == 1)), None)
                if hit:
                    hit["tags"].append(TFN[g])
                else:
                    why = ("A" if L["ac"] else "") + ("B" if L["br"] else "") + ("L" if L["lq"] > 0 else "")
                    cl.append(dict(price=p, role="support" if r == 1 else "resistance", tags=[TFN[g]], kd=L["kd"], kind=_kind(L["kd"], r), why=why,
                                   hl=L["hl"], af=0, rank=RANK[g], tests=L["ts"], vl=L.get("vl", 0)))
        for c in cl:
            c["key"] = len(c["why"]) * 10 + (5 if len(c["tags"]) > 1 else 0) + c["rank"]
        out = {}
        for role in ("support", "resistance"):
            side = [c for c in cl if c["role"] == role]
            side.sort(key=lambda c: (-c["key"], abs(c["price"] - cur)))
            out[role] = side[:P["mapCount"]]
        if P.get("erlIrl"):
            try:
                out.update(self.erl_irl(cur))
            except Exception:
                pass
        return out

    def erl_irl(self, cur):
        """ERL = أقرب قمة/قاع خارجي لم يُكسر · IRL = أقرب فجوة قيمة عادلة (FVG) لم تُملأ، على فريم العرض (30M افتراضيًا) كما في المؤشر."""
        P = self.P; pip = P["pipSize"]; Ln = int(P["swingLen"]); gmin = P["fvgMin"] * pip; g = int(P["erlIrlTf"])
        bars = self.cl[g][:self.ptr[g]][-700:]; n = len(bars)
        out = dict(erl=dict(up=None, dn=None), irl=dict(up=None, dn=None))
        if n < 2 * Ln + 3:
            return out
        hs = [b["high"] for b in bars]; ls = [b["low"] for b in bars]
        sufmax = [0.0] * (n + 1); sufmin = [1e18] * (n + 1)
        for i in range(n - 1, -1, -1):
            sufmax[i] = max(hs[i], sufmax[i + 1]); sufmin[i] = min(ls[i], sufmin[i + 1])
        lv = []
        for i in range(Ln, n - Ln):
            if hs[i] >= max(hs[i - Ln:i + Ln + 1]) and hs[i] > max(hs[i - Ln:i]) and sufmax[i + 1] <= hs[i]:
                lv.append(hs[i])
            if ls[i] <= min(ls[i - Ln:i + Ln + 1]) and ls[i] < min(ls[i - Ln:i]) and sufmin[i + 1] >= ls[i]:
                lv.append(ls[i])
        ups = [p for p in lv if p > cur]; dns = [p for p in lv if p < cur]
        out["erl"]["up"] = min(ups) if ups else None; out["erl"]["dn"] = max(dns) if dns else None
        fv = []
        for j in range(2, n):
            if bars[j]["low"] > bars[j - 2]["high"] and bars[j]["low"] - bars[j - 2]["high"] >= gmin:
                fv.append((j, 1, bars[j - 2]["high"], bars[j]["low"]))
            if bars[j]["high"] < bars[j - 2]["low"] and bars[j - 2]["low"] - bars[j]["high"] >= gmin:
                fv.append((j, -1, bars[j]["high"], bars[j - 2]["low"]))
        alive = []
        for j, t, bot, top in fv:
            later = bars[j + 1:]
            if (t == 1 and any(b["close"] < bot for b in later)) or (t == -1 and any(b["close"] > top for b in later)):
                continue
            alive.append((bot, top))
        alive = alive[-60:]
        up = [z for z in alive if z[0] > cur]; dn = [z for z in alive if z[1] < cur]
        out["irl"]["up"] = min(up, key=lambda z: z[0] - cur) if up else None
        out["irl"]["dn"] = min(dn, key=lambda z: cur - z[1]) if dn else None
        return out


def _kind(kd, role):
    return "Classic V" if kd == 1 and role == 1 else "Classic A" if kd == 1 else "OC" if kd == 2 else ("RBS" if role == 1 else "SBR") if kd == 3 else "QML"
