"""Phase 0 probes stay importable anywhere and refuse to run off their platform."""
import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

REPO = Path(__file__).resolve().parents[1]
ROOT = REPO / "spikes" / "phase0"
PROBES = {"macos/touchid_probe.py": "darwin", "macos/secure_input_probe.py": "darwin",
          "windows/hello_probe.py": "win32", "windows/uia_password_probe.py": "win32",
          "windows/env_report.py": "win32"}


def load(relative):
    spec = importlib.util.spec_from_file_location(Path(relative).stem, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("relative", PROBES)
def test_probe_imports_without_platform_modules(relative):
    before = set(sys.modules)
    module = load(relative)
    assert callable(module.main)
    loaded = set(sys.modules) - before
    assert not {m for m in loaded if m.split(".")[0] in {"AppKit", "Foundation", "LocalAuthentication", "Quartz", "comtypes", "winrt", "screen_context"}}


@pytest.mark.parametrize("relative", [r for r, platform in PROBES.items() if platform != sys.platform])
def test_probe_refuses_other_platforms(relative):
    with pytest.raises(SystemExit):
        load(relative).main([])


@pytest.mark.skipif(shutil.which("sh") is None, reason="requires a POSIX shell to syntax-check the macOS-only scripts")
@pytest.mark.parametrize("script", [ROOT / "macos" / "signing_spike.sh", REPO / "packaging" / "macos" / "signing_identity.sh",
                                    REPO / "packaging" / "build_mac.sh"])
def test_signing_scripts_parse(script):
    subprocess.run(["sh", "-n", str(script)], check=True)
