"""scripts/pipeline/autophot_stack.py and the runner's normalize_gain: the gain AutoPhOT is handed.

Lulin's pipeline multiplies by the gain to remove cosmic rays and divides back to ADU (BUNIT adu); ccdproc's
GAINCOR record stays in the header either way, so it says nothing about the units. An older pipeline version kept
electrons (BUNIT electron) beside the camera's GAIN. SLT writes GAIN as '0.95 [electrons/ADU]', which AutoPhOT
cannot read and replaces by 1. A mean of N frames has N times the per-frame gain."""
import importlib.util
import json
import os

import numpy as np
import pytest

fits = pytest.importorskip('astropy.io.fits')
from astropy.wcs import WCS  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STACK = os.path.join(HERE, 'scripts', 'pipeline', 'autophot_stack.py')
RUNNER = os.path.join(HERE, 'scripts', 'pipeline', 'autophot_web_run.py')


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope='module')
def st():
    return load('autophot_stack', STACK)


@pytest.fixture(scope='module')
def runner():
    return load('autophot_web_run', RUNNER)


def frame(path, i, **cards):
    w = WCS(naxis=2)
    w.wcs.crpix, w.wcs.cdelt = [32.5, 32.5], [-0.8 / 3600, 0.8 / 3600]
    w.wcs.crval, w.wcs.ctype = [47.9, -2.0], ['RA---TAN', 'DEC--TAN']
    h = w.to_header()
    h.update({'FILTER': 'rp_Astrodon_2018', 'EXPTIME': 150.0, 'DATE-OBS': f'2026-11-16T17:{10 + 3 * i:02d}:00',
              'TELESCOP': 'SLT', 'INSTRUME': 'Andor CCD/EMCCD (SDK2)', **cards})
    rng = np.random.default_rng(i)
    fits.PrimaryHDU(rng.normal(300, 17, (64, 64)).astype('float32'), header=h).writeto(path)
    return str(path)


@pytest.mark.parametrize('cards, expected', [
    ({'GAINCOR': 'ccd=<CCDData>, gain=0.92 electron / adu', 'GAIN': '0.92', 'BUNIT': 'adu'}, 0.92),   # LOT now
    ({'GAINCOR': 'ccd=<CCDData>, gain=0.95 electron / adu', 'GAIN': '0.95 [electrons/ADU]', 'BUNIT': 'adu'}, 0.95),
    ({'GAINCOR': 'ccd=<CCDData>, gain=0.92 electron / adu', 'GAIN': '0.92', 'BUNIT': 'electron'}, 1.0),  # older
    ({'GAIN': 0.92}, 0.92),
    ({'GAIN': ''}, None),
    ({}, None),
])
def test_frame_gain(st, cards, expected):
    h = fits.Header()
    h.update(cards)
    assert st.frame_gain(h, 'GAIN')[0] == expected


@pytest.mark.parametrize('cards, gain', [
    ({'GAINCOR': 'x', 'GAIN': '0.95 [electrons/ADU]', 'BUNIT': 'adu'}, 6.65),    # SLT as it arrives
    ({'GAINCOR': 'x', 'GAIN': '0.92', 'BUNIT': 'adu'}, 6.44),                    # LOT
    ({'GAINCOR': 'x', 'GAIN': '0.92', 'BUNIT': 'electron'}, 7.0),                # older electrons
    ({}, 7.0),                                                                   # nothing usable: 1 per frame
])
def test_a_mean_stack_carries_n_times_the_per_frame_gain(st, tmp_path, cards, gain):
    pytest.importorskip('reproject')
    files = [frame(tmp_path / f'f{i}.fits', i, **cards) for i in range(7)]
    st.stack({'files': files, 'out': str(tmp_path / 'stack.fits'), 'align': 'wcs', 'combine': 'mean'})
    h = fits.getheader(tmp_path / 'stack.fits')
    assert h['GAIN'] == pytest.approx(gain)
    assert h['NCOMBINE'] == 7 and h['EXPTIME'] == 150.0


def test_runner_gives_every_single_frame_a_readable_gain(runner, tmp_path):
    top = tmp_path / 'images'
    top.mkdir()
    old = frame(top / 'old.fits', 0, GAINCOR='x', GAIN='0.92', BUNIT='electron', TELESCOP='LOT')
    slt = frame(top / 'slt.fits', 1, GAINCOR='x', GAIN='0.95 [electrons/ADU]', BUNIT='adu')
    lot = frame(top / 'lot.fits', 2, GAINCOR='x', GAIN=0.92, BUNIT='adu', TELESCOP='LOT')
    stk = frame(top / 'stack.fits', 3, GAIN='0.95 [electrons/ADU]', STACKCMB='mean 3sigma')
    before = fits.getdata(slt).copy()

    changed = runner.normalize_gain({'fits_dir': str(top), 'wdir': str(tmp_path / 'nowdir')})

    assert changed == ['old.fits', 'slt.fits']
    assert fits.getheader(old)['GAIN'] == 1.0 and fits.getheader(old)['GAINORIG'] == '0.92'
    assert fits.getheader(slt)['GAIN'] == 0.95 and fits.getheader(slt)['GAINORIG'] == '0.95 [electrons/ADU]'
    assert np.array_equal(fits.getdata(slt), before)          # header only
    assert fits.getheader(lot)['GAIN'] == 0.92                 # already right
    assert fits.getheader(stk)['GAIN'] == '0.95 [electrons/ADU]'  # stacks keep their own
    assert runner.normalize_gain({'fits_dir': str(top), 'wdir': ''}) == []   # once only
