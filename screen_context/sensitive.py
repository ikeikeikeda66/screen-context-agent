"""Detectors for input that must never be stored (roadmap decision 11, single-signal rules).

A frame whose OCR text contains a card number or a My Number is dropped whole, text and
image, before anything is written. Both detectors check a checksum, so order numbers,
phone numbers and dates rarely match. Only the category is counted, never the content.
"""
import re

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


DETECTORS = {"card_number": card_number, "my_number": my_number}


def detect(text, enabled):
    """The first enabled category found in `text`, or None."""
    return next((name for name in enabled if DETECTORS[name](text or "")), None)
