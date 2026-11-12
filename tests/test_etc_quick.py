"""The Exposure Time Calculator's Simple-mode route (POST /api/exposure_time_calculator/quick).

The planner itself is CASTOR's (castorCLI/plan.py) and is tested there (tests/test_plan.py); this checks that
Kinder's route takes both goals and answers like CASTOR's own server.py. Runs CASTOR, so it needs the vendored
clone (app/vendor/CASTOR); skipped without it. The target sits near the zenith over Lulin (RA 22h, Dec +20 at
14:00 UTC on 2025-09-28).
"""
import pytest

from app.paths import CASTOR_SRC

pytestmark = pytest.mark.skipif(not CASTOR_SRC.is_dir(), reason="vendored CASTOR not present")

URL = "/api/exposure_time_calculator/quick"
BASE = dict(site="lulin", telescope="LOT", camera="Sophia", filter="Sloan_r",
            ra="22:00:00", dec="+20:00:00", mag=21.0, fwhm=1.4, observing_time_utc="2025-09-28T14:00:00Z")


def post(client, **body):
    r = client.post(URL, json=body)
    return r.status_code, r.get_json()


def test_solve_time_is_the_default(client):
    code, res = post(client, **BASE, target_snr=10)
    assert code == 200 and res["goal"] == "solve_time" and res["status"] == "ok"
    assert res["recommended"]["snr"] >= 10


def test_solve_snr_returns_the_snr_of_the_frames_given(client):
    code, res = post(client, **BASE, goal="solve_snr", single_exp_time=120, num_exposures=3)
    assert code == 200 and res["goal"] == "solve_snr" and res["status"] == "ok"
    chosen = res["chosen"]
    assert (chosen["exp_s"], chosen["frames"], chosen["total_s"]) == (120, 3, 360)
    # the same 6 min cut into more frames costs SNR (one more readout each)
    by_frames = {r["frames"]: r["snr"] for r in res["rows"]}
    assert by_frames[1] > by_frames[3] > by_frames[10]


def test_bad_input_is_a_400_with_a_message(client):
    assert post(client, **BASE, goal="solve_magic", target_snr=10) == (
        400, {"error": "Unknown goal 'solve_magic': use solve_time or solve_snr."})
    code, res = post(client, **BASE, goal="solve_snr", single_exp_time=120, num_exposures=0)
    assert code == 400 and "whole number" in res["error"]
    code, res = post(client, **{k: v for k, v in BASE.items() if k != "mag"}, goal="solve_snr", single_exp_time=120)
    assert code == 400 and res["error"] == "Fill in the magnitude, exposure time and seeing."
    code, res = post(client, **BASE)
    assert code == 400 and res["error"] == "Fill in the magnitude, target SNR and seeing."
