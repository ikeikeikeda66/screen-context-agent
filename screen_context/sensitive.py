"""Detectors for input that must never be stored (roadmap decision 11, single-signal rules).

A frame whose OCR text contains a card number or a My Number is dropped whole, text and
image, before anything is written. Both detectors check a checksum, so order numbers,
phone numbers and dates rarely match. Only the category is counted, never the content.

`account_list` (#65) drops a frame that shows a table of accounts or people: a header row with
at least two of name, ID, password, phone, postal code and address columns, one of them name, ID
or password, followed by at least two rows with IDs, e-mail addresses, masked values, phone
numbers, postal codes or addresses. A login form has the labels but not the rows, so it is kept.
"""
import re
from .pii import ADDRESS, phone

# Digits with optional single spaces or hyphens between them.
CARD = re.compile(r"(?<![\d-])\d(?:[ -]?\d){12,18}(?![\d-])")
MY_NUMBER = re.compile(r"(?<![\d-])\d{4}[ -]?\d{4}[ -]?\d{4}(?![\d-])")
MY_NUMBER_LABEL = re.compile(r"個人番号|マイナンバー|(?i:my\s*number)")


def luhn(digits):
    total = 0
    for i, d in enumerate(reversed(digits)):
        n = int(d) * (2 if i % 2 else 1)
        total += n - 9 if n > 9 else n
    return total % 10 == 0


def card_number(text):
    for match in CARD.finditer(text):
        digits = re.sub(r"\D", "", match.group())
        # Issuer prefixes 2–6 (Mastercard 2-series, Amex/Diners/JCB, Visa, Mastercard, Discover/UnionPay).
        # Repeated digits pass Luhn trivially ("0000…"), so they are not card numbers.
        if 13 <= len(digits) <= 19 and digits[0] in "23456" and len(set(digits)) > 1 and luhn(digits):
            return True
    return False


def my_number_check_digit(first11):
    """Check digit of an individual number (総務省令: P×Q weights, modulus 11)."""
    total = sum(int(p) * (n + 1 if n <= 6 else n - 5) for n, p in enumerate(reversed(first11), start=1))
    remainder = total % 11
    return 0 if remainder <= 1 else 11 - remainder


def my_number(text):
    """A 12-digit number with a valid check digit, within three lines of a My Number label."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        for match in MY_NUMBER.finditer(line):
            digits = re.sub(r"\D", "", match.group())
            if int(digits[-1]) != my_number_check_digit(digits[:11]): continue
            if MY_NUMBER_LABEL.search("\n".join(lines[max(0, i - 3):i + 1])): return True
    return False


# Column labels. ASCII words must stand alone, so "username" in "get_username(" or "id" in
# "valid" do not count; Japanese labels are matched as written.
ASCII = r"(?<![A-Za-z0-9_]){}(?![A-Za-z0-9_])"
COLUMNS = {
    "name": re.compile(r"氏名|お名前|名前|表示名|フルネーム|" + ASCII.format(r"(?i:(?:full\s*|display\s*)?name)")),
    "id": re.compile(r"(?:ユーザー|ログイン|アカウント|社員|会員)\s*(?:ID|ＩＤ|名)|アカウント|メールアドレス|"
                     + ASCII.format(r"(?:ＩＤ|(?i:id|user\s*(?:id|name)|login(?:\s*id)?|account(?:\s*id)?|e-?mail))")),
    "password": re.compile(r"パスワード|暗証番号|" + ASCII.format(r"(?i:pass\s*word|passwd|passcode|pwd?)")),
    "phone": re.compile(r"電話|携帯|ＴＥＬ|" + ASCII.format(r"(?:TEL|Tel|FAX|Fax|(?i:phone(?:\s*number)?|mobile))")),
    "postal": re.compile(r"郵便番号|〒|" + ASCII.format(r"(?i:zip(?:\s*code)?|postal\s*code|post\s*code)")),
    # Not "E-mail address" or "IP address".
    "address": re.compile(r"住所|所在地|" + ASCII.format(r"(?i:(?<!mail )(?<!ip )address)")),
}
# A table of postal codes, or of phone numbers and addresses, is a directory, not a list of people.
PERSON = {"name", "id", "password"}
# A header is short, not a sentence and not code.
NOT_HEADER = re.compile(r"[。、？！?!=(){}<>;\"'`]")
ROW_VALUE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+|[•●＊*]{4,}|"
                       r"(?<![A-Za-z0-9_])[A-Za-z][A-Za-z0-9._-]*\d[A-Za-z0-9._-]*(?![A-Za-z0-9_@])|"
                       r"(?<![\d-])\d{3}-\d{4}(?![\d-])")                    # postal code
HEADER_LINES, ROWS, ROW_WINDOW = 3, 2, 30


def columns(line):
    if len(line) > 80 or NOT_HEADER.search(line): return set()
    return {name for name, pattern in COLUMNS.items() if pattern.search(line)}


def account_list(text):
    """A header with two column labels, one of them name, ID or password (on one line, or one
    label per line as OCR reads table cells), then at least two lines with a value."""
    lines = text.splitlines()
    for i in range(len(lines)):
        found, end = set(), i
        for j in range(i, min(i + HEADER_LINES, len(lines))):
            labels = columns(lines[j])
            if not labels: break
            found |= labels
            end = j
        if len(found) < 2 or not found & PERSON: continue
        rows = sum(1 for line in lines[end + 1:end + 1 + ROW_WINDOW] if ROW_VALUE.search(line) or phone(line) or ADDRESS.search(line))
        if rows >= ROWS: return True
    return False


DETECTORS = {"card_number": card_number, "my_number": my_number, "account_list": account_list}


def enabled(policy):
    """The detectors a policy turns on. `account_list` has its own key so that it reaches
    policy.json files written before it existed."""
    return policy["sensitive_detectors"] + policy["sensitive_tables"]


def detect(text, enabled):
    """The first enabled category found in `text`, or None."""
    return next((name for name in enabled if DETECTORS[name](text or "")), None)
