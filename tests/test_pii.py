"""Synthetic data only: invented names, addresses and numbers."""
import json
import subprocess
import sys
import pytest
from PIL import Image
from test_core import settings, change
from screen_context import store
from screen_context.capture import spool
from screen_context.indexer import drain
from screen_context.pii import parse, scan, signals
from screen_context.service import Service

RULES = ["name+address", "name+phone", "name+dob", "name+email"]

SIGNATURE = """お世話になっております。
来週の打ち合わせ資料を添付します。
ご確認のほどよろしくお願いいたします。
--
山田 花子 様
〒100-0001 東京都千代田区千代田1-1
TEL 03-1234-5678"""


def test_email_signature_is_redacted_and_the_body_kept():
    lines = SIGNATURE.splitlines()
    indexes, matched = scan(lines, RULES)
    assert matched == ["name+address", "name+phone"]
    assert indexes == {4, 5, 6}  # name, address, phone lines; the body stays


def test_company_page_without_a_name_is_kept():
    page = "会社概要\n本社 〒100-0001 東京都千代田区千代田1-1\n代表電話 03-1234-5678\nお客様窓口 info@example.com"
    assert scan(page.splitlines(), RULES) == (set(), [])


def test_signals_farther_apart_than_the_window_are_not_combined():
    lines = ["氏名 山田花子"] + ["本文"] * 6 + ["TEL 090-1234-5678"]
    assert scan(lines, RULES)[1] == []
    assert scan(lines, ["name+phone:7"])[1] == ["name+phone"]


def test_form_layout_label_above_value():
    form = ["お名前", "佐藤 一郎", "生年月日", "1990年1月2日", "メールアドレス", "ichiro@example.com"]
    indexes, matched = scan(form, RULES)
    assert matched == ["name+dob", "name+email"] and {0, 1, 2, 3, 5} <= indexes


@pytest.mark.parametrize("line", ["お客様各位", "ご担当者様", "username: taro", "File name: report.txt", "様式第1号", "皆様へ"])
def test_not_names(line):
    assert not signals([line])["name"]


@pytest.mark.parametrize("line, category", [
    ("TEL 03-1234-5678", "phone"), ("携帯 09012345678", "phone"), ("+81 90-1234-5678", "phone"),
    ("〒530-0001", "address"), ("大阪府大阪市北区梅田1-2-3", "address"), ("誕生日 平成2年3月4日", "dob"),
])
def test_signals(line, category):
    assert signals([line])[category]


@pytest.mark.parametrize("line", ["注文番号 0123456789", "2026-09-26", "version 1.2.3"])
def test_not_phones(line):
    assert not signals([line])["phone"]


@pytest.mark.parametrize("rules", [["name"], ["name+passport"], ["name+name"], ["name+phone:x"]])
def test_invalid_rules_fail_closed(settings, rules):
    with pytest.raises(ValueError): parse(rules)
    change(settings, pii_combinations=rules)
    with pytest.raises(ValueError): settings.policy()


def test_indexer_redacts_lines_and_stores_no_image(settings):
    spool(settings, Image.new("RGB", (100, 100)), dict(app_bundle="com.microsoft.Outlook", app_name="Outlook", window_title="Re: 資料", display_id="1"))
    stats = drain(settings, lambda _: [{"text": line, "bbox": [0, i / 10, .5, .05]} for i, line in enumerate(SIGNATURE.splitlines())])
    assert stats["indexed"] == 1 and stats["redacted"] == 1
    with store.connect(settings, readonly=True) as con:
        row = dict(con.execute("SELECT * FROM frames").fetchone())
        skips = dict(con.execute("SELECT category, count FROM skip_counts").fetchall())
    assert row["image_path"] is None and not list((settings.root / "images").iterdir())
    assert "打ち合わせ資料" in row["ocr_text"] and "03-1234-5678" not in row["ocr_text"] and "千代田" not in row["ocr_text"]
    redacted = [line for line in json.loads(row["ocr_json"]) if line["bbox"] is None]
    from screen_context.i18n import resolve, t
    assert len(redacted) == 3 and {line["text"] for line in redacted} == {t("pii.redacted", resolve(settings))}
    assert skips == {"name+address": 1, "name+phone": 1}
    assert Service(settings).search_screen_history("打ち合わせ")["count"] == 1


def test_rules_can_be_turned_off(settings):
    change(settings, pii_combinations=[])
    spool(settings, Image.new("RGB", (100, 100)), dict(app_bundle="x", app_name="x", window_title="Mail", display_id="1"))
    assert "redacted" not in drain(settings, lambda _: [{"text": line, "bbox": [0, 0, 1, 1]} for line in SIGNATURE.splitlines()])


def test_cli_pii_check(settings, tmp_path):
    sample = tmp_path / "sample.txt"
    sample.write_text(SIGNATURE + "\nカード 4111 1111 1111 1111", encoding="utf-8")
    env = {"SCREEN_CONTEXT_HOME": str(settings.root), "SCREEN_CONTEXT_PLAINTEXT": "1", "PATH": "/usr/bin:/bin"}
    out = json.loads(subprocess.run([sys.executable, "-m", "screen_context.cli", "pii-check", str(sample)], env=env, capture_output=True, check=True).stdout)
    assert out["drop_frame"] == "card_number" and out["combinations"] == ["name+address", "name+phone"]
    assert [r["line"] for r in out["redacted_lines"]] == [5, 6, 7]
