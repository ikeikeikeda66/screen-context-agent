"""Synthetic data only: published test card numbers and made-up individual numbers."""
import re
import pytest
from PIL import Image
from test_core import settings, add, change
from screen_context import store
from screen_context.capture import spool
from screen_context.indexer import drain
from screen_context.sensitive import card_number, detect, my_number, my_number_check_digit
from screen_context.service import Service


@pytest.mark.parametrize("text", ["4111 1111 1111 1111", "カード番号 5555-5555-5555-4444", "378282246310005", "3530111333300000", "6011111111111117"])
def test_card_numbers_are_found(text):
    assert card_number(text)


@pytest.mark.parametrize("text", [
    "4111 1111 1111 1112",           # Luhn fails
    "注文番号 1234567890123",          # issuer prefix 1
    "0000 0000 0000 0000",           # repeated digit passes Luhn trivially
    "2026-09-26 10:15",              # date
    "090-1234-5678",                 # phone number
    "4111 1111 11",                  # too short
    "Invoice 42424242424242424242",  # too long
])
def test_other_numbers_are_not_cards(text):
    assert not card_number(text)


def test_my_number_needs_a_valid_check_digit_and_a_label():
    assert my_number_check_digit("12345678901") == 8  # worked by hand: Σ=212, 212 mod 11 = 3, 11−3 = 8
    assert my_number("個人番号\n1234 5678 9018")
    assert my_number("マイナンバー: 123456789018")
    assert not my_number("マイナンバー: 123456789017")          # wrong check digit
    assert not my_number("伝票番号 123456789018")               # no label nearby
    assert not my_number("個人番号\n\n\n\n\n1234 5678 9018")    # label too far away


def test_detect_respects_enabled_detectors():
    assert detect("4111 1111 1111 1111", ["card_number", "my_number"]) == "card_number"
    assert detect("4111 1111 1111 1111", ["my_number"]) is None
    assert detect("", ["card_number"]) is None


def frame(settings, text, title="Checkout"):
    spool(settings, Image.new("RGB", (100, 100)), dict(app_bundle="com.google.Chrome", app_name="Chrome", window_title=title, display_id="1"))
    return drain(settings, lambda _: [{"text": text, "bbox": [0, 0, 1, 1]}])


def stored(settings):
    with store.connect(settings, readonly=True) as con:
        return con.execute("SELECT count(*) FROM frames").fetchone()[0], dict(con.execute("SELECT category, count FROM skip_counts").fetchall())


def test_indexer_drops_the_whole_frame_and_counts_only_the_reason(settings):
    assert frame(settings, "お支払い 4111 1111 1111 1111", title="Store")["excluded"] == 1
    assert frame(settings, "個人番号 1234 5678 9018", title="Form")["excluded"] == 1
    assert frame(settings, "普通のページ", title="Docs")["indexed"] == 1
    count, skips = stored(settings)
    assert count == 1 and skips == {"card_number": 1, "my_number": 1}
    assert not list((settings.root / "spool").iterdir()) and len(list((settings.root / "images").iterdir())) == 1
    assert "4111" not in (settings.root / "history.db").read_bytes().decode("latin-1")


def test_detectors_can_be_turned_off(settings):
    change(settings, sensitive_detectors=[])
    assert frame(settings, "4111 1111 1111 1111", title="Store")["indexed"] == 1


@pytest.mark.parametrize("policy", [{"sensitive_detectors": ["passport"]}, {"sensitive_url_patterns": ["("]}])
def test_invalid_rules_fail_closed(settings, policy):
    change(settings, **policy)
    with pytest.raises((ValueError, re.error)): settings.policy()
    with pytest.raises((ValueError, re.error)): frame(settings, "普通のページ", title="Docs")  # capture refuses
    assert stored(settings)[0] == 0


def test_default_rules_exclude_contacts_and_checkout_pages_everywhere(settings):
    frame(settings, "https://shop.example.com/checkout/step1 配送先", title="Shop")  # URL: dropped after OCR
    frame(settings, "内容", title="ご注文手続き - Shop")                              # title: never spooled
    assert stored(settings)[0] == 0
    assert frame(settings, "Payment API reference https://docs.example.com/api/payments", title="Docs")["indexed"] == 1
    add(settings, "連絡先の内容", app="com.apple.AddressBook")
    assert Service(settings, "full").search_screen_history("連絡先")["count"] == 0
