# -*- coding: utf-8 -*-
"""
SH v2 + RSI — تشغيل على GitHub Actions (مرة كل 5 دقائق). نظام منفصل تماماً عن CRT:
ملف إعداداته sh_config.json، وحالته sh_state.json، ورسائله بعنوان «SH v2 + RSI».
الأسعار من Yahoo (GC=F) مصحّحة بفرق الذهب الفوري الحالي ليقترب من شارت TradingView.

    python sh_actions.py              تشغيل مرة واحدة
    python sh_actions.py --test       رسالة تجربة
    python sh_actions.py --history 3  أحداث آخر 3 أيام على الشاشة بدون إرسال
"""
import json, os, sys, time, datetime as dt
import pandas as pd
import requests
import yfinance as yf

from sh_engine import run_engine, DEFAULTS
from sh_messages import message, ev_key, NAME, fmt_time
import crt_bot as core                      # Telegram فقط

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_PATH = os.path.join(HERE, "sh_state.json")
SPOT_URL = "https://api.gold-api.com/price/{}"
LIVE = {}                                   # آخر سعر حي (شمعة غير مكتملة) لكل رمز


def log(msg):
    print(f"[{dt.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


def load_state():
    if os.path.exists(STATE_PATH):
        return json.load(open(STATE_PATH, encoding="utf-8"))
    return {"sent": []}


def save_state(st):
    st["sent"] = st["sent"][-800:]
    json.dump(st, open(STATE_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def yf_candles(ticker, interval, period, minutes):
    """شموع مكتملة فقط: قائمة dict(time=epoch UTC، open، high، low، close)."""
    last = None
    for attempt in range(4):
        try:
            d = yf.download(ticker, period=period, interval=interval, progress=False, auto_adjust=False)
            d.columns = [c[0] if isinstance(c, tuple) else c for c in d.columns]
            d = d[["Open", "High", "Low", "Close"]].dropna()
            if len(d) < 200:
                raise RuntimeError(f"بيانات قليلة لـ {ticker} {interval}: {len(d)}")
            LIVE[ticker] = float(d.Close.values[-1])
            ts = ((d.index.tz_convert("UTC") - pd.Timestamp("1970-01-01", tz="UTC")) // pd.Timedelta(seconds=1)).tolist()   # آمن مع أي وحدة زمنية لـ pandas
            now = time.time()
            out = []
            for t, o, h, l, c in zip(ts, d.Open.values, d.High.values, d.Low.values, d.Close.values):
                if t + minutes * 60 <= now:
                    out.append(dict(time=int(t), open=float(o), high=float(h), low=float(l), close=float(c)))
            return out
        except Exception as ex:
            last = ex
            time.sleep(15 * (attempt + 1))
    raise RuntimeError(f"فشل جلب {ticker} {interval}: {last}")


def commit_state():
    """داخل GitHub Actions: يحفظ الحالة فوراً (3 محاولات) حتى لا تتكرر الرسائل ولا يظن الحارس أن البوت معلّق."""
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return
    try:
        import subprocess
        run = lambda *a: subprocess.run(a, cwd=HERE, capture_output=True, text=True, timeout=60)
        run("git", "config", "user.name", "sh-bot"); run("git", "config", "user.email", "sh-bot@users.noreply.github.com")
        run("git", "add", "sh_state.json")
        if run("git", "diff", "--cached", "--quiet").returncode == 0:
            return
        run("git", "commit", "-m", "sh state")
        for k in range(3):
            run("git", "pull", "--rebase", "-q")
            if run("git", "push").returncode == 0:
                return
            time.sleep(3 * (k + 1))
        log("تعذّر دفع الحالة بعد 3 محاولات")
    except Exception as ex:
        log(f"تعذّر حفظ الحالة: {ex}")


def spot_quote(sym, ref):
    try:
        r = requests.get(SPOT_URL.format(sym), timeout=12, headers={"User-Agent": "Mozilla/5.0"})
        p = float(r.json()["price"])
        return None if (ref and abs(p - ref) / ref > 0.06) else p
    except Exception:
        return None


def calc_offset(state, sym, live):
    """offset = سعر الآجل الحي - سعر الفوري الآن، منعّم عبر التشغيلات، ويُحدَّث فقط والسوق نشط."""
    old = state.get("off")
    q = spot_quote(sym, live) if live else None
    if q is None:
        return old                                   # قد يكون None إن لم يُقَس الفرق بعد (السوق مغلق)
    raw = live - q
    if abs(raw) > 60:                                # قراءة شاذة
        return old
    new = raw if old is None else 0.7 * old + 0.3 * raw
    log(f"تصحيح: آجل {live:.2f} - فوري {q:.2f} = {raw:.2f}$ (المعتمد {new:.2f}$)")
    return new


PERSIST = {}                  # شموع فوري محفوظة من التشغيل السابق (فيبدأ التشغيل الجديد دافئاً)
SPOT_BUF = []                 # (epoch, price) عينات gold-api لبناء شموع 5 دقائق لحظية
START_T = time.time()


def sample_spot(sym="XAU"):
    try:
        p = float(requests.get(SPOT_URL.format(sym), timeout=8, headers={"User-Agent": "Mozilla/5.0"}).json()["price"])
        if p > 0:
            SPOT_BUF.append((time.time(), p)); del SPOT_BUF[:-6000]
    except Exception:
        pass


def spot_bars(now):
    """شموع 5 دقائق مكتملة من عينات الذهب الفوري (يُشترط تغطية كافية للنافذة حتى لا نبني شمعة من عينة وحيدة)."""
    groups = {}
    for t, p in SPOT_BUF:
        groups.setdefault(int(t) // 300 * 300, []).append((t, p))
    out = []
    for st in sorted(groups):
        g = groups[st]; end = st + 300
        if end > now or len(g) < 3 or g[0][0] - st > 150 or end - g[-1][0] > 100:
            continue
        ps = [p for _, p in g]
        out.append(dict(time=st, open=ps[0], high=max(ps), low=min(ps), close=ps[-1]))
    have = {b["time"] for b in out}
    out += [b for t, b in PERSIST.items() if t not in have and t + 300 <= now and now - t < 3 * 3600]
    return sorted(out, key=lambda b: b["time"])


def merge_spot(yb, sb, now):
    """تاريخ Yahoo (يُحذف آخر 20 دقيقة منه لأنها قد تكون ناقصة) مُنزَّل إلى مستوى الذهب الفوري بوسيط فرق الإغلاقات في التقاطع، ثم تُلصق شموع الفوري."""
    yb = [b for b in yb if b["time"] + 300 <= now - 1200]
    if not yb or not sb or now - (yb[-1]["time"] + 300) > 3600:
        return yb, None
    sd = {b["time"]: b for b in sb}
    diffs = sorted(b["close"] - sd[b["time"]]["close"] for b in yb[-48:] if b["time"] in sd)
    if len(diffs) < 3:
        return yb, None
    s = diffs[len(diffs) // 2]
    new = [b for b in sb if b["time"] > yb[-1]["time"]]
    if not new or (new[0]["time"] - yb[-1]["time"]) // 300 > 5:
        return yb, None
    shifted = [dict(b, open=b["open"] - s, high=b["high"] - s, low=b["low"] - s, close=b["close"] - s) for b in yb]
    filled = []; prev = yb[-1]["time"]; lc = yb[-1]["close"] - s; gaps = 0
    for b in new:
        t = prev + 300
        while t < b["time"]:
            filled.append(dict(time=t, open=lc, high=lc, low=lc, close=lc)); t += 300; gaps += 1
        filled.append(b); prev = b["time"]; lc = b["close"]
    if gaps > 4:
        return yb, None
    return shifted + filled, s


def realtime_5m(now):
    """شموع 5 دقائق مكتملة لحظياً من الذهب الرقمي PAXG (Kraken ثم OKX). Yahoo متأخر نحو 10–15 دقيقة، وهذا بلا تأخير."""
    try:
        r = requests.get("https://api.kraken.com/0/public/OHLC", params={"pair": "PAXGUSD", "interval": 5}, timeout=15).json()
        rows = list(r["result"].values())[0]
        out = [dict(time=int(x[0]), open=float(x[1]), high=float(x[2]), low=float(x[3]), close=float(x[4])) for x in rows]
        out = [b for b in out if b["time"] + 300 <= now]
        if len(out) > 100:
            return out, "Kraken"
    except Exception as ex:
        log(f"Kraken فشل: {ex}")
    try:
        r = requests.get("https://www.okx.com/api/v5/market/candles", params={"instId": "PAXG-USDT", "bar": "5m", "limit": 300}, timeout=15).json()
        out = sorted((dict(time=int(x[0]) // 1000, open=float(x[1]), high=float(x[2]), low=float(x[3]), close=float(x[4])) for x in r["data"] if x[8] == "1"),
                     key=lambda b: b["time"])
        if len(out) > 100:
            return out, "OKX"
    except Exception as ex:
        log(f"OKX فشل: {ex}")
    return None, None


def merge_realtime(yb, rt, now):
    """يلصق شموع اللحظي بعد آخر شمعة موثوقة من Yahoo (تُحذف آخر 20 دقيقة منه لأنها قد تكون ناقصة) بعد مواءمة المستوى."""
    yb = [b for b in yb if b["time"] + 300 <= now - 1200]
    if not rt or not yb or now - (yb[-1]["time"] + 300) > 3600:         # لا بيانات Yahoo حديثة = السوق مغلق
        return yb, None
    rtd = {b["time"]: b for b in rt}
    diffs = sorted(b["close"] - rtd[b["time"]]["close"] for b in yb[-48:] if b["time"] in rtd)
    if len(diffs) < 2:
        return yb, None
    s = diffs[len(diffs) // 2]
    new = [dict(b, open=b["open"] + s, high=b["high"] + s, low=b["low"] + s, close=b["close"] + s) for b in rt if b["time"] > yb[-1]["time"]]
    return yb + new, s


def resample(bars, minutes):
    """يجمّع شموع 5 دقائق إلى فريم أكبر (مجموعات مكتملة فقط)."""
    sec = minutes * 60; n = sec // 300; groups = {}
    for b in bars:
        groups.setdefault(b["time"] // sec * sec, []).append(b)
    out = []
    for t in sorted(groups):
        g = groups[t]
        if len(g) == n:
            out.append(dict(time=t, open=g[0]["open"], high=max(x["high"] for x in g), low=min(x["low"] for x in g), close=g[-1]["close"]))
    return out


def shift(bars, off):
    if not off:
        return bars
    return [dict(b, open=b["open"] - off, high=b["high"] - off, low=b["low"] - off, close=b["close"] - off) for b in bars]


def params(cfg):
    P = {**DEFAULTS, **cfg.get("strategy", {})}
    if "sessions" in cfg.get("strategy", {}):                  # دمج الجلسات بدل الاستبدال الكامل
        P["sessions"] = {k: {**DEFAULTS["sessions"][k], **cfg["strategy"]["sessions"].get(k, {})} for k in DEFAULTS["sessions"]}
    return P


def compute(cfg, state):
    P = params(cfg)
    now = time.time()
    chart = yf_candles(cfg["ticker"], "5m", "30d", P["chartTF"])
    live, src, merged_ok = LIVE.get(cfg["ticker"]), "Yahoo", False
    cfg["_meta"] = dict(mode="closed", src="Yahoo", age=None)
    if P["chartTF"] == 5 and P["mainTF"] == 15:
        merged, s = merge_spot(chart, spot_bars(now), now)
        if s is not None:
            chart = merged; merged_ok = True; src = "الذهب الفوري"
            main = resample(chart, 15)
            age = (now - chart[-1]["time"] - 300) / 60
            cfg["_meta"] = dict(mode="live", src=src, age=age)
            cfg["dataNote"] = f"الأسعار: Yahoo (تاريخ) + الذهب الفوري (لحظي)، مواءمة {s:+.1f}$ — تقارب شارتك بفرق نحو 1$: اعتمد على المسافات."
            log(f"مصدر الأسعار: Yahoo (تاريخ) + الذهب الفوري (لحظي) | آخر شمعة مغلقة قبل {age:.1f} دقيقة | مواءمة {s:+.2f}$ | عينات {len(SPOT_BUF)}")
        else:
            main = yf_candles(cfg["ticker"], "15m", "30d", P["mainTF"])
            age_y = (now - chart[-1]["time"] - 300) / 60
            if age_y >= 40:
                mode = "closed"
            else:
                mode = "warming" if now - START_T < 2700 else "degraded"        # أول 45 دقيقة: تجميع عينات الفوري
            cfg["_meta"] = dict(mode=mode, src="Yahoo", age=age_y)
            log(f"الدمج اللحظي غير متاح ({mode}): نعتمد Yahoo المتأخر")
    else:
        main = yf_candles(cfg["ticker"], "15m", "30d", P["mainTF"])
    if not merged_ok and cfg.get("spotCorrection", True):
        fresh = (now - (chart[-1]["time"] + 300)) <= 1500
        off = calc_offset(state, cfg.get("spotSym", "XAU"), live) if fresh else state.get("off")
        if off is not None:
            state["off"] = off
            chart, main = shift(chart, off), shift(main, off)
            cfg["dataNote"] = f"الأسعار من Yahoo (متأخرة 10–15 دقيقة) مصحّحة بفرق الذهب الفوري ({off:.1f}$): اعتمد على المسافات."
        else:
            cfg["dataNote"] = "الأسعار بلا تصحيح الآن (السوق مغلق)، وقد تزيد 15–28$ عن شارتك: اعتمد على المسافات."
    return run_engine(chart, main, P), chart[-1]["time"], P


def code_changed():
    """هل على GitHub نسخة أحدث من ملفات البوت؟ (للتحديث الذاتي دون تدخل يدوي)"""
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return False
    try:
        import subprocess
        run = lambda *a: subprocess.run(a, cwd=HERE, capture_output=True, text=True, timeout=60)
        run("git", "fetch", "-q", "origin", "main")
        d = run("git", "diff", "--name-only", "HEAD", "origin/main", "--", "sh_engine.py", "sh_messages.py", "sh_actions.py", "sh_config.json", "crt_bot.py")
        return bool(d.stdout.strip())
    except Exception:
        return False


def heartbeat_text(cfg, P):
    m = cfg.get("_meta", {}); tz = cfg.get("displayTz", "Asia/Hebron")
    now = fmt_time(time.time(), tz)
    if m.get("mode") == "live":
        data = f"📡 البيانات لحظية ({m['src']}) — آخر شمعة مغلقة قبل {m['age']:.1f} دقيقة ✅"
    elif m.get("mode") == "warming":
        data = "⏳ البوت يبدأ للتو ويجمع الأسعار اللحظية (نحو 45 دقيقة)؛ مؤقتاً البيانات متأخرة 10–15 دقيقة"
    elif m.get("mode") == "degraded":
        data = "⚠️ المصدر اللحظي معطّل الآن؛ البيانات متأخرة 10–15 دقيقة (قد تتأخر الإشارات)"
    else:
        data = "🌙 السوق مغلق الآن (عطلة نهاية الأسبوع أو استراحة)، والبوت يعمل وينتظر الافتتاح"
    return (f"🟦 <b>{NAME} — البوت حيّ ✅</b>\n{data}\n"
            f"⚙️ الإعداد: طوكيو كل المستويات | لندن/نيويورك مستويات 15m | TP1 {P['tp1R']:g}R / TP2 {P['rr']:g}R\n🕒 {now}")


def main():
    cfg = json.load(open(os.path.join(HERE, "sh_config.json"), encoding="utf-8"))
    cfg["telegramToken"] = (os.environ.get("TELEGRAM_TOKEN") or cfg.get("telegramToken", "")).strip()
    cfg["chatId"] = str(cfg.get("chatId") or os.environ.get("TELEGRAM_CHAT_ID") or "").strip()   # معرّف المحادثة (ليس سرّاً) من ملف الإعدادات أولاً
    args = sys.argv[1:]
    tg = core.Telegram(cfg["telegramToken"], cfg["chatId"])
    if "--test" in args:
        t = cfg["telegramToken"]
        log(f"فحص الإعدادات: طول التوكن {len(t)} (المتوقع 46) | معرّف المحادثة: {cfg['chatId']!r}")
        ok = tg.send(f"🟦 {NAME} (GitHub): الاتصال بتلجرام يعمل.")
        print("Telegram:", "OK" if ok else "فشل")
        sys.exit(0 if ok else 1)                    # تظهر الخطوة حمراء في GitHub عند الفشل
    state = load_state()
    if "--history" in args:
        evs, last_t, P = compute(cfg, state)
        k = args.index("--history")
        days = int(args[k + 1]) if len(args) > k + 1 else 3
        for e in evs:
            if e["bar_time"] >= last_t - days * 86400:
                print("─" * 40)
                print(message(e, cfg, P).replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", ""))
        return
    # GitHub يؤخر الجدولة أحياناً 25–40 دقيقة، فكل تشغيل يفحص كل دقيقة لمدة --loop دقيقة ليغطي الفجوات
    loop_min = float(args[args.index("--loop") + 1]) if "--loop" in args else 0
    deadline = time.time() + loop_min * 60
    sent = set(state["sent"])
    PERSIST.update({int(b["time"]): b for b in state.get("spot", [])})
    max_age = cfg.get("maxAgeMin", 60) * 60
    beat_every = float(cfg.get("heartbeatHours", 2)) * 3600
    errs = 0; last_chk = time.time()
    while True:
        try:
            sample_spot(cfg.get("spotSym", "XAU"))
            evs, last_t, P = compute(cfg, state)
            errs = 0
            fresh = [e for e in evs if e["bar_time"] >= time.time() - max_age and ev_key(e) not in sent]
            log(f"{NAME} | آخر شمعة مغلقة: {dt.datetime.fromtimestamp(last_t, dt.timezone.utc):%Y-%m-%d %H:%M} UTC | أحداث جديدة: {len(fresh)}")
            for e in fresh:
                txt = message(e, cfg, P)
                if txt and tg.send(txt):
                    log(f"أُرسل: {e['kind']} {ev_key(e)}")
                    sent.add(ev_key(e))
            state["sent"] = list(sent)
            state["spot"] = spot_bars(time.time())[-24:]                  # آخر ساعتين تقريباً (24 شمعة) لتبدأ التشغيلات التالية دافئة
            now = time.time(); meta = cfg.get("_meta", {})
            dirty = bool(fresh)
            # تنبيه عند تعطّل المصدر اللحظي أثناء السوق (مرة كل ساعة كحد أقصى)
            if meta.get("mode") == "degraded" and now - state.get("warn", 0) >= 3600:
                if tg.send("⚠️ <b>تنبيه SH:</b> المصدر اللحظي للأسعار معطّل والسوق مفتوح. البيانات الآن متأخرة 10–15 دقيقة، فقد تتأخر الإشارات. سأعود للوضع الطبيعي تلقائياً حين يعود المصدر."):
                    state["warn"] = now; dirty = True
            # نبض: «البوت حيّ» كل ساعتين (صامت بلا صوت)
            if beat_every > 0 and now - state.get("beat", 0) >= beat_every:
                if tg.send(heartbeat_text(cfg, P), silent=True):
                    state["beat"] = now; dirty = True
            save_state(state)
            if dirty:
                commit_state()
        except Exception as ex:
            errs += 1
            log(f"خطأ ({errs}): {ex}")
            if errs >= 5 and time.time() - state.get("warn", 0) >= 3600:       # 5 أخطاء متتالية ≈ 5 دقائق
                if tg.send(f"⚠️ <b>تنبيه SH:</b> البوت يواجه أخطاء متكررة منذ دقائق ولا يستطيع جلب الأسعار. سيعيد المحاولة تلقائياً.\nآخر خطأ: {str(ex)[:150]}"):
                    state["warn"] = time.time(); save_state(state)
        if time.time() + 60 >= deadline:
            break
        # تحديث ذاتي: إن رُفعت نسخة أحدث من الكود، أعد التشغيل بها دون تدخل
        if time.time() - last_chk >= 300:
            last_chk = time.time()
            if code_changed():
                log("وُجدت نسخة أحدث من الكود: إعادة التشغيل بها")
                commit_state()
                os.execv(sys.executable, [sys.executable, os.path.join(HERE, "sh_actions.py"), "--loop", f"{max((deadline - time.time()) / 60, 1):.1f}"])
        for _ in range(3):                                   # عيّنة سعر فوري كل 20 ثانية لبناء الشموع اللحظية
            time.sleep(20); sample_spot(cfg.get("spotSym", "XAU"))


if __name__ == "__main__":
    try:
        main()
    except Exception as ex:                 # فشل مؤقت: نسجّله ونكمل، التشغيل التالي يعيد المحاولة
        log(f"خطأ: {ex}")
        sys.exit(0)
