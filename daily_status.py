#!/usr/bin/env python3
"""Daily status automation for Google Chat (Hangouts).

Run once in the morning:  python daily_status.py
  1. Paste your "Daily Start Report" in a popup -> it is posted to Google Chat
     and the "Today's Tasks" become your checklist.
  2. Every INTERVAL_HOURS a popup lists each task (New / In Progress / Done);
     your answers are posted to Google Chat in the "Update:" format.
  3. At END_TIME a popup builds the "Daily End Report" and posts it.

Single steps (for cron / Task Scheduler):  --start | --update | --end
Standard library only. Falls back to the terminal when no display is available.
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
STATUSES = ["New", "In Progress", "Done"]


def load_env():
    env_file = BASE / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip("\"'"))


# ---------- state ----------

def state_path():
    return DATA / f"{datetime.now():%Y-%m-%d}.json"


def load_state():
    p = state_path()
    if p.exists():
        return json.loads(p.read_text())
    return {"start_report": "", "tasks": [], "started": False}


def save_state(state):
    DATA.mkdir(exist_ok=True)
    state_path().write_text(json.dumps(state, indent=2, ensure_ascii=False))


# ---------- parsing / formatting ----------

def _is_heading(line):
    return line.endswith(":") and len(line) < 60


def parse_tasks(report):
    """Return the bullet lines under the 'Today's Tasks:' heading."""
    tasks, inside = [], False
    for raw in report.splitlines():
        line = raw.strip()
        if not line:
            continue
        if _is_heading(line):
            inside = "task" in line.lower() and "today" in line.lower()
            continue
        if inside:
            tasks.append(re.sub(r"^[-*•\d.)\s]+", "", line))
    return tasks


def _bullets(items, empty="None"):
    return "\n".join(f"- {i}" for i in items) if items else empty


def by_status(state, status):
    return [t["title"] for t in state["tasks"] if t["status"] == status]


def build_update(state, next_activity, blocker, expected):
    new = by_status(state, "New")
    return (
        "Update:\n"
        f"Completed:\n{_bullets(by_status(state, 'Done'))}\n\n"
        f"Currently working on:\n{_bullets(by_status(state, 'In Progress'))}\n\n"
        f"Next activity:\n{next_activity or (new[0] if new else 'None')}\n\n"
        f"Blocker/dependency:\n{blocker or 'None'}\n\n"
        f"Expected completion:\n{expected or 'Today'}"
    )


def build_end_report(state, achieved, tomorrow, remaining, blockers):
    return (
        "🌃 Daily End Report\n"
        f"What Was Planned:\n{_bullets([t['title'] for t in state['tasks']])}\n"
        f"What Was Achieved:\n{achieved or 'None'}\n"
        f"Plan for Tomorrow:\n{tomorrow or 'None'}\n"
        f"What Is Remaining:\n{remaining or 'None'}\n"
        f"Blockers:\n{blockers or 'None'}"
    )


# ---------- Google Chat ----------

def send_chat(text):
    print("\n" + text + "\n")
    url = os.environ.get("GOOGLE_CHAT_WEBHOOK", "").strip()
    if not url:
        print("[!] GOOGLE_CHAT_WEBHOOK not set - message printed only.")
        return False
    req = urllib.request.Request(
        url,
        data=json.dumps({"text": text}).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=UTF-8"},
    )
    try:
        urllib.request.urlopen(req, timeout=30).read()
        print("[ok] Sent to Google Chat.")
        return True
    except Exception as exc:  # network / bad webhook
        print(f"[!] Failed to send to Google Chat: {exc}")
        return False


# ---------- popup forms ----------

def form_gui(title, tasks, fields):
    """tasks: list of dicts (edited in place) or None. fields: [(key,label,default,lines)].
    Returns dict of field values, or None if the user skipped."""
    import tkinter as tk
    from tkinter import ttk

    root = tk.Tk()
    root.title(title)
    root.attributes("-topmost", True)
    root.geometry("720x680")
    result = {}
    task_vars = []

    outer = ttk.Frame(root, padding=12)
    outer.pack(fill="both", expand=True)
    ttk.Label(outer, text=title, font=("Segoe UI", 14, "bold")).pack(anchor="w")

    if tasks is not None:
        box = ttk.LabelFrame(outer, text="Tasks", padding=8)
        box.pack(fill="x", pady=8)

        def add_row(task):
            row = ttk.Frame(box)
            row.pack(fill="x", pady=2)
            var = tk.StringVar(value=task["status"])
            task_vars.append((task, var))
            ttk.Label(row, text=task["title"], wraplength=360, width=50).pack(side="left")
            for s in STATUSES:
                ttk.Radiobutton(row, text=s, value=s, variable=var).pack(side="left", padx=3)

        for t in tasks:
            add_row(t)
        new_row = ttk.Frame(outer)
        new_row.pack(fill="x")
        new_entry = ttk.Entry(new_row)
        new_entry.pack(side="left", fill="x", expand=True)

        def add_new():
            title_ = new_entry.get().strip()
            if title_:
                task = {"title": title_, "status": "New"}
                tasks.append(task)
                add_row(task)
                new_entry.delete(0, "end")

        ttk.Button(new_row, text="+ Add new task", command=add_new).pack(side="left", padx=6)

    widgets = {}
    for key, label, default, lines in fields:
        ttk.Label(outer, text=label).pack(anchor="w", pady=(8, 0))
        if lines > 1:
            w = tk.Text(outer, height=lines, wrap="word")
            w.insert("1.0", default)
        else:
            w = ttk.Entry(outer)
            w.insert(0, default)
        w.pack(fill="x")
        widgets[key] = (w, lines)

    def submit():
        for task, var in task_vars:
            task["status"] = var.get()
        for key, (w, lines) in widgets.items():
            result[key] = (w.get("1.0", "end") if lines > 1 else w.get()).strip()
        root.destroy()

    def skip():
        result.clear()
        root.destroy()

    btns = ttk.Frame(outer)
    btns.pack(fill="x", pady=12)
    ttk.Button(btns, text="Send to Google Chat", command=submit).pack(side="right")
    ttk.Button(btns, text="Skip this time", command=skip).pack(side="right", padx=6)
    root.protocol("WM_DELETE_WINDOW", skip)
    root.lift()
    root.focus_force()
    root.mainloop()
    return result or None


def form_cli(title, tasks, fields):
    print(f"\n=== {title} ===")
    if tasks is not None:
        for t in tasks:
            ans = input(f"{t['title']}\n  [n]ew / [p]rogress / [d]one (current: {t['status']}): ").strip().lower()
            t["status"] = {"n": "New", "p": "In Progress", "d": "Done"}.get(ans[:1], t["status"])
        while True:
            extra = input("Add a new task (blank to finish): ").strip()
            if not extra:
                break
            tasks.append({"title": extra, "status": "New"})
    out = {}
    for key, label, default, lines in fields:
        if lines > 1 and default:
            print(f"{label} (suggested):\n{default}")
        out[key] = input(f"{label} [Enter = keep/blank]: ").strip() or default
    return out


def form(title, tasks, fields):
    if os.environ.get("NO_GUI") or not (os.environ.get("DISPLAY") or sys.platform in ("win32", "darwin")):
        return form_cli(title, tasks, fields)
    try:
        return form_gui(title, tasks, fields)
    except Exception as exc:
        print(f"[!] Popup unavailable ({exc}); using terminal.")
        return form_cli(title, tasks, fields)


# ---------- steps ----------

def step_start(state):
    res = form(
        "Daily Start Report - paste your report",
        None,
        [("report", "Paste the full Daily Start Report:", state.get("start_report", ""), 22)],
    )
    if not res or not res["report"]:
        return
    state["start_report"] = res["report"]
    state["tasks"] = [{"title": t, "status": "New"} for t in parse_tasks(res["report"])]
    state["started"] = True
    save_state(state)
    send_chat(res["report"])
    print(f"Loaded {len(state['tasks'])} task(s) for the checklist.")


def step_update(state):
    if not state["tasks"]:
        print("No tasks loaded - run with --start first.")
        return
    new = by_status(state, "New")
    res = form(
        f"Status Update - {datetime.now():%H:%M}",
        state["tasks"],
        [
            ("next", "Next activity", new[0] if new else "", 1),
            ("blocker", "Blocker/dependency", "None", 1),
            ("expected", "Expected completion", "Today", 1),
        ],
    )
    if not res:
        return
    save_state(state)
    send_chat(build_update(state, res["next"], res["blocker"], res["expected"]))


def step_end(state):
    done = by_status(state, "Done")
    left = [t["title"] for t in state["tasks"] if t["status"] != "Done"]
    res = form(
        "Daily End Report",
        state["tasks"],
        [
            ("achieved", "What Was Achieved", _bullets(done, ""), 6),
            ("tomorrow", "Plan for Tomorrow", "None", 3),
            ("remaining", "What Is Remaining", _bullets(left, "None"), 4),
            ("blockers", "Blockers", "None", 2),
        ],
    )
    if not res:
        return
    save_state(state)
    send_chat(build_end_report(state, res["achieved"], res["tomorrow"], res["remaining"], res["blockers"]))


def run_day():
    interval = float(os.environ.get("INTERVAL_HOURS", "2")) * 3600
    end_h, end_m = map(int, os.environ.get("END_TIME", "18:30").split(":"))
    state = load_state()
    if not state["started"]:
        step_start(state)
    while True:
        now = datetime.now()
        end = now.replace(hour=end_h, minute=end_m, second=0, microsecond=0)
        remaining = (end - now).total_seconds()
        if remaining <= 0:
            break
        print(f"Next popup in {min(interval, remaining) / 3600:.1f}h (Ctrl+C to stop).")
        time.sleep(min(interval, remaining))
        if datetime.now() < end:
            step_update(load_state())
    step_end(load_state())


def main():
    load_env()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--start", action="store_true", help="only the morning start report")
    g.add_argument("--update", action="store_true", help="only one status popup now")
    g.add_argument("--end", action="store_true", help="only the end report")
    a = ap.parse_args()
    try:
        if a.start:
            step_start(load_state())
        elif a.update:
            step_update(load_state())
        elif a.end:
            step_end(load_state())
        else:
            run_day()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
