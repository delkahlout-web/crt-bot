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
              "<code>1 وقف هدف</code> — شراء الذهب الآن للجميع، مثال: <code>1 60 120</code>\n"
              "<code>2 وقف هدف</code> — بيع الذهب الآن للجميع، مثال: <code>2 60 120</code>\n"
              "(الوقف والهدف بالنقاط، والنقطة = 0.1$؛ اكتبها مباشرة بلا أمر)\n"
              "/map — خريطة المناطق\n/health — حالة النظام الآن")
_TRADE = re.compile(r"^\s*([12])\s*[\s,،/]+\s*(\d+(?:\.\d+)?)\s*[\s,،/]+\s*(\d+(?:\.\d+)?)\s*$")
_DIG = str.maketrans("٠١٢٣٤٥٦٧٨٩٫", "0123456789.")


def _ago(t):
    d = max(0, int(time.time()) - int(t or 0))
    return f"{d // 86400} يوم" if d >= 86400 else f"{d // 3600} س" if d >= 3600 else f"{max(d // 60, 1)} د"


class Broadcast:
    def __init__(self, tg, state, code="", max_subs=100, log=print):
        self.tg = tg; self.state = state; self.code = str(code or ""); self.max_subs = int(max_subs); self.log = log
        self.subs = state.setdefault("subs", {})
        self.banned = state.setdefault("banned", {})
        state.setdefault("upd", 0)
        self.dirty = False
        self.handlers = {}                                           # أوامر إضافية: {"/map": دالة تعيد النص}
        self.owner_handlers = {}                                     # أوامر لصاحب البوت فقط: {"/health": دالة}
        self.trade_handler = None                                    # دالة (side, وقف, هدف) ← نص التوصية؛ تُفعَّل بكتابة «1 60 120» مباشرة من صاحب البوت
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

    def send(self, text, silent=False, private=False):
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

    def _trade(self, cid, side, sl, tp):
        """توصية فورية من صاحب البوت: 1 = شراء، 2 = بيع، ثم وقف وهدف بالنقاط. تصل لكل المشتركين وله."""
        if not (0 < sl <= 2000 and 0 < tp <= 5000):
            self._post(cid, "⚠️ الوقف أو الهدف خارج المدى المعقول. أعد الكتابة، مثال: <code>1 60 120</code>")
            return
        try:
            text = self.trade_handler(side, sl, tp)
        except Exception as ex:
            self.log(f"توصية: {ex}"); self._post(cid, f"تعذّر: {ex}"); return
        if not text:
            self._post(cid, "⚠️ لا يوجد سعر حديث الآن، لم يُرسل شيء. أعد المحاولة بعد لحظات.")
            return
        self.send(text)
        self._post(cid, f"✅ أُرسلت التوصية لـ {len([c for c in self.subs if c != str(self.chat_id)])} مشترك", silent=True)
        self.log(f"توصية يدوية: {'شراء' if side == 1 else 'بيع'} وقف {sl:g} هدف {tp:g}")

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
    def poll(self):
        """يقرأ رسائل المستخدمين وضغطات الأزرار الجديدة. استدعاء خفيف (بلا انتظار طويل)."""
        try:
            self._set_menu()
            r = requests.get(self.base + "/getUpdates", params={"offset": int(self.state.get("upd", 0)) + 1, "timeout": 0,
                                                                "allowed_updates": json.dumps(["message", "callback_query"])}, timeout=8)
            if not r.ok:
                return
            for u in r.json().get("result", []):
                self.state["upd"] = u["update_id"]; self.dirty = True
                cb = u.get("callback_query")
                if cb:
                    self._on_callback(cb); continue
                m = u.get("message") or {}
                text = (m.get("text") or "").strip()
                chat = m.get("chat") or {}; frm = m.get("from") or {}
                if self.trade_handler and not frm.get("is_bot") and str(chat.get("id")) == str(self.chat_id) and str(frm.get("id")) == str(self.chat_id):
                    mt = _TRADE.match(text.translate(_DIG))
                    if mt:
                        self._trade(str(chat.get("id")), int(mt.group(1)), float(mt.group(2)), float(mt.group(3)))
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
                        self._post(cid, self.handlers[cmd]())
                    except Exception as exh:
                        self.log(f"أمر {cmd}: {exh}")
                elif cmd == "/status":
                    self._post(cid, "✅ مشترك — الرسائل تصلك لحظياً." if (cid in self.subs or cid == str(self.chat_id)) else "غير مشترك — أرسل /start.")
        except Exception as ex:
            self.log(f"poll: {ex}")

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
