# -*- coding: utf-8 -*-
"""
تتبّع صفقات SH المُرسلة. المشكلة التي يحلّها: المحرك يُعاد حسابه كل دقيقة على بيانات قد تتغيّر قليلاً (إعادة رسم)، فكان يولّد «صفقة مختلفة»
برسائل جديدة (نقل وقف/هدف/إغلاق) بأسعار دخول مغايرة لصفقة لم تُرسَل إشارتها أصلاً.
الآن: عند إرسال إشارة تُثبَّت أرقامها (دخول/وقف/أهداف) في الحالة، ثم تُتابَع بالشموع نفسها بنفس منطق المحرك حرفياً، ولا يُرسل شيء عن صفقة غير مسجَّلة.
"""

DEDUP_SEC = 1800          # إشارة بنفس الاتجاه خلال 30 دقيقة من إشارة مرسلة = نفس الصفقة (تغيّر طفيف في البيانات)


def history_from_sent(sent):
    """يبني قائمة (وقت الإشارة، الاتجاه) من مفاتيح الإرسال القديمة sh|signal|sig_time|dir|bar_time."""
    out = []
    for k in sent:
        p = k.split("|")
        if len(p) >= 5 and p[1] == "signal":
            try:
                out.append((int(p[2]), int(p[3])))
            except ValueError:
                pass
    return out


def is_duplicate(sigs, active, trade):
    st, d = int(trade["sig_time"]), int(trade["dir"])
    if any(r["dir"] == d and abs(int(r["sig_time"]) - st) <= DEDUP_SEC for r in active):
        return True
    return any(dd == d and abs(t - st) <= DEDUP_SEC for t, dd in sigs)


def register(trades, sigs, ev):
    """يسجّل صفقة من حدث «signal» بعد نجاح إرسال رسالته."""
    tr = dict(ev["trade"])
    tr.update(sl=tr["sl0"], tp1done=False, be=False, realR=0.0, rem=1.0, last=int(ev["bar_time"]), done=False,
              tbar_time=int(ev["bar_time"]), fill_time=(None if tr.get("pending") else int(ev["bar_time"])), queue=[])
    trades.append(tr)
    sigs.append((int(tr["sig_time"]), int(tr["dir"])))
    return tr


def snap(tr):
    return {k: v for k, v in tr.items() if k not in ("queue",)}


def advance(tr, bars, P):
    """يعالج الشموع المكتملة بعد آخر شمعة معالَجة، ويعيد أحداثاً [dict(kind, bar_time, trade, result?, R?, reason?)] بنفس منطق sh_engine."""
    out = []
    d = tr["dir"]; rr = tr["rr"]; usePart = tr["usePart"]
    for b in bars:
        t = int(b["time"])
        if t <= tr["last"] or tr["done"]:
            continue
        tr["last"] = t
        hi, lo, op = b["high"], b["low"], b["open"]
        if tr["pending"]:
            filled = (lo <= tr["entry"]) if d == 1 else (hi >= tr["entry"])
            tpFirst = (hi >= tr["tp"]) if d == 1 else (lo <= tr["tp"])
            if filled:
                tr["pending"] = False; tr["fill_time"] = t
                out.append(dict(kind="fill", bar_time=t, trade=snap(tr)))
            elif (t - tr["tbar_time"]) // 300 >= tr["retestBars"] or tpFirst:
                out.append(dict(kind="cancel", bar_time=t, trade=snap(tr),
                                reason="وصل السعر للهدف دون أن يلمس الأمر" if tpFirst else "انتهت مدة الأمر المعلق دون لمسه"))
                tr["done"] = True
                break
        if not tr["pending"]:
            after = t > tr["fill_time"]
            hitSL = (lo <= tr["sl"]) if d == 1 else (hi >= tr["sl"])
            hitTP1 = after and usePart and not tr["tp1done"] and ((hi >= tr["tp1"]) if d == 1 else (lo <= tr["tp1"]))
            hitTP = after and ((hi >= tr["tp"]) if d == 1 else (lo <= tr["tp"]))
            res = None; R = 0.0
            if hitSL:
                ex = min(tr["sl"], op) if d == 1 else max(tr["sl"], op)
                Rrem = (ex - tr["entry"]) * d / tr["risk"]
                R = tr["realR"] + tr["rem"] * Rrem
                if tr["tp1done"]:
                    res = "TP1+BE" if Rrem >= -0.05 else "TP1+SL"
                else:
                    res = "BE" if R >= -0.05 else "SL"
            else:
                if hitTP1:
                    tr["tp1done"] = True; tr["realR"] = tr["tp1Pct"] / 100 * tr["tp1R"]; tr["rem"] = 1 - tr["tp1Pct"] / 100
                    tr["be"] = True; tr["sl"] = tr["entry"]
                    out.append(dict(kind="tp1", bar_time=t, trade=snap(tr)))
                if hitTP:
                    R = tr["realR"] + tr["rem"] * rr; res = "TP2" if usePart else "TP"
            if res:
                out.append(dict(kind="closed", bar_time=t, trade=snap(tr), result=res, R=R))
                tr["done"] = True
                break
            elif P["useBE"] and not tr["be"] and ((hi >= tr["entry"] + P["beAtR"] * tr["risk"]) if d == 1 else (lo <= tr["entry"] - P["beAtR"] * tr["risk"])):
                tr["be"] = True; tr["sl"] = tr["entry"]
                out.append(dict(kind="breakeven", bar_time=t, trade=snap(tr)))
    return out
