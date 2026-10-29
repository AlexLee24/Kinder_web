"""Pipeline workspaces: names, owners, share links and header tags. Works on a temporary
workspaces folder; no database, no AutoPhOT."""
import pytest

from app.services.pipeline import autophot as ap
from app.services.pipeline import filters as bands


@pytest.fixture
def runs(tmp_path, monkeypatch):
    monkeypatch.setattr(ap, 'runs_root', lambda: tmp_path)
    return tmp_path


def test_tag_reads_telescope_filter_exposure():
    h = {'TELESCOP': 'LOT', 'INSTRUME': 'LOT', 'FILTER': 'rp_Astrodon_2019', 'EXPTIME': '300.0'}
    info = bands.header_info(h, bands.telescope_db(ap.TELESCOPE_YML), bands.telescope_meta(ap.TELESCOPE_YML))
    assert info['tag'] == 'LOT rp 300s' and info['band'] == 'r'


def test_tag_uses_the_exposure_key_of_the_telescope_yml():
    h = {'TELESCOP': 'Lulin observatory, Taiwan', 'INSTRUME': 'Andor DZ936', 'FILTER': 'gp_astrodon_2018', 'EXPOSURE': '60'}
    info = bands.header_info(h, bands.telescope_db(ap.TELESCOPE_YML), bands.telescope_meta(ap.TELESCOPE_YML))
    assert info['tag'].endswith('gp 60s')


def test_same_name_asks_for_an_ending(runs):
    assert ap.create_workspace({'name': 'SN 2025abc_LOT_20261027'}, user='a@x') == 'SN_2025abc_LOT_20261027'
    with pytest.raises(ap.NameTaken):
        ap.create_workspace({'name': 'sn_2025abc_lot_20261027'}, user='b@x')      # case does not matter
    assert ap.create_workspace({'name': 'SN 2025abc_LOT_20261027', 'suffix': 'second'}, user='b@x') == 'SN_2025abc_LOT_20261027_second'
    assert ap.name_taken('SN_2025abc_LOT_20261027')


def test_private_until_shared(runs):
    tid = ap.create_workspace({'name': 'ws'}, user='a@x')
    assert ap.require(tid, 'a@x') == 'owner'
    assert ap.require(tid, 'root@x', is_admin=True) == 'owner'
    with pytest.raises(ap.NotFound):
        ap.require(tid, 'b@x')
    assert [w['id'] for w in ap.targets('a@x')] == [tid] and ap.targets('b@x') == []

    token = ap.share_on(tid)['token']
    with pytest.raises(ap.NotFound):
        ap.join_share(tid, 'wrong', 'b@x')
    ap.join_share(tid, token, 'b@x')
    assert ap.require(tid, 'b@x') == 'editor'
    with pytest.raises(ap.Forbidden):
        ap.require(tid, 'b@x', owner=True)
    assert [w['id'] for w in ap.targets('b@x')] == [tid]
    assert ap.info(tid, 'b@x')['share'] is None                  # only the owner sees the link

    ap.share_off(tid)
    with pytest.raises(ap.NotFound):
        ap.require(tid, 'b@x')


def test_workspaces_from_before_owners_stay_open(runs):
    tid = ap.create_workspace({'name': 'old'}, user='a@x')
    cfg = ap._read_json(runs / tid / 'target.json')
    cfg.pop('owner')
    ap._write_json(runs / tid / 'target.json', cfg)
    assert ap.require(tid, 'anyone@x') == 'owner'


def test_settings_are_saved_piece_by_piece(runs):
    tid = ap.create_workspace({'name': 'ws'}, user='a@x')
    ap.save_target(tid, {'ra': '12.5'}, 'a@x')                    # half a position is fine while typing
    ap.save_target(tid, {'target': 'SN2025abc', 'dec': '-3', 'catalog': 'gaia'}, 'a@x')
    cfg = ap.info(tid)['cfg']
    assert (cfg['target'], cfg['ra'], cfg['dec'], cfg['catalog']) == ('SN2025abc', '12.5', '-3', 'gaia')
    assert ap.info(tid)['name'] == 'ws'                           # the target is not the workspace name
    with pytest.raises(ap.PipelineError):
        ap.rename_workspace(tid, '')
