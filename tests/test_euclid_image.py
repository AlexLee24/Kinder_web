"""DETECT's Euclid VIS review image and the Euclid tile-centre pre-filter."""
import json
import time

import numpy as np
import pytest

from app.services.astro import euclid_cutout as ec
from app.services.detect import euclid_image


@pytest.fixture
def tiles(tmp_path, monkeypatch):
    f = tmp_path / 'tiles.json'
    f.write_text(json.dumps({'fetched': time.time(), 'tiles': [[52.9, -28.1], [269.7, 66.0]]}))
    monkeypatch.setattr(ec, 'TILES_FILE', f)
    monkeypatch.setattr(ec, '_tiles', {'ra': None, 'dec': None, 'fetched': 0.0})
    monkeypatch.setattr(ec, 'refresh_tiles', lambda: (_ for _ in ()).throw(AssertionError('no ESA call expected')))
    return f


def test_near_tile(tiles):
    assert ec.near_tile(52.9, -28.1) is True
    assert ec.near_tile(53.2, -28.3) is True          # ~0.33 deg away, inside the tile
    assert ec.near_tile(10.0, 10.0) is False
    assert ec.near_tile(269.0, 66.1) is True          # RA spacing shrinks with cos(dec)


def test_outside_euclid_needs_no_archive(tiles, monkeypatch):
    monkeypatch.setattr(ec.es, 'esa_reachable', lambda *a, **k: pytest.fail('ESA asked for a position outside Euclid'))
    assert ec.coverage(10.0, 10.0) == {'covered': False, 'reason': 'outside Euclid DR1 / Q1'}
    assert euclid_image.build_png('X', 10.0, 10.0) is None


def test_render_marks_png():
    rng = np.random.default_rng(1)
    data = rng.normal(0, 1, (300, 300)).astype('f4')
    png = euclid_image._render('2026abc', 52.9, -28.1, data, 150, 150, 0.1, 30,
                               {'release': 'dr1', 'tile': 101375805},
                               [{'ra': 52.9005, 'dec': -28.1, 'crossmatch_uid': 'a', 'catalog_name': 'DESI'}], 'a')
    assert png[:8] == b'\x89PNG\r\n\x1a\n' and len(png) > 10_000


def test_fov_clamped():
    assert euclid_image._fov(5) == euclid_image.FOV_MIN
    assert euclid_image._fov(500) == euclid_image.FOV_MAX
    assert euclid_image._fov(None) == 60


def test_ls_finder_readers_skip_euclid_rows():
    import inspect
    from app.db import transient
    assert "source <> 'Euclid'" in inspect.getsource(transient.get_target_image)
    assert "source = 'DESI'" in inspect.getsource(transient.save_target_image)
