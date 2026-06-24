"""Tests for the local labeler server (dtk autotune --label, server mode)."""

import json
import threading
import urllib.error
import urllib.request

import numpy as np
import pytest

from detectkit.autotune.html_labeler import render_labeler_html
from detectkit.autotune.label_server import _sanitize, build_label_server


def _data(n=120):
    ts = (
        np.datetime64("2026-01-01T00:00:00", "ms") + np.arange(n) * np.timedelta64(1, "h")
    ).astype("datetime64[ms]")
    return {"timestamp": ts, "value": (1.0 + np.sin(np.arange(n) / 4)).astype(float)}


def _serve(server):
    th = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.05), daemon=True)
    th.start()
    return th


def _post(url_base, token, name, yaml_text):
    req = urllib.request.Request(
        f"{url_base}/save?token={token}",
        data=json.dumps({"name": name, "yaml": yaml_text}).encode(),
        headers={"Content-Type": "application/json"},
    )
    return urllib.request.urlopen(req, timeout=5)


def test_sanitize():
    assert _sanitize("My Outage!") == "my-outage"
    assert _sanitize("   ") == ""  # blank → no suffix (file is named after the metric)
    assert _sanitize("a/b\\c") == "a-b-c"
    assert _sanitize("CheckOut_5xx") == "checkout_5xx"


def test_render_labeler_html_modes():
    static = render_labeler_html("demo", _data(8))
    assert "const SAVE_URL = null;" in static
    assert "const INTERVAL_S = null;" in static  # inferred from data when omitted
    assert "const PRELOAD = [];" in static  # no seed incidents
    assert 'rel="icon"' in static and "data:image/svg+xml;base64," in static  # favicon
    # threshold capture + its time-window controls are present
    assert 'id="thbtn"' in static and 'id="thwin"' in static
    assert "function capRange()" in static
    served = render_labeler_html(
        "demo", _data(8), save_url="http://127.0.0.1:9/save?token=t", interval_seconds=3600
    )
    assert 'const SAVE_URL = "http://127.0.0.1:9/save?token=t";' in served
    assert "const INTERVAL_S = 3600;" in served
    assert "__SAVE_URL__" not in served and "__METRIC__" not in served
    assert "__INTERVAL__" not in served
    # every templated placeholder is filled in
    for placeholder in ("__PAYLOAD__", "__INCIDENTS__", "__FAVICON__"):
        assert placeholder not in served


def test_render_labeler_html_preloads_incidents():
    """`incidents=` seeds the editor so an existing labels file can be edited."""
    seed = [
        {"start": "2026-01-02 00:00:00", "end": "2026-01-02 06:00:00", "label": "outage"},
        {"start": "2026-01-03 01:00:00", "end": "2026-01-03 01:00:00", "label": ""},  # a point
    ]
    html = render_labeler_html("demo", _data(48), incidents=seed)
    assert "const PRELOAD = [" in html
    assert "2026-01-02 00:00:00" in html and "2026-01-02 06:00:00" in html
    assert "outage" in html


def test_build_label_server_preload_threads_into_page(tmp_path):
    seed = [{"start": "2026-01-02 00:00:00", "end": "2026-01-02 06:00:00", "label": "seeded"}]
    server, _url = build_label_server(
        metric_name="demo",
        data=_data(),
        incidents_dir=tmp_path,
        interval_seconds=3600,
        preload=seed,
    )
    try:
        assert "2026-01-02 00:00:00" in server.html and "seeded" in server.html
    finally:
        server.server_close()


def test_server_saves_valid_labels(tmp_path):
    inc = tmp_path / "incidents" / "demo"
    server, url = build_label_server(
        metric_name="demo", data=_data(), incidents_dir=inc, interval_seconds=3600
    )
    th = _serve(server)
    try:
        base, token = url.split("/?")[0], url.split("token=")[1]
        y = (
            "metric: demo\ntimezone: UTC\nincidents:\n"
            "  - {start: '2026-01-02 00:00:00', end: '2026-01-02 06:00:00', label: 'outage'}\n"
        )
        r = _post(base, token, "Set One", y)
        assert r.status == 200
        th.join(timeout=5)  # server stops itself after a successful save
        assert server.saved_path is not None and server.saved_path.exists()
        assert server.saved_path.parent == inc
        # File is named after the metric; the set name rides along as a suffix.
        assert server.saved_path.name.startswith("demo-set-one-")
        assert "outage" in server.saved_path.read_text()
    finally:
        try:
            server.shutdown()
        except Exception:
            pass
        server.server_close()


def test_server_filename_without_set_name(tmp_path):
    """A blank set name yields a file named after the metric alone (no leading dash)."""
    inc = tmp_path / "incidents" / "demo"
    server, url = build_label_server(
        metric_name="demo", data=_data(), incidents_dir=inc, interval_seconds=3600
    )
    th = _serve(server)
    try:
        base, token = url.split("/?")[0], url.split("token=")[1]
        y = (
            "metric: demo\ntimezone: UTC\nincidents:\n"
            "  - {start: '2026-01-02 00:00:00', end: '2026-01-02 06:00:00', label: 'outage'}\n"
        )
        r = _post(base, token, "", y)
        assert r.status == 200
        th.join(timeout=5)
        assert server.saved_path is not None and server.saved_path.exists()
        assert server.saved_path.name.startswith("demo-")
        assert not server.saved_path.name.startswith("demo--")  # no empty suffix
    finally:
        try:
            server.shutdown()
        except Exception:
            pass
        server.server_close()


def test_server_rejects_bad_token(tmp_path):
    inc = tmp_path / "incidents" / "demo"
    server, url = build_label_server(
        metric_name="demo", data=_data(), incidents_dir=inc, interval_seconds=3600
    )
    _serve(server)
    try:
        base = url.split("/?")[0]
        with pytest.raises(urllib.error.HTTPError) as ei:
            _post(base, "WRONG", "x", "metric: demo\nincidents: []\n")
        assert ei.value.code == 403
        assert server.saved_path is None
    finally:
        server.shutdown()
        server.server_close()


def test_server_rejects_invalid_labels(tmp_path):
    inc = tmp_path / "incidents" / "demo"
    server, url = build_label_server(
        metric_name="demo", data=_data(), incidents_dir=inc, interval_seconds=3600
    )
    _serve(server)
    try:
        base, token = url.split("/?")[0], url.split("token=")[1]
        with pytest.raises(urllib.error.HTTPError) as ei:
            _post(base, token, "x", "metric: demo\nincidents:\n  - {note: 'oops'}\n")
        assert ei.value.code == 400
        assert server.saved_path is None
        assert not inc.exists() or not list(inc.glob("*.yml"))
    finally:
        server.shutdown()
        server.server_close()
