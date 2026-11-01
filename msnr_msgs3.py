# -*- coding: utf-8 -*-
"""رسائل MSNR (عربي، توقيت فلسطين): لمس · رفض مؤكَّد (T1–T4 + منطقة الدخول + قوة المستوى) · إعادة اختبار · صفقة جلسة 4H ونتيجتها."""
import time

from msnr_v4 import TYPE_TXT

LINE = "━━━━━━━━━━━━━━"
BANNER = "🟧 <b>MSNR Levels</b>"
SBANNER = "🟧 <b>MSNR Session</b>"
WHY_TXT = {"A": "A مفعَّل من مستوى سابق", "B": "B كسر آخر نقطة معاكسة", "L": "L سيولة مخفية"}
RANK_TXT = {"W": "أسبوعي (الأقوى)", "D": "يومي", "4H": "4 ساعات", "1H": "ساعة", "30M": "30 دقيقة", "15M": "15 دقيقة"}


def when4(e, tz):
    """وقت الحدث نفسه (إغلاق الشمعة أو لحظة اللمس) لا وقت الإرسال، مع تنبيه إن تأخر الإرسال أكثر من دقيقتين ونصف."""
    from sh_messages import fmt_time
    now = time.time(); at = e.get("at", now)
    late = now - at
    return fmt_time(at, tz) + (f" (أُرسلت متأخرة {int(late // 60)} د)" if late > 150 else "")


def strength(e):
    """سطر قوة المستوى: عدد النجوم وسببها وفريم المستوى."""
    why = e.get("why") or ""
    stars = "★" * len(why) if why else "☆"
    reasons = " · ".join(WHY_TXT[c] for c in why) if why else "بلا نجوم إضافية"
    af = " · ⚡ مفعَّل من مستوى فريش" if e.get("af") else ""
    rk = RANK_TXT.get(e.get("rank", ""), e.get("rank", ""))
    return f"💪 قوة المستوى: {stars} ({reasons}){af} — فريم {rk}"


def v4_text(e, tz, P):
    sup = e["role"] == 1
    icon = "🟢" if sup else "🔴"
    side = "دعم (شراء)" if sup else "مقاومة (بيع)"
    p = e["p"]; cur = e["cur"]; cf = e["cf"]; nxt = e.get("nxt", "")
    base = f"{icon} <b>{e['tag']}</b> @ <b>{p:.2f}</b> — {side}"
    st = strength(e)
    tm = f"🕒 {when4(e, tz)}"
    k = e["kind"]
    if k == "touch":
        return (f"{BANNER}\n⚡ <b>لمس المستوى الآن</b>\n{base}\n📍 السعر الآن: {cur:.2f}\n{st}\n"
                f"<i>ننتظر الرفض: يتأكد بإغلاق شمعة {cf} {'فوق' if sup else 'تحت'} المستوى.</i>\n{tm}")
    if k == "retE":
        return f"{BANNER}\n🔁 <b>إعادة اختبار المستوى الآن</b> (بعد رفض مؤكَّد)\n{base}\n📍 السعر الآن: {cur:.2f}\n{st}\n{tm}"
    if k == "ret":
        return (f"{BANNER}\n✅ <b>إعادة اختبار مؤكَّدة</b> — أُغلقت شمعة {cf} {'فوق' if sup else 'تحت'} المستوى\n{base}\n"
                f"📍 السعر الآن: {cur:.2f}\n{st}\n{tm}")
    x = e.get("x") or 0
    lines = [f"{BANNER}\n✅ <b>رفض مؤكَّد (REJ)</b> — أُغلقت شمعة {cf} {'فوق' if sup else 'تحت'} المستوى", base, f"📍 السعر الآن: {cur:.2f}", st]
    if e.get("fake"):
        lines.append("<i>بعد إغلاق واحد خلف المستوى (كسر وهمي محتمل)</i>")
    if x:
        lines += [LINE, f"🧭 <b>نوع الرفض T{x}</b>: {TYPE_TXT[x]}"]
        z = e.get("zone")
        if z is not None:
            if x == 1:
                lines.append(f"🎯 قمة/قاع الذيل (سحب السيولة): {z[0]:.2f}")
            else:
                lines.append(f"🎯 منطقة الدخول: {z[0]:.2f} – {z[1]:.2f} | 50%: {e['mid']:.2f}")
    if e.get("refine"):
        lines.append(f"⇢ Refine قريب: {e['refine'][0]:.2f} ({e['refine'][1]})")
    if nxt:
        lines.append(f"🔎 التأكيد/الدخول على الفريم الأصغر التالي: {nxt} (مستوى {cf} ← دخول {nxt})")
    lines += [LINE, tm]
    return "\n".join(lines)


def plan_text(e, tz, P):
    from sh_messages import fmt_time
    buy = e["dir"] == 1
    side = "شراء 🟢" if buy else "بيع 🔴"
    pip = P["pipSize"]
    entry, sl, tp = e["entry"], e["sl"], e["tp"]
    risk = abs(entry - sl); rew = abs(tp - entry)
    at = e.get("at", time.time()); late = time.time() - at
    tm = fmt_time(at, tz) + (f" (أُرسلت متأخرة {int(late // 60)} د)" if late > 150 else "")
    if e["kind"] == "plan":
        win = fmt_time(e["win"], tz)
        return (f"{SBANNER}\n🎯 <b>صفقة {side} الآن</b> — إغلاق رفض عند مستوى 30M\n{LINE}\n"
                f"📍 الدخول: <b>{entry:.2f}</b> (سعر الإغلاق)\n🛑 الوقف: <b>{sl:.2f}</b> (−{risk:.2f}$ · {risk / pip:.0f} نقطة)\n"
                f"✅ الهدف: <b>{tp:.2f}</b> (+{rew:.2f}$ · {rew / pip:.0f} نقطة)\n⚖️ العائد/المخاطرة: <b>1:{rew / risk:.1f}</b>\n{LINE}\n"
                f"🏷️ المستوى: {e['tag']} @ {e['lv']:.2f}\n🕐 نافذة جلسة 4H بدأت {win} وتستمر {e['winMin']} دقيقة — صفقة واحدة لكل نافذة\n🕒 {tm}\n"
                "<i>نسبة النجاح التاريخية ≈ 41% باختبار 10 أشهر، وهي ليست ضماناً. الأسعار بسعر الذهب الفوري وقد تختلف نحو 1$ عن شارتك.</i>")
    res = e.get("res")
    if res == "TP":
        t = f"🎯 <b>تحقق الهدف</b> — {side}\n💰 +{rew:.2f}$ ({rew / pip:.0f} نقطة)"
    else:
        t = f"🛑 <b>ضرب الوقف</b> — {side}\n📉 −{risk:.2f}$ ({risk / pip:.0f} نقطة)"
    return f"{SBANNER}\n{t}\n📍 دخول {entry:.2f} | 🛑 {sl:.2f} | ✅ {tp:.2f}\n🕒 {tm}"
