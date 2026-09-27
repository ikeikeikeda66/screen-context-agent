"""Control tabs (#30): each UI action calls the same function as its CLI command, writes need a
valid session and a confirmation bound to their parameters, and the pages show the right data."""
import asyncio
import json
import sys
import time
import pytest
from test_core import settings, add
from test_ui import world, sessions, call, opened, BASE, ORIGIN
from screen_context import access, audit, cli, exclusions, purge, store, ui, ui_actions
from screen_context.config import Settings

NOW = time.time()


def spy(monkeypatch, owner, name):
    calls, real = [], getattr(owner, name)
    def wrapper(*args, **kwargs):
        calls.append((args, kwargs))
        return real(*args, **kwargs)
    monkeypatch.setattr(owner, name, wrapper)
    return calls


async def confirmed(client, action, fields):
    ask = await client.post(f"/api/{action}", json=fields, headers=ORIGIN)
    assert ask.status_code == 200, ask.text
    return ask.json()["message"], await client.post(f"/api/{action}", json={**fields, "confirm": ask.json()["confirm"]}, headers=ORIGIN)


def with_ui(settings, sessions, steps):
    async def run(client):
        await opened(client, sessions)
        return await steps(client)
    return call(settings, sessions, run)


def run_cli(monkeypatch, settings, *argv):
    monkeypatch.setenv("SCREEN_CONTEXT_HOME", str(settings.root)); monkeypatch.setenv("SCREEN_CONTEXT_PLAINTEXT", "1")
    monkeypatch.setattr(sys, "argv", ["screen-context", *argv])
    cli.main()


# --- the same code path as the CLI ---------------------------------------------------------------

def test_purge_uses_purge_run_like_the_cli(settings, sessions, monkeypatch, capsys):
    keep = add(settings, "keep this", app="com.apple.Notes", ts=NOW - 100)
    gone = add(settings, "delete this", app="com.google.Chrome", ts=NOW - 90)
    calls = spy(monkeypatch, purge, "run")
    run_cli(monkeypatch, settings, "purge", "--app", "com.google.Chrome")
    assert calls[-1][1]["apply"] is False and json.loads(capsys.readouterr().out)["frames"] == 1
    async def steps(client):
        return await confirmed(client, "purge", {"app": "com.google.Chrome"})
    message, done = with_ui(settings, sessions, steps)
    assert "Delete 1 screens" in message and done.status_code == 200
    assert [c[1].get("apply", False) for c in calls[-3:]] == [False, False, True] and calls[-1][1]["actor"] == "ui"  # preview, re-check, delete
    with store.connect(settings, readonly=True) as con:
        assert [r["id"] for r in con.execute("SELECT id FROM frames")] == [keep["id"]]
    row = next(r for r in audit.rows(settings, client=ui.CLIENT) if r["action"] == "ui.purge")
    assert row["params"]["frames"] == 1


def test_retention_uses_set_retention_like_the_cli(settings, sessions, monkeypatch):
    calls = spy(monkeypatch, Settings, "set_retention")
    async def steps(client): return await confirmed(client, "retention", {"preview": "30", "text": "", "audit": "365"})
    message, done = with_ui(settings, sessions, steps)
    assert done.status_code == 200 and "30 days" in message and "forever" in message
    assert [(c[0][1], c[0][2]) for c in calls] == [("preview_retention_days", 30), ("text_retention_days", None), ("audit_retention_days", 365)]
    assert settings.retention("audit_retention_days") == 365


def test_exclude_uses_the_shared_function_and_the_cli_has_it_too(settings, sessions, monkeypatch, capsys):
    old = add(settings, "on https://news.example.net/today", ts=NOW - 100)
    calls = spy(monkeypatch, exclusions, "exclude")
    async def steps(client): return await confirmed(client, "exclude", {"kind": "domain", "value": "news.example.net", "delete_past": False})
    message, done = with_ui(settings, sessions, steps)
    assert done.status_code == 200 and calls[-1][1]["actor"] == "ui"
    assert "news.example.net" in settings.policy()["denied_domains"]
    with store.connect(settings, readonly=True) as con:                       # checkbox off: hidden, not deleted
        assert con.execute("SELECT count(*) FROM frames WHERE id=?", (old["id"],)).fetchone()[0] == 1
    run_cli(monkeypatch, settings, "exclude", "--app", "com.example.Game")
    assert json.loads(capsys.readouterr().out)["added"] is True and "com.example.Game" in settings.policy()["denied_apps"]


def test_exclude_with_delete_past_removes_only_that_rules_matches(settings, sessions):
    hit = add(settings, "read https://news.example.net/a", ts=NOW - 100)
    sub = add(settings, "read https://m.news.example.net/c", ts=NOW - 95)                   # subdomain: matched
    other = add(settings, "read https://docs.example.com/b", ts=NOW - 90)
    lookalike = add(settings, "read https://fakenews.example.net/d", ts=NOW - 80)          # contains the text, not the domain
    async def steps(client): return await confirmed(client, "exclude", {"kind": "domain", "value": "news.example.net", "delete_past": True})
    message, done = with_ui(settings, sessions, steps)
    assert "delete 2 screens" in message and done.json()["deleted"] == 2
    with store.connect(settings, readonly=True) as con:
        assert [r["id"] for r in con.execute("SELECT id FROM frames ORDER BY ts")] == [other["id"], lookalike["id"]]


def test_revoke_uses_access_revoke(settings, sessions, monkeypatch):
    access.issue(settings, "cursor")
    calls = spy(monkeypatch, access, "revoke")
    async def steps(client): return await confirmed(client, "revoke", {"name": "cursor"})
    message, done = with_ui(settings, sessions, steps)
    assert done.status_code == 200 and calls[-1][1] == {"actor": "ui"} and access.state(settings, "cursor") == "revoked"
    assert next(r for r in audit.rows(settings) if r["action"] == "clients.revoke")["client"] == "ui"


# --- writes need a session and a confirmation bound to the same parameters ---------------------

@pytest.mark.parametrize("action,fields", [("purge", {"app": "x"}), ("retention", {"preview": "30"}), ("exclude", {"kind": "app", "value": "x"}),
                                          ("revoke", {"name": "x"}), ("pause", {})])
def test_writes_are_refused_without_a_valid_session(settings, sessions, world, action, fields):
    async def steps(client):
        anonymous = await client.post(f"/api/{action}", json=fields, headers=ORIGIN)
        await opened(client, sessions)
        world.now += ui.IDLE + 1
        expired = await client.post(f"/api/{action}", json=fields, headers=ORIGIN)
        return anonymous.status_code, expired.status_code
    assert call(settings, sessions, steps) == (401, 401)


def test_a_confirmation_cannot_be_reused_for_other_parameters(settings, sessions):
    a = add(settings, "a", app="com.a", ts=NOW - 100)
    b = add(settings, "b", app="com.b", ts=NOW - 90)
    async def steps(client):
        nonce = (await client.post("/api/purge", json={"app": "com.a"}, headers=ORIGIN)).json()["confirm"]
        return await client.post("/api/purge", json={"app": "com.b", "confirm": nonce}, headers=ORIGIN)
    assert with_ui(settings, sessions, steps).status_code == 403
    with store.connect(settings, readonly=True) as con:
        assert con.execute("SELECT count(*) FROM frames").fetchone()[0] == 2


def test_invalid_input_and_managed_settings_are_explained(settings, sessions):
    class Managed:
        def values(self): return {"options": {"text_retention_days": 30}}
    locked = Settings(settings.root, plaintext=True, managed=Managed())
    async def steps(client):
        bad = [(await client.post("/api/retention", json={"preview": "0"}, headers=ORIGIN)),
               (await client.post("/api/purge", json={}, headers=ORIGIN)),
               (await client.post("/api/purge", json={"app": "com.none"}, headers=ORIGIN)),
               (await client.post("/api/exclude", json={"kind": "domain", "value": "not a domain"}, headers=ORIGIN))]
        return [r.status_code for r in bad], bad[2].json()["error"]
    codes, nothing = with_ui(settings, sessions, steps)
    assert codes == [400, 400, 400, 400] and "Nothing matches" in nothing
    async def managed(client): return await confirmed(client, "retention", {"preview": "90", "text": "365"})
    _, done = with_ui(locked, ui.Sessions(locked=lambda: False), managed)
    assert done.status_code == 403 and "administrator" in done.json()["error"]


# --- pages --------------------------------------------------------------------------------------

def page(settings, sessions, path, **params):
    async def steps(client): return await client.get(path, params=params)
    return with_ui(settings, sessions, steps)


def test_data_page_shows_usage_skips_forms_and_the_cli_for_reauthenticated_actions(settings, sessions):
    with store.connect(settings) as con:
        store.count_skip(con, time.strftime("%Y-%m-%d"), "card_number")
        store.count_skip(con, time.strftime("%Y-%m-%d"), "name+phone")
    text = page(settings, sessions, "/data", kind="domain", value="news.example.net").text
    assert "1 screens not recorded: possible card number" in text and "possible personal data (name+phone)" in text
    assert 'data-write="retention"' in text and 'data-write="purge"' in text and 'value="90"' in text
    assert 'name="delete_past">' in text and "checked" not in text.split('name="delete_past"')[1][:20]      # off by default
    assert 'value="news.example.net"' in text and '<option value="domain" selected>' in text
    assert "screen-context backup FILE" in text and 'data-write="backup"' not in text


def test_access_page_shows_queries_and_returned_screens_escaped(settings, sessions):
    frame = add(settings, "t", title="Returned <b>page</b>", ts=NOW - 100)
    audit.record(settings, "agent", "cursor", "search_screen_history", query="<script>x</script>", frame_ids=[frame["id"]], count=1)
    audit.record(settings, "agent", "other", "get_recent_activity", count=0)
    audit.record(settings, "user", "cli", "export", count=0)
    text = page(settings, sessions, "/access", client="cursor").text
    assert "&lt;script&gt;x&lt;/script&gt;" in text and "<script>x" not in text
    assert "Returned &lt;b&gt;page&lt;/b&gt;" in text and "get_recent_activity" not in text
    assistants = page(settings, sessions, "/access").text                              # default: the agent path only
    assert "get_recent_activity" in assistants and ">export<" not in assistants and "ui.open" not in assistants
    everything = page(settings, sessions, "/access", client="*").text
    assert ">export<" in everything and "ui.open" in everything


def test_clients_page_lists_revokes_and_sends_approval_to_the_app(settings, sessions):
    access.issue(settings, "cursor", "full")
    text = page(settings, sessions, "/clients").text
    assert "cursor" in text and "full" in text and "waiting for approval" in text
    assert 'data-action="revoke" data-param-name="cursor"' in text and "clients approve cursor" in text and 'data-action="approve"' not in text


def test_digest_offers_exclude_links_and_deletes_one_interval(settings, sessions):
    first = add(settings, "chrome work https://docs.example.com", app="com.google.Chrome", ts=NOW - 400)
    add(settings, "notes", app="com.apple.Notes", ts=NOW - 300)
    today = time.strftime("%Y-%m-%d")
    text = page(settings, sessions, "/", date=today).text
    assert "/data?kind=app&amp;value=com.google.Chrome#exclude" in text and "/data?kind=domain&amp;value=docs.example.com#exclude" in text
    import re
    button = re.search(r'data-action="purge" data-param-from="([^"]+)" data-param-to="([^"]+)" data-param-app="com.google.Chrome"', text)
    async def steps(client): return await confirmed(client, "purge", {"from": button.group(1), "to": button.group(2), "app": "com.google.Chrome"})
    message, done = with_ui(settings, sessions, steps)
    assert "Delete 1 screens" in message and done.status_code == 200
    with store.connect(settings, readonly=True) as con:
        assert [r["app_bundle"] for r in con.execute("SELECT app_bundle FROM frames")] == ["com.apple.Notes"]


def test_purge_warns_about_copies_but_not_about_page_views(settings):
    frame = add(settings, "t", ts=NOW - 100)
    audit.record(settings, "user", "ui", "get_diary_material", frame_ids=[frame["id"]], count=1)       # viewing the Today page
    assert purge.plan(settings, [frame["id"]])["already_received_by"] == []
    audit.record(settings, "user", "ui.copy", "get_diary_material", frame_ids=[frame["id"]], count=1)  # copy for your assistant
    audit.record(settings, "agent", "cursor", "search_screen_history", frame_ids=[frame["id"]], count=1)
    assert {r["client"] for r in purge.plan(settings, [frame["id"]])["already_received_by"]} == {"ui.copy", "cursor"}
