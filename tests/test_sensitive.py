"""Synthetic data only: published test card numbers and made-up individual numbers."""
import json
import re
import pytest
from PIL import Image
from test_core import settings, add, change
from screen_context import store
from screen_context.capture import spool
from screen_context.indexer import drain
from screen_context.sensitive import account_list, card_number, detect, enabled, my_number, my_number_check_digit
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


# --- account lists (#65): made-up accounts only ------------------------------------------------

@pytest.mark.parametrize("text", [
    "氏名 ユーザーID パスワード\n山田 太郎 yamada01 Abc12345\n佐藤 花子 sato02 Xyz67890",          # one row per line
    "Name | Username | Password\nTaro Example | taro.example1 | ********\nHana Example | hana2 | ********",
    "No. アカウント 暗証番号 備考\n1 user001 ●●●●●● 管理者\n2 user002 ●●●●●● 一般",
    "氏名\nログインID\nパスワード\n山田 太郎\nyamada01\nAbc12345\n佐藤 花子\nsato02\nXyz67890",       # one cell per line
    "名前 メールアドレス\n山田 taro@example.com\n佐藤 hana@example.com",
    "氏名 電話番号\n山田 太郎 090-0000-1111\n佐藤 花子 03-0000-2222",                               # phone column
    "氏名 郵便番号 住所\n山田 太郎 100-0000 東京都千代田区架空1-2-3\n佐藤 花子 530-0000 大阪府大阪市北区架空4-5",
    "Name\nPhone\nAddress\nTaro Example\n(03) 0000-1111\nHana Example\n(06) 0000-2222",          # one cell per line
])
def test_account_lists_are_found(text):
    assert account_list(text)


@pytest.mark.parametrize("text", [
    "ログインID\nパスワード\nログイン\nパスワードを忘れた方",                                         # empty login form
    "ログインID\nuser01\nパスワード\n••••••••\nログイン",                                            # filled login form
    "氏名 ユーザーID パスワード\n山田 太郎 yamada01 Abc12345",                                        # one row only
    "パスワードを忘れた場合は、ユーザーIDを入力してください。\nuser01\nuser02",                     # a sentence, not a header
    "def login(username, password):\n    user1 = find(username)\n    key2 = hash(password)",     # code
    "パスワード\n\n" + "\n" * 40 + "ユーザーID\nuser01\nuser02",                                    # labels far apart
    "Name Size Modified\nreport1.pdf 2 MB\nslides2.key 5 MB",                                     # one column label
    "郵便番号 住所\n100-0001 東京都千代田区千代田\n100-0002 東京都千代田区皇居外苑",              # postal-code lookup
    "電話番号 住所\n03-0000-1111 東京都千代田区架空1-2-3\n06-0000-2222 大阪府大阪市北区架空4-5",  # no name, ID or password
    "Name | IP address\nserver1 | 192.0.2.1\nserver2 | 192.0.2.2",                               # not a postal address
    "電話番号\n03-0000-1111\nお問い合わせ時間 9:00〜17:00",                                       # contact page
])
def test_other_screens_are_not_account_lists(text):
    assert not account_list(text)


def test_account_lists_are_dropped_by_default_and_can_be_turned_off(settings):
    table = "氏名 ユーザーID パスワード\n山田 太郎 yamada01 Abc12345\n佐藤 花子 sato02 Xyz67890"
    assert frame(settings, table, title="Accounts")["excluded"] == 1
    assert stored(settings) == (0, {"account_list": 1})
    change(settings, sensitive_tables=[])
    assert frame(settings, table, title="Accounts")["indexed"] == 1


def test_policy_files_written_before_the_rule_still_get_it(settings):
    """policy.json lists every key it was written with; `sensitive_tables` is new, so the default applies."""
    path = settings.root / "policy.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    del data["sensitive_tables"]
    path.write_text(json.dumps(data), encoding="utf-8")
    assert enabled(settings.policy()) == ["card_number", "my_number", "account_list"]
    change(settings, sensitive_tables=["passport"])
    with pytest.raises(ValueError, match="sensitive_tables"): settings.policy()
