import json
import pickle
import re
import pytest
from screen_context.config import DEFAULT_POLICY, Settings


class Managed:
    def __init__(self, values): self.data = values
    def values(self): return self.data


def make(tmp_path, managed=None, options=None, policy=None):
    settings = Settings(tmp_path) if managed is None else Settings(tmp_path, managed=Managed(managed))
    settings.prepare()
    if options is not None: (tmp_path / "capture-options.json").write_text(json.dumps(options))
    if policy is not None: (tmp_path / "policy.json").write_text(json.dumps(policy))
    return settings


def test_option_precedence_and_origin(tmp_path):
    settings = make(tmp_path)
    assert settings.capture_interval() == 15 and settings.origin("interval_seconds", 15) == "default"
    settings = make(tmp_path, options={"interval_seconds": 30})
    assert settings.capture_interval() == 30 and settings.origin("interval_seconds") == "user"
    settings = make(tmp_path, {"options": {"interval_seconds": 60, "language": "ja"}}, options={"interval_seconds": 30})
    assert settings.capture_interval() == 60 and settings.origin("interval_seconds") == "managed"
    assert settings.language() == "ja"


def test_managed_option_is_locked(tmp_path):
    settings = make(tmp_path, {"options": {"interval_seconds": 60}})
    with pytest.raises(PermissionError): settings.set_capture_interval(5)
    settings.set_language("en")  # options the administrator did not set stay editable
    assert settings.language() == "en" and settings.capture_interval() == 60


def test_managed_policy_adds_entries_the_user_cannot_remove(tmp_path):
    settings = make(tmp_path, {"policy": {"denied_apps": ["com.example.Vault"]}}, policy={"denied_apps": ["com.example.Mine"]})
    policy, origin = settings.policy_with_origin()
    assert policy["denied_apps"] == ["com.example.Mine", "com.example.Vault"]
    assert origin["denied_apps"] == "managed" and origin["ide_apps"] == "default"
    assert policy["ide_apps"] == DEFAULT_POLICY["ide_apps"]
    settings = make(tmp_path, {"policy": {"denied_apps": ["com.example.Vault"]}}, policy={"denied_apps": []})
    assert settings.policy()["denied_apps"] == ["com.example.Vault"]


@pytest.mark.parametrize("managed", [{"policy": {"unknown": []}}, {"policy": {"denied_apps": "one"}},
                                     {"policy": {"denied_title_patterns": ["("]}}, {"policy": []}, {"options": []}])
def test_invalid_managed_values_fail_closed(tmp_path, managed):
    settings = make(tmp_path, managed)
    with pytest.raises((ValueError, re.error)):
        settings.policy()
        settings.capture_interval()


def test_without_managed_source_behaviour_is_unchanged(tmp_path):
    settings = make(tmp_path, policy={"denied_domains": ["example.com"]})
    assert settings.policy() == {**DEFAULT_POLICY, "denied_domains": ["example.com"]}
    assert set(settings.policy_with_origin()[1].values()) == {"default", "user"}
    # Settings crosses process boundaries (multiprocessing spawn) and must stay picklable.
    assert pickle.loads(pickle.dumps(settings)).policy() == settings.policy()
