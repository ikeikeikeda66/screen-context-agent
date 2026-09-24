"""Compact, bounded diary material for an LLM prompt. Evidence of viewing only."""
import time
from .i18n import resolve, t
from .service import Service

FILE_SUFFIXES = {"py", "md", "js", "ts", "json", "yaml", "yml", "ps1", "exe", "app", "html", "css", "txt", "sh", "dmg", "pdf", "zip", "plist", "resolved"}


def sites(domains):
    return [d for d in domains if d.rsplit(".", 1)[-1] not in FILE_SUFFIXES]


def pages(service, date):
    offset = 0
    while offset is not None:
        page = service.get_diary_material(date=date, offset=offset, limit=10)
        yield page
        offset = page["next_offset"]


def readable(line):
    """Skip OCR noise: toolbar fragments, symbol runs, near-duplicate short lines."""
    letters = sum(ch.isalnum() for ch in line)
    return len(line) >= 6 and letters / len(line) >= 0.6


def furniture(blocks, ratio=0.2, minimum=3):
    """Lines that recur across many intervals are UI furniture (tab bars, bookmarks), not content."""
    from collections import Counter
    counts = Counter()
    for b in blocks:
        counts.update({" ".join(l.split()) for l in b["text"].splitlines()})
    threshold = max(minimum, int(len(blocks) * ratio))
    return {line for line, n in counts.items() if n >= threshold}


def excerpt(text, limit, skip=frozenset()):
    seen, out, used = set(), [], 0
    for line in (text or "").splitlines():
        line = " ".join(line.split())
        if not readable(line) or line in seen or line in skip: continue
        seen.add(line)
        if used + len(line) + 3 > limit: break
        out.append(line); used += len(line) + 3
    return " / ".join(out)


def diary_markdown(settings, date, budget=6000, per_block=240, client="diary", lang=None):
    lang = lang or resolve(settings)
    service = Service(settings, "full", client)
    blocks, meta = [], None
    for page in pages(service, date):
        meta = meta or page
        blocks.extend(page["records"])
    hm = lambda t: time.strftime("%H:%M", time.localtime(t))
    # Consecutive intervals of one app within 10 minutes form one entry, even when the window title changes.
    merged = []
    for b in blocks:
        last = merged[-1] if merged else None
        if last and last["app"] == b["app"] and b["start_ts"] - last["end_ts"] <= 600:
            last["end_ts"] = b["end_ts"]; last["frames"] += b["frames"]
            last["text"] += "\n" + b["text"]; last["domains"] = sorted(set(last["domains"]) | set(b["domains"]))
            if b["title"] and b["title"] not in last["titles"]: last["titles"].append(b["title"])
        else: merged.append({**b, "titles": [b["title"]] if b["title"] else []})
    lines = [t("diary.title", lang, date=date, timezone=meta["timezone"] if meta else ""), t("diary.rules", lang), ""]
    if not merged:
        lines.append(t("diary.empty", lang)); return "\n".join(lines)
    gaps = [(a["end_ts"], b["start_ts"]) for a, b in zip(merged, merged[1:]) if b["start_ts"] - a["end_ts"] > 3600]
    lines.append(t("diary.range", lang, start=hm(merged[0]["start_ts"]), end=hm(merged[-1]["end_ts"]), blocks=len(merged), frames=sum(b["frames"] for b in merged)))
    if gaps: lines.append(t("diary.gaps", lang, gaps=t("list.sep", lang).join(f"{hm(a)}–{hm(b)}" for a, b in gaps)))
    lines.append("")
    # budget bounds the whole section: headers first, excerpts while room remains,
    # and a per-app count for intervals that no longer fit.
    used = sum(len(x) + 1 for x in lines)
    omitted, dropped, skip = 0, [], furniture(merged)
    for b in merged:
        head = f"- {hm(b['start_ts'])}–{hm(b['end_ts'])} {b['app']}"
        titles = [t[:50] for t in b["titles"][:3]]
        if titles: head += " | " + " / ".join(titles) + (t("diary.more_titles", lang, n=len(b["titles"]) - 3) if len(b["titles"]) > 3 else "")
        if sites(b["domains"]): head += " | " + ", ".join(sites(b["domains"]))[:80]
        head += f" | frame={b['frame_id'][:8]}"
        body = excerpt(b["text"], per_block, skip)
        if not body and not titles: continue
        if dropped or used + len(head) + 1 > budget - 200:
            dropped.append(b["app"]); continue
        used += len(head) + 1
        if body and used + len(body) + 3 <= budget - 200:
            used += len(body) + 3; head += f"\n  {body}"
        elif body: omitted += 1
        lines.append(head)
    if omitted: lines.append(t("diary.omitted", lang, n=omitted))
    if dropped:
        from collections import Counter
        counts = t("list.sep", lang).join(f"{app} {n}" for app, n in Counter(dropped).most_common(8))
        lines.append(t("diary.dropped", lang, n=len(dropped), apps=counts))
    return "\n".join(lines)
