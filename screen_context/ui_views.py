"""Pages of the local web UI: the frame, the Today digest and search (#28).

Everything shown here comes from other people's screens, so every value is HTML-escaped. The
policy applies to every read (Service and material read through it); IDE apps are included
because this is the user's own path. Reads are audited on the user path like the CLI's.
"""
import html
import re
import time
from datetime import datetime, timedelta
from . import material, sessions, store
from .i18n import t
from .privacy import SELF_TITLE
from .service import Service

DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
SEARCH_LIMIT = 50
PREVIEWS = 20  # thumbnails on a results page; each one is an audited image read
STYLE = """\
:root { color-scheme: light dark; font-family: system-ui, sans-serif; --muted: #6b6b6b; }
@media (prefers-color-scheme: dark) { :root { --muted: #a0a0a0; } }
body { margin: 0; padding: 16px; }
main { max-width: 52rem; margin: 0 auto; }
header, nav, form { display: flex; flex-wrap: wrap; gap: .5rem; align-items: center; }
header { justify-content: space-between; margin-bottom: 1rem; }
button, input { font: inherit; padding: .4rem .7rem; }
input[type=search] { flex: 1 1 14rem; min-width: 0; }
table { border-collapse: collapse; width: 100%; }
th, td { text-align: left; padding: .3rem .5rem; border-bottom: 1px solid color-mix(in srgb, currentColor 15%, transparent); }
td.n, th.n { text-align: right; font-variant-numeric: tabular-nums; }
.note, .muted { color: var(--muted); font-size: .9rem; }
ol.results { padding-left: 1.2rem; }
ol.results li { margin-bottom: 1rem; overflow-wrap: anywhere; }
section.card { border: 1px solid color-mix(in srgb, currentColor 25%, transparent); border-radius: 8px; padding: .2rem 1rem .6rem; margin: 1rem 0; }
blockquote { margin: .5rem 0; padding-left: .8rem; border-left: 3px solid var(--muted); overflow-wrap: anywhere; }
img.preview { display: block; max-width: 100%; max-height: 18rem; margin-top: .4rem; border: 1px solid var(--muted); }
"""


def day(value):
    """A valid YYYY-MM-DD from the request, else today."""
    if value and DATE.fullmatch(value):
        try: return datetime.strptime(value, "%Y-%m-%d").strftime("%Y-%m-%d")
        except ValueError: pass
    return datetime.now().strftime("%Y-%m-%d")


def shift(date, days): return (datetime.strptime(date, "%Y-%m-%d") + timedelta(days=days)).strftime("%Y-%m-%d")
def hm(ts): return time.strftime("%H:%M", time.localtime(ts))
def esc(value): return html.escape(str(value), quote=True)


class Text:
    """Localized, escaped UI text."""
    def __init__(self, lang): self.lang = lang
    def __call__(self, key, **values): return esc(t(key, self.lang, **values))
    def minutes(self, seconds): return self("ui.minutes", n=round(seconds / 60)) if seconds >= 60 else self("ui.minutes.under")


def document(lang, body):
    return (f'<!doctype html><html lang="{lang}"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1"><title>{SELF_TITLE}</title>'
            f'<link rel="stylesheet" href="/ui.css"></head>{body}</html>')


def notice(lang, key):
    return document(lang, f'<body><main><h1>{esc(t("ui.title", lang))}</h1><p>{esc(t(key, lang))}</p></main></body>')


def page(settings, lang, date, content, query=""):
    """The frame every signed-in page shares: capture state, date navigation and search."""
    x = Text(lang)
    paused = (settings.root / "paused").exists()
    action = "resume" if paused else "pause"
    data = " ".join(f'data-{name}="{x(key)}"' for name, key in
                    (("expired", "ui.expired"), ("failed", "ui.failed"), ("copied", "ui.copied"), ("copy-failed", "ui.copy.failed")))
    return document(lang, f'<body {data}><main>'
        f'<header><h1>{x("ui.title")}</h1><div><span id="status">{x("ui.status.paused" if paused else "ui.status.recording")}</span> '
        f'<button type="button" data-action="{action}">{x("ui." + action)}</button></div></header>'
        f'<nav><a href="/?date={shift(date, -1)}">{x("ui.nav.prev")}</a>'
        f'<form method="get" action="/"><input type="date" name="date" value="{date}" aria-label="{x("ui.nav.go")}">'
        f'<button type="submit">{x("ui.nav.go")}</button></form>'
        f'<a href="/">{x("ui.nav.today")}</a><a href="/?date={shift(date, 1)}">{x("ui.nav.next")}</a></nav>'
        f'<form method="get" action="/search" role="search"><input type="hidden" name="date" value="{date}">'
        f'<input type="search" name="q" value="{esc(query)}" maxlength="500" aria-label="{x("ui.search.label")}" placeholder="{x("ui.search.label")}">'
        f'<button type="submit">{x("ui.search.button")}</button></form>'
        f'<p id="message" role="status"></p>{content}'
        f'<p class="note">{x("ui.untrusted")}</p><p class="note">{x("ui.session")}</p>'
        f'</main><script src="/ui.js"></script></body>')


def when(ts, date):
    """HH:MM on `date`, with the date otherwise (a session can start on an earlier day)."""
    local = datetime.fromtimestamp(ts)
    return local.strftime("%H:%M") if local.strftime("%Y-%m-%d") == date else local.strftime("%m-%d %H:%M")


def card(settings, lang, date, client):
    """The Resume card: the latest work session. Shown on today's page only; pull, never pushed."""
    if date != datetime.now().strftime("%Y-%m-%d"): return ""
    x, s = Text(lang), sessions.resume(settings, client)
    if s is None: return ""
    blocks = "".join(f'<li>{when(b["start_ts"], date)}–{when(b["end_ts"], date)} <strong>{esc(b["app"])}</strong> '
                     f'{esc((b["title"] or "")[:120])}</li>' for b in s["blocks"])
    documents = "".join(f'<li>{esc(d["title"][:160])} <span class="muted">{esc(d["app"])}'
                        f'{" · " + esc(", ".join(d["domains"])) if d["domains"] else ""}</span></li>' for d in s["documents"])
    return (f'<section class="card" id="resume-card" data-start="{s["start_ts"]}" data-end="{s["end_ts"]}">'
            f'<h2>{x("ui.card.title")}</h2>'
            f'<p class="muted">{x("ui.card.span", start=when(s["start_ts"], date), end=when(s["end_ts"], date), frames=s["frames"], app=s["last_app"])}</p>'
            f'<ul>{blocks}</ul>'
            + (f'<h3>{x("ui.card.documents")}</h3><ul>{documents}</ul>' if documents else "")
            + (f'<h3>{x("ui.card.excerpt")}</h3><blockquote>{esc(s["excerpt"])}</blockquote>' if s["excerpt"] else "")
            + f'<p><button type="button" data-feedback="helpful">{x("ui.card.helpful")}</button> '
            f'<button type="button" data-feedback="off">{x("ui.card.off")}</button> '
            f'<span id="feedback-message" data-thanks="{x("ui.card.thanks")}" role="status"></span></p>'
            f'<p class="note">{x("ui.card.note", minutes=s["idle_minutes"])}</p></section>')


def table(headers, rows):
    head = "".join(f'<th class="{"n" if numeric else ""}">{label}</th>' for label, numeric in headers)
    body = "".join("<tr>" + "".join(f'<td class="{"n" if numeric else ""}">{cell}</td>' for cell, (_, numeric) in zip(row, headers)) + "</tr>"
                   for row in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def today(settings, lang, date, client):
    x, d = Text(lang), material.digest(settings, date, client)
    out = [f"<section><h2>{date}</h2>"]
    if not d["intervals"]:
        return "".join(out) + f'<p>{x("ui.digest.empty")}</p></section>'
    out.append(f'<p>{x("ui.digest.summary", start=hm(d["start_ts"]), end=hm(d["end_ts"]), intervals=len(d["intervals"]), frames=d["frames"])}</p>'
               f'<p><button type="button" id="copy" data-date="{date}">{x("ui.copy")}</button></p>')
    out.append(f'<h3>{x("ui.digest.apps")}</h3>' + table(
        [(x("ui.col.app"), False), (x("ui.col.observed"), True), (x("ui.col.intervals"), True), (x("ui.col.screens"), True)],
        [(esc(a["app"]), x.minutes(a["seconds"]), a["intervals"], a["frames"]) for a in d["apps"]]))
    if d["domains"]:
        out.append(f'<h3>{x("ui.digest.sites")}</h3>' + table(
            [(x("ui.col.site"), False), (x("ui.col.observed"), True), (x("ui.col.intervals"), True)],
            [(esc(s["domain"]), x.minutes(s["seconds"]), s["intervals"]) for s in d["domains"][:30]]))
    if d["pages"]:
        items = "".join(f'<li>{hm(p["ts"])} {esc(p["title"][:200])} <span class="muted">{esc(", ".join(p["domains"][:3]))}</span></li>'
                        for p in d["pages"][:100])
        out.append(f'<h3>{x("ui.digest.pages")}</h3><ul>{items}</ul>')
    items = "".join(f'<li>{hm(i["start_ts"])}–{hm(i["end_ts"])} <strong>{esc(i["app"])}</strong> '
                    f'{esc(" / ".join(title[:80] for title in i["titles"][:3]))} '
                    f'<span class="muted">{esc(", ".join(i["domains"][:3]))}</span></li>' for i in d["intervals"])
    out.append(f'<h3>{x("ui.digest.intervals")}</h3><ol>{items}</ol><p class="note">{x("ui.observed.note")}</p></section>')
    return "".join(out)


def snippet(text, query, radius=120):
    """The text around the first hit, with the hit marked. Everything else is escaped."""
    flat = lambda s: re.sub(r"\s+", " ", s)  # OCR line breaks become spaces; the hit keeps its neighbours
    hit = re.search(re.escape(query), text, re.IGNORECASE)
    if hit is None: return esc(flat(text[:radius * 2]).strip())
    start, end = max(0, hit.start() - radius), min(len(text), hit.end() + radius)
    return (("… " if start else "") + esc(flat(text[start:hit.start()]).lstrip()) + f"<mark>{esc(hit.group())}</mark>"
            + esc(flat(text[hit.end():end]).rstrip()) + (" …" if end < len(text) else ""))


def previewable(settings, ids):
    """Frame IDs that still have a preview image within retention."""
    if not ids: return set()
    cutoff = time.time() - settings.retention("preview_retention_days") * 86400
    with store.connect(settings, readonly=True) as con:
        rows = con.execute(f"SELECT id FROM frames WHERE image_path IS NOT NULL AND ts >= ? AND id IN ({','.join('?' * len(ids))})",
                           [cutoff, *ids])
        return {r["id"] for r in rows}


def search(settings, lang, query, date, client):
    x, query = Text(lang), query.strip()
    back = f'<p><a href="/?date={date}">{x("ui.search.back", date=date)}</a></p>'
    if not query or len(query) > 500: return f'<section>{back}<p>{x("ui.search.invalid")}</p></section>'
    records = Service(settings, "full", client, audit_path="user").search_screen_history(query, limit=SEARCH_LIMIT)["records"]
    if not records: return f'<section><h2>{x("ui.search.none")}</h2>{back}</section>'
    previews = previewable(settings, [r["frame_id"] for r in records[:PREVIEWS]])
    items = []
    for r in records:
        when = datetime.fromtimestamp(r["ts"])
        image = (f'<img class="preview" loading="lazy" src="/image/{esc(r["frame_id"])}" alt="{x("ui.preview", time=when.strftime("%Y-%m-%d %H:%M"))}">'
                 if r["frame_id"] in previews else "")
        items.append(f'<li><div class="muted"><a href="/?date={when:%Y-%m-%d}">{when:%Y-%m-%d %H:%M}</a> · {esc(r["app"])} · {esc((r["title"] or "")[:200])}</div>'
                     f'<p>{snippet(r["text"] or "", query)}</p>{image}</li>')
    return f'<section><h2>{x("ui.search.results", n=len(records), query=query)}</h2>{back}<ol class="results">{"".join(items)}</ol></section>'
