# -*- coding: utf-8 -*-
"""
مشتركو البوت: أي شخص يفتح البوت ويضغط /start يصله كل ما يصل صاحب البوت في اللحظة نفسها (/stop للإلغاء).
  • الإرسال للمشتركين في خيوط متوازية، وصاحب البوت يُرسَل له أولاً دون انتظارهم.
  • رسائل الأعطال والصيانة (private=True) لا تصل إلا لصاحب البوت.
  • من يحظر البوت يُحذف تلقائياً. رمز دخول اختياري (subscribeCode) وحدّ أقصى للمشتركين (maxSubs).
  • لوحة تحكم لصاحب البوت (من محادثته فقط): /users بأزرار (إزالة / حظر / فك حظر)، و/ban و/unban و/kick و/say و/help.
"""
import html
import json
import re
import threading
import time

import requests

WELCOME = ("🟧 <b>أهلاً بك في MSNR</b>\n▰▰▰▰▰▰▰▰▰▰▰▰▰▰\n"
           "ستصلك لحظة حدوثها رسائل مستويات الذهب:\n"
           "⚠️ قرب  ·  ⚡ لمس  ·  ✅ رفض مؤكَّد  ·  🔁 إعادة اختبار\n"
           "🎯 وصفقات جلسة 4H مع الدخول والوقف والهدف\n┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
           "للإلغاء /stop  ·  للحالة /status  ·  لخريطة المناطق /map\n"
           "<i>المعلومات للتعليم وليست توصية مالية.</i>")
OWNER_HELP = ("🛠 <b>لوحة التحكم</b>\n┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
              "/users — قائمة المستخدمين بأزرار (إزالة / حظر / فك حظر)\n"
              "<code>/kick رقم_أو_@اسم</code> — إزالة (يستطيع العودة بـ /start)\n"
              "<code>/ban رقم_أو_@اسم</code> — حظر (لا يستطيع الاشتراك)\n"
              "<code>/unban رقم_أو_@اسم</code> — فك الحظر\n"
              "<code>/say نص</code> — رسالة لكل المشتركين\n"
              "<code>1</code> — شراء الذهب الآن للجميع بالقيم الافتراضية (وقف 30 · هدف 100 · سبريد 3)\n"
              "<code>2</code> — بيع الذهب الآن للجميع بالقيم الافتراضية\n"
              "<code>1 3920</code> — شراء معلّق عند 3920 بالقيم الافتراضية\n"
              "<code>ضبط 30 100 3</code> — تغيير الافتراضي (وقف، هدف، سبريد بالنقاط)\n"
              "<code>1 60 120</code> — شراء الآن بوقف وهدف مخصّصين · <code>2 60 120</code> بيع\n"
              "(الوقف والهدف بالنقاط، والنقطة = 0.1$؛ اكتبها مباشرة بلا أمر)\n"
              "<code>1 3920 60 120</code> — أمر معلّق عند 3920 (يُبلَّغون عند تفعيله)\n"
              "<code>ت 1 60 120</code> — تجربة تصلك وحدك بلا إرسال لأحد\n"
              "<code>الغاء</code> — إلغاء آخر أمر معلّق · <code>اغلاق</code> — إغلاق آخر صفقة بالسعر الآن\n"
              "<code>تراجع</code> — إن أُعلن هدف/وقف خطأً: تعود الصفقة مفتوحة ويُعلَم الجميع\n"
              "<code>سعر 4041.32</code> — معايرة: اكتب السعر الذي تراه الآن على منصتك فتطابقه كل أسعار الرسائل · <code>سعر</code> تعرض الحالة · <code>سعر صفر</code> تلغيها\n"
              "الهدف والوقف يُتابَعان تلقائيًا ويصل «مبروك» أو «بنعوّض» للجميع.\n"
              "✍️ أي رسالة عادية تكتبها هنا (نص أو صورة أو صوت) تصل لكل المشتركين فورًا.\n"
              "/map — خريطة المناطق\n/health — حالة النظام الآن")
_N = r"(\d+(?:\.\d+)?)"; _SEP = r"\s*[\s,،/]+\s*"
_TRADE = re.compile(rf"^\s*(ت|تجربة|t|test)?\s*[:\-]?\s*([12])(?:{_SEP}{_N}(?:{_SEP}{_N}(?:{_SEP}{_N})?)?)?\s*$", re.I)
_SET = re.compile(rf"^\s*(?:ضبط|اعدادات|إعدادات)\s+{_N}{_SEP}{_N}(?:{_SEP}{_N})?\s*$")
_CAL = re.compile(r"^\s*(?:سعر|معايرة)(?:\s+(\d{4,5}(?:\.\d+)?|صفر))?\s*$")
_TCMD = re.compile(r"^\s*(الغاء|إلغاء|اغلاق|إغلاق|تراجع)\s*$")
_TRYTRADE = re.compile(r"^\s*(ت|تجربة|t|test)?\s*[:\-]?\s*[12]\b[\d\s.,،/]*$", re.I)
_CONTENT = ("text", "photo", "video", "voice", "audio", "document", "sticker", "animation", "video_note", "location", "poll", "contact")
_PRICE = re.compile(r"(<(?:code|b)>)(\d{4,5}\.\d{2})(</(?:code|b)>)")
_DIG = str.maketrans("٠١٢٣٤٥٦٧٨٩٫", "0123456789.")


def _ago(t):
    d = max(0, int(time.time()) - int(t or 0))
    return f"{d // 86400} يوم" if d >= 86400 else f"{d // 3600} س" if d >= 3600 else f"{max(d // 60, 1)} د"


def cal_add(state, off, now):
    """يضيف قراءة معايرة ويعتمد وسيط آخر 5 قراءات خلال 6 ساعات (يلغي خطأ التوقيت عند الكتابة). يعيد (الوسيط، التشتت، العدد، التغيّر عن السابق)."""
    L = [x for x in state.get("pcal_s", []) if now - x[0] < 6 * 3600] + [[now, off]]
    L = L[-5:]; state["pcal_s"] = L
    v = sorted(x[1] for x in L); n = len(v)
    med = v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2
    prev = state.get("pcal"); state["pcal"] = round(med, 3)
    return med, v[-1] - v[0], n, (None if prev is None else med - prev)


class Broadcast:
    def __init__(self, tg, state, code="", max_subs=100, log=print):
        self.tg = tg; self.state = state; self.code = str(code or ""); self.max_subs = int(max_subs); self.log = log
        self.subs = state.setdefault("subs", {})
        self.banned = state.setdefault("banned", {})
        state.setdefault("upd", 0)
        self.dirty = False
        self.handlers = {}                                           # أوامر إضافية: {"/map": دالة تعيد النص}
        self.owner_handlers = {}                                     # أوامر لصاحب البوت فقط: {"/health": دالة}
        self.price_fn = None                                         # دالة ← (السعر الفوري, وقته)؛ تُفعِّل التوصيات اليدوية «1 60 120» من صاحب البوت مباشرة
        self.tz = "Asia/Hebron"
        state.setdefault("mtr", [])
        state.setdefault("pshift", 0.0)                              # معايرة الأسعار: فرق (سعر وسيطك − سعر البوت) يُضاف لكل الأسعار الظاهرة
        self._pt = False; self._pth = None
        self.shift_fn = None; self.raw_fn = None                    # إزاحة العرض (معايرتك) وقراءة المصدر الخام
        state.setdefault("mdef", dict(sl=30.0, tp=100.0, sp=3.0))      # القيم الافتراضية للتوصية: وقف 30 · هدف 100 · سبريد 3 نقاط
        self.base = tg.base; self.token = tg.token; self.chat_id = tg.chat_id
        self._lock = threading.Lock(); self._menu = False

    # ───────────── إرسال ─────────────
    def bump(self, key, n=1):
        """عدّاد يومي في الحالة (للتقرير و/health)."""
        st = self.state.setdefault("stats", {})
        day = time.strftime("%Y-%m-%d", time.gmtime())
        if st.get("day") != day:
            st.clear(); st["day"] = day
        st[key] = st.get(key, 0) + n

    def _shift(self):
        try:
            return float(self.shift_fn()) if self.shift_fn else float(self.state.get("pshift") or 0.0)
        except Exception:
            return float(self.state.get("pshift") or 0.0)

    def _px(self, text):
        """يُزيح كل الأسعار الظاهرة (داخل <code> أو <b>) بفرق المعايرة ليطابق سعر وسيط صاحب البوت."""
        sh = self._shift()
        if abs(sh) < 1e-9:
            return text

        def f(m):
            v = float(m.group(2))
            return m.group(1) + f"{v + sh:.2f}" + m.group(3) if 1000 <= v <= 20000 else m.group(0)
        return _PRICE.sub(f, text)

    def send(self, text, silent=False, private=False):
        text = self._px(text)
        if not private:
            self.fanout(text, silent)
            self.bump("msgs")
        return self.tg.send(text, silent)

    def fanout(self, text, silent=False):
        for cid in list(self.subs):
            if cid != str(self.chat_id):
                threading.Thread(target=self._send_one, args=(cid, text, silent), daemon=True).start()

    def _api(self, method, **data):
        return requests.post(self.base + "/" + method, data=data, timeout=15)

    def _post(self, cid, text, silent=False, markup=None):
        data = {"chat_id": cid, "text": text, "parse_mode": "HTML", "disable_web_page_preview": "true", "disable_notification": "true" if silent else "false"}
        if markup:
            data["reply_markup"] = json.dumps(markup, ensure_ascii=False)
        return requests.post(self.base + "/sendMessage", data=data, timeout=15)

    def _send_one(self, cid, text, silent):
        for attempt in range(3):
            try:
                r = self._post(cid, text, silent)
                if r.ok:
                    return
                if r.status_code == 429:
                    time.sleep(float(r.json().get("parameters", {}).get("retry_after", 2)) + 0.5); continue
                if r.status_code in (400, 403) and any(w in r.text.lower() for w in ("blocked", "chat not found", "deactivated", "kicked", "not a member")):
                    with self._lock:
                        self.subs.pop(cid, None); self.dirty = True
                    self.log(f"حُذف مشترك: {cid}")
                    return
            except Exception:
                pass
            time.sleep(1.5 * (attempt + 1))

    def _copy_one(self, cid, mid):
        """ينسخ رسالة صاحب البوت كما هي (نص منسّق أو صورة أو صوت...) إلى مشترك."""
        for attempt in range(3):
            try:
                r = self._api("copyMessage", chat_id=cid, from_chat_id=self.chat_id, message_id=mid)
                if r.ok:
                    return
                if r.status_code == 429:
                    time.sleep(float(r.json().get("parameters", {}).get("retry_after", 2)) + 0.5); continue
                if r.status_code in (400, 403) and any(w in r.text.lower() for w in ("blocked", "chat not found", "deactivated", "kicked", "not a member")):
                    with self._lock:
                        self.subs.pop(cid, None); self.dirty = True
                    self.log(f"حُذف مشترك: {cid}")
                    return
            except Exception:
                pass
            time.sleep(1.5 * (attempt + 1))

    def _relay(self, mid):
        """أي رسالة عادية يكتبها صاحب البوت في محادثته (بلا أمر) تصل لكل المشتركين."""
        subs = [c for c in list(self.subs) if c != str(self.chat_id)]
        for cid in subs:
            threading.Thread(target=self._copy_one, args=(cid, mid), daemon=True).start()
        self.bump("msgs")
        self._post(self.chat_id, f"✅ أُرسلت لـ {len(subs)} مشترك", silent=True)
        self.log(f"رسالة حرّة من صاحب البوت إلى {len(subs)} مشترك")

    # ───────────── لوحة صاحب البوت ─────────────
    def _label(self, cid, v):
        n = html.escape(str(v.get("n") or "—")); u = v.get("u")
        return n + (f" @{html.escape(u)}" if u and u.lower() not in n.lower() else "")

    def _find(self, token):
        """يحوّل رقماً أو @اسماً أو اسماً إلى معرّف محادثة (بين المشتركين والمحظورين)."""
        t = token.strip().lstrip("@").lower()
        if t.lstrip("-").isdigit():
            return t
        for pool in (self.subs, self.banned):
            for cid, v in pool.items():
                if t in (str(v.get("u") or "").lower(), str(v.get("n") or "").lower()):
                    return cid
        return None

    def users_view(self):
        rows = []; kb = []
        for i, (cid, v) in enumerate(self.subs.items(), 1):
            rows.append(f"{i}) <b>{self._label(cid, v)}</b> · <code>{cid}</code> · منذ {_ago(v.get('t'))}")
            kb.append([{"text": f"➖ إزالة {i}", "callback_data": f"kick:{cid}"}, {"text": f"🚫 حظر {i}", "callback_data": f"ban:{cid}"}])
        text = f"👥 <b>المستخدمون</b> ({len(self.subs)})\n┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n" + ("\n".join(rows) if rows else "لا يوجد مشتركون بعد")
        if self.banned:
            text += f"\n┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n🚫 <b>المحظورون</b> ({len(self.banned)})\n" + "\n".join(f"• {self._label(c, v)} · <code>{c}</code>" for c, v in self.banned.items())
            for c, v in list(self.banned.items())[:10]:
                kb.append([{"text": f"✅ فك حظر {str(v.get('n') or c)[:18]}", "callback_data": f"unban:{c}"}])
        return text, {"inline_keyboard": kb}

    def _act(self, action, cid):
        """ينفّذ الإجراء ويعيد جملة نتيجة."""
        v = self.subs.get(cid) or self.banned.get(cid) or {}
        who = str(v.get("n") or cid)
        if action == "kick":
            if self.subs.pop(cid, None) is None:
                return "غير موجود بين المشتركين"
            self._post(cid, "تم إيقاف اشتراكك من قِبل المشرف. يمكنك العودة بـ /start.")
            self.dirty = True; return f"أُزيل: {who}"
        if action == "ban":
            self.subs.pop(cid, None)
            self.banned[cid] = {"n": v.get("n") or cid, "u": v.get("u"), "t": int(time.time())}
            self._post(cid, "🚫 تم حظرك من البوت.")
            self.dirty = True; return f"حُظر: {who}"
        if action == "unban":
            if self.banned.pop(cid, None) is None:
                return "غير محظور"
            self.dirty = True; return f"فُكّ الحظر: {who}"
        return "أمر غير معروف"

    def _owner(self, cid, text, cmd, arg):
        if cmd in self.owner_handlers:
            try:
                self._post(cid, self.owner_handlers[cmd]())
            except Exception as exh:
                self.log(f"أمر {cmd}: {exh}"); self._post(cid, f"تعذّر: {exh}")
            return True
        if cmd in ("/users", "/panel", "/help"):
            if cmd == "/help":
                self._post(cid, OWNER_HELP)
            else:
                t, kb = self.users_view(); self._post(cid, t, markup=kb)
        elif cmd in ("/kick", "/ban", "/unban"):
            target = self._find(arg) if arg.strip() else None
            if not target:
                self._post(cid, f"استعمل: <code>{cmd} رقم_المحادثة</code> أو <code>{cmd} @اسم</code> (الأرقام من /users)")
            else:
                self._post(cid, "✅ " + self._act(cmd[1:], target))
        elif cmd == "/say":
            if arg.strip():
                self.fanout(arg.strip()); self._post(cid, f"✅ أُرسلت لـ {len([c for c in self.subs if c != str(self.chat_id)])} مشترك")
            else:
                self._post(cid, "استعمل: <code>/say نص الرسالة</code>")
        else:
            return False
        return True

    # ───────────── توصيات يدوية من صاحب البوت (1 = شراء، 2 = بيع) مع متابعة تلقائية للوقف والهدف ─────────────
    def _tm(self):
        from sh_messages import fmt_time
        return fmt_time(time.time(), self.tz)

    @staticmethod
    def _say(line):
        return f"<blockquote>🗣 <b>ضياء بقول لكم:</b>\n{line}</blockquote>"

    def _card(self, x, head, note=""):
        """بطاقة التوصية: سطر ضياء، ثم الدخول والوقف والهدف (أسعار قابلة للنسخ بلمسة) وشريط المسافة."""
        buy = x["s"] == 1
        kind = "" if x["st"] == "open" else f"\n📌 نوع الأمر: <b>{x['pt']}</b>  ·  يتفعّل عند <code>{x['e']:.2f}</code>"
        return (f"{head}\n\n"
                f"{'🟢' if buy else '🔴'} <b>XAUUSD</b>  ·  {'شراء ▲' if buy else 'بيع ▼'}{kind}\n"
                f"┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\n"
                f"📍 الدخول    <code>{x['e']:.2f}</code>\n"
                f"🛑 الوقف     <code>{x['slp']:.2f}</code>   ‹ {x['sl']:g} نقطة ›\n"
                f"🎯 الهدف     <code>{x['tpp']:.2f}</code>   ‹ {x['tp']:g} نقطة ›\n"
                f"↔️ السبريد   <b>{self.state['mdef']['sp']:g} نقطة</b>  ({self.state['mdef']['sp'] * 0.1:.1f}$) — الأسعار قبل السبريد\n"
                f"┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈{note}")

    def _trade_in(self, cid, side, nums, test):
        """يحوّل الأرقام المكتوبة إلى توصية: «1» = شراء بالقيم الافتراضية · «1 3920» = معلّق بالافتراضية · «1 60 120» = وقف وهدف · «1 3920 60 120» = معلّق كامل."""
        d = self.state["mdef"]; entry = None; sl, tp = d["sl"], d["tp"]
        if len(nums) == 1:
            if nums[0] < 500:
                self._post(cid, f"⚠️ رقم واحد يجب أن يكون سعر الدخول (مثل <code>1 3920</code>). للوقف والهدف اكتب الرقمين: <code>1 {nums[0]:g} {tp:g}</code>")
                return
            entry = nums[0]
        elif len(nums) == 2:
            sl, tp = nums
        elif len(nums) == 3:
            entry, sl, tp = nums
        self._trade(cid, side, entry, sl, tp, test)

    def _settings(self, cid, sl, tp, sp):
        d = self.state["mdef"]
        if not (0 < sl <= 2000 and 0 < tp <= 5000) or (sp is not None and not 0 <= sp <= 100):
            self._post(cid, "⚠️ أرقام غير معقولة. مثال: <code>ضبط 30 100 3</code> (وقف، هدف، سبريد بالنقاط)")
            return
        d["sl"], d["tp"] = sl, tp
        if sp is not None:
            d["sp"] = sp
        self.dirty = True
        self._post(cid, f"✅ حُفظت القيم الافتراضية: وقف <b>{sl:g}</b> · هدف <b>{tp:g}</b> · سبريد <b>{d['sp']:g}</b> نقطة\nالآن <code>1</code> = شراء و<code>2</code> = بيع بهذه القيم.", silent=True)

    def _trade(self, cid, side, entry, sl, tp, test=False):
        """توصية فورية (entry=None) أو أمر معلّق (entry=سعر). «ت» في أول الأمر = تجربة لك وحدك."""
        if not (0 < sl <= 2000 and 0 < tp <= 5000) or (entry is not None and not 500 < entry < 20000):
            self._post(cid, "⚠️ الأرقام خارج المدى المعقول. مثال: <code>1 60 120</code> أو أمر معلّق: <code>1 3920 60 120</code>")
            return
        pr = self.price_fn() if self.price_fn else None
        if not pr or time.time() - pr[1] > 60:
            self._post(cid, "⚠️ لا يوجد سعر حديث الآن، لم يُرسل شيء. أعد المحاولة بعد لحظات.")
            return
        px, pt = pr; pip = 0.1; buy = side == 1
        if not test and len(self.state.setdefault("mtr", [])) >= 5:
            self._post(cid, "⚠️ عندك 5 توصيات قيد المتابعة. اكتب <code>الغاء</code> أو <code>اغلاق</code> أولًا.")
            return
        e = px if entry is None else entry
        x = dict(id=int(time.time()), s=side, e=e, sl=sl, tp=tp, slp=e - sl * pip if buy else e + sl * pip, tpp=e + tp * pip if buy else e - tp * pip,
                 st="open" if entry is None else "pending", lt=time.time(), t0=time.time(),
                 pt="Buy Limit" if buy else "Sell Limit", up=e > px)
        act = "نشتري" if buy else "نبيع"
        if x["st"] == "open":
            head = self._say(f"{act} الذهب الآن {'🟢' if buy else '🔴'}")
            text = self._card(x, head)
        else:
            head = self._say(f"أمر معلّق — {act} الذهب عند <b>{e:.2f}</b> {'🟢' if buy else '🔴'}")
            text = self._card(x, head, f"\n💲 السعر الآن <code>{px:.2f}</code> — نخبركم لحظة تفعيل الأمر")
        if test:
            self._post(cid, "🧪 <b>تجربة — وصلتك وحدك ولم تُرسل لأحد</b>\n\n" + self._px(text))
            return
        self.state["mtr"].append(x); self.dirty = True
        self.send(text)
        self._post(cid, f"✅ أُرسلت لـ {len([c for c in self.subs if c != str(self.chat_id)])} مشترك · أتابع الوقف والهدف تلقائيًا", silent=True)
        self.log(f"توصية يدوية: {'شراء' if buy else 'بيع'} {x['st']} @ {e:.2f} وقف {sl:g} هدف {tp:g}")

    def _calibrate(self, cid, arg):
        """«سعر 4041.32» = السعر الذي تراه الآن على منصتك: يحسب البوت الفرق ويُزيح به كل الأسعار الظاهرة. «سعر» وحدها تعرض الحالة، و«سعر صفر» تلغي المعايرة."""
        pr = self.price_fn() if self.price_fn else None
        if not pr or time.time() - pr[1] > 60:
            self._post(cid, "⚠️ لا يوجد سعر حديث الآن. أعد المحاولة بعد لحظات.")
            return
        cur = pr[0]; sh = self._shift()
        if arg is None:
            self._post(cid, f"📐 المعايرة الحالية: <b>{sh:+.2f}$</b>\nسعر البوت الآن (بعد المعايرة): <code>{cur + sh:.2f}</code>\nاكتب <code>سعر</code> ثم السعر الذي تراه على منصتك لتضبطها، مثال: <code>سعر 4041.32</code>", silent=True)
            return
        if arg == "صفر":
            self.state["pshift"] = 0.0; self.state.pop("pcal", None); self.dirty = True
            self._post(cid, "✅ أُلغيت المعايرة: الأسعار كما يراها البوت.", silent=True)
            return
        x = float(arg)
        if not 1000 < x < 20000 or abs(x - cur) > 15:
            self._post(cid, f"⚠️ الرقم بعيد عن سعر البوت ({cur:.2f}). تأكد منه وأعد الكتابة.")
            return
        self.state["pshift"] = round(x - cur, 3)
        raw = self.raw_fn() if self.raw_fn else None
        extra = ""
        if raw is not None:
            med, spread, n, drift = cal_add(self.state, x - raw, time.time())          # معايرة ثابتة مرتبطة بسعر الوسيط الخام (Bid)
            extra = f"\n📊 القراءات: {n} · تشتّتها ±{spread / 2:.2f}$" + ("" if drift is None else f" · تغيّر عن المعايرة السابقة {drift:+.2f}$")
        self.dirty = True
        self._post(cid, f"✅ ضُبطت المعايرة: فرق منصتك عن مصدر البوت <b>{x - cur:+.2f}$</b>.\nمن الآن كل الأسعار في الرسائل تطابق منصتك عند <code>{x:.2f}</code>. أعد المعايرة (<code>سعر ...</code>) متى لاحظت فرقًا: كل قراءة جديدة تُدمج مع السابقة فتزداد الدقة." + extra, silent=True)

    def _trade_cmd(self, cid, word):
        """«الغاء» يلغي آخر أمر معلّق، و«اغلاق» يغلق آخر صفقة مفتوحة بالسعر الآن، ويُعلَم المشتركون."""
        tr = self.state.setdefault("mtr", [])
        if word == "تراجع":                                    # تصحيح إعلان هدف/وقف خاطئ: تعود الصفقة مفتوحة ويُعلَم الجميع
            x = self.state.get("mlast")
            if not x:
                self._post(cid, "لا توجد صفقة أُغلقت مؤخرًا للتراجع عنها.")
                return
            x = dict(x); x.pop("res", None); x["st"] = "open"; x["lt"] = time.time()
            self.state["mlast"] = None; tr.append(x)
            if self.state.get("mhist"):
                self.state["mhist"].pop()
            self.dirty = True
            self.send(self._say("تصحيح: الصفقة ما زالت مفتوحة، آسفين على الإرباك 🙏") + f"\n\n📍 الدخول <code>{x['e']:.2f}</code>   🛑 <code>{x['slp']:.2f}</code>   🎯 <code>{x['tpp']:.2f}</code>")
            self._post(cid, "✅ أُعيدت الصفقة للمتابعة وأُعلم المشتركون", silent=True)
            return
        cancel = word in ("الغاء", "إلغاء")
        x = next((t for t in reversed(tr) if t["st"] == ("pending" if cancel else "open")), None)
        if not x:
            self._post(cid, "لا يوجد أمر معلّق الآن." if cancel else "لا توجد صفقة مفتوحة الآن.")
            return
        pr = self.price_fn() if self.price_fn else None
        tr.remove(x); self.dirty = True
        if cancel:
            self.send(self._say("ألغينا الأمر المعلّق، ما بتم تفعيله ✋") + f"\n\n{'🟢' if x['s'] == 1 else '🔴'} {x['pt']} عند <code>{x['e']:.2f}</code>\n🕒 {self._tm()}")
        else:
            if not pr:
                self._post(cid, "⚠️ لا يوجد سعر حديث الآن. أعد المحاولة."); tr.append(x); return
            pts = (pr[0] - x["e"]) / 0.1 * (1 if x["s"] == 1 else -1)
            self.send(self._say(f"أغلقنا الصفقة الآن {'✅' if pts >= 0 else '🤝'}") + f"\n\n📍 الدخول <code>{x['e']:.2f}</code>  ←  🚪 الإغلاق <code>{pr[0]:.2f}</code>\n"
                      f"{'📈' if pts >= 0 else '📉'} النتيجة: <b>{pts:+.0f} نقطة</b> ({pts * 0.1:+.1f}$)\n🕒 {self._tm()}")
        self._post(cid, "✅ تم وأُعلم المشتركون", silent=True)

    def track(self, buf):
        """يتابع كل توصية بعيّنات السعر الفوري: تفعيل الأمر المعلّق، ثم الهدف (مبروك) أو الوقف (بنعوّض)، ويُعلم الجميع لحظتها."""
        tr = self.state.get("mtr")
        if not tr or not buf:
            return
        for x in list(tr):
            for t, p in [s for s in buf if s[0] > x["lt"]]:
                x["lt"] = t; buy = x["s"] == 1; pip = 0.1
                if x["st"] == "pending":
                    hit = (p >= x["e"]) if x.get("up") else (p <= x["e"])          # يتفعّل عند وصول السعر إلى الدخول من الجهة التي بدأ منها
                    if hit:
                        x["st"] = "open"; x["ot"] = t; self.dirty = True
                        self.send(self._say(f"تفعّل الأمر المعلّق، {'اشترينا' if buy else 'بعنا'} الذهب ⚡") + f"\n\n📍 الدخول <code>{x['e']:.2f}</code>   🛑 <code>{x['slp']:.2f}</code>   🎯 <code>{x['tpp']:.2f}</code>\n🕒 {self._tm()}")
                    continue
                bf = self.state["mdef"]["sp"] * pip                              # هامش = السبريد: لا يُعلَن الهدف/الوقف إلا بتجاوز واضح للمستوى (يقلّل فرق التغذية عن وسيطك)
                win = (p >= x["tpp"] + bf) if buy else (p <= x["tpp"] - bf); loss = (p <= x["slp"] - bf) if buy else (p >= x["slp"] + bf)
                if not (win or loss):
                    continue
                tr.remove(x); self.dirty = True
                hist = self.state.setdefault("mhist", []); hist.append(dict(s=x["s"], e=x["e"], r="tp" if win else "sl", t=int(t), p=round(p, 2))); del hist[:-30]
                self.state["mlast"] = dict(x, res="tp" if win else "sl"); self.dirty = True   # لأمر «تراجع» إن كان الإعلان خاطئًا
                if win:
                    self.send(self._say("مبروك الهدف! 🎉🏆") + f"\n\n✅ <b>تحقق الهدف  +{x['tp']:g} نقطة</b>  ({x['tp'] * pip:+.1f}$)\n"
                              f"📍 <code>{x['e']:.2f}</code>  ←  🎯 <code>{x['tpp']:.2f}</code>\n🔎 سجّل البوت السعر <code>{p:.2f}</code>")
                else:
                    self.send(self._say("ولا يهمكم الستوب، بنعوّض إن شاء الله 💪") + f"\n\n🛑 ضُرب الوقف  −{x['sl']:g} نقطة  ({-x['sl'] * pip:+.1f}$)\n"
                              f"📍 <code>{x['e']:.2f}</code>  ←  🛑 <code>{x['slp']:.2f}</code>\n🔎 سجّل البوت السعر <code>{p:.2f}</code>")
                break

    def _set_menu(self):
        """قائمة الأوامر (زر / في تلجرام): عامة للجميع، وإضافية لصاحب البوت في محادثته."""
        if self._menu:
            return
        self._menu = True
        try:
            pub = [{"command": "start", "description": "الاشتراك بالرسائل"}, {"command": "stop", "description": "إلغاء الاشتراك"},
                   {"command": "map", "description": "خريطة أقوى المناطق"}, {"command": "status", "description": "حالة اشتراكك"}]
            self._api("setMyCommands", commands=json.dumps(pub, ensure_ascii=False))
            own = pub + [{"command": "users", "description": "لوحة المستخدمين (حظر/إزالة)"}, {"command": "say", "description": "رسالة لكل المشتركين"},
                         {"command": "help", "description": "أوامر المشرف"}, {"command": "health", "description": "حالة النظام الآن"}]
            self._api("setMyCommands", commands=json.dumps(own, ensure_ascii=False), scope=json.dumps({"type": "chat", "chat_id": int(self.chat_id)}))
        except Exception as ex:
            self.log(f"قائمة الأوامر: {ex}")

    # ───────────── قراءة التحديثات ─────────────
    def start_poll_thread(self):
        """خيط مخصّص لتلقّي الرسائل بالاستطلاع الطويل: أوامر صاحب البوت (مثل «1») تُنفَّذ خلال ~ثانية بدل 5–8 ثوانٍ فيُؤخذ السعر لحظتها."""
        if self._pt:
            return
        self._pt = True

        def run():
            while True:
                t0 = time.time()
                try:
                    self.poll(wait=20)
                except Exception as ex:
                    self.log(f"خيط الاستطلاع: {ex}"); time.sleep(2)
                if time.time() - t0 < 0.5:                                  # ردّ فوري (خطأ/لا شيء): لا تُغرق تلجرام بطلبات متتالية
                    time.sleep(1.0)
        self._pth = threading.Thread(target=run, daemon=True); self._pth.start()

    def poll(self, wait=0):
        """يقرأ رسائل المستخدمين وضغطات الأزرار الجديدة. مع الخيط المخصّص تتجاهل استدعاءات الحلقة الرئيسية."""
        if self._pt and threading.current_thread() is not self._pth:
            return
        try:
            self._set_menu()
            r = requests.get(self.base + "/getUpdates", params={"offset": int(self.state.get("upd", 0)) + 1, "timeout": wait,
                                                                "allowed_updates": json.dumps(["message", "callback_query", "message_reaction"])}, timeout=wait + 8)
            if not r.ok:
                return
            for u in r.json().get("result", []):
                self.state["upd"] = u["update_id"]; self.dirty = True
                cb = u.get("callback_query")
                if cb:
                    self._on_callback(cb); continue
                mr = u.get("message_reaction")
                if mr:
                    self._on_reaction(mr); continue
                m = u.get("message") or {}
                text = (m.get("text") or "").strip()
                chat = m.get("chat") or {}; frm = m.get("from") or {}
                if self.price_fn and not frm.get("is_bot") and str(chat.get("id")) == str(self.chat_id) and str(frm.get("id")) == str(self.chat_id):
                    mt = _TRADE.match(text.translate(_DIG))
                    if mt:
                        self._trade_in(str(chat.get("id")), int(mt.group(2)), [float(g) for g in mt.groups()[2:] if g], bool(mt.group(1)))
                        continue
                    ms = _SET.match(text.translate(_DIG))
                    if ms:
                        self._settings(str(chat.get("id")), float(ms.group(1)), float(ms.group(2)), float(ms.group(3)) if ms.group(3) else None)
                        continue
                    mcal = _CAL.match(text.translate(_DIG))
                    if mcal:
                        self._calibrate(str(chat.get("id")), mcal.group(1))
                        continue
                    mc = _TCMD.match(text)
                    if mc:
                        self._trade_cmd(str(chat.get("id")), mc.group(1))
                        continue
                    if not text.startswith("/") and any(k in m for k in _CONTENT):
                        if _TRYTRADE.match(text.translate(_DIG)):                 # يشبه توصية لكن ناقصة الأرقام: لا تُرسل كنص للمشتركين
                            self._post(str(chat.get("id")), "⚠️ لم أفهم الأرقام فلم أرسل شيئًا. الصيغة: <code>1 60 120</code> أو معلّق <code>1 3920 60 120</code>")
                        else:
                            self._relay(m.get("message_id"))
                        continue
                if not text.startswith("/") or frm.get("is_bot"):
                    continue
                cid = str(chat.get("id")); name = chat.get("title") or frm.get("first_name") or chat.get("first_name") or chat.get("username") or ""
                uname = chat.get("username") or frm.get("username")
                cmd, _, arg = text.partition(" ")
                cmd = cmd.split("@")[0].lower()
                if cid == str(self.chat_id) and self._owner(cid, text, cmd, arg):
                    continue
                if cmd == "/start":
                    if cid in self.banned:
                        self._post(cid, "🚫 غير مسموح لك بالاشتراك في هذا البوت.")
                    elif self.code and arg.strip() != self.code:
                        self._post(cid, "🔒 هذا البوت يتطلب رمز دخول: أرسل /start مع الرمز، مثال: <code>/start 1234</code>")
                    elif cid in self.subs or cid == str(self.chat_id):
                        self._post(cid, "✅ أنت مشترك بالفعل. ستصلك الرسائل لحظة حدوثها.")
                    elif len(self.subs) >= self.max_subs:
                        self._post(cid, "عذراً: اكتمل عدد المشتركين.")
                    else:
                        self.subs[cid] = {"n": name, "u": uname, "t": int(time.time())}
                        self._post(cid, WELCOME); self.log(f"مشترك جديد: {name} ({cid})")
                        self._post(self.chat_id, f"🔔 مشترك جديد: <b>{html.escape(str(name))}</b>" + (f" @{html.escape(uname)}" if uname else "") + f" · <code>{cid}</code>\nللتحكم: /users", silent=True)
                elif cid in self.banned:
                    continue
                elif cmd == "/stop":
                    if self.subs.pop(cid, None) is not None:
                        self._post(cid, "تم إلغاء اشتراكك. أرسل /start متى شئت للعودة.")
                elif cmd in self.handlers:
                    try:
                        self._post(cid, self._px(self.handlers[cmd]()))
                    except Exception as exh:
                        self.log(f"أمر {cmd}: {exh}")
                elif cmd == "/status":
                    self._post(cid, "✅ مشترك — الرسائل تصلك لحظياً." if (cid in self.subs or cid == str(self.chat_id)) else "غير مشترك — أرسل /start.")
        except Exception as ex:
            self.log(f"poll: {ex}")

    def _on_reaction(self, mr):
        """تفاعل مشترك (إيموجي) على رسالة من البوت: إشعار صامت لصاحب البوت، وعدّاد يومي."""
        try:
            cid = str((mr.get("chat") or {}).get("id"))
            if cid == str(self.chat_id):
                return
            new = [r.get("emoji") or "⭐" for r in mr.get("new_reaction", []) if r.get("type") == "emoji" or r.get("emoji") or r.get("type") == "custom_emoji"]
            old = [r.get("emoji") or "⭐" for r in mr.get("old_reaction", [])]
            added = [e for e in new if e not in old]
            if not added:
                return
            u = mr.get("user") or {}
            name = (self.subs.get(cid) or {}).get("n") or u.get("first_name") or u.get("username") or cid
            self.bump("reacts")
            self._post(self.chat_id, f"{''.join(added)}  <b>{html.escape(str(name))}</b> تفاعل مع إحدى رسائل البوت", silent=True)
        except Exception as ex:
            self.log(f"تفاعل: {ex}")

    def _on_callback(self, cb):
        """ضغطة زر من لوحة /users (لصاحب البوت فقط)."""
        try:
            frm = cb.get("from") or {}; msg = cb.get("message") or {}; chat = msg.get("chat") or {}
            if str(chat.get("id")) != str(self.chat_id) or str(frm.get("id")) != str(self.chat_id):
                self._api("answerCallbackQuery", callback_query_id=cb["id"], text="غير مصرح")
                return
            action, _, cid = (cb.get("data") or "").partition(":")
            res = self._act(action, cid)
            self._api("answerCallbackQuery", callback_query_id=cb["id"], text=res)
            t, kb = self.users_view()
            self._api("editMessageText", chat_id=self.chat_id, message_id=msg.get("message_id"), text=t, parse_mode="HTML", reply_markup=json.dumps(kb, ensure_ascii=False))
        except Exception as ex:
            self.log(f"callback: {ex}")
