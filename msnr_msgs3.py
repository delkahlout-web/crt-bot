# -*- coding: utf-8 -*-
"""رسائل MSNR (عربي، توقيت فلسطين) — تصميم مختصر ومرتّب: عنوان المرحلة ← المستوى ← القوة ← التفاصيل ← الوقت."""
import datetime as dt
import time
from zoneinfo import ZoneInfo

SEP = "┄┄┄┄┄┄┄┄┄┄┄┄┄┄"
TOP = "▰▰▰▰▰▰▰▰▰▰▰▰▰▰"
WHY = {"A": "تفعيل", "B": "كسر", "L": "سيولة"}
RANK = {"W": "أسبوعي", "D": "يومي", "4H": "4س", "1H": "ساعة", "30M": "30د", "15M": "15د"}
TYPE_SHORT = {
    1: ("ذيل ضعيف · إغلاق قريب", "انتظر سحب قمة/قاع الذيل ثم ابحث عن Refine"),
    2: ("ذيل ضعيف · إغلاق بعيد", "الدخول داخل الصندوق: 50% أو Refine"),
    3: ("ذيل قوي · إغلاق قريب", "الدخول من 50% الذيل أو Refine"),
    4: ("ذيل قوي · إغلاق بعيد", "يرجع غالباً لـ50% الذيل أو المستوى — Refine"),
}


def fmt_tags(tags):
    """يدمج الفريمات المكررة: ['30M','30M','1H'] ← 30M×2+1H."""
    out = []; cnt = {}
    for t in tags:
        if t not in cnt:
            out.append(t)
        cnt[t] = cnt.get(t, 0) + 1
    return "+".join(t + (f"×{cnt[t]}" if cnt[t] > 1 else "") for t in out)


def hm(at, tz):
    """وقت الحدث نفسه (لا وقت الإرسال) بتوقيت فلسطين، مع تنبيه قصير إن تأخر الإرسال."""
    d = dt.datetime.fromtimestamp(at, ZoneInfo(tz))
    late = time.time() - at
    return f"{d:%H:%M} · {d:%d/%m}" + (f" · ⏱ متأخرة {int(late // 60)}د" if late > 150 else "")


def stars(why):
    return ("★" * len(why)) if why else "☆"


def power(why, af, rank):
    """سطر القوة: نجوم + سببها + فريم المستوى."""
    reasons = " · ".join(WHY[c] for c in (why or ""))
    return f"💪 القوة: {stars(why)}" + (f"  ({reasons})" if reasons else "") + ("  ⚡فريش" if af else "") + f"  ·  {rank}"


def head(stage, role, tag):
    icon = "🟩" if role == 1 else "🟥"
    side = "دعم" if role == 1 else "مقاومة"
    return f"{TOP}\n{stage}\n{icon} <b>{side}</b>  ·  <b>{tag}</b>\n{SEP}"


def v4_text(e, tz, P):
    sup = e["role"] == 1
    p = e["p"]; cur = e["cur"]; cf = e["cf"]; nxt = e.get("nxt", "")
    k = e["kind"]
    side_word = "فوق" if sup else "تحت"
    rank = RANK.get(e.get("rank", cf), cf)
    pw = power(e.get("why", ""), e.get("af"), rank)
    base = f"المستوى  <code>{p:.2f}</code>\nالسعر     <code>{cur:.2f}</code>\n{pw}"
    tm = f"🕒 {hm(e.get('at', time.time()), tz)}"
    if k == "touch":
        return f"{head('⚡ <b>لمس المستوى</b>', e['role'], e['tag'])}\n{base}\n{SEP}\n⏳ ننتظر إغلاق شمعة {cf} {side_word} المستوى\n{tm}"
    if k == "retE":
        return f"{head('🔁 <b>إعادة اختبار</b> · بعد رفض مؤكَّد', e['role'], e['tag'])}\n{base}\n{SEP}\n{tm}"
    if k == "ret":
        return f"{head('🔁 <b>إعادة اختبار مؤكَّدة</b>', e['role'], e['tag'])}\n{base}\n{SEP}\n✔️ أُغلقت شمعة {cf} {side_word} المستوى\n{tm}"
    x = e.get("x") or 0
    title = f"✅ <b>رفض مؤكَّد</b>" + (f" · <b>T{x}</b>" if x else "")
    lines = [head(title, e["role"], e["tag"]), base, SEP]
    if x:
        what, act = TYPE_SHORT[x]
        lines.append(f"🧭 {what}")
        z = e.get("zone")
        if z is not None:
            lines.append(f"🎯 الذيل <code>{z[0]:.2f}</code>" if x == 1 else f"🎯 الدخول <code>{z[0]:.2f}</code> – <code>{z[1]:.2f}</code>  ·  50% <code>{e['mid']:.2f}</code>")
        lines.append(f"💡 {act}")
    if e.get("refine"):
        lines.append(f"⇢ Refine <code>{e['refine'][0]:.2f}</code> ({e['refine'][1]})")
    if e.get("fake"):
        lines.append("⚠️ بعد إغلاق واحد خلف المستوى (كسر وهمي محتمل)")
    if nxt:
        lines.append(f"🔎 التأكيد على {cf}  ·  الدخول على {nxt}")
    lines += [SEP, f"✔️ أُغلقت شمعة {cf} {side_word} المستوى", tm]
    return "\n".join(lines)


def plan_text(e, tz, P):
    buy = e["dir"] == 1
    side = "شراء 🟢" if buy else "بيع 🔴"
    pip = P["pipSize"]
    entry, sl, tp = e["entry"], e["sl"], e["tp"]
    risk = abs(entry - sl); rew = abs(tp - entry)
    tm = f"🕒 {hm(e.get('at', time.time()), tz)}"
    if e["kind"] == "plan":
        w0 = dt.datetime.fromtimestamp(e["win"], ZoneInfo(tz)); w1 = w0 + dt.timedelta(minutes=e["winMin"])
        return (f"{TOP}\n🎯 <b>صفقة {side}</b>  ·  جلسة 4H\n{SEP}\n"
                f"الدخول  <code>{entry:.2f}</code>\n"
                f"الوقف   <code>{sl:.2f}</code>  (−{risk:.2f}$)\n"
                f"الهدف   <code>{tp:.2f}</code>  (+{rew:.2f}$)\n"
                f"النسبة  <b>1 : {rew / risk:.1f}</b>\n{SEP}\n"
                f"📌 إغلاق رفض عند {e['tag']} @ <code>{e['lv']:.2f}</code>\n"
                f"🕐 النافذة {w0:%H:%M} ← {w1:%H:%M}  ·  صفقة واحدة لكل نافذة\n{tm}\n"
                f"<i>نجاح تاريخي ≈ 41% (10 أشهر) — ليس ضماناً</i>")
    res = e.get("res")
    if res == "TP":
        t = f"🏆 <b>تحقق الهدف</b>  ·  {side}\n💰 <b>+{rew:.2f}$</b>"
    else:
        t = f"🛑 <b>ضرب الوقف</b>  ·  {side}\n📉 <b>−{risk:.2f}$</b>"
    return f"{TOP}\n{t}\n{SEP}\nدخول <code>{entry:.2f}</code>  ·  وقف <code>{sl:.2f}</code>  ·  هدف <code>{tp:.2f}</code>\n{tm}"


# ───────────── قرب + لقطة المستويات ─────────────
def level_desc(c):
    why = c.get("why", "")
    reasons = " · ".join(WHY[x] for x in why)
    tags = fmt_tags(c["tags"])
    return f"{tags} {c.get('kind', '')}  {stars(why)}" + (f" ({reasons})" if reasons else "") + (f" 💧{c['hl']}" if c.get("hl") else "") + (" ⚡" if c.get("af") else "")


def alert_text(c, cur, tz, P):
    d = c["price"] - cur; pts = abs(d) / P["pipSize"]
    role = 1 if c["role"] == "support" else -1
    why = c.get("why", "")
    rank = RANK.get(c["tags"][0], c["tags"][0])
    lines = [head("⚠️ <b>قرب من المستوى</b>", role, fmt_tags(c["tags"]) + " " + c.get("kind", "")),
             f"المستوى  <code>{c['price']:.2f}</code>", f"السعر     <code>{cur:.2f}</code>  ({'يقترب من الأعلى' if d > 0 else 'يقترب من الأسفل'})",
             f"المسافة  {abs(d):.2f}$  ({pts:.0f} نقطة)", power(why, c.get("af"), rank)]
    if c.get("hl"):
        lines.append(f"💧 سيولة مخفية {c['hl']} نقطة")
    lines += [SEP, f"🕒 {hm(time.time(), tz)}"]
    return "\n".join(lines)


def snapshot_text(levels, cur, tz, P):
    if not levels:
        return f"{TOP}\n📋 <b>المستويات الحالية</b>\n{SEP}\nلا مستويات ضمن {P['maxDist']:g} نقطة من السعر الآن."
    rows = []
    for c in levels:
        icon = "🟥" if c["role"] == "resistance" else "🟩"
        rows.append(f"{icon} <code>{c['price']:.2f}</code>  ({c['price'] - cur:+.1f}$)  ·  {level_desc(c)}")
    return (f"{TOP}\n📋 <b>المستويات الحالية</b>\n{SEP}\n" + "\n".join(rows) +
            f"\n{SEP}\nالسعر الآن <code>{cur:.2f}</code>\n🕒 {hm(time.time(), tz)}\n<i>الأسعار تقديرية بفرق نحو 1$ عن شارتك: اعتمد على القرب والنوع.</i>")


def map_text(m, cur, tz, title="خريطة المناطق"):
    """أقوى المستويات على أي بُعد: مقاومات من الأعلى للأدنى ثم السعر ثم الدعوم (كما تظهر على الشارت)."""
    def row(c):
        icon = "🟥" if c["role"] == "resistance" else "🟩"
        reasons = " · ".join(WHY[x] for x in c["why"])
        multi = " ✓متعدد" if len(c["tags"]) > 1 else ""
        return (f"{icon} <code>{c['price']:.2f}</code> ({c['price'] - cur:+.1f}$)  {fmt_tags(c['tags'])} {c['kind']}  {stars(c['why'])}"
                + (f" ({reasons})" if reasons else "") + (f" 💧{c['hl']}" if c.get("hl") else "") + multi)
    res = sorted(m.get("resistance", []), key=lambda c: -c["price"]); sup = sorted(m.get("support", []), key=lambda c: -c["price"])
    lines = [f"{TOP}", f"🗺 <b>{title}</b> · أقوى المستويات", SEP]
    lines += [row(c) for c in res] or ["— لا مقاومات —"]
    lines += [f"━━ السعر الآن <code>{cur:.2f}</code> ━━"]
    lines += [row(c) for c in sup] or ["— لا دعوم —"]
    lines += [SEP, f"🕒 {hm(time.time(), tz)}", "<i>الأقوى أولاً: نجوم + تقاطع فريمات + رتبة الفريم. أرسل /map لتحديثها في أي وقت.</i>"]
    return "\n".join(lines)
