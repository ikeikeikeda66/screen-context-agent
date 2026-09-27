"""Dogfooding report (#32, roadmap decision 17): is the Today view used, and do the Resume card and
the sensitive-input rules need tuning?

Counts only: dates, action names, thresholds and rule names. It never reads screen text, titles or
the queries in the audit log, so the Markdown form can be pasted into an issue as is. Frame times
are read to compare session thresholds; no frame content is loaded, and nothing is audited.
"""
import statistics
import time
from datetime import date, timedelta
from . import sessions, store
from .i18n import t
from .storage import skip_counts

TARGET_DAYS = 10                     # working days with the Today view opened (Phase 2 exit)
THRESHOLDS = (5, 10, 15, 20, 30)     # idle minutes compared for the Resume card


def local_day(ts): return time.strftime("%Y-%m-%d", time.localtime(ts))


def report(settings, days=14, now=None):
    now = now or time.time()
    first = date.fromisoformat(local_day(now)) - timedelta(days=days - 1)
    since = time.mktime(first.timetuple())
    with store.connect(settings, readonly=True) as con:
        opened = [r["ts"] for r in con.execute(
            "SELECT ts FROM audit WHERE path = 'user' AND client = 'ui' AND action = 'ui.open' AND ts >= ? AND ts <= ?", (since, now))]
        actions = {r["action"]: r["n"] for r in con.execute(
            "SELECT action, count(*) AS n FROM audit WHERE path = 'user' AND (client = 'ui' OR client LIKE 'ui.%') "
            "AND ts >= ? AND ts <= ? GROUP BY action ORDER BY action", (since, now))}
        verdicts = con.execute("SELECT idle_minutes, verdict, count(*) AS n FROM feedback WHERE ts >= ? AND ts <= ? "
                               "GROUP BY idle_minutes, verdict ORDER BY idle_minutes", (since, now)).fetchall()
        stamps = [{"ts": r["ts"]} for r in con.execute("SELECT ts FROM frames WHERE ts >= ? AND ts <= ? ORDER BY ts", (since, now))]
    per_day = {}
    for ts in opened: per_day[local_day(ts)] = per_day.get(local_day(ts), 0) + 1
    working = [d for d in per_day if date.fromisoformat(d).weekday() < 5]
    feedback = {}
    for r in verdicts: feedback.setdefault(r["idle_minutes"], {v: 0 for v in sessions.VERDICTS})[r["verdict"]] = r["n"]
    return {
        "from": first.isoformat(), "to": local_day(now), "days": days,
        "today_view": {"days_opened": len(per_day), "working_days_opened": len(working), "target_working_days": TARGET_DAYS,
                       "target_met": len(working) >= TARGET_DAYS, "opens_per_day": dict(sorted(per_day.items())), "actions": actions},
        "resume_card": {"idle_minutes": settings.session_idle_minutes(),
                        "feedback": [{"idle_minutes": m, **counts} for m, counts in feedback.items()],
                        "thresholds": compare(stamps, sessions.presence(settings, since, now), now)},
        "sensitive_input": {"skipped": skip_counts(settings, days)},
    }


def compare(frames, events, now):
    """Sessions per threshold over the same frames: how many, and how long (median minutes)."""
    out = []
    for minutes in THRESHOLDS:
        groups = sessions.split(frames, events, minutes * 60, now)
        lengths = [(g[-1]["ts"] - g[0]["ts"]) / 60 for g in groups]
        out.append({"idle_minutes": minutes, "sessions": len(groups),
                    "median_minutes": round(statistics.median(lengths), 1) if lengths else 0})
    return out


def markdown(result, lang="en"):
    """The report as Markdown for the dogfooding issue: counts only."""
    x = lambda key, **values: t(key, lang, **values)
    view, card = result["today_view"], result["resume_card"]
    lines = [f'## {x("review.title", start=result["from"], end=result["to"])}', "",
             f'### {x("review.today")}', "",
             x("review.days", opened=view["days_opened"], working=view["working_days_opened"], target=view["target_working_days"])
             + x("review.met" if view["target_met"] else "review.not_met"), ""]
    if view["actions"]:
        lines += [f'| {x("review.action")} | {x("review.count")} |', "|---|---:|"]
        lines += [f"| `{a}` | {n} |" for a, n in view["actions"].items()]
        lines.append("")
    lines += [f'### {x("review.resume")}', "", x("review.current", minutes=card["idle_minutes"]), ""]
    if card["feedback"]:
        lines += [f'| {x("review.threshold")} | {x("review.helpful")} | {x("review.off")} |', "|---:|---:|---:|"]
        lines += [f'| {f["idle_minutes"]} | {f["helpful"]} | {f["off"]} |' for f in card["feedback"]]
    else:
        lines.append(x("review.no_feedback"))
    lines += ["", f'| {x("review.threshold")} | {x("review.sessions")} | {x("review.median")} |', "|---:|---:|---:|"]
    lines += [f'| {c["idle_minutes"]}{" ←" if c["idle_minutes"] == card["idle_minutes"] else ""} | {c["sessions"]} | {c["median_minutes"]} |'
              for c in card["thresholds"]]
    lines += ["", f'### {x("review.sensitive")}', ""]
    skipped = result["sensitive_input"]["skipped"]
    if skipped:
        lines += [f'| {x("review.rule")} | {x("review.count")} |', "|---|---:|"]
        lines += [f"| `{rule}` | {n} |" for rule, n in skipped.items()]
    else:
        lines.append(x("review.no_skips"))
    lines += ["", x("review.pii_check"), ""]
    return "\n".join(lines)
