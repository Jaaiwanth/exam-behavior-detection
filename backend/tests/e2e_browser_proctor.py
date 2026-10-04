"""
Real-browser end-to-end test of the student proctoring path (NOT run by pytest — it needs real
AWS credentials, a Chromium download and ~6 minutes):

    py -3.11 backend/tests/e2e_browser_proctor.py <path-to-fake-webcam.mjpeg>

What runs for real:
    Chromium (fake webcam fed from an MJPEG file: a real face, then blank frames)
      -> frontend/src/hooks/useProctoring.js  (getUserMedia, fullscreen, WebSocket, 2 FPS JPEG frames)
      -> FastAPI /ws/student/{uid}?exam_id=...  (uvicorn, WS_AUTH=0 for this harness only)
      -> the real ExamMonitor (MediaPipe + YOLO + face verifier)
      -> real DynamoDB `exam_events` + real private S3 bucket

What is NOT covered here: Firebase login and the Firestore parts of ExamRoom (they need a verified
student account). All AWS test data is created under a throw-away exam id and deleted at the end.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("AWS_REGION", "ap-south-1")

import boto3
from playwright.sync_api import sync_playwright

from backend import dynamo_logger as db, s3_store

FAKE_CAM = sys.argv[1]
EXAM = f"ui-e2e-{int(time.time())}"
UID = "ui-e2e-student"
API = "http://127.0.0.1:8000"
WEB = "http://127.0.0.1:5173"
LOG = ROOT / "backend" / "tests" / "_e2e_backend.log"
results: list[tuple[str, bool, str]] = []
procs: list[subprocess.Popen] = []


def check(label: str, ok: bool, extra: str = "") -> bool:
    results.append((label, ok, extra))
    print(f"  [{'PASS' if ok else 'FAIL'}] {label} {extra}", flush=True)
    return ok


def wait_for(fn, timeout, interval=1.0, label=""):
    end = time.time() + timeout
    while time.time() < end:
        try:
            v = fn()
        except Exception:
            v = None
        if v:
            return v
        time.sleep(interval)
    return None


def backend_log() -> str:
    return LOG.read_text(errors="ignore") if LOG.exists() else ""


def start_backend():
    env = {**os.environ, "WS_AUTH": "0", "PYTHONUNBUFFERED": "1", "TF_CPP_MIN_LOG_LEVEL": "3"}
    f = open(LOG, "a")
    p = subprocess.Popen([sys.executable, "-m", "uvicorn", "backend.main:app", "--port", "8000"],
                         cwd=ROOT, env=env, stdout=f, stderr=subprocess.STDOUT)
    procs.append(p)
    ok = wait_for(lambda: urllib.request.urlopen(f"{API}/api/health", timeout=2).status == 200, 120, 1)
    return p, bool(ok)


def start_web():
    env = {**os.environ, "VITE_API_URL": API, "VITE_WS_URL": "ws://127.0.0.1:8000"}
    npm = "npm.cmd" if os.name == "nt" else "npm"
    p = subprocess.Popen([npm, "run", "dev", "--", "--port", "5173", "--strictPort", "--host", "127.0.0.1"],
                         cwd=ROOT / "frontend", env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    procs.append(p)
    return p, bool(wait_for(lambda: urllib.request.urlopen(f"{WEB}/proctor-harness.html", timeout=2).status == 200, 60, 1))


def state(page):
    return page.evaluate("window.__proctor || {}")


def session():
    return db.get_session(EXAM, UID)


def events():
    return db.list_events(EXAM, UID)


def cleanup():
    print("\nCleanup (throw-away exam only)")
    try:
        s3 = boto3.client("s3", region_name=os.environ["AWS_REGION"])
        prefix = f"recordings/{EXAM}/"
        n = 0
        for page in s3.get_paginator("list_objects_v2").paginate(Bucket=s3_store.bucket_name(), Prefix=prefix):
            for o in page.get("Contents", []):
                s3.delete_object(Bucket=s3_store.bucket_name(), Key=o["Key"]); n += 1
        t = db._get_table()
        m = 0
        for it in db._query_exam(EXAM):
            if it["exam_id"] == EXAM:
                t.delete_item(Key={"exam_id": it["exam_id"], "sort_key": it["sort_key"]}); m += 1
        print(f"  deleted {n} S3 objects, {m} DynamoDB items")
        check("no test items left", len(db._query_exam(EXAM)) == 0)
    except Exception as exc:
        print("  CLEANUP ERROR:", exc)
        check("cleanup", False, str(exc))
    for p in procs:
        try:
            p.terminate()
        except Exception:
            pass


def main():
    LOG.write_text("")
    print(f"exam id {EXAM}\n")
    try:
        print("0. Start backend (real ML) + frontend dev server")
        backend, ok = start_backend()
        if not check("backend up (real ExamMonitor loads on first connection)", ok):
            return
        web, ok = start_web()
        if not check("frontend dev server up", ok):
            return

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=[
                "--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream",
                f"--use-file-for-fake-video-capture={FAKE_CAM}",
            ])
            ctx = browser.new_context(permissions=["camera"], viewport={"width": 1000, "height": 700})
            ctx.add_init_script("""
                window.__gumCalls = 0;
                const orig = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
                navigator.mediaDevices.getUserMedia = (c) => { window.__gumCalls++; return orig(c); };
            """)
            page = ctx.new_page()
            page.on("pageerror", lambda e: print("  [page error]", e))
            url = f"{WEB}/proctor-harness.html?uid={UID}&exam={EXAM}"

            print("\n1. Camera permission + preview (before exam start)")
            page.goto(url)
            check("camera idle before the student acts", state(page).get("camera") == "idle")
            page.click("#enable")
            check("camera ready after permission", bool(wait_for(lambda: state(page).get("camera") == "ready", 20)))
            vw = wait_for(lambda: page.evaluate("document.getElementById('preview').videoWidth"), 15)
            check("preview is playing real video", bool(vw), f"(videoWidth={vw})")

            print("2. Start: fullscreen + WebSocket + frames")
            page.click("#start")
            check("fullscreen entered", bool(wait_for(lambda: page.evaluate("!!document.fullscreenElement"), 5)),
                  "(headless Chromium)")
            check("exactly ONE getUserMedia call (single camera stream)", page.evaluate("window.__gumCalls") == 1,
                  f"(calls={page.evaluate('window.__gumCalls')})")
            check("websocket authenticated + live", bool(wait_for(lambda: state(page).get("monitor") == "live", 120)))
            check("backend accepted /ws/student/{uid}?exam_id=",
                  bool(wait_for(lambda: f"Student connected: {UID} (exam={EXAM})" in backend_log(), 10)))
            progressed = wait_for(lambda: state(page).get("calibrating") and state(page).get("calibProgress", 0) > 0, 60)
            check("frames reach the ML pipeline (calibration progress comes back)", bool(progressed),
                  f"(progress={state(page).get('calibProgress')})")
            done = wait_for(lambda: state(page).get("monitor") == "live" and not state(page).get("calibrating"), 90)
            check("ML calibration completed on the browser's webcam frames", bool(done))

            print("3. Real warnings -> DynamoDB -> S3")
            evs = wait_for(lambda: events() if len(events()) >= 3 else None, 150, 3)
            check("warnings reached DynamoDB", bool(evs), f"({len(evs or [])} events)")
            if evs:
                check("event is tagged with the right exam + student",
                      all(e["exam_id"] == EXAM and e["student_id"] == UID for e in evs))
                check("warning type from the real ML", evs[0]["warning_type"].startswith("Face not visible"),
                      f"({evs[0]['warning_type']})")
                s = session()
                check("exactly one event per warning (no hold-time duplicates)", len(evs) == s["warning_count"],
                      f"(events={len(evs)}, warning_count={s['warning_count']})")
                ready = wait_for(lambda: [e for e in events() if e.get("s3_object_key")], 60, 2)
                check("recording uploaded to private S3 and linked", bool(ready))
                if ready:
                    head = boto3.client("s3", region_name=os.environ["AWS_REGION"]).head_object(
                        Bucket=s3_store.bucket_name(), Key=ready[0]["s3_object_key"])
                    check("S3 object exists (video/mp4)", head["ContentType"] == "video/mp4",
                          f"({head['ContentLength']} bytes)")

            print("4. Camera disconnect handling")
            page.evaluate("""() => { window.__tracks = window.__proctorApi.stream.getTracks();
                                      window.__tracks[0].stop();
                                      window.__tracks[0].dispatchEvent(new Event('ended')); }""")
            check("camera loss detected", bool(wait_for(lambda: state(page).get("camera") == "lost", 5)))
            page.evaluate("window.__proctorApi.requestCamera()")
            check("camera recovers via Reconnect", bool(wait_for(lambda: state(page).get("camera") == "ready", 20)))
            check("recovery opened a NEW stream only because the old one was dead",
                  page.evaluate("window.__gumCalls") == 2, f"(calls={page.evaluate('window.__gumCalls')})")

            print("5. Browser refresh keeps the server-side session")
            before = session()
            page.goto(url + "&resume=1")
            check("reconnected after refresh", bool(wait_for(lambda: state(page).get("monitor") == "live", 60)))
            check("backend restored the score from DynamoDB",
                  bool(wait_for(lambda: f"Session state restored (score={before['last_score']}, "
                                        f"warnings={before['warning_count']})" in backend_log(), 10)),
                  f"(was score={before['last_score']}, warnings={before['warning_count']})")
            after = session()
            check("refresh did not reset score or duplicate events",
                  after["last_score"] <= before["last_score"] and len(events()) == after["warning_count"])

            print("6. Backend restart: client reconnects by itself")
            backend.terminate(); backend.wait(timeout=20); procs.remove(backend)
            check("client notices the drop and goes to 'reconnecting'",
                  bool(wait_for(lambda: state(page).get("monitor") == "reconnecting", 30, 0.5)))
            backend, ok = start_backend()
            check("backend back up", ok)
            check("client reconnected automatically (no page action)",
                  bool(wait_for(lambda: state(page).get("monitor") == "live", 90)))
            # restart the fake webcam so the re-calibration after the restart sees the face again
            page.goto(url + "&resume=1")
            wait_for(lambda: state(page).get("monitor") == "live", 60)

            print("7. Keep going until the sanity score reaches 0 (real ML, ~20 warnings)")
            last = [None]
            def at_zero():
                s = session()
                if s and s["last_score"] != last[0]:
                    last[0] = s["last_score"]; print(f"     score {s['last_score']} / warnings {s['warning_count']}", flush=True)
                return s and s["last_score"] == 0
            check("score reached 0", bool(wait_for(at_zero, 420, 5)))
            s = session()
            check("session is PENDING_REVIEW (flagged, not failed)", s and s["review_status"] == "PENDING_REVIEW")
            check("no automatic verdict recorded", s and "mentor_decision" not in s)
            time.sleep(8)
            st = state(page)
            check("student can still continue: camera + monitoring stay on at score 0",
                  st.get("camera") == "ready" and st.get("monitor") == "live")
            check("page was not navigated away / submitted", "proctor-harness" in page.url)

            print("8. Stop: clean shutdown")
            page.evaluate("window.__tracks = window.__proctorApi.stream.getTracks()")
            page.click("#stop")
            check("monitoring off", state(page).get("monitor") == "off")
            check("camera tracks stopped", page.evaluate("window.__tracks.every(t => t.readyState === 'ended')"))
            check("backend saw a clean disconnect",
                  bool(wait_for(lambda: backend_log().count("Student disconnected") >= 1, 10)))
            ctx.close(); browser.close()

        print("\n9. Server rules")
        log = backend_log()
        check("no unhandled backend exceptions", "Traceback" not in log, "")
        check("warning clips encoded + uploaded", log.count("uploaded") >= 1, f"({log.count('uploaded')} uploaded, {log.count('FAILED')} failed)")
    finally:
        cleanup()
        bad = [r for r in results if not r[1]]
        print("\nRESULT:", "ALL PASSED" if not bad else f"{len(bad)} FAILED: {[b[0] for b in bad]}")
        sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
