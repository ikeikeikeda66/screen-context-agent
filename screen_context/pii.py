"""Combination rule for personal data (roadmap decision 11).

A name alone is kept; a name next to an address, phone number, date of birth or e-mail
address is what makes a leak harmful. When a rule's signals appear within a few OCR lines
of each other, those lines are replaced with a placeholder and no preview image is kept.
The rest of the frame (an e-mail body above a signature, for example) stays searchable.

Names cannot be recognised reliably by pattern, so NAME is found only through labels
(氏名, お名前, フリガナ, "Name:") and the "〇〇 様" form. Unlabelled names, as in a
contacts app, are handled by excluding the app (`sensitive_apps`).
"""
import re

CATEGORIES = ("name", "address", "phone", "dob", "email")
DEFAULT_WINDOW = 5
RULE = re.compile(r"([a-z]+(?:\+[a-z]+)+)(?::(\d{1,2}))?")

PREFECTURES = ("北海道|青森県|岩手県|宮城県|秋田県|山形県|福島県|茨城県|栃木県|群馬県|埼玉県|千葉県|東京都|神奈川県|"
               "新潟県|富山県|石川県|福井県|山梨県|長野県|岐阜県|静岡県|愛知県|三重県|滋賀県|京都府|大阪府|兵庫県|"
               "奈良県|和歌山県|鳥取県|島根県|岡山県|広島県|山口県|徳島県|香川県|愛媛県|高知県|福岡県|佐賀県|長崎県|"
               "熊本県|大分県|宮崎県|鹿児島県|沖縄県")
# English labels only at the start of a line (or after a table separator), so "username:" and
# "File name:" are not names. Group 2 is the first character of a value on the same line, if any.
NAME_LABEL = re.compile(r"(氏名|お名前|ご氏名|フリガナ|ふりがな|(?i:(?:^|[|｜])\s*(?:full\s*name|name)(?=\s*[:：])))\s*[:：]?\s*(\S?)")
HONORIFIC = re.compile(r"(?<![お皆各])([一-鿿゠-ヿー]{2,10})[ 　]?様(?![式々子相])")
NOT_NAMES = ("担当者", "関係者", "利用者", "会員", "お客", "皆", "各位", "購入者", "申込者", "契約者", "ユーザー")
ADDRESS = re.compile(r"〒\s?\d{3}-?\d{4}|郵便番号\s*[:：]?\s*\d{3}-?\d{4}|(?:" + PREFECTURES + r")\S{0,12}?[市区町村郡]\S*\d")
PHONE = re.compile(r"(?<![\d+])(?:\+81[- ]?\(?0?\)?|0)\d{1,4}[- (（)）]*\d{1,4}[- )）]*\d{3,4}(?!\d)")
PHONE_LABEL = re.compile(r"電話|携帯|TEL|Tel|tel|Phone|phone|FAX")
DOB_LABEL = re.compile(r"生年月日|誕生日|(?i:date\s*of\s*birth|\bdob\b|birthday)")
DATE = re.compile(r"\d{4}\s?[年/.-]\s?\d{1,2}\s?[月/.-]\s?\d{1,2}|(?:昭和|平成|令和|大正)\s?(?:\d{1,2}|元)\s?年\s?\d{1,2}\s?月\s?\d{1,2}")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def phone(line):
    for match in PHONE.finditer(line):
        text = match.group()
        digits = re.sub(r"\D", "", text)
        domestic = digits[2:] if text.startswith("+81") else digits
        if not domestic.startswith("0"): domestic = "0" + domestic
        # Separators or a label: a bare run of digits is more often an order or account number.
        if len(domestic) in (10, 11) and (re.search(r"[- ()（）]", text) or PHONE_LABEL.search(line)): return True
    return False


def name(line):
    if NAME_LABEL.search(line): return True
    return any(not m.group(1).endswith(NOT_NAMES) for m in HONORIFIC.finditer(line))


def signals(lines):
    """{category: set of line indexes}. A label alone on its line also marks the next line (form layout)."""
    found = {c: set() for c in CATEGORIES}
    for i, line in enumerate(lines):
        label = NAME_LABEL.search(line)
        if name(line):
            found["name"].add(i)
            if label and not label.group(2) and i + 1 < len(lines): found["name"].add(i + 1)
        if ADDRESS.search(line): found["address"].add(i)
        if phone(line): found["phone"].add(i)
        if EMAIL.search(line): found["email"].add(i)
        if DOB_LABEL.search(line):
            if DATE.search(line): found["dob"].add(i)
            elif i + 1 < len(lines) and DATE.search(lines[i + 1]): found["dob"].update((i, i + 1))
    return found


def parse(rules):
    """[(categories, window)] from strings like "name+address" or "name+phone:3"; ValueError if invalid."""
    parsed = []
    for rule in rules:
        match = RULE.fullmatch(rule)
        parts = match.group(1).split("+") if match else []
        if not match or set(parts) - set(CATEGORIES) or len(set(parts)) != len(parts):
            raise ValueError(f"Invalid policy: pii_combinations ({rule})")
        parsed.append((tuple(parts), int(match.group(2) or DEFAULT_WINDOW)))
    return parsed


def scan(lines, rules):
    """(line indexes to redact, sorted list of matched rule names)."""
    found, redact, matched = signals(lines), set(), set()
    for parts, window in parse(rules):
        first, others = parts[0], parts[1:]
        for anchor in found[first]:
            near = {c: {j for j in found[c] if abs(j - anchor) <= window} for c in others}
            if all(near.values()):
                redact.add(anchor)
                for indexes in near.values(): redact |= indexes
                matched.add("+".join(parts))
    return redact, sorted(matched)


def redact(ocr_lines, rules, placeholder):
    """Apply the rules to OCR output [{"text", "bbox", ...}]. Returns (new lines, matched rule names)."""
    indexes, matched = scan([line["text"] for line in ocr_lines], rules)
    return [{**line, "text": placeholder, "bbox": None} if i in indexes else line for i, line in enumerate(ocr_lines)], matched
