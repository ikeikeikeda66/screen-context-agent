from dataclasses import dataclass, field
from pathlib import Path
import json
import os
import re
import sys
from . import resolver

DEFAULT_POLICY = {
    "denied_apps": ["com.apple.Passwords", "com.apple.keychainaccess", "com.1password.1password", "com.agilebits.onepassword7", "us.zoom.xos", "com.microsoft.teams2", "com.apple.FaceTime", "1Password.exe", "Zoom.exe", "ms-teams.exe"],
    "denied_domains": ["mail.google.com"],
    "denied_title_patterns": ["(?i)password|パスワード|secret|シークレット|incognito|private browsing"],
    # Frames from these apps (or with matching titles) show an assistant's output, not new facts about the user.
    "ai_output_apps": ["com.anthropic.claudefordesktop", "com.openai.codex", "com.openai.chat", "claude.exe", "ChatGPT.exe"],
    "ai_output_title_patterns": [],
    # Sensitive-input rules (roadmap decision 11). They live in their own keys because `prepare`
    # writes every key into policy.json: new defaults under an existing key would never reach
    # existing users. Set a key to [] to turn that rule off.
    "sensitive_detectors": ["card_number", "my_number"],
    "sensitive_apps": ["com.apple.AddressBook"],
    "sensitive_title_patterns": [r"(?i)\bcheckout\b|payment details|billing information|お支払い(方法|手続き|情報)|ご注文手続き|レジに進む"],
    "sensitive_url_patterns": [r"(?i)/(checkout|payment|billing)(?:[/?#]|$)"],
    # Signals within 5 OCR lines of each other ("name+phone:3" sets another window). See pii.py.
    "pii_combinations": ["name+address", "name+phone", "name+dob", "name+email"],
    "ide_apps": ["com.microsoft.VSCode", "com.apple.Terminal", "com.googlecode.iterm2", "com.jetbrains.pycharm", "com.jetbrains.intellij", "com.todesktop.230313mzl4w4u92", "com.openai.codex", "Code.exe", "WindowsTerminal.exe", "cmd.exe", "powershell.exe", "pwsh.exe", "idea64.exe", "pycharm64.exe", "Cursor.exe"],
}

@dataclass(frozen=True)
class Settings:
    root: Path
    plaintext: bool = False
    retention_days: int = 90
    managed: object = field(default_factory=resolver.NoManagedSettings, compare=False, repr=False)

    @classmethod
    def environment(cls):
        default = Path.home() / ("Library/Application Support/ScreenContext" if sys.platform == "darwin" else ".screen-context")
        return cls(Path(os.environ.get("SCREEN_CONTEXT_HOME", default)).expanduser().resolve(), os.environ.get("SCREEN_CONTEXT_PLAINTEXT") == "1")

    @property
    def db(self): return self.root / "history.db"

    def options(self):
        path = self.root / "capture-options.json"
        if not path.exists(): return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict): raise ValueError("Invalid capture options")
        return data

    def option(self, name, default):
        """Resolved value of one capture option (managed > user > default)."""
        return resolver.option(name, default, self.options(), resolver.managed_section(self.managed, "options"))[0]

    def origin(self, name, default=None):
        """Which layer supplies an option: "managed", "user" or "default"."""
        return resolver.option(name, default, self.options(), resolver.managed_section(self.managed, "options"))[1]

    def save_option(self, name, value):
        from .crypto import atomic_write
        if name in resolver.managed_section(self.managed, "options"):
            raise PermissionError(f"{name} is set by your administrator")
        atomic_write(self.root / "capture-options.json", json.dumps({**self.options(), name: value}).encode())

    def capture_interval(self):
        value = self.option("interval_seconds", 15)
        if type(value) is not int or not 5 <= value <= 300:
            raise ValueError("Capture interval must be 5–300 seconds")
        return value

    def set_capture_interval(self, seconds):
        if type(seconds) is not int or not 5 <= seconds <= 300:
            raise ValueError("Capture interval must be 5–300 seconds")
        self.save_option("interval_seconds", seconds)

    def language(self):
        """Saved UI language choice: "system", "en" or "ja"."""
        from .i18n import CHOICES
        value = self.option("language", "system")
        if value not in CHOICES: raise ValueError("Invalid language option")
        return value

    def set_language(self, value):
        from .i18n import CHOICES
        if value not in CHOICES: raise ValueError("Language must be one of " + ", ".join(CHOICES))
        self.save_option("language", value)

    def prepare(self):
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        for name in ("spool", "images", "exports", "requests"):
            (self.root / name).mkdir(exist_ok=True, mode=0o700)
        p = self.root / "policy.json"
        if not p.exists():
            p.write_text(json.dumps(DEFAULT_POLICY, ensure_ascii=False, indent=2), encoding="utf-8")
            p.chmod(0o600)

    def policy(self):
        return self.policy_with_origin()[0]

    def policy_with_origin(self):
        """(policy, {key: layer}). Invalid input from any layer fails closed."""
        p = self.root / "policy.json"
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict): raise ValueError("Invalid policy keys")
        result, origin = resolver.policy(DEFAULT_POLICY, data, resolver.managed_section(self.managed, "policy"))
        for key, values in result.items():
            if not isinstance(values, list) or any(not isinstance(x, str) or not x for x in values):
                raise ValueError(f"Invalid policy: {key}")
        for key in ("denied_title_patterns", "sensitive_title_patterns", "sensitive_url_patterns"):
            for pattern in result[key]: re.compile(pattern)
        from .pii import parse
        from .sensitive import DETECTORS
        parse(result["pii_combinations"])
        if set(result["sensitive_detectors"]) - set(DETECTORS): raise ValueError("Invalid policy: sensitive_detectors")
        return result, origin
