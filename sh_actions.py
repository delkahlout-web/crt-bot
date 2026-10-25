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
import sh_track as T

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


_YC = {}          # تخزين مؤقت لشموع Yahoo (مفتاح: الرمز/الفريم/المدة)
LAST_MODE = {"m": "closed"}


def yf_candles(ticker, interval, period, minutes, ttl=0):
    """شموع مكتملة فقط: قائمة dict(time=epoch UTC، open، high، low، close). ttl>0: يعيد المخزّن إن كان أحدث من ttl ثانية."""
    key = (ticker, interval, period)
    if ttl and key in _YC and time.time() - _YC[key][0] < ttl:
        return [b for b in _YC[key][1] if b["time"] + minutes * 60 <= time.time()]
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
            _YC[key] = (time.time(), out)
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
        if os.path.exists(os.path.join(HERE, "msnr_state.json")):
            run("git", "add", "msnr_state.json")
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
        if max(ps) - min(ps) < 0.005:                         # لا حركة طوال الشمعة = السوق مغلق (استراحة يومية/عطلة)
            continue
        out.append(dict(time=st, open=ps[0], high=max(ps), low=min(ps), close=ps[-1]))
    have = {b["time"] for b in out}
    out += [b for t, b in PERSIST.items() if t not in have and t + 300 <= now and now - t < 8 * 3600]
    return sorted(out, key=lambda b: b["time"])


def merge_spot(yb, sb, now):
    """شموع الفوري (المبنية لحظياً والمحفوظة) تُعتمد كما هي لكامل نافذتها ولا تُستبدل لاحقاً بـ Yahoo (يمنع إعادة الرسم)؛
    وقبل نافذتها يُستعمل تاريخ Yahoo (المكتمل منذ 20 دقيقة على الأقل) مُنزَّلاً بوسيط فرق الإغلاقات في التقاطع.
    لا يُشترط أن تكون شموع Yahoo حديثة: في الاستراحة اليومية (21:00–22:00 UTC صيفاً) والعطلة تتوقف بينما شموع الفوري المحفوظة تكفي للمواءمة."""
    ybv = [b for b in yb if b["time"] + 300 <= now - 1200]
    if not ybv or not sb:
        return ybv, None
    sd = {b["time"]: b for b in sb}
    diffs = sorted(b["close"] - sd[b["time"]]["close"] for b in ybv[-96:] if b["time"] in sd)
    if len(diffs) < 3:
        return ybv, None
    s_ = diffs[len(diffs) // 2]
    ymap = {b["time"]: b for b in ybv}
    out = []; prev = None
    for t in sorted(set(ymap) | set(sd)):
        if prev is not None and t > prev + 300 and (t in sd or prev in sd):
            g = (t - prev) // 300 - 1
            if prev > now - 1800:                                                 # فجوة حديثة (بدأت قبل أقل من 30 دقيقة): تُملأ إن كانت قصيرة
                if g > 4:
                    return ybv, None
                lc = out[-1]["close"]
                for k in range(g):
                    out.append(dict(time=prev + 300 * (k + 1), open=lc, high=lc, low=lc, close=lc))
            # فجوة أقدم = استراحة أو إغلاق سوق: تبقى فجوة طبيعية بلا شموع مسطحة
        out.append(sd[t] if t in sd else dict(ymap[t], open=ymap[t]["open"] - s_, high=ymap[t]["high"] - s_, low=ymap[t]["low"] - s_, close=ymap[t]["close"] - s_))
        prev = t
    if now - (out[-1]["time"] + 300) > 1500:                                      # لا شموع فوري حديثة ⇒ ليس وضعاً لحظياً
        return ybv, None
    return out, s_


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
    chart = yf_candles(cfg["ticker"], "5m", "30d", P["chartTF"], ttl=(240 if LAST_MODE["m"] == "live" else 0))   # في الوضع اللحظي يُستعمل تاريخ Yahoo الأقدم من 20 دقيقة فقط
    live, src, merged_ok = LIVE.get(cfg["ticker"]), "Yahoo", False
    cfg["_meta"] = dict(mode="closed", src="Yahoo", age=None); cfg["_basis"] = None
    if P["chartTF"] == 5 and P["mainTF"] == 15:
        merged, s = merge_spot(chart, spot_bars(now), now)
        if s is not None:
            chart = merged; merged_ok = True; src = "الذهب الفوري"; cfg["_basis"] = s
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
            state["off"] = off; cfg["_basis"] = off
            chart, main = shift(chart, off), shift(main, off)
            cfg["dataNote"] = f"الأسعار من Yahoo (متأخرة 10–15 دقيقة) مصحّحة بفرق الذهب الفوري ({off:.1f}$): اعتمد على المسافات."
        else:
            cfg["dataNote"] = "الأسعار بلا تصحيح الآن (السوق مغلق)، وقد تزيد 15–28$ عن شارتك: اعتمد على المسافات."
    cfg["_chart5"] = chart
    return run_engine(chart, main, P), chart[-1]["time"], P


def code_changed():
    """هل على GitHub نسخة أحدث من ملفات البوت؟ (للتحديث الذاتي دون تدخل يدوي)"""
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return False
    try:
        import subprocess
        run = lambda *a: subprocess.run(a, cwd=HERE, capture_output=True, text=True, timeout=60)
        run("git", "fetch", "-q", "origin", "main")
        d = run("git", "diff", "--name-only", "HEAD", "origin/main", "--", "sh_engine.py", "sh_messages.py", "sh_actions.py", "sh_config.json", "crt_bot.py", "msnr_engine.py", "msnr_actions.py", "msnr_pro.py", "msnr_msgs.py", "msnr_config.json", "sh_track.py")
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
    handover = False
    sent = set(state["sent"])
    PERSIST.update({int(b["time"]): b for b in state.get("spot", [])})
    try:
        import msnr_actions as MA
        MS = MA.Msnr()
    except Exception as ex:                                   # أي عطل في MSNR لا يمسّ إشارات SH
        MS = None; log(f"MSNR معطّل: {ex}")
    yh1 = {"t": 0, "bars": []}
    max_age = cfg.get("maxAgeMin", 60) * 60
    beat_every = float(cfg.get("heartbeatHours", 2)) * 3600
    errs = 0; last_chk = time.time()
    while True:
        fresh_sent = False
        try:
            sample_spot(cfg.get("spotSym", "XAU"))
            evs, last_t, P = compute(cfg, state)
            sh_on = cfg.get("shEnabled", True)
            if not sh_on:
                evs = []                                  # إشارات SH متوقفة بقرار المستخدم؛ MSNR يستمر
            LAST_MODE["m"] = cfg.get("_meta", {}).get("mode", "closed")
            errs = 0
            now = time.time()
            trades = state.setdefault("trades", []); sigl = state.setdefault("sigs", [])
            if not sh_on:
                trades.clear()
            sigs_now = [(int(a), int(b)) for a, b in sigl] + T.history_from_sent(sent)
            # تبنّي صفقة أُرسلت إشارتها سابقاً (مثلاً بنسخة أقدم من البوت) ولم تنتهِ بعد، لتكتمل رسائل مصيرها
            known = {(int(r["sig_time"]), int(r["dir"])) for r in trades}
            closed_keys = {(int(e["trade"]["sig_time"]), int(e["trade"]["dir"])) for e in evs if e["kind"] == "closed"}
            for e in evs:
                if e["kind"] == "signal" and ev_key(e) in sent and e["bar_time"] >= now - 8 * 3600:
                    kk = (int(e["trade"]["sig_time"]), int(e["trade"]["dir"]))
                    if kk not in known and kk not in closed_keys and not any(r["dir"] == kk[1] and abs(int(r["sig_time"]) - kk[0]) <= T.DEDUP_SEC for r in trades):
                        T.register(trades, sigl, e); sigl[-1] = list(sigl[-1]); known.add(kk)
                        log(f"تبنّي صفقة مرسلة سابقاً لمتابعة مصيرها: {ev_key(e)}")
            fresh = [e for e in evs if e["kind"] == "signal" and e["bar_time"] >= now - max_age and ev_key(e) not in sent]
            log(f"{NAME} | آخر شمعة مغلقة: {dt.datetime.fromtimestamp(last_t, dt.timezone.utc):%Y-%m-%d %H:%M} UTC | إشارات جديدة: {len(fresh)} | صفقات متابَعة: {sum(1 for r in trades if not r['done'])}")
            for e in fresh:
                active = [r for r in trades if not r["done"]]
                if active or T.is_duplicate(sigs_now, active, e["trade"]):          # صفقة مفتوحة أو نفس الإشارة بتغيّر طفيف في البيانات
                    sent.add(ev_key(e)); log(f"تجاهل إشارة مكرّرة/متزامنة: {ev_key(e)}"); continue
                txt = message(e, cfg, P)
                if txt and tg.send(txt):
                    log(f"أُرسل: {e['kind']} {ev_key(e)}")
                    sent.add(ev_key(e)); T.register(trades, sigl, e); sigl[-1] = list(sigl[-1]); fresh_sent = True
            # متابعة الصفقات المرسلة بشموعها (تعادل/هدف أول/إغلاق/تفعيل/إلغاء) بأرقامها المثبّتة لا بإعادة حساب المحرك
            chart5 = cfg.get("_chart5") or []
            for r in trades:
                if not r["done"]:
                    r["queue"].extend(T.advance(r, chart5, P))
                keep = []
                for e2 in r["queue"]:
                    k2 = ev_key(e2)
                    if k2 in sent or e2["bar_time"] < now - 3 * 3600:
                        continue
                    txt = message(e2, cfg, P)
                    if txt and tg.send(txt):
                        log(f"أُرسل: {e2['kind']} {k2}"); sent.add(k2); fresh_sent = True
                    else:
                        keep.append(e2)
                r["queue"] = keep
            state["trades"] = [r for r in trades if (not r["done"]) or r["queue"] or now - r["last"] < 6 * 3600]
            state["sigs"] = [list(x) for x in sigl][-30:]
            state["sent"] = list(sent)
            state["spot"] = spot_bars(time.time())[-96:]                  # آخر 8 ساعات (96 شمعة): تبدأ التشغيلات دافئة وتبقى الشموع مجمّدة
            now = time.time(); meta = cfg.get("_meta", {})
            dirty = fresh_sent
            # تنبيه عند تعطّل المصدر اللحظي أثناء السوق (مرة كل ساعة كحد أقصى)
            state["degN"] = state.get("degN", 0) + 1 if meta.get("mode") == "degraded" else 0
            if sh_on and state["degN"] >= 5 and now - state.get("warn", 0) >= 3600:
                if tg.send("⚠️ <b>تنبيه SH:</b> المصدر اللحظي للأسعار معطّل والسوق مفتوح. البيانات الآن متأخرة 10–15 دقيقة، فقد تتأخر الإشارات. سأعود للوضع الطبيعي تلقائياً حين يعود المصدر."):
                    state["warn"] = now; dirty = True
            # نبض: «البوت حيّ» كل ساعتين (صامت بلا صوت)
            if beat_every > 0 and now - state.get("beat", 0) >= beat_every:
                # النبض يُسجَّل في الحالة (يراقبه الحارس)؛ وإرساله لتلجرام اختياري ومتوقف افتراضياً لأنه مزعج
                if not cfg.get("heartbeatTelegram", False) or tg.send(heartbeat_text(cfg, P), silent=True):
                    state["beat"] = now; dirty = True
            try:
                if MS is not None:
                    if time.time() - yh1["t"] > 600:                       # شموع Yahoo (1h/30m/15m) تُجلب كل 10 دقائق
                        yh1["bars"] = {"h1": yf_candles(cfg["ticker"], "1h", "60d", 60), "m30": yf_candles(cfg["ticker"], "30m", "60d", 30), "m15": yf_candles(cfg["ticker"], "15m", "60d", 15)}
                        yh1["t"] = time.time()
                    ch5 = cfg.get("_chart5") or []
                    cur = SPOT_BUF[-1][1] if SPOT_BUF and time.time() - SPOT_BUF[-1][0] < 180 else (ch5[-1]["close"] if ch5 else None)
                    if cur:
                        if MS.tick(tg, ch5, cur, time.time(), yh1["bars"], cfg.get("_basis"), cfg.get("displayTz", "Asia/Hebron")) > 0:
                            dirty = True
            except Exception as ex:
                log(f"MSNR خطأ: {ex}")
            save_state(state)
            if dirty:
                commit_state()
        except Exception as ex:
            errs += 1
            log(f"خطأ ({errs}): {ex}")
            if errs >= 5 and time.time() - state.get("warn", 0) >= 3600:       # 5 أخطاء متتالية ≈ 5 دقائق
                if tg.send(f"⚠️ <b>تنبيه SH:</b> البوت يواجه أخطاء متكررة منذ دقائق ولا يستطيع جلب الأسعار. سيعيد المحاولة تلقائياً.\nآخر خطأ: {str(ex)[:150]}"):
                    state["warn"] = time.time(); save_state(state)
        if not handover and loop_min >= 30 and time.time() >= deadline - 420 and os.environ.get("GH_TOKEN"):
            # تسليم بلا فجوة: قبل 7 دقائق من النهاية نُشغّل التشغيل التالي (ينتظر هو انتهاء هذا ثم يبدأ)
            try:
                import subprocess
                r = subprocess.run(["gh", "workflow", "run", "sh.yml", "--repo", os.environ.get("GITHUB_REPOSITORY", ""), "-f", "test=false"], capture_output=True, text=True, timeout=60)
                log(f"تسليم: تشغيل التالي ({'تم' if r.returncode == 0 else 'فشل: ' + r.stderr[:120]})")
            except Exception as ex:
                log(f"تسليم فشل: {ex}")
            handover = True
        if time.time() + 25 >= deadline:
            break
        # تحديث ذاتي: إن رُفعت نسخة أحدث من الكود، أعد التشغيل بها دون تدخل
        if time.time() - last_chk >= 300:
            last_chk = time.time()
            if code_changed():
                log("وُجدت نسخة أحدث من الكود: إعادة التشغيل بها")
                commit_state()
                os.execv(sys.executable, [sys.executable, os.path.join(HERE, "sh_actions.py"), "--loop", f"{max((deadline - time.time()) / 60, 1):.1f}"])
        time.sleep(20); sample_spot(cfg.get("spotSym", "XAU"))   # دورة كل نحو 20 ثانية: عيّنة سعر فوري ثم فحص الإشارات (تأخير الاكتشاف ≤ نحو 25 ثانية)


if __name__ == "__main__":
    try:
        main()
    except Exception as ex:                 # فشل مؤقت: نسجّله ونكمل، التشغيل التالي يعيد المحاولة
        log(f"خطأ: {ex}")
        sys.exit(0)
