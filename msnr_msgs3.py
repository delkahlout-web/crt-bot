# -*- coding: utf-8 -*-
"""رسائل MSNR v3: لمس المستوى · رفض (مبدئي/مؤكَّد + النوع T1–T4 + منطقة الدخول) · إعادة اختبار (فوري/مؤكَّد)."""
import time

from msnr_msgs import LINE
from msnr_v3 import TYPE_TXT

BANNER = "🟧 <b>MSNR Levels</b>"


def when3(e, tz):
    from sh_messages import fmt_time
    now = time.time(); at = e.get("at", now)
    late = now - at
    return fmt_time(at, tz) + (f" (أُرسلت متأخرة {int(late // 60)} د)" if late > 150 else "")


def v3_text(e, tz, P):
    pip = P["pipSize"]; sup = e["role"] == 1
    icon = "🟢" if sup else "🔴"
    side = "دعم (شراء)" if sup else "مقاومة (بيع)"
    p = e["p"]; cur = e["cur"]; cf = e["cf"]
    head = f"{BANNER}\n"
    flags = ("\n↺ مستوى مقلوب لُمس عند كسره" if e.get("rt") else "") + ("\n⚡ مفعَّل من مستوى فريش" if e.get("af") else "")
    base = f"{icon} <b>{e['tag']}</b> @ <b>{p:.2f}</b> — {side}"
    tm = f"🕒 {when3(e, tz)}"
    k = e["kind"]
    if k == "touch":
        return (f"{head}⚡ <b>لمس مستوى الآن</b>\n{base}\n📍 السعر الآن: {cur:.2f}\n"
                f"<i>ننتظر الرفض: يتأكد بإغلاق شمعة {cf} {'فوق' if sup else 'تحت'} المستوى.</i>{flags}\n{tm}")
    if k == "rejE":
        return (f"{head}↩️ <b>رفض مبدئي (فوري)</b>\n{base}\n📍 السعر الآن: {cur:.2f} (ابتعد {abs(cur - p):.2f}$ عن المستوى)\n"
                f"<i>يتأكد الرفض رسمياً عند إغلاق شمعة {cf}.</i>\n{tm}")
    if k == "retE":
        return f"{head}🔁 <b>إعادة اختبار المستوى الآن</b> (بعد رفض مؤكَّد)\n{base}\n📍 السعر الآن: {cur:.2f}\n{tm}"
    if k == "ret":
        return f"{head}✅ <b>إعادة اختبار مؤكَّدة (RET)</b>\n{base}\n📍 السعر الآن: {cur:.2f}\n{tm}"
    # رفض مؤكَّد
    x = e.get("x") or 0
    lines = [f"{head}✅ <b>رفض مؤكَّد (REJ)</b> — أُغلقت شمعة {cf} {'فوق' if sup else 'تحت'} المستوى", base, f"📍 السعر الآن: {cur:.2f}"]
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
    return "\n".join(lines) + flags.replace("\n", "\n", 1)
