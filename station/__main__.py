"""Generation station command line.

  python -m station run   TASKS_ROOT [-n 2] [--wait] [--model M] [--effort high]   # the pool, priority first
  python -m station one   TASK_FOLDER [--root TASKS_ROOT]                            # one task now
  python -m station queue TASKS_ROOT                                                 # what is ready to run
  python -m station check TASKS_ROOT                                                 # automatic checks of the latest results
"""

import argparse
import os

from . import codex, pool, tasks


def main():
    ap = argparse.ArgumentParser(prog="station", description="Picture generation station on Codex (ChatGPT subscription).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("root")
    r.add_argument("-n", "--workers", type=int, default=1)
    r.add_argument("--wait", action="store_true", help="keep going through usage limits until the queue is empty")
    r.add_argument("--model")
    r.add_argument("--effort", default="high")
    o = sub.add_parser("one")
    o.add_argument("task")
    o.add_argument("--root", help="tasks root (for STYLE.md); default: the task's parent")
    o.add_argument("--model")
    o.add_argument("--effort", default="high")
    q = sub.add_parser("queue")
    q.add_argument("root")
    c = sub.add_parser("check")
    c.add_argument("root")
    a = ap.parse_args()
    if a.cmd == "run":
        pool.run(a.root, a.workers, a.wait, a.model, a.effort)
    elif a.cmd == "one":
        root = a.root or os.path.dirname(os.path.abspath(a.task))
        path, output, timed_out = codex.generate(root, os.path.abspath(a.task), a.model, a.effort)
        print(("OK " + path + "  problems: " + "; ".join(tasks.check_image(path)) if path else "NO FILE" + (" (timeout)" if timed_out else "") + "\n" + output[-1500:]))
    elif a.cmd == "queue":
        for t in tasks.queue(a.root):
            print(os.path.relpath(t, a.root))
    else:
        for t in tasks.task_dirs(a.root):
            res = tasks.results(t)
            if res:
                probs = tasks.check_image(res[-1])
                print(("OK  " if not probs else "FIX ") + os.path.relpath(res[-1], a.root) + ("" if not probs else "  " + "; ".join(probs)))


if __name__ == "__main__":
    main()
