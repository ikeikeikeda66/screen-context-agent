"""OS credential store protects a random key; images and spool use AES-GCM."""
import os
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def get_key(settings, create=False):
    # Explicit environment key permits headless deployments without credential UI.
    value = os.environ.get("SCREEN_CONTEXT_KEY")
    if not value:
        import keyring
        account = str(settings.root)
        value = keyring.get_password("screen-context-agent", account)
        if not value and create:
            value = os.urandom(32).hex()
            keyring.set_password("screen-context-agent", account, value)
    if not value: raise RuntimeError("Encryption key missing; run screen-context init")
    key = bytes.fromhex(value)
    if len(key) != 32: raise ValueError("SCREEN_CONTEXT_KEY must be 64 hex characters")
    return key


def store_key(settings, key):
    """Put a key (restored from a backup) into the OS credential store for this data folder."""
    if os.environ.get("SCREEN_CONTEXT_KEY"):
        if bytes.fromhex(os.environ["SCREEN_CONTEXT_KEY"]) != key: raise RuntimeError("SCREEN_CONTEXT_KEY does not match the backup's key")
        return
    import keyring
    keyring.set_password("screen-context-agent", str(settings.root), key.hex())


def delete_key(settings):
    """Remove the key from the OS credential store. False when the key comes from SCREEN_CONTEXT_KEY,
    which only the user can remove."""
    if os.environ.get("SCREEN_CONTEXT_KEY"): return False
    import keyring
    from keyring.errors import PasswordDeleteError
    try: keyring.delete_password("screen-context-agent", str(settings.root))
    except PasswordDeleteError: pass  # already gone
    return True


def seal(data, key):
    nonce = os.urandom(12)
    return b"SCA1" + nonce + AESGCM(key).encrypt(nonce, data, b"screen-context-v1")


def unseal(data, key):
    if not data.startswith(b"SCA1"): raise ValueError("Invalid encrypted file")
    return AESGCM(key).decrypt(data[4:16], data[16:], b"screen-context-v1")


def atomic_write(path, data):
    import uuid
    tmp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        fd = os.open(tmp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
