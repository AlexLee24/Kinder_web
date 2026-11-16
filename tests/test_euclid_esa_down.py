"""When the ESA Euclid archive is down, Sky Cutouts and Euclid-SLSN answer at once with a JSON error, not after the
reverse proxy has replaced a slow answer with its own HTML page."""
import time

import pytest

from app.services.astro import euclid_cutout as ec
from app.services.special_run import euclid_slsn as es


@pytest.fixture
def down(monkeypatch, tmp_path):
    monkeypatch.setattr(ec, '_pos_dir', lambda ra, dec: tmp_path / f'{ra}_{dec}')
    # no tile-centre list yet: every position has to ask the archive (with one, far positions never do)
    monkeypatch.setattr(ec, 'TILES_FILE', tmp_path / 'no_tiles.json')
    monkeypatch.setattr(ec, '_tiles', {'ra': None, 'dec': None, 'fetched': 0.0})
    monkeypatch.setattr(es, 'esa_reachable', lambda timeout=4.0: False)
    monkeypatch.setattr(es, '_euclid', lambda: pytest.fail('must not query ESA when it is down'))


def test_coverage_fails_fast_with_503(down):
    t = time.monotonic()
    with pytest.raises(ec.EuclidError) as e:
        ec.coverage(149.9286333, 0.4184389)
    assert e.value.status == 503 and 'not responding' in str(e.value) and time.monotonic() - t < 2


def test_coverage_api_returns_json(down, client_factory):
    r = client_factory('admin').get('/api/cutouts/coverage?ra=149.9286333&dec=0.4184389')
    assert r.status_code == 503 and 'not responding' in r.get_json()['error']


def test_failure_is_not_cached(down, monkeypatch, tmp_path):
    with pytest.raises(ec.EuclidError):
        ec.coverage(10.0, 1.0)
    assert not (tmp_path / '10.0_1.0' / 'coverage.json').exists()


def test_probe_is_cached(monkeypatch):
    calls = []

    def fake_conn(addr, timeout):
        calls.append(addr)
        raise OSError('refused')
    monkeypatch.setattr(es.socket, 'create_connection', fake_conn)
    monkeypatch.setitem(es._probe, 'at', 0.0)
    assert es.esa_reachable() is False and es.esa_reachable() is False
    assert len(calls) == 1 and calls[0][1] == 443 and calls[0][0].endswith('esac.esa.int')


def test_special_run_refuses_to_start(monkeypatch, client_factory):
    monkeypatch.setattr(es, 'esa_reachable', lambda timeout=4.0: False)
    monkeypatch.setattr(es, 'start', lambda **k: pytest.fail('must not start'))
    r = client_factory('admin').post('/api/special_run/euclid_slsn/run', json={})
    assert r.status_code == 503 and 'not responding' in r.get_json()['error']
