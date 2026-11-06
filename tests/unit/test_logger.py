from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from sgk_wordwrap.utils.logger import _SgkJsonFormatter


def _record(**extra) -> logging.LogRecord:
    rec = logging.LogRecord("sgk_wordwrap.t", logging.INFO, __file__, 1, "sgk_evt", None, None)
    for k, v in extra.items():
        setattr(rec, k, v)
    return rec


def test_timestamp_is_utc_with_millis() -> None:
    rec = _record()
    payload = json.loads(_SgkJsonFormatter().format(rec))
    ts = payload["timestamp"]
    assert ts.endswith("Z")
    parsed = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
    assert abs(parsed.timestamp() - rec.created) < 0.002


def test_extra_fields_serialised() -> None:
    payload = json.loads(_SgkJsonFormatter().format(_record(want="ru", presses=1)))
    assert payload["event"] == "sgk_evt"
    assert payload["want"] == "ru"
    assert payload["presses"] == 1


def test_non_serialisable_extra_does_not_raise() -> None:
    payload = json.loads(_SgkJsonFormatter().format(_record(obj=object())))
    assert "object" in payload["obj"]
