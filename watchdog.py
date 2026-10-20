# -*- coding: utf-8 -*-
"""حارس SH: يعمل ضمن workflow بوت CRT (منتظم التشغيل). إن مرّ زمن طويل بلا «نبض» من بوت SH يعني أنه معلّق
(تعليق تشغيلات GitHub حدث فعلاً 5 ساعات)، فيُلغي التشغيل المعلّق بالقوة ويشغّل SH من جديد. مكتبات بايثون القياسية فقط."""
import base64, datetime as dt, json, os, sys, time, urllib.error, urllib.request

REPO = os.environ["GITHUB_REPOSITORY"]; TOKEN = os.environ["GH_TOKEN"]
STALE_MIN = float(os.environ.get("SH_STALE_MIN", "140"))      # النبض كل ساعتين + هامش 20 دقيقة
FRESH_MIN = 15                                                 # تشغيل بدأ منذ أقل من هذا يُمهَل قبل الحكم عليه


def call(method, path, body=None):
    req = urllib.request.Request("https://api.github.com" + path, method=method,
                                 data=(json.dumps(body).encode() if body is not None else None),
                                 headers={"Authorization": "Bearer " + TOKEN, "Accept": "application/vnd.github+json",
                                          "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "sh-watchdog"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            t = r.read()
            return r.status, (json.loads(t) if t else {})
    except urllib.error.HTTPError as e:
        return e.code, {"error": e.read()[:200].decode("utf-8", "ignore")}


def age_min(iso):
    t = dt.datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    return (dt.datetime.now(dt.timezone.utc) - t).total_seconds() / 60


def main():
    st, c = call("GET", f"/repos/{REPO}/contents/sh_state.json?ref=main")
    if st != 200:
        print("watchdog: تعذّر قراءة الحالة", st); return
    beat = json.loads(base64.b64decode(c["content"])).get("beat", 0)
    age = (time.time() - beat) / 60 if beat else 9999
    print(f"watchdog: آخر نبض لـ SH قبل {age:.0f} دقيقة (الحد {STALE_MIN:.0f})")
    if age < STALE_MIN:
        return
    runs = []
    for status in ("in_progress", "queued", "pending"):
        s, d = call("GET", f"/repos/{REPO}/actions/workflows/sh.yml/runs?status={status}&per_page=20")
        runs += d.get("workflow_runs", []) if s == 200 else []
    for r in runs:                                              # تشغيل حديث: انتظر، فقد لا يكون أرسل نبضه بعد
        if age_min(r["created_at"]) < FRESH_MIN:
            print(f"watchdog: يوجد تشغيل SH حديث (#{r['run_number']}) — أمهله"); return
    for r in runs:
        if r["status"] == "in_progress":
            s, d = call("POST", f"/repos/{REPO}/actions/runs/{r['id']}/force-cancel")
            print(f"watchdog: إلغاء قسري للتشغيل المعلّق #{r['run_number']} → {s}")
    s, d = call("POST", f"/repos/{REPO}/actions/workflows/sh.yml/dispatches", {"ref": "main", "inputs": {"test": "false"}})
    print(f"watchdog: تشغيل SH من جديد → {s} {d if s >= 300 else ''}")


if __name__ == "__main__":
    try:
        main()
    except Exception as ex:
        print("watchdog خطأ:", ex)
