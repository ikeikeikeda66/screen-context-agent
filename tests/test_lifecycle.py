"""Wipe, backup and restore, with the encrypted database and a fake OS credential store."""
import json
import subprocess
import sys
import types
import uuid
import time
import zipfile
import pytest
from screen_context import access, audit, lifecycle, store
from screen_context.config import Settings
from screen_context.locking import lock
from screen_context.service import Service

MARKER = "zqxjbackup"
PASSPHRASE = "correct horse battery staple"


class Keyring:
    """In-memory stand-in for the keyring package."""
    def __init__(self): self.items, self.deleted_while = {}, []
    def get_password(self, service, account): return self.items.get((service, account))
    def set_password(self, service, account, value): self.items[(service, account)] = value
    def delete_password(self, service, account):
        from pathlib import Path
        self.deleted_while.append(Path(account).joinpath("history.db").exists())  # data still there?
        if (service, account) not in self.items: raise self.errors.PasswordDeleteError()
        del self.items[(service, account)]


@pytest.fixture
def keyring(monkeypatch):
    fake = Keyring()
    errors = types.SimpleNamespace(PasswordDeleteError=type("PasswordDeleteError", (Exception,), {}))
    fake.errors = errors
    monkeypatch.setitem(sys.modules, "keyring", fake)
    monkeypatch.setitem(sys.modules, "keyring.errors", errors)
    monkeypatch.delenv("SCREEN_CONTEXT_KEY", raising=False)
    return fake


def filled(root):
    settings = Settings(root)
    store.initialize(settings)
    record = dict(id=uuid.uuid4().hex, ts=time.time(), app_bundle="x", app_name="x", window_title="Docs", display_id="1", dhash="0",
                  image_path="p.webp.enc", ocr_text="page " + MARKER, ocr_json="[]", domains="[]", src_w=1, src_h=1, ocr_ms=1)
    with store.connect(settings) as con: store.insert(con, record)
    (settings.root / "images" / "p.webp.enc").write_bytes(b"sealed image")
    access.issue(settings, "cursor")
    return settings


def search(settings): return Service(settings, "full", audit_path=None).search_screen_history(MARKER)["count"]


def test_wipe_deletes_the_key_before_the_data(tmp_path, keyring):
    settings = filled(tmp_path / "data")
    result = lifecycle.wipe(settings)
    assert keyring.deleted_while == [True] and keyring.items == {}
    assert not settings.root.exists() and result["key_deleted"] and "backup" in result["note"]


def test_wipe_refuses_while_a_worker_runs(tmp_path, keyring):
    settings = filled(tmp_path / "data")
    with lock(settings.root / "indexer.lock"):
        with pytest.raises(RuntimeError, match="Quit ScreenContext"): lifecycle.wipe(settings)
    assert settings.db.exists() and keyring.items


def test_backup_round_trip_to_another_folder(tmp_path, keyring):
    source = filled(tmp_path / "old machine")
    archive = tmp_path / "history.scbackup"
    assert lifecycle.backup(source, archive, PASSPHRASE)["images"] == 1
    raw = archive.read_bytes()
    assert MARKER.encode() not in raw and bytes.fromhex(keyring.items[("screen-context-agent", str(source.root))]) not in raw
    target = Settings(tmp_path / "new machine")
    lifecycle.restore(target, archive, PASSPHRASE)
    assert search(target) == 1 and (target.root / "images" / "p.webp.enc").read_bytes() == b"sealed image"
    assert keyring.items[("screen-context-agent", str(target.root))] == keyring.items[("screen-context-agent", str(source.root))]
    assert [c["name"] for c in access.clients(target)] == ["cursor"]
    # The backup is recorded in the source after its snapshot; the restore in the target.
    assert audit.rows(source)[0]["action"] == "backup" and audit.rows(target)[0]["action"] == "restore"


def test_wrong_passphrase_writes_nothing(tmp_path, keyring):
    archive = tmp_path / "b.zip"
    lifecycle.backup(filled(tmp_path / "data"), archive, PASSPHRASE)
    target = Settings(tmp_path / "elsewhere")
    with pytest.raises(PermissionError, match="Wrong passphrase"): lifecycle.restore(target, archive, "not the passphrase")
    assert not target.root.exists() and ("screen-context-agent", str(target.root)) not in keyring.items


def test_restore_after_wipe_and_overwrite_protection(tmp_path, keyring):
    settings = filled(tmp_path / "data")
    archive = tmp_path / "b.zip"
    lifecycle.backup(settings, archive, PASSPHRASE)
    lifecycle.wipe(settings)
    lifecycle.restore(settings, archive, PASSPHRASE)
    assert search(settings) == 1
    with pytest.raises(FileExistsError): lifecycle.restore(settings, archive, PASSPHRASE)
    lifecycle.restore(settings, archive, PASSPHRASE, replace=True)
    assert search(settings) == 1


def test_backup_rules(tmp_path, keyring):
    settings = filled(tmp_path / "data")
    with pytest.raises(ValueError): lifecycle.backup(settings, tmp_path / "b.zip", "short")
    (tmp_path / "exists.zip").write_bytes(b"")
    with pytest.raises(FileExistsError): lifecycle.backup(settings, tmp_path / "exists.zip", PASSPHRASE)
    class Managed:
        def values(self): return {"options": {"backup_allowed": False}}
    with pytest.raises(PermissionError): lifecycle.backup(Settings(settings.root, managed=Managed()), tmp_path / "c.zip", PASSPHRASE)


def test_unsafe_archive_paths_are_refused(tmp_path, keyring):
    archive = tmp_path / "b.zip"
    lifecycle.backup(filled(tmp_path / "data"), archive, PASSPHRASE)
    with zipfile.ZipFile(archive, "a") as z: z.writestr("images/../../escape", b"x")
    with pytest.raises(ValueError, match="Unsafe"): lifecycle.restore(Settings(tmp_path / "t"), archive, PASSPHRASE)
    assert not (tmp_path / "escape").exists()


def test_cli_wipe_needs_erase_and_backup_uses_a_passphrase_file(tmp_path):
    key = "ab" * 32
    env = {"SCREEN_CONTEXT_HOME": str(tmp_path / "data"), "SCREEN_CONTEXT_KEY": key, "PATH": "/usr/bin:/bin"}
    cli = lambda *a, **k: subprocess.run([sys.executable, "-m", "screen_context.cli", *a], env={**env, **k}, capture_output=True, text=True, input="no\n")
    assert cli("init").returncode == 0
    secret = tmp_path / "pass.txt"; secret.write_text(PASSPHRASE + "\n")
    assert json.loads(cli("backup", str(tmp_path / "b.zip"), "--passphrase-file", str(secret)).stdout)["encrypted"] is True
    refused = cli("wipe")
    assert refused.returncode != 0 and "nothing was deleted" in refused.stderr and (tmp_path / "data" / "history.db").exists()
    wiped = json.loads(cli("wipe", "--confirm", "ERASE").stdout)
    assert wiped["key_deleted"] is False and "SCREEN_CONTEXT_KEY" in wiped["note"] and not (tmp_path / "data").exists()
    assert json.loads(cli("restore", str(tmp_path / "b.zip"), "--passphrase-file", str(secret)).stdout)["schema"] == [3, 3]
