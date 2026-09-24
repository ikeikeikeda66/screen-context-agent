"""Run the portable bundle verifier against the source CLI on this host."""
import importlib.util
from pathlib import Path
import sys


def test_encrypted_mcp_verification():
    path = Path(__file__).resolve().parents[1] / "packaging" / "verify_windows.py"
    spec = importlib.util.spec_from_file_location("verify_windows", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.verify_command([sys.executable, "-m", "screen_context.cli"])
