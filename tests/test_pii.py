"""Synthetic data only: invented names, addresses and numbers."""
import json
import subprocess
import sys
import time
import pytest
from PIL import Image
from test_core import settings, change
from screen_context import store
from screen_context.capture import spool
from screen_context.indexer import drain
from screen_context.pii import parse, scan, signals
from screen_context import pii
from screen_context.pii import redact
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


EMAIL_FRAME = ["Name: Taro Example", "taro.example@example-test.com", "unrelated line"]
PHONE_FRAME = ["Name: Taro Example", "TEL 03-1234-5678", "unrelated line"]


def hit(frame, extra, rules=RULES):
    lines = frame + [extra]
    return len(lines) - 1 in scan(lines, rules)[0]


@pytest.mark.parametrize("extra", [
    "example-test.com", "@example-test.com", "example-test", "Reply-To: example-test.com",
    "<taro.example@example-test.com>", "taro.example@example-te", "taro.exam", "taro.example",
    "EXAMPLE-TEST.COM", "Taro.Example@Example-Test.com", "example-t",
])
def test_email_fragments_are_redacted(extra):
    assert hit(EMAIL_FRAME, extra)


def test_unrelated_lines_stay_when_fragment_is_redacted():
    assert scan(EMAIL_FRAME + ["example-test.com"], RULES)[0] == {0, 1, 3}


@pytest.mark.parametrize("extra", ["example", "test.com", "info", "taro", "gmail.com", "2026-10-12", "¥12,345,678"])
def test_short_or_common_text_stays(extra):
    assert not hit(EMAIL_FRAME, extra)


def test_public_mail_domains_are_not_fragments():
    frame = ["Name: Taro Example", "taro.example@gmail.com"]
    assert not hit(frame, "gmail.com")
    assert not hit(frame, "Login with gmail.com")
    assert not hit(frame, "@gmail.com")
    assert hit(frame, "taro.example")
    assert hit(frame, "taro.exam")


@pytest.mark.parametrize("extra", ["1234-5678", "0312345678", "+81 3 1234 5678", "03-1234-5", "1234-567", "１２３４－５６７８"])
def test_phone_fragments_are_redacted(extra):
    assert hit(PHONE_FRAME, extra)


@pytest.mark.parametrize("extra", ["(03) 1234", "03-1234", "2026-10-12", "¥12,345,678", "Order 87654321", "Order 5678"])
def test_phone_lookalikes_stay(extra):
    assert not hit(PHONE_FRAME, extra)


def test_fragment_minimums_are_constants(monkeypatch):
    assert not hit(EMAIL_FRAME, "taro.exa")  # 7 letters
    assert not hit(PHONE_FRAME, "03-1234")
    monkeypatch.setattr(pii, "MIN_EMAIL_FRAGMENT", 7)
    monkeypatch.setattr(pii, "MIN_PHONE_DIGITS", 6)
    assert hit(EMAIL_FRAME, "taro.exa")
    assert hit(PHONE_FRAME, "03-1234")


def test_fragments_do_nothing_without_a_matching_rule_or_rules():
    assert scan(["taro.example@example-test.com", "example-test.com"], RULES) == (set(), [])
    assert scan(EMAIL_FRAME + ["example-test.com"], []) == (set(), [])


def test_fragments_match_outside_the_window():
    assert hit(EMAIL_FRAME + ["filler"] * 8, "example-test.com")


def test_redact_applies_fragments():
    ocr = [{"text": text, "bbox": [0, 0, 1, 1]} for text in EMAIL_FRAME + ["example-test.com"]]
    out, matched = redact(ocr, RULES, "X")
    assert matched == ["name+email"]
    assert [line["text"] for line in out] == ["X", "X", EMAIL_FRAME[2], "X"]
    assert [line["bbox"] for line in out] == [None, None, [0, 0, 1, 1], None]


def test_cli_pii_check_redacts_fragment_lines(settings, tmp_path):
    sample = tmp_path / "sample.txt"
    sample.write_text("\n".join(EMAIL_FRAME + ["example-test.com"]), encoding="utf-8")
    env = {"SCREEN_CONTEXT_HOME": str(settings.root), "SCREEN_CONTEXT_PLAINTEXT": "1", "PATH": "/usr/bin:/bin"}
    out = json.loads(subprocess.run([sys.executable, "-m", "screen_context.cli", "pii-check", str(sample)], env=env, capture_output=True, check=True).stdout)
    assert out["combinations"] == ["name+email"]
    assert [r["line"] for r in out["redacted_lines"]] == [1, 2, 4]


@pytest.mark.parametrize("frame, extra", [
    (["Name: Taro Example", "customer-support@example-test.com"], "Customer reviews and ratings"),
    (["Name: Taro Example", "taro@softwarehouse.example"], "Download the software update"),
    (["Name: Taro Example", "taro.yamamoto@example-test.com"], "Meeting with Hanako Yamamoto"),
    (["Name: Taro Example", "administrator@example-test.com"], "Contact the administrator for access"),
    (["Name: Taro Example", "administrator@example-test.com"], "misinformation spreads"),
    (["Name: Taro Example", "information@example-test.com"], "misinformation spreads"),
])
def test_common_words_next_to_a_fragment_stay(frame, extra):
    assert not hit(frame, extra)


@pytest.mark.parametrize("extra", ["hanako@example-test.com", "https://example-test.com/page", "see example-test.com/page"])
def test_domain_inside_another_address_or_url_stays(extra):
    # Eight lines after the name, so an address in the line is not redacted by the name+email rule itself.
    assert not hit(EMAIL_FRAME + ["filler"] * 8, extra)


@pytest.mark.parametrize("extra", ["example-test.com", "@example-test.com", "example-t"])
def test_standalone_domain_is_redacted(extra):
    assert hit(EMAIL_FRAME, extra)


def test_fullwidth_address_fragments_are_compared_after_nfkc():
    frame = ["Name: Taro Example", "ｔａｒｏ.ｅｘａｍｐｌｅ@example-test.com"]
    assert scan(frame, RULES)[0] == {0, 1}
    assert hit(frame, "taro.example")


def test_invoice_number_matching_phone_digits_is_redacted_by_design():
    assert hit(PHONE_FRAME, "Invoice 1234567")


def test_long_digit_runs_scan_fast():
    lines = PHONE_FRAME + [" ".join(["12"] * 2000)]
    started = time.perf_counter()
    scan(lines, RULES)
    assert time.perf_counter() - started < 1
