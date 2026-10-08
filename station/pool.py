"""The pool: hands the task queue out to several Codex workers in parallel, top priority first.

- a worker that hits the subscription usage limit rests until the time Codex names ("try again at 1:19 PM"),
  or REST_DEFAULT if no time is given; its task goes back to the queue;
- a worker that fails within FAST_FAIL seconds without a picture is broken (login lost, CLI missing), not the task:
  the task goes back, the worker rests FAST_FAIL_REST;
- every event goes to <root>/station_events.jsonl (time, worker, task, status, problems).
"""

import datetime
import json
import os
import re
import threading
import time

from . import codex, tasks

REST_DEFAULT = 45 * 60
FAST_FAIL = 20
FAST_FAIL_REST = 30 * 60
LOCK = threading.Lock()


def _log(root, rec):
    rec["t"] = time.time()
    with LOCK, open(os.path.join(root, "station_events.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(time.strftime("%H:%M:%S"), rec.get("worker"), rec.get("status"), os.path.relpath(rec.get("task", root), root), flush=True)


def _limit_rest(output):
    low = output.lower()
    if not ("usage limit" in low or "rate limit" in low or "quota" in low or " 429" in output):
        return None
    m = re.search(r"try again at (\d{1,2}):(\d{2})\s*([AP]M)?", output, re.I)
    if not m:
        return REST_DEFAULT
    h, mi = int(m.group(1)), int(m.group(2))
    if m.group(3) and m.group(3).upper() == "PM" and h < 12:
        h += 12
    if m.group(3) and m.group(3).upper() == "AM" and h == 12:
        h = 0
    now = datetime.datetime.now()
    at = now.replace(hour=h, minute=mi, second=0, microsecond=0)
    if at <= now:
        at += datetime.timedelta(days=1)
    return int((at - now).total_seconds()) + 60


def run(root, workers=1, wait=False, model=None, effort="high"):
    taken, rest_until = set(), {}

    def worker(name):
        while True:
            now = time.time()
            if rest_until.get(name, 0) > now:
                if not wait:
                    return
                time.sleep(min(600, rest_until[name] - now))
                continue
            with LOCK:
                q = [t for t in tasks.queue(root) if t not in taken]
                task = q[0] if q else None
                if task:
                    taken.add(task)
            if task is None:
                if not wait:
                    return
                time.sleep(30)
                continue
            t0 = time.time()
            try:
                path, output, timed_out = codex.generate(root, task, model=model, effort=effort)
            except OSError as exc:
                _log(root, {"worker": name, "task": task, "status": "worker_unavailable", "error": str(exc)})
                with LOCK:
                    taken.discard(task)
                return
            secs = round(time.time() - t0)
            if path:
                probs = tasks.check_image(path, "tileable" not in open(os.path.join(task, "prompt.txt"), encoding="utf-8").read())
                _log(root, {"worker": name, "task": task, "status": "ok" if not probs else "check_fail", "file": os.path.basename(path), "seconds": secs, "problems": probs})
                continue
            rest = _limit_rest(output)
            with LOCK:
                taken.discard(task)
            if rest:
                rest_until[name] = time.time() + rest
                _log(root, {"worker": name, "task": task, "status": "limit", "rest_min": rest // 60})
            elif not timed_out and secs < FAST_FAIL:
                rest_until[name] = time.time() + FAST_FAIL_REST
                _log(root, {"worker": name, "task": task, "status": "worker_fail", "output": output[-300:]})
            else:
                _log(root, {"worker": name, "task": task, "status": "timeout" if timed_out else "no_file", "seconds": secs, "output": output[-300:]})
                with LOCK:
                    taken.add(task)  # do not spin on the same task in this run

    threads = [threading.Thread(target=worker, args=(f"codex{i + 1}",), daemon=True) for i in range(workers)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
