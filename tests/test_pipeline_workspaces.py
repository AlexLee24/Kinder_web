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


def test_private_until_invited_and_only_the_owner_runs(runs):
    tid = ap.create_workspace({'name': 'ws'}, user='a@x', user_name='Alex')
    assert ap.require(tid, 'a@x', owner=True, edit=True) == 'owner'
    with pytest.raises(ap.NotFound):
        ap.require(tid, 'b@x')
    assert [w['id'] for w in ap.targets('a@x')] == [tid] and ap.targets('b@x') == []

    token = ap.share_on(tid)['token']
    with pytest.raises(ap.NotFound):
        ap.join_share(tid, 'wrong', 'b@x')
    ap.join_share(tid, token, 'b@x')
    assert ap.require(tid, 'b@x') == 'member'                     # may look
    with pytest.raises(ap.Forbidden):
        ap.require(tid, 'b@x', edit=True)                          # but not run or change
    with pytest.raises(ap.Forbidden):
        ap.require(tid, 'b@x', owner=True)
    info = ap.info(tid, 'b@x')
    assert info['share'] is None and not info['can_edit'] and info['owner_name'] == 'Alex'

    ap.set_run_access(tid, add={'user': 'b@x', 'name': 'Bea'})      # the owner gives b the right to run
    assert ap.require(tid, 'b@x', edit=True) == 'member' and ap.info(tid, 'b@x')['can_edit']
    with pytest.raises(ap.Forbidden):
        ap.require(tid, 'b@x', owner=True)                         # delete, share, keep stay the owner's
    assert ap.info(tid)['runners'] == [{'user': 'b@x', 'name': 'Bea'}]

    ap.share_off(tid)                                              # stopping the link does not take a runner's right away
    assert ap.require(tid, 'b@x', edit=True) == 'member'
    ap.set_run_access(tid, remove='b@x')
    with pytest.raises(ap.NotFound):
        ap.require(tid, 'b@x')


def test_running_can_be_opened_to_everyone_with_an_account_that_sees_the_page(runs):
    tid = ap.create_workspace({'name': 'ws'}, user='a@x')
    with pytest.raises(ap.NotFound):
        ap.require(tid, 'c@x')
    ap.set_run_access(tid, run_all=True)
    assert ap.require(tid, 'c@x', edit=True) == 'member'
    assert [w['id'] for w in ap.targets('c@x')] == [tid]
    with pytest.raises(ap.Forbidden):
        ap.require(tid, 'c@x', owner=True)
    ap.set_run_access(tid, run_all=False)
    with pytest.raises(ap.NotFound):
        ap.require(tid, 'c@x')


def test_an_admin_is_the_owner_of_every_workspace(runs):
    tid = ap.create_workspace({'name': 'ws'}, user='a@x')
    assert ap.require(tid, 'root@x', is_admin=True, owner=True, edit=True) == 'owner'
    assert [w['id'] for w in ap.targets('root@x', True)] == [tid]


def test_images_can_be_kept_one_more_day_at_a_time(runs):
    tid = ap.create_workspace({'name': 'ws'}, user='a@x')
    img = ap.images_dir(tid) / 'a.fits'
    img.write_bytes(b'x')
    first = ap.info(tid)['expires']
    assert first and ap.info(tid)['keep_days'] == ap.config.FITS_KEEP_DAYS
    assert ap.keep_one_more_day(tid) == ap.config.FITS_KEEP_DAYS + 1
    assert ap.info(tid)['expires'] == pytest.approx(first + 86400)
    for _ in range(ap.MAX_KEEP_EXTRA):
        try:
            ap.keep_one_more_day(tid)
        except ap.PipelineError:
            break
    with pytest.raises(ap.PipelineError):
        ap.keep_one_more_day(tid)


def test_results_link_needs_the_password_of_the_owner(runs):
    tid = ap.create_workspace({'name': 'ws'}, user='a@x')
    with pytest.raises(ap.PipelineError):
        ap.result_share_create(tid, '', 'abc')                      # too short
    with pytest.raises(ap.NotFound):
        ap.result_share_create(tid, '20200101-000000', 'secret1')   # no such earlier run
    share = ap.result_share_create(tid, '', 'secret1', user='a@x')
    found_tid, found = ap.find_result_share(share['token'])
    assert found_tid == tid and found['id'] == share['id']
    assert ap.check_result_password(found, 'secret1') and not ap.check_result_password(found, 'secret2')
    assert 'hash' not in ap.result_shares(ap._read_json(ap.tdir(tid) / 'target.json'))[0]
    assert ap.find_result_share('nope') == (None, None)
    ap.result_share_stop(tid, share['id'])
    assert ap.find_result_share(share['token']) == (None, None)


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


LOG_WITH_ERRORS = '''[WARNING] Reproject failed. Falling back to AstroAlign.

[ERROR] Reproject footprint coverage 18.3% below minimum 25.0%; too little overlap for a
          meaningful subtraction.

[ERROR] All alignment methods failed (spalipy->swarp->reproject->astroalign->chi2_shift).
          Skipping template subtraction: aligned inputs are required for a meaningful
          difference image.

[ERROR] Template alignment failed

        Type     : RuntimeError
        File     : /x/main.py
        Traceback (most recent call last):

[ERROR] Reproject footprint coverage 18.3% below minimum 25.0%; too little overlap for a
          meaningful subtraction.
'''


def test_the_errors_of_a_run_are_listed_once_each(runs):
    tid = ap.create_workspace({'name': 'ws'}, user='a@x')
    (runs / tid / 'web_run.log').write_text(LOG_WITH_ERRORS)
    problems = ap.run_problems(tid)
    assert [p['n'] for p in problems] == [2, 1, 1]
    assert problems[0]['text'] == ('Reproject footprint coverage 18.3% below minimum 25.0%; too little overlap for a '
                                   'meaningful subtraction.')
    assert problems[2]['text'] == 'Template alignment failed'


def test_a_new_survey_or_size_downloads_the_templates_again(runs):
    tid = ap.create_workspace({'name': 'ws'}, user='a@x')
    ap.save_target(tid, {'subtraction': True, 'ts_download': 'panstarrs', 'ts_size': 10}, 'a@x')
    folder = ap.images_dir(tid) / 'templates' / 'r_template'
    folder.mkdir(parents=True)
    (folder / 'panstarrs_r_band_template.fits').write_bytes(b'x')
    (folder / 'my_own_r.fits').write_bytes(b'x')
    ap.save_target(tid, {'catalog': 'gaia'}, 'a@x')                  # other settings: the download stays
    assert (folder / 'panstarrs_r_band_template.fits').exists()
    ap.save_target(tid, {'ts_size': 15}, 'a@x')
    assert not (folder / 'panstarrs_r_band_template.fits').exists()
    assert (folder / 'my_own_r.fits').exists()                       # an uploaded template is never removed
    assert ap.info(tid)['cfg']['ts_crop'] is True
