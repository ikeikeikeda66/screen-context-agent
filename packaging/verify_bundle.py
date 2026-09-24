"""Verify the frozen app without requesting screen access or opening a GUI."""
from pathlib import Path
import os
import subprocess
import tempfile

root = Path(__file__).resolve().parent.parent
bundle = root / "dist/ScreenContext.app"
resources = bundle / "Contents/Resources"
python = bundle / "Contents/MacOS/python"
application = bundle / "Contents/MacOS/ScreenContext"

# Do not use the launcher until all native dependencies pass in a plain interpreter.
probe = '''
import sys
from pathlib import Path
p=Path(sys.argv[1])
v=f'{sys.version_info[0]}.{sys.version_info[1]}'
sys.path[:]=[str(p/f'lib/python{v}'),str(p/f'lib/python{v.replace(".","")}.zip'),str(p),str(p/f'lib/python{v}/lib-dynload')]
from screen_context.crypto import seal, unseal
from screen_context.config import Settings
from screen_context.store import initialize, connect
import _cffi_backend
import sqlcipher3.dbapi2
key=b't'*32
assert unseal(seal(b'synthetic',key),key)==b'synthetic'
cfg=Settings.environment()
initialize(cfg)
with connect(cfg, readonly=True) as con:
    assert con.execute('SELECT count(*) FROM frames').fetchone()[0]==0
print('Frozen dependencies and encrypted DB: OK')
'''
with tempfile.TemporaryDirectory(prefix="screen-context-bundle-") as directory:
    env = {**os.environ, "SCREEN_CONTEXT_HOME": directory, "SCREEN_CONTEXT_KEY": os.urandom(32).hex()}
    env.pop("SCREEN_CONTEXT_PLAINTEXT", None)
    subprocess.run([str(python), "-I", "-S", "-c", probe, str(resources)], env=env, cwd=directory, check=True, timeout=30)
    for args in (("--help",), ("status",)):
        subprocess.run([str(application), *args], env=env, cwd=directory, check=True, timeout=20)
    assert not (Path(directory)/"history.db").read_bytes().startswith(b"SQLite format")
assert not list(bundle.rglob("Tk.framework"))
subprocess.run(["codesign", "--verify", "--deep", "--strict", str(bundle)], check=True)
print("Bundle validation: OK; no screen capture performed")
