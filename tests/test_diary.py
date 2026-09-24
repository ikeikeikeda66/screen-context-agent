from datetime import datetime, timedelta
import json
import pytest
from test_core import settings, add, change
from screen_context.service import Service


def test_diary_day_pagination_and_evidence(settings):
    start = datetime(2026, 9, 12)
    add(settings, ts=(start-timedelta(seconds=1)).timestamp())
    ids = [add(settings, ts=(start+timedelta(hours=i)).timestamp(), text="資料確認"*500)["id"] for i in range(12)]
    add(settings, ts=(start+timedelta(days=1)).timestamp())
    s = Service(settings, "full")
    first = s.get_diary_material("2026-09-12")
    second = s.get_diary_material("2026-09-12", first["next_offset"])
    assert first["total_blocks"] == 12
    assert first["next_offset"] == 10 and second["next_offset"] is None
    assert [r["frame_id"] for r in first["records"]+second["records"]] == ids
    assert all(r["excerpt_truncated"] and r["trust"] == "untrusted" for r in first["records"])
    assert sum(len(r["text"]) for r in first["records"]) <= 10000


def test_diary_live_policy_and_profile(settings):
    add(settings)
    s = Service(settings, "full")
    assert s.get_diary_material()["count"] == 1
    change(settings, denied_apps=["com.google.Chrome"])
    empty = s.get_diary_material()
    assert empty["count"] == empty["total_blocks"] == 0
    assert empty["next_offset"] is None
    with pytest.raises(PermissionError): Service(settings).get_diary_material()
    with pytest.raises(ValueError): s.get_diary_material("2026-02-30")
    with pytest.raises(ValueError): s.get_diary_material(offset=-1)


def test_report_material_is_profile_safe_and_snapshot_paged(settings):
    tokyo = __import__("zoneinfo").ZoneInfo("Asia/Tokyo")
    start = datetime(2026, 9, 22, 0, 0, tzinfo=tokyo)
    first = add(settings, ts=(start-timedelta(seconds=1)).timestamp(), text="前日の記録")
    ids = [add(settings, ts=(start+timedelta(hours=i)).timestamp(), text=f"日報根拠{i}") ["id"] for i in range(12)]
    add(settings, ts=(start+timedelta(days=1)).timestamp(), text="翌日の記録")

    service = Service(settings, "standard")
    page = service.get_day_material("2026-09-22", "Asia/Tokyo", limit=5)
    assert page["count"] == 5 and page["has_more"] is True
    assert page["purpose"] == "report" and page["coverage"]["full_day"] is False
    assert first["id"] not in {r["frame_id"] for r in page["records"]}
    assert all(r["trust"] == "untrusted" for r in page["records"])

    # The second page uses the original snapshot and is bound to its date, zone and policy.
    late = add(settings, ts=(start+timedelta(hours=12)).timestamp(), text="遅着OCR")
    second = service.get_day_material("2026-09-22", "Asia/Tokyo", page["next_cursor"], limit=10)
    assert second["has_more"] is False
    assert [r["frame_id"] for r in page["records"] + second["records"]] == ids
    assert late["id"] not in {r["frame_id"] for r in page["records"] + second["records"]}
    with pytest.raises(ValueError, match="CURSOR_EXPIRED"):
        service.get_day_material("2026-09-23", "Asia/Tokyo", page["next_cursor"])
def test_report_material_live_exclusions_and_dst_day(settings):
    from zoneinfo import ZoneInfo
    zone = ZoneInfo("America/Los_Angeles")
    start = datetime(2026, 3, 8, 0, 0, tzinfo=zone)
    allowed = add(settings, ts=(start+timedelta(hours=1)).timestamp(), text="確認可能な資料")
    ide = add(settings, app="com.microsoft.VSCode", ts=(start+timedelta(hours=2)).timestamp(), text="IDE secret")
    gmail = add(settings, ts=(start+timedelta(hours=3)).timestamp(), text="mail.google.com inbox")
    service = Service(settings, "standard")
    page = service.get_day_material("2026-03-08", "America/Los_Angeles")
    assert [r["frame_id"] for r in page["records"]] == [allowed["id"]]
    assert page["coverage"]["has_gaps"] is True
    change(settings, denied_apps=["com.google.Chrome"])
    revised = service.get_day_material("2026-03-08", "America/Los_Angeles")
    assert revised["count"] == 0
    assert ide["id"] != gmail["id"]


@pytest.mark.parametrize("date,timezone,purpose", [
    ("2026-02-30", "UTC", "report"), ("2026-03-08", "Unknown/Zone", "report"),
    ("2026-03-08", "UTC", "send_email"),
])
def test_report_material_validates_scope(settings, date, timezone, purpose):
    with pytest.raises(ValueError):
        Service(settings, "standard").get_day_material(date, timezone, purpose=purpose)
