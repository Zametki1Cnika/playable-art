"""Generate one picture for a task with the Codex CLI (its built-in image generation, on a ChatGPT subscription).

The request = a short worker instruction + the shared style block (STYLE.md, one source for every task) + prompt.txt.
Every picture in the task folder is attached as a reference. Codex saves the picture into result/<name>_vN.png.
"""

import glob
import os
import re
import shutil
import subprocess

from . import tasks

NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def codex_exe():
    found = shutil.which("codex")
    if found:
        return found
    # Windows desktop app bundles the CLI here
    hits = sorted(glob.glob(os.path.join(os.environ.get("LOCALAPPDATA", ""), "OpenAI", "Codex", "bin", "*", "codex.exe")), key=os.path.getmtime)
    return hits[-1] if hits else ""


def style_block(root):
    """The text between ``` fences under a '## Prompt block' heading of STYLE.md in the tasks root ('' if none)."""
    p = os.path.join(root, "STYLE.md")
    if not os.path.exists(p):
        return ""
    m = re.search(r"##\s*Prompt block.*?```\s*\n(.*?)```", open(p, encoding="utf-8").read(), re.S | re.I)
    return m.group(1).strip() if m else ""


def build_request(root, task, out_name):
    spec = open(os.path.join(task, "prompt.txt"), encoding="utf-8").read().strip()
    style = style_block(root)
    attach = [f for f in sorted(os.listdir(task)) if f.lower().endswith(tasks.IMG)]
    lines = [
        "You are an image-generation worker. Generate ONE picture with your built-in image generation tool exactly as the spec says,",
        f"and save it as PNG to result/{out_name} in the current folder (create result/ if needed). Do not touch any other file.",
        "Reply with one line: OK and the path, or FAIL and the reason.",
    ]
    if attach:
        lines.append("Attached reference pictures (use them as the spec says): " + ", ".join(attach) + ".")
    note = os.path.join(task, "REWORK.txt")
    if os.path.exists(note):  # a human rejected the previous attempt: this note overrides the spec
        lines.append("OWNER'S CORRECTION (mandatory, overrides the spec): " + open(note, encoding="utf-8").read().strip())
    lines += ["", "SPEC:"]
    if style and "STYLE_" not in spec:
        lines.append(style)
        lines.append("")
    lines.append(spec)
    return "\n".join(lines)


def generate(root, task, model=None, effort="high", timeout=900):
    """Run Codex for one task. Returns (path or None, codex output text, timed_out)."""
    exe = codex_exe()
    if not exe:
        raise OSError("Codex CLI not found: install the Codex app or put `codex` on PATH and log in")
    out_name = tasks.next_name(task)
    os.makedirs(os.path.join(task, "result"), exist_ok=True)
    cmd = [exe, "exec", "-C", task, "--skip-git-repo-check", "-s", "workspace-write", "-c", f'model_reasoning_effort="{effort}"']
    if model:
        cmd += ["-m", model]
    for f in sorted(os.listdir(task)):
        if f.lower().endswith(tasks.IMG):
            cmd += ["-i", os.path.join(task, f)]
    cmd.append("-")
    try:
        done = subprocess.run(cmd, input=build_request(root, task, out_name), capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout, creationflags=NO_WINDOW)
        output, timed_out = (done.stdout or "") + (done.stderr or ""), False
    except subprocess.TimeoutExpired:
        output, timed_out = "", True
    path = os.path.join(task, "result", out_name)
    return (path if os.path.exists(path) else None), output, timed_out
