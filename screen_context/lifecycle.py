"""Full wipe, backup and restore (roadmap decisions 5-C and 6).

wipe: the key is deleted from the credential store first, which makes every encrypted
file unreadable at once (crypto-erase); then the data folder is removed. Both workers'
locks are held throughout, so capture and indexing cannot run or start meanwhile.

backup: one zip with a consistent database snapshot, the preview images and the settings.
Those stay encrypted with the data key; the data key itself is sealed with a key derived
from the user's passphrase (scrypt, AES-GCM). A backup therefore restores on another
machine, and after a wipe, but only with the passphrase.
"""
import base64
import json
import os
import shutil
import tempfile
import time
import zipfile
from contextlib import ExitStack
from pathlib import Path
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from . import audit, store
from .crypto import atomic_write, delete_key, get_key, store_key
from .locking import lock

FORMAT = 1
AAD = b"screen-context-backup-v1"
SETTINGS_FILES = ("policy.json", "capture-options.json")
MIN_PASSPHRASE = 12
REMAINS = "Backups made with `screen-context backup` can still be restored with their passphrase."


def workers_stopped(settings):
    """Hold both worker locks, or raise if capture or indexing is running."""
    stack = ExitStack()
    try:
        for name in ("capture.lock", "indexer.lock"):
            stack.enter_context(lock(settings.root / name))
    except OSError:
        stack.close()
        raise RuntimeError("Quit ScreenContext (capture and indexer) first") from None
    return stack


def wipe(settings):
    if not settings.root.exists(): raise FileNotFoundError(f"No data folder at {settings.root}")
    with workers_stopped(settings):
        key_deleted = False if settings.plaintext else delete_key(settings)
        for path in settings.root.iterdir():
            if path.name in ("capture.lock", "indexer.lock"): continue  # still held; removed below
            shutil.rmtree(path) if path.is_dir() and not path.is_symlink() else path.unlink()
    shutil.rmtree(settings.root)
    return {"wiped": str(settings.root), "key_deleted": key_deleted, "note": REMAINS if key_deleted else
            "The key comes from SCREEN_CONTEXT_KEY; remove it yourself. " + REMAINS}


def derive(passphrase, salt, n=2**15):
    return Scrypt(salt=salt, length=32, n=n, r=8, p=1).derive(passphrase.encode())


def backup(settings, target, passphrase):
    if settings.option("backup_allowed", True) is False: raise PermissionError("Backups are disabled by your administrator")
    if len(passphrase) < MIN_PASSPHRASE: raise ValueError(f"Use a passphrase of at least {MIN_PASSPHRASE} characters")
    target = Path(target)
    if target.exists(): raise FileExistsError(f"{target} already exists")
    manifest = {"format": FORMAT, "created": time.time(), "schema": store.SCHEMA_VERSION, "encrypted": not settings.plaintext}
    if not settings.plaintext:
        salt, nonce = os.urandom(16), os.urandom(12)
        sealed = AESGCM(derive(passphrase, salt)).encrypt(nonce, get_key(settings), AAD)
        manifest.update(kdf={"name": "scrypt", "n": 2**15, "r": 8, "p": 1, "salt": base64.b64encode(salt).decode()},
                        key=base64.b64encode(nonce + sealed).decode())
    images = sorted(p for p in (settings.root / "images").glob("*") if p.is_file())
    with tempfile.TemporaryDirectory(dir=target.parent) as temp:
        snapshot = Path(temp) / "history.db"
        store.snapshot(settings, snapshot)
        partial = Path(temp) / "backup.zip"
        with zipfile.ZipFile(partial, "w", zipfile.ZIP_STORED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest))
            archive.write(snapshot, "history.db")
            for image in images: archive.write(image, "images/" + image.name)
            for name in SETTINGS_FILES:
                if (settings.root / name).exists(): archive.write(settings.root / name, name)
        os.replace(partial, target)
    target.chmod(0o600)
    audit.record(settings, "user", "cli", "backup", params={"images": len(images)})
    return {"backup": str(target), "images": len(images), "encrypted": manifest["encrypted"]}


def restore(settings, source, passphrase, replace=False):
    """Check the passphrase before writing anything; refuse to overwrite unless `replace`."""
    with zipfile.ZipFile(source) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        if manifest.get("format") != FORMAT: raise ValueError("Unknown backup format")
        if manifest["encrypted"] == settings.plaintext: raise ValueError("Backup and data folder differ in encryption mode")
        key = None
        if manifest["encrypted"]:
            kdf, sealed = manifest["kdf"], base64.b64decode(manifest["key"])
            try: key = AESGCM(derive(passphrase, base64.b64decode(kdf["salt"]), kdf["n"])).decrypt(sealed[:12], sealed[12:], AAD)
            except InvalidTag: raise PermissionError("Wrong passphrase") from None
        names = archive.namelist()
        images = [n for n in names if n.startswith("images/")]
        if any(Path(n).name != n[len("images/"):] or n == "images/" for n in images): raise ValueError("Unsafe path in backup")
        if settings.db.exists() and not replace: raise FileExistsError("A history already exists here; use --replace to overwrite it")
        settings.prepare()
        with workers_stopped(settings):
            for suffix in ("", "-wal", "-shm"): Path(str(settings.db) + suffix).unlink(missing_ok=True)
            for old in (settings.root / "images").glob("*"): old.unlink()
            atomic_write(settings.db, archive.read("history.db"))
            for name in images: atomic_write(settings.root / "images" / Path(name).name, archive.read(name))
            for name in SETTINGS_FILES:
                if name in names: atomic_write(settings.root / name, archive.read(name))
            if key: store_key(settings, key)
    versions = store.initialize(settings)  # migrates an older backup to this version's schema
    audit.record(settings, "user", "cli", "restore", params={"images": len(images), "schema": list(versions)})
    return {"restored": str(settings.root), "images": len(images), "schema": list(versions)}
