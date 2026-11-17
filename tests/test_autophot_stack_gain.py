"""scripts/pipeline/autophot_stack.py and the runner's electron_gain: the gain AutoPhOT is handed.

Lulin's Calibrated_Science frames are already in electrons (ccdproc's gain_correct leaves GAINCOR) but keep the
camera's GAIN (LOT 0.92) or none usable (SLT). A mean of N such frames has an effective gain of N; before this the
stack kept 0.92 x N for LOT and the reference frame's GAIN, 1, for SLT, so AutoPhOT's noise for an SLT stack was
N times too large in variance."""
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
    ({'GAINCOR': 'ccd=<CCDData>, gain=0.92 electron / adu', 'GAIN': 0.92, 'BUNIT': 'adu'}, 1.0),
    ({'GAINCOR': 'ccd=<CCDData>, gain=0.95 electron / adu'}, 1.0),
    ({'GAIN': 0.92}, 0.92),
    ({'GAIN': '0.95 [electrons/ADU]'}, 0.95),
    ({'BUNIT': 'electron', 'GAIN': 2.0}, 1.0),
    ({}, None),
])
def test_frame_gain(st, cards, expected):
    h = fits.Header()
    h.update(cards)
    assert st.frame_gain(h, 'GAIN')[0] == expected


@pytest.mark.parametrize('cards, gain', [
    ({'GAINCOR': 'ccd=<CCDData>, gain=0.95 electron / adu', 'GAIN': 1.0}, 7.0),   # SLT as it arrives
    ({'GAINCOR': 'ccd=<CCDData>, gain=0.92 electron / adu', 'GAIN': 0.92}, 7.0),  # LOT
    ({'GAIN': 0.92}, 6.44),                                                       # raw ADU frames
    ({}, 7.0),                                                                    # nothing usable: 1 per frame
])
def test_a_mean_stack_carries_n_times_the_per_frame_gain(st, tmp_path, cards, gain):
    pytest.importorskip('reproject')
    files = [frame(tmp_path / f'f{i}.fits', i, **cards) for i in range(7)]
    st.stack({'files': files, 'out': str(tmp_path / 'stack.fits'), 'align': 'wcs', 'combine': 'mean'})
    h = fits.getheader(tmp_path / 'stack.fits')
    assert h['GAIN'] == pytest.approx(gain)
    assert h['NCOMBINE'] == 7 and h['EXPTIME'] == 150.0


def test_runner_sets_electron_frames_to_gain_one(runner, tmp_path):
    top = tmp_path / 'images'
    top.mkdir()
    lot = frame(top / 'lot.fits', 0, GAINCOR='ccd=<CCDData>, gain=0.92 electron / adu', GAIN=0.92, TELESCOP='LOT')
    raw = frame(top / 'raw.fits', 1, GAIN=0.92)
    stk = frame(top / 'stack.fits', 2, GAINCOR='x', GAIN=5.52, STACKCMB='mean 3sigma')
    before = fits.getdata(lot).copy()

    changed = runner.electron_gain({'fits_dir': str(top), 'wdir': str(tmp_path / 'nowdir')})

    assert changed == ['lot.fits']
    h = fits.getheader(lot)
    assert h['GAIN'] == 1.0 and h['GAINORIG'] == '0.92'
    assert np.array_equal(fits.getdata(lot), before)          # header only
    assert fits.getheader(raw)['GAIN'] == 0.92                 # not electrons: left alone
    assert fits.getheader(stk)['GAIN'] == 5.52                 # stacks keep their own
    assert runner.electron_gain({'fits_dir': str(top), 'wdir': ''}) == []   # once only
