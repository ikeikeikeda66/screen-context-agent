"""Today view (#28): the digest matches diary-material, search shows context and previews, the
policy always applies (IDE apps shown on this user path), and screen text is escaped."""
import re
from datetime import datetime
import pytest
from test_core import settings, add, change
from test_ui import world, sessions, call, opened, BASE
from screen_context import audit, material, store, ui, ui_views

DAY = "2026-09-20"
at = lambda hhmm: datetime.strptime(f"{DAY} {hhmm}", "%Y-%m-%d %H:%M").timestamp()


@pytest.fixture
def day(settings):
    add(settings, "設計レビュー https://docs.example.com/spec", app="com.google.Chrome", ts=at("09:00"), title="Spec — Docs")
    add(settings, "設計レビュー続き https://docs.example.com/spec", app="com.google.Chrome", ts=at("09:05"), title="Spec — Docs")
    add(settings, "def main(): return 42", app="com.microsoft.VSCode", ts=at("09:20"), title="main.py")
    add(settings, "Pull request https://github.com/org/repo/pull/7", app="com.google.Chrome", ts=at("11:00"), title="PR #7")
    add(settings, "secret vault", app="com.1password.1password", ts=at("10:00"), title="Vault")             # denied app
    add(settings, "hidden https://private.example.org/x", app="com.google.Chrome", ts=at("10:30"), title="Private page")
    change(settings, denied_domains=["private.example.org"])                                               # excluded later
    return settings


def page(settings, sessions, path, **params):
    async def steps(client):
        await opened(client, sessions)
        return await client.get(path, params=params)
    return call(settings, sessions, steps)


def test_digest_numbers_match_diary_material(day):
    digest = material.digest(day, DAY)
    text = material.diary_markdown(day, DAY, lang="en")
    start, end, intervals, frames = re.search(r"Recorded range: (\S+)–(\S+), (\d+) intervals, (\d+) screens", text).groups()
    assert (ui_views.hm(digest["start_ts"]), ui_views.hm(digest["end_ts"])) == (start, end)
    assert (len(digest["intervals"]), digest["frames"]) == (int(intervals), int(frames)) == (3, 4)
    assert sum(a["frames"] for a in digest["apps"]) == digest["frames"]
    chrome = next(a for a in digest["apps"] if a["app"] == "com.google.Chrome")
    assert (chrome["intervals"], chrome["frames"], chrome["seconds"]) == (2, 3, 300)   # 09:00–09:05 and 11:00
    assert [d["domain"] for d in digest["domains"]] == ["docs.example.com", "github.com"]
    assert [p["title"] for p in digest["pages"]] == ["Spec — Docs", "PR #7"]


def test_minutes_show_under_one_minute_for_a_single_screen():
    x = ui_views.Text("en")
    assert (x.minutes(0), x.minutes(59), x.minutes(300)) == ("&lt;1 min", "&lt;1 min", "5 min")


def test_excluded_apps_and_domains_never_appear_ide_does(day, sessions):
    home = page(day, sessions, "/", date=DAY).text
    assert "Spec" in home and "main.py" in home and "PR #7" in home                   # IDE shown on the user path
    for hidden in ("1password", "Vault", "Private page", "private.example.org"):
        assert hidden not in home
    for query in ("secret vault", "hidden"):
        assert "No results" in page(day, sessions, "/search", q=query, date=DAY).text
    assert "Vault" not in page(day, sessions, "/material", date=DAY).text


def test_search_shows_context_marks_the_hit_and_escapes_screen_text(settings, sessions):
    add(settings, "<i>x</i> " + "before " * 40 + "needle <script>alert(1)</script> " + "after " * 40, title="<b>t</b>", ts=at("08:00"))
    add(settings, "a tag <u>under</u> here", ts=at("08:01"))
    result = page(settings, sessions, "/search", q="needle", date=DAY)
    assert result.status_code == 200 and "<mark>needle</mark>" in result.text
    assert "<script>alert" not in result.text and "&lt;script&gt;" in result.text      # after the hit
    assert "<i>x</i>" not in result.text                                               # trimmed: too far before the hit
    assert "&lt;b&gt;t&lt;/b&gt;" in result.text and "… " in result.text
    tag = page(settings, sessions, "/search", q="<u>under</u>", date=DAY).text
    assert "<mark>&lt;u&gt;under&lt;/u&gt;</mark>" in tag and "<u>" not in tag           # the hit itself
    joined = page(settings, sessions, "/search", q="under", date=DAY).text
    assert "&lt;u&gt;<mark>under</mark>&lt;/u&gt;" in joined                          # no space added around the hit
    near = page(settings, sessions, "/search", q="here", date=DAY).text
    assert "&lt;u&gt;under&lt;/u&gt; <mark>here</mark>" in near                        # before the hit
    row = next(r for r in audit.rows(settings, client=ui.CLIENT) if r["action"] == "search_screen_history")
    assert (row["path"], row["query"]) == ("user", "here")                                # audited like the CLI
    assert "1–500" in page(settings, sessions, "/search", q="   ").text


def test_digest_escapes_screen_text_and_is_audited(settings, sessions):
    shown = add(settings, "see https://x.example.com/a", title="<img src=x onerror=alert(1)>", ts=at("13:00"))
    home = page(settings, sessions, "/", date=DAY).text
    assert "<img src=x" not in home and home.count("&lt;img src=x onerror=alert(1)&gt;") == 2   # pages and intervals
    row = next(r for r in audit.rows(settings, client=ui.CLIENT) if r["action"] == "get_diary_material")
    assert row["path"] == "user" and shown["id"] in row["frame_ids"]


def test_date_navigation(day, sessions):
    home = page(day, sessions, "/", date=DAY).text
    assert 'href="/?date=2026-09-19"' in home and 'href="/?date=2026-09-21"' in home and f'value="{DAY}"' in home
    assert "No records for this day" in page(day, sessions, "/", date="2026-09-19").text
    today = datetime.now().strftime("%Y-%m-%d")
    for bad in ("2026-13-40", "yesterday", "../etc"):
        assert f'value="{today}"' in page(day, sessions, "/", date=bad).text


def test_copy_endpoint_returns_diary_material(day, sessions):
    copied = page(day, sessions, "/material", date=DAY)
    assert copied.status_code == 200 and copied.headers["content-type"].startswith("text/plain")
    assert copied.text == material.diary_markdown(day, DAY, client=ui.CLIENT, lang="en")
    async def anonymous(client): return await client.get("/material", params={"date": DAY})
    assert call(day, sessions, anonymous).status_code == 401


def test_previews_only_for_frames_that_have_one(settings, sessions):
    shown = add(settings, "preview target", ts=at("12:00"))
    add(settings, "preview target without image", ts=at("12:01"))
    denied = add(settings, "preview target denied", app="com.1password.1password", ts=at("12:02"))
    for frame in (shown, denied):
        (settings.root / "images").mkdir(exist_ok=True)
        (settings.root / "images" / f"{frame['id']}.webp").write_bytes(b"RIFF....WEBP")
        with store.connect(settings) as con:
            con.execute("UPDATE frames SET image_path=?, ts=? WHERE id=?", (f"{frame['id']}.webp", __import__("time").time(), frame["id"]))
    results = page(settings, sessions, "/search", q="preview target")
    assert results.text.count('class="preview"') == 1 and f'/image/{shown["id"]}' in results.text
    assert page(settings, sessions, f"/image/{shown['id']}").content == b"RIFF....WEBP"
    assert page(settings, sessions, f"/image/{denied['id']}").status_code == 404        # policy applies to images too
    async def anonymous(client): return await client.get(f"/image/{shown['id']}")
    assert call(settings, sessions, anonymous).status_code == 401
