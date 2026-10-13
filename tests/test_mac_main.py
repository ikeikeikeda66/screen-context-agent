import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_mac_main():
    spec = importlib.util.spec_from_file_location("mac_main_under_test", ROOT / "packaging/mac_main.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # must not run main(): the entry point sits under __main__
    return module


def test_app_name_runs_the_menu_bar_app_without_arguments():
    plan = load_mac_main().plan
    assert plan(["x.py"], "ScreenContext") == ("gui", ["x.py"])
    assert plan(["x.py"], "") == ("gui", ["x.py"])


def test_app_name_with_arguments_runs_the_cli():
    plan = load_mac_main().plan
    assert plan(["x.py", "index", "--watch"], "ScreenContext") == ("cli", ["x.py", "index", "--watch"])


def test_cli_name_without_arguments_shows_help():
    plan = load_mac_main().plan
    assert plan(["x.py"], "screen-context") == ("cli", ["screen-context", "--help"])


def test_cli_name_always_runs_the_cli():
    plan = load_mac_main().plan
    assert plan(["x.py", "serve", "--profile", "full"], "screen-context") == ("cli", ["screen-context", "serve", "--profile", "full"])
