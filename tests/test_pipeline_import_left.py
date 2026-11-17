"""A Pipeline import into a Kinder object only counts as "already imported" while its points are still there:
points deleted on the Transient page leave the record behind, and the next import must not warn about it."""
import pytest

from app.services.pipeline import autophot as ap


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.setattr(ap, 'runs_root', lambda: tmp_path)
    tid = ap.create_workspace({'name': 'AT2026ajog_SLT_20261115'}, user='a@x')
    cfg = ap._read_json(tmp_path / tid / 'target.json')
    cfg['imports'] = [{'id': '20261117-095346', 'time': 1794880426, 'object': '2026ajog', 'method': 'PSF', 'limit': 3.0,
                       'run': None, 'n_points': 3, 'n_inserted': 3, 'phot_ids': [11, 12, 13]}]
    ap._write_json(tmp_path / tid / 'target.json', cfg)
    pts = [{'mjd': 61359.53917, 'magnitude': 20.682, 'magnitude_error': 0.103, 'filter': 'r', 'telescope': 'SLT', 'upper': False}]
    monkeypatch.setattr(ap, 'export_rows', lambda *a, **k: pts)
    from app.db.transient import TNSObjectDB
    monkeypatch.setattr(TNSObjectDB, 'resolve_object_name', staticmethod(lambda n: '2026ajog'))
    monkeypatch.setattr(TNSObjectDB, 'get_photometry', staticmethod(lambda n: []))
    return tid


def test_deleted_points_do_not_count_as_imported(ws, monkeypatch):
    monkeypatch.setattr(ap, '_live_phot_ids', lambda ids: set())
    assert ap.import_preview(ws, {'object': '2026ajog'})['already'] is None
    assert ap.imports(ws)[0]['n_left'] == 0


def test_points_still_there_warn_with_how_many(ws, monkeypatch):
    monkeypatch.setattr(ap, '_live_phot_ids', lambda ids: {12})
    already = ap.import_preview(ws, {'object': '2026ajog'})['already']
    assert already['n_left'] == 1 and already['n_inserted'] == 3 and 'phot_ids' not in already
