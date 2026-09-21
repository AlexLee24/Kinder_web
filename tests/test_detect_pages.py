"""DETECT pages of the web app render, against the live Kinder DB.

    .venv/bin/python -m pytest tests/test_detect_pages.py -q

Uses the Flask test client with a fake admin session (no login), so a template
error or a broken query shows up here instead of in a browser. Read-only: no
decision endpoints are exercised.
"""
import pytest

from tests.conftest import BASE_URL

pytestmark = pytest.mark.live_db


def _get(client, url):
    return client.get(url, base_url=BASE_URL)


def test_home_renders(admin_client):
    r = _get(admin_client, "/detect")
    assert r.status_code == 200
    html = r.data.decode()
    assert "Pipeline" in html and "Host rule v1" in html and "Latest run" in html


def test_archives_render(admin_client):
    assert _get(admin_client, "/detect/archives").status_code == 200


def test_review_page_renders_for_latest_day(app, admin_client):
    from app.db.transient import get_detect_metadata
    from app.blueprints.detect import cache, payload
    dates = get_detect_metadata().get("available_dates") or []
    if not dates:
        pytest.skip("no cross-match days in the database")
    with app.app_context():
        data = payload._assemble_detect_payload(dates[0])
        cache._set_detect_page_cache(dates[0], data)
    r = _get(admin_client, f"/detect?detect_results={dates[0]}")
    assert r.status_code == 200
    html = r.data.decode()
    assert html.count('class="target-card') == len(data["results"])
    assert "How to review" in html
    for t in data["results"]:
        assert t["host_status"] in ("confirmed", "review", "none", "unscreened")
        assert t["verdict"]["headline"]
        for m in t["matches"]:
            assert m["rule"]["kind"] in ("host", "shred", "member", "tentative", "outside", "lens", "nomodel")


def test_tracker_and_overview_endpoints(admin_client):
    r = _get(admin_client, "/api/detect/followup_tracker")
    assert r.status_code == 200 and r.get_json()["success"] is True
    from app.db.transient import get_detect_overview
    ov = get_detect_overview()
    assert set(ov) >= {"last_run", "counts", "pending", "top"}


def test_calculator_is_detects(app):
    """One absolute-magnitude formula on the site: DETECT's cosmology and extinction."""
    from app.services.astro import ext_M_calculator as m
    assert m.cosmo.name == "DETECT-Planck18"
    a_g = float(m.get_extinction(337.7080, -1.0384, "g"))
    assert 0.15 < a_g < 0.3
    assert m.apm_to_abm(19.7086, 0.1505279282024094, a_g) == pytest.approx(-20.005, abs=0.002)


def test_embedded_detect_importable(app):
    from app.services.detect import detect_pipeline
    from function.run_detect import run_detect_for_names, run_detect_single, run_detect_followups  # noqa: F401
    from function.module.cross_match import D_MAX_QSO, LENS_SEARCH_RADIUS_ARCSEC
    assert detect_pipeline.ENABLED
    # Constants of the vendored DETECT copy (app/vendor/DETECT/VERSION says which commit).
    assert D_MAX_QSO == 1.0 and LENS_SEARCH_RADIUS_ARCSEC == 10.0


def test_admin_detect_status(admin_client):
    r = _get(admin_client, "/admin/detect-status")
    assert r.status_code == 200
    st = r.get_json()
    assert {"enabled", "code_present", "sfd_maps", "running", "db"} <= set(st)
    assert st["code_present"] and "screened_24h" in st["db"]
