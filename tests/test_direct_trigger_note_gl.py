"""Direct Trigger: a new target needs a Note for Lab (web only, never in the script)."""
from app.blueprints.private_area.direct_trigger import _script_payload, _validate_target

BASE = {'telescope': 'SLT', 'name': 'SN 2026abc', 'ra': '10:00:00', 'dec': '+20:00:00', 'mag': '18',
        'priority': 'Normal', 'repeat_count': 0, 'auto_exp': True}


def test_note_for_lab_is_required():
    for missing in ({}, {'note_gl': ''}, {'note_gl': '   '}):
        clean, err = _validate_target({**BASE, **missing})
        assert clean is None and 'Note for Lab' in err


def test_note_for_lab_kept_and_out_of_script():
    clean, err = _validate_target({**BASE, 'note_gl': ' Young SN II, flash features ', 'note': 'g first'})
    assert err is None and clean['note_gl'] == 'Young SN II, flash features'
    item = _script_payload([{**clean, 'id': 1, 'filters': []}])[0]
    assert 'Young SN II' not in str(item) and item['priority_message'] == 'g first'


def test_note_for_lab_length_limit():
    clean, err = _validate_target({**BASE, 'note_gl': 'x' * 301})
    assert clean is None and '300' in err
