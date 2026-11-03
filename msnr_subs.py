# -*- coding: utf-8 -*-
"""
مشتركو البوت: أي شخص يفتح البوت ويضغط /start يصله كل ما يصل صاحب البوت في اللحظة نفسها (/stop للإلغاء).
  • الإرسال للمشتركين في خيوط متوازية، وصاحب البوت يُرسَل له أولاً دون انتظارهم.
  • رسائل الأعطال والصيانة (private=True) لا تصل إلا لصاحب البوت.
  • من يحظر البوت يُحذف تلقائياً. رمز دخول اختياري (subscribeCode) وحدّ أقصى للمشتركين (maxSubs).
"""
import json
import threading
import time

import requests

WELCOME = ("🟧 <b>أهلاً بك في MSNR</b>\n▰▰▰▰▰▰▰▰▰▰▰▰▰▰\n"
           "ستصلك لحظة حدوثها رسائل مستويات الذهب:\n"
           "⚠️ قرب  ·  ⚡ لمس  ·  ✅ رفض مؤكَّد  ·  🔁 إعادة اختبار\n"
           "🎯 وصفقات جلسة 4H مع الدخول والوقف والهدف\n┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
           "للإلغاء /stop  ·  للحالة /status  ·  لخريطة المناطق /map\n"
           "<i>المعلومات للتعليم وليست توصية مالية.</i>")


class Broadcast:
    def __init__(self, tg, state, code="", max_subs=100, log=print):
        self.tg = tg; self.state = state; self.code = str(code or ""); self.max_subs = int(max_subs); self.log = log
        self.subs = state.setdefault("subs", {})
        state.setdefault("upd", 0)
        self.dirty = False
        self.handlers = {}                                           # أوامر إضافية: {"/map": دالة تعيد النص}
        self.base = tg.base; self.token = tg.token; self.chat_id = tg.chat_id
        self._lock = threading.Lock()

    # ───────────── إرسال ─────────────
    def send(self, text, silent=False, private=False):
        if not private:
            for cid in list(self.subs):
                if cid != str(self.chat_id):
                    threading.Thread(target=self._send_one, args=(cid, text, silent), daemon=True).start()
        return self.tg.send(text, silent)

    def _post(self, cid, text, silent=False):
        return requests.post(self.base + "/sendMessage", data={"chat_id": cid, "text": text, "parse_mode": "HTML", "disable_web_page_preview": "true",
                                                              "disable_notification": "true" if silent else "false"}, timeout=15)

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

    # ───────────── الأوامر ─────────────
    def poll(self):
        """يقرأ رسائل المستخدمين الجديدة (/start /stop /status). استدعاء خفيف (بلا انتظار طويل)."""
        try:
            r = requests.get(self.base + "/getUpdates", params={"offset": int(self.state.get("upd", 0)) + 1, "timeout": 0, "allowed_updates": json.dumps(["message"])}, timeout=8)
            if not r.ok:
                return
            for u in r.json().get("result", []):
                self.state["upd"] = u["update_id"]; self.dirty = True
                m = u.get("message") or {}
                text = (m.get("text") or "").strip()
                chat = m.get("chat") or {}; frm = m.get("from") or {}
                if not text.startswith("/") or frm.get("is_bot"):
                    continue
                cid = str(chat.get("id")); name = chat.get("title") or chat.get("username") or chat.get("first_name") or ""
                cmd, _, arg = text.partition(" ")
                cmd = cmd.split("@")[0].lower()
                if cmd == "/start":
                    if self.code and arg.strip() != self.code:
                        self._post(cid, "🔒 هذا البوت يتطلب رمز دخول: أرسل /start مع الرمز، مثال: <code>/start 1234</code>")
                    elif cid in self.subs or cid == str(self.chat_id):
                        self._post(cid, "✅ أنت مشترك بالفعل. ستصلك الرسائل لحظة حدوثها.")
                    elif len(self.subs) >= self.max_subs:
                        self._post(cid, "عذراً: اكتمل عدد المشتركين.")
                    else:
                        self.subs[cid] = {"n": name, "t": int(time.time())}
                        self._post(cid, WELCOME); self.log(f"مشترك جديد: {name} ({cid})")
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
