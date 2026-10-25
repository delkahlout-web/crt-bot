# -*- coding: utf-8 -*-
"""رسائل صفقات MSNR Trader Pro (عربي، توقيت فلسطين)."""
import time

BANNER = "🟧 <b>MSNR Trader</b>"
LINE = "━━━━━━━━━━━━━━"
HOW = {"LIMIT": "أمر معلّق عند المستوى", "REFINED": "أمر معلّق عند المستوى المحسَّن", "KL AFTER REJ": "أمر معلّق عند مستوى تشكّل بعد الرفض",
       "50%": "أمر معلّق (50%)", "ENTRY HERE": "دخول بالسوق"}


def when(e, tz):
    """وقت الحدث نفسه (إغلاق شمعة الشارت) لا وقت الإرسال، مع تنبيه إن تأخر الإرسال."""
    from sh_messages import fmt_time
    now = time.time(); t = e.get("time")
    if t is None:
        return fmt_time(now, tz)
    at = t + 300
    late = now - at
    return fmt_time(at, tz) + (f" (أُرسلت متأخرة {int(late // 60)} د)" if late > 150 else "")


def trade_text(e, tz, P):
    from sh_messages import fmt_time
    pip = P["pipSize"]; buy = e["dir"] == 1
    side = "شراء 🟢" if buy else "بيع 🔴"
    entry, sl, tp = e["entry"], e["sl"], e["tp"]
    risk = abs(entry - sl); rew = abs(tp - entry)
    tm = when(e, tz)
    if e["kind"] == "plan":
        how = HOW.get(e.get("how"), "أمر معلّق")
        life = "" if e.get("mkt") else f"\n⏳ يبقى الأمر حتى {P['orderWin']} شمعة 5د (نحو {P['orderWin'] * 5 // 60} ساعات) أو كسر المستوى بإغلاقين"
        ct = "\n⚠️ صفقة عكس اتجاه 4H" if e.get("ct") else ""
        return (f"{BANNER}\n🎯 <b>صفقة {side}</b> — {how}\n{LINE}\n"
                f"📍 الدخول: <b>{entry:.2f}</b>\n🛑 الوقف: <b>{sl:.2f}</b> (−{risk:.2f}$ · {risk / pip:.0f} نقطة)\n"
                f"✅ الهدف: <b>{tp:.2f}</b> (+{rew:.2f}$ · {rew / pip:.0f} نقطة)\n⚖️ العائد/المخاطرة: <b>{e['rr']:.1f}R</b>\n{LINE}\n"
                f"🏷️ المستوى: {e['tag']} @ {e['pK']:.2f}\n🏁 الهدف عند: {e['tpTag']}{life}{ct}\n🕒 {tm}\n"
                "<i>الأسعار بسعر الذهب الفوري (OANDA تقريباً) وقد تختلف نحو 1$ عن شارتك.</i>")
    if e["kind"] == "fill":
        return f"{BANNER}\n✅ <b>تفعّل الدخول</b> — {side}\n📍 {entry:.2f} | 🛑 {sl:.2f} | ✅ {tp:.2f}\n🕒 {tm}"
    if e["kind"] == "cancel":
        return f"{BANNER}\n❌ <b>أُلغي الأمر</b> — {side} @ {entry:.2f}\nالسبب: {e.get('reason', '')}\n🕒 {tm}"
    res = e.get("res"); pts = e.get("pts", 0.0)
    if res == "TP":
        t = f"🎯 <b>تحقق الهدف</b> — {side}\n💰 +{pts * pip:.2f}$ ({pts:.0f} نقطة · {pts * pip / risk:.1f}R)"
    elif res == "BE":
        t = f"⚪ <b>إغلاق عند التعادل</b> — {side}"
    else:
        t = f"🛑 <b>ضرب الوقف</b> — {side}\n📉 {pts * pip:.2f}$ ({pts:.0f} نقطة · −1R)"
    return f"{BANNER}\n{t}\n📍 دخول {entry:.2f} | 🛑 {sl:.2f} | ✅ {tp:.2f}\n🕒 {tm}"


def stage_text(e, tz):
    from sh_messages import fmt_time
    if e["kind"] == "early":
        icon = "🟢" if e["sd"] == 1 else "🔴"
        return (f"{BANNER}\n⚡ {icon} <b>لمس إعادة اختبار الآن</b> — {e['tag']} @ {e['p']:.2f}\n"
                f"📍 السعر الآن: {e['cur']:.2f}\n<i>تنبيه فوري؛ يتأكد RET رسمياً عند إغلاق شمعة {e['cf']}.</i>\n🕒 {fmt_time(time.time(), tz)}")
    name = {"touch": "لمس", "rej": "رفض (REJ)", "ret": "إعادة اختبار (RET)", "bo": "كسر (BO)"}[e["kind"]]
    icon = "🟢" if e["sd"] == 1 else "🔴"
    return f"{BANNER}\n{icon} <b>{name}</b> — {e['tag']} @ {e['p']:.2f}\n🕒 {when(e, tz)}"
