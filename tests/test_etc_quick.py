"""The Exposure Time Calculator's Simple mode (app/blueprints/astronomy_tools/etc_quick.py).

Runs CASTOR itself, so it needs the vendored clone (app/vendor/CASTOR); skipped without it.
The target is placed near the zenith over Lulin (RA 22h, Dec +20 at 14:00 UTC on 2025-09-28).
"""
import pytest

from app.paths import CASTOR_SRC

pytestmark = pytest.mark.skipif(not CASTOR_SRC.is_dir(), reason="vendored CASTOR not present")

WHEN = "2025-09-28T14:00:00Z"


@pytest.fixture(scope="module")
def catalogue():
    from app.paths import add_vendor_paths
    add_vendor_paths()
    from castorCLI import presets
    return presets.load()


def plan(catalogue, **overrides):
    from app.blueprints.astronomy_tools.etc_quick import compute_plan
    args = dict(site="lulin", telescope="LOT", camera="Sophia", optic_filter="Sloan_r",
                ra=330.0, dec=20.0, mag=21.0, target_snr=10.0,
                observing_time_utc=WHEN, fwhm=1.4)
    args.update(overrides)
    return compute_plan(catalogue, **args)


def test_recommended_plan_reaches_the_target(catalogue):
    result = plan(catalogue)
    assert result["status"] == "ok"
    rec = result["recommended"]
    assert rec["snr"] >= 10.0
    assert rec["exp_s"] < result["conditions"]["saturation_time_s"]
    # Within the stated tolerance of the fastest row, and the shortest frame that is.
    fastest = min(row["total_s"] for row in result["rows"])
    assert rec["total_s"] <= fastest * 1.10
    assert all(row["total_s"] > fastest * 1.10 for row in result["rows"] if row["exp_s"] < rec["exp_s"])


def test_single_frame_time_is_what_castor_says(catalogue):
    """The closed-form single-frame time, fed back to CASTOR, gives the target SNR."""
    from castor import schema
    from castor.calculator import run_calculation

    result = plan(catalogue)
    t_one = result["single_frame_time_s"]
    request = catalogue.resolve("lulin", "LOT", "Sophia", "Sloan_r")
    request["target"] = {"ra": 330.0, "dec": 20.0, "morphology": {"type": "point"},
                         "sed": {"type": "flat"}, "brightness": {"type": "ab_mag", "target_mag": 21.0}}
    request["environment"].update({"total_fwhm": 1.4, "observing_time_utc": WHEN, "auto_calc_background": True})
    request["instrument"]["throughput_correction"] = 1.0
    request["options"] = {"type": "solve_snr", "num_exposures": 1, "single_exp_time": t_one,
                          "aperture_factor": 0.85,
                          "sky_annulus": {"inner_factor": 3.0, "outer_factor": 5.0, "estimator": "median"}}
    snr = run_calculation(schema.ObservationRequest.model_validate(request)).core.total_snr
    assert snr == pytest.approx(10.0, rel=1e-6)


def test_faint_target_needs_several_frames(catalogue):
    result = plan(catalogue, mag=23.5)
    assert result["recommended"]["frames"] > 1
    assert [row["exp_s"] for row in result["rows"]] == sorted(row["exp_s"] for row in result["rows"])


def test_target_below_the_horizon(catalogue):
    result = plan(catalogue, ra=150.0)
    assert result["status"] == "below_horizon"
    assert result["rows"] == []


def test_bright_star_saturates(catalogue):
    result = plan(catalogue, mag=6.0)
    assert result["status"] == "saturated"


def test_coordinates_in_either_notation():
    from app.blueprints.astronomy_tools.etc_quick import QuickInputError, parse_coordinates
    assert parse_coordinates("22:00:00", "+20:00:00") == pytest.approx((330.0, 20.0))
    assert parse_coordinates("330", "20") == pytest.approx((330.0, 20.0))
    with pytest.raises(QuickInputError):
        parse_coordinates("xyz", "1")
