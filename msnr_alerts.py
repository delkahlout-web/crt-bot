# -*- coding: utf-8 -*-
"""
بوت تنبيهات الأسعار (بوت تلجرام مستقل بتوكنه): تكتب له رقماً (مثل 4050) فينبّهك عندما يقترب السعر منه بمسافة صغيرة، ثم عند وصوله.
  • السعر من مصدر البوت الحي نفسه (Swissquote) مع معايرتك (سعر X) فيطابق منصتك.
  • مخصَّص لصاحب البوت وحده؛ التنبيهات محفوظة في الحالة فتبقى بعد أي إعادة تشغيل.
"""
import html
import json
import re
import threading
import time

import requests

_DIG = str.maketrans("٠١٢٣٤٥٦٧٨٩٫", "0123456789.")
_ADD = re.compile(r"^\s*(\d{3,5}(?:\.\d+)?)(?:\s+(\d+(?:\.\d+)?))?\s*$")
_DEL = re.compile(r"^\s*(?:حذف|الغاء|إلغاء|مسح|/del)\s+(\d{3,5}(?:\.\d+)?|الكل)\s*$")
_NEAR = re.compile(r"^\s*(?:قرب|/near)\s+(\d+(?:\.\d+)?)\s*$")
_CAL = re.compile(r"^\s*(?:سعر|معايرة)(?:\s+(\d{4,5}(?:\.\d+)?|صفر))?\s*$")
HELP = ("🔔 <b>بوت تنبيهات الأسعار</b>\n┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\n"
        "اكتب لي السعر الذي تريد التنبيه عنده، مثال:\n"
        "<code>4050</code> ← أنبّهك عند اقتراب الذهب منه ثم عند وصوله\n"
        "<code>4050 5</code> ← نفسه لكن أنبّهك على بُعد 5$\n"
        "┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\n"
        "<code>قائمة</code> — تنبيهاتك الحالية\n"
        "<code>حذف 4050</code> — حذف تنبيه · <code>حذف الكل</code>\n"
        "<code>قرب 3</code> — مسافة التنبيه الافتراضية بالدولار\n"
        "<code>سعر</code> — السعر الآن · <code>سعر 4041.32</code> — معايرة على منصتك\n"
        "<i>الأسعار من وسيط حقيقي لحظي، وتتطابق مع منصتك بعد المعايرة.</i>")


class PriceAlerts:
    def __init__(self, token, owner_id, state, price_fn, log=print):
        self.base = f"https://api.telegram.org/bot{token}"
        self.owner = str(owner_id); self.state = state; self.price_fn = price_fn; self.log = log
        self.al = state.setdefault("pa", [])                       # [{id,p,near,st}]
        self.cfg = state.setdefault("pacfg", {"near": 3.0})
        self.dirty = False; self.prev = None; self.started = False; self._menu = False
        self.sent = 0

    # ───────────── تلجرام ─────────────
    def _post(self, text, silent=False):
        try:
            r = requests.post(self.base + "/sendMessage", data={"chat_id": self.owner, "text": text, "parse_mode": "HTML", "disable_notification": "true" if silent else "false"}, timeout=15)
            if r.ok:
                self.sent += 1
            return r.ok
        except Exception as ex:
            self.log(f"تنبيهات: {ex}")
            return False

    def shown(self, internal):
        return internal + float(self.state.get("pshift") or 0.0)

    # ───────────── التنبيه ─────────────
    def check(self, internal):
        """يُستدعى مع كل عيّنة سعر (~4ث): قرب ← وصول، مع كشف العبور بين عيّنتين."""
        if internal is None:
            return
        cur = self.shown(internal); prev = self.prev; self.prev = cur
        for a in list(self.al):
            p = a["p"]; d = abs(cur - p); near = a.get("near", self.cfg["near"])
            crossed = prev is not None and (prev - p) * (cur - p) <= 0
            if crossed or d <= 0.3:
                self._post(f"🎯 <b>وصل السعر إلى</b> <code>{p:.2f}</code>\n┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\nالآن <code>{cur:.2f}</code>")
                self.al.remove(a); self.dirty = True
                self.log(f"تنبيه وصول {p:.2f}")
            elif d <= near and a.get("st") != "near":
                self._post(f"⚠️ <b>السعر قرب من</b> <code>{p:.2f}</code>\n┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\nالآن <code>{cur:.2f}</code>  ·  يبعد <b>{d:.2f}$</b> ({d * 10:.0f} نقطة) {'▲' if p > cur else '▼'}")
                a["st"] = "near"; self.dirty = True
                self.log(f"تنبيه قرب {p:.2f}")
            elif a.get("st") == "near" and d > near * 3:           # ابتعد كثيراً: يُنبَّه من جديد عند الاقتراب التالي
                a["st"] = "armed"; self.dirty = True

    # ───────────── الأوامر ─────────────
    def handle(self, text):
        t = text.strip().translate(_DIG)
        low = t.lower()
        if low in ("/start", "/help", "مساعدة", "help"):
            self._post(HELP); return
        if low in ("/list", "قائمة", "تنبيهاتي", "/alerts"):
            self._list(); return
        m = _DEL.match(t)
        if m:
            self._delete(m.group(1)); return
        m = _NEAR.match(t)
        if m:
            self.cfg["near"] = max(0.3, min(100.0, float(m.group(1)))); self.dirty = True
            self._post(f"✅ المسافة الافتراضية للتنبيه: <b>{self.cfg['near']:g}$</b>", silent=True); return
        m = _CAL.match(t)
        if m:
            self._price(m.group(1)); return
        m = _ADD.match(t)
        if m:
            self._add(float(m.group(1)), float(m.group(2)) if m.group(2) else None); return
        self._post("لم أفهم. اكتب السعر فقط، مثال: <code>4050</code>، أو اكتب <code>مساعدة</code>.", silent=True)

    def _now(self):
        pr = self.price_fn() if self.price_fn else None
        return pr[0] if pr else None

    def _add(self, p, near):
        cur = self._now()
        if cur is None:
            self._post("⚠️ لا يوجد سعر حديث الآن، أعد المحاولة بعد لحظات."); return
        cur = self.shown(cur)
        if not 500 < p < 20000 or abs(p - cur) > cur * 0.5:
            self._post(f"⚠️ الرقم <code>{p:g}</code> بعيد جداً عن السعر الآن (<code>{cur:.2f}</code>). تأكد منه."); return
        if len(self.al) >= 30:
            self._post("⚠️ وصلتَ إلى 30 تنبيهاً. احذف بعضها أولاً (<code>حذف الكل</code>)."); return
        near = near if near is not None else self.cfg["near"]
        self.al[:] = [a for a in self.al if abs(a["p"] - p) > 0.05]
        self.al.append(dict(id=int(time.time()), p=p, near=near, st="armed")); self.dirty = True
        self._post(f"🔔 <b>تنبيه جديد</b>\n┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\nعند <code>{p:.2f}</code>  {'▲' if p > cur else '▼'}\nالسعر الآن <code>{cur:.2f}</code> · يبعد {abs(p - cur):.2f}$\nأنبّهك على بُعد <b>{near:g}$</b> وعند الوصول.", silent=True)
        self.log(f"تنبيه جديد {p:.2f} قرب {near:g}")

    def _list(self):
        cur = self._now(); cur = self.shown(cur) if cur is not None else None
        if not self.al:
            self._post("لا توجد تنبيهات. اكتب سعرًا مثل <code>4050</code>.", silent=True); return
        rows = []
        for a in sorted(self.al, key=lambda a: a["p"], reverse=True):
            d = "" if cur is None else f"  ·  يبعد {abs(a['p'] - cur):.2f}$ {'▲' if a['p'] > cur else '▼'}"
            rows.append(f"• <code>{a['p']:.2f}</code>{d}  ·  قرب {a.get('near', self.cfg['near']):g}$")
        self._post("📋 <b>تنبيهاتك</b>\n┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\n" + "\n".join(rows) + ("" if cur is None else f"\n┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\nالسعر الآن <code>{cur:.2f}</code>"), silent=True)

    def _delete(self, what):
        if what == "الكل":
            n = len(self.al); self.al.clear()
        else:
            p = float(what); n = len([a for a in self.al if abs(a["p"] - p) <= 0.05]); self.al[:] = [a for a in self.al if abs(a["p"] - p) > 0.05]
        self.dirty = True
        self._post(f"🗑 حُذف {n} تنبيه." if n else "لا يوجد تنبيه بهذا السعر.", silent=True)

    def _price(self, arg):
        cur = self._now()
        if cur is None:
            self._post("⚠️ لا يوجد سعر حديث الآن."); return
        sh = float(self.state.get("pshift") or 0.0)
        if arg is None:
            self._post(f"💲 السعر الآن: <code>{cur + sh:.2f}</code>  (معايرتك {sh:+.2f}$)", silent=True); return
        if arg == "صفر":
            self.state["pshift"] = 0.0; self.dirty = True
            self._post("✅ أُلغيت المعايرة.", silent=True); return
        x = float(arg)
        if not 1000 < x < 20000 or abs(x - cur) > 15:
            self._post(f"⚠️ الرقم بعيد عن سعر البوت ({cur:.2f}). تأكد منه."); return
        self.state["pshift"] = round(x - cur, 3); self.dirty = True
        self._post(f"✅ ضُبطت المعايرة: <b>{x - cur:+.2f}$</b>. الأسعار تطابق منصتك عند <code>{x:.2f}</code>.", silent=True)

    # ───────────── الاستقبال (استطلاع طويل في خيط) ─────────────
    def poll(self, wait=20):
        r = requests.get(self.base + "/getUpdates", params={"offset": int(self.state.get("pa_upd", 0)) + 1, "timeout": wait, "allowed_updates": json.dumps(["message"])}, timeout=wait + 8)
        if not r.ok:
            return
        for u in r.json().get("result", []):
            self.state["pa_upd"] = u["update_id"]; self.dirty = True
            m = u.get("message") or {}
            chat = m.get("chat") or {}; frm = m.get("from") or {}; text = (m.get("text") or "").strip()
            if frm.get("is_bot") or not text:
                continue
            if str(chat.get("id")) != self.owner:                   # للمالك وحده
                continue
            try:
                self.handle(text)
            except Exception as ex:
                self.log(f"تنبيهات أمر: {ex}")
                self._post("تعذّر تنفيذ الأمر.", silent=True)

    def start(self):
        if self.started:
            return
        self.started = True

        def run():
            while True:
                t0 = time.time()
                try:
                    self.poll(20)
                except Exception as ex:
                    self.log(f"تنبيهات استقبال: {ex}"); time.sleep(2)
                if time.time() - t0 < 0.5:
                    time.sleep(1.0)
        threading.Thread(target=run, daemon=True).start()
        self.log("بوت التنبيهات يعمل")
