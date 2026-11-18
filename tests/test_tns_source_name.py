"""A TNS discovery point is named after its discovery group, like the TNS sync names it."""
from app.services.photometry.download_phot import tns_source_name


def test_discovery_group_names_the_point():
    data = {'discovery_data_source': {'group_id': 48, 'group_name': 'ZTF'},
            'reporting_group': {'group_id': 48, 'group_name': 'ALeRCE'},
            'discmagfilter': {'name': 'r', 'family': 'ZTF'}}
    assert tns_source_name(data) == 'ZTF (TNS)'


def test_falls_back_to_the_reporting_group_then_plain_tns():
    assert tns_source_name({'discovery_data_source': None, 'reporting_group': {'group_name': 'YSE'}}) == 'YSE (TNS)'
    assert tns_source_name({'discovery_data_source': 'GOTO'}) == 'GOTO (TNS)'
    assert tns_source_name({'discovery_data_source': {'group_name': ''}}) == '(TNS)'
    assert tns_source_name({}) == '(TNS)'


def test_never_the_filter_family():
    """'Sloan' is a filter system used by many groups (Shadow, YSE, DESI, …), not who found it."""
    data = {'discovery_data_source': {'group_name': 'Shadow'}, 'discmagfilter': {'name': 'g', 'family': 'Sloan'}}
    assert tns_source_name(data) == 'Shadow (TNS)'
