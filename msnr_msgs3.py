# -*- coding: utf-8 -*-
"""رسائل MSNR (عربي، توقيت فلسطين): رفض مؤكَّد (T1–T4 + منطقة الدخول) · إعادة اختبار · صفقة جلسة 4H ونتيجتها."""
import time

from msnr_v4 import TYPE_TXT

LINE = "━━━━━━━━━━━━━━"
BANNER = "🟧 <b>MSNR Levels</b>"
SBANNER = "🟧 <b>MSNR Session</b>"


def when4(e, tz):
    """وقت الحدث نفسه (إغلاق الشمعة أو لحظة اللمس) لا وقت الإرسال، مع تنبيه إن تأخر الإرسال أكثر من دقيقتين ونصف."""
    from sh_messages import fmt_time
    now = time.time(); at = e.get("at", now)
    late = now - at
    return fmt_time(at, tz) + (f" (أُرسلت متأخرة {int(late // 60)} د)" if late > 150 else "")


def v4_text(e, tz, P):
    sup = e["role"] == 1
    icon = "🟢" if sup else "🔴"
    side = "دعم (شراء)" if sup else "مقاومة (بيع)"
    p = e["p"]; cur = e["cur"]; cf = e["cf"]
    base = f"{icon} <b>{e['tag']}</b> @ <b>{p:.2f}</b> — {side}"
    tm = f"🕒 {when4(e, tz)}"
    k = e["kind"]
    if k == "retE":
        return f"{BANNER}\n🔁 <b>إعادة اختبار المستوى الآن</b> (بعد رفض مؤكَّد)\n{base}\n📍 السعر الآن: {cur:.2f}\n{tm}"
    if k == "ret":
        return f"{BANNER}\n✅ <b>إعادة اختبار مؤكَّدة</b> — أُغلقت شمعة {cf} {'فوق' if sup else 'تحت'} المستوى\n{base}\n📍 السعر الآن: {cur:.2f}\n{tm}"
    x = e.get("x") or 0
    lines = [f"{BANNER}\n✅ <b>رفض مؤكَّد (REJ)</b> — أُغلقت شمعة {cf} {'فوق' if sup else 'تحت'} المستوى", base, f"📍 السعر الآن: {cur:.2f}"]
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
