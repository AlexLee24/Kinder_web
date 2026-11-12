"""DETECT light curves: one absolute-magnitude axis per matched redshift. No database needed."""
import json

from app.blueprints.detect.payload import MAX_Z_AXES, detect_z_axes
from app.services.photometry.data_processing import DataVisualization

ROWS = [   # as get_detect_match_rows / lightcurve_rows return them: host first
    {'catalog_name': 'DESI', 'is_host': True, 'z': 0.0523, 'match_data': {}},
    {'catalog_name': 'DESI', 'is_host': False, 'z': None, 'match_data': {'Z': 0.21}},
    {'catalog_name': 'Lens_Lens_UNKNOWN', 'is_host': False, 'z': None, 'match_data': {'z_lens': 0.4, 'reference': 'Hsu+2025'}},
    {'catalog_name': 'DESI', 'is_host': False, 'z': 0.05231, 'match_data': {}},   # same galaxy z as the host
    {'catalog_name': 'DESI', 'is_host': False, 'z': None, 'match_data': {}},      # no redshift: no axis
]


def test_one_entry_per_redshift_host_first_then_the_objects_own():
    axes = detect_z_axes(ROWS, own_z=0.3)
    assert [(round(a['z'], 4), a['label']) for a in axes] == [
        (0.0523, 'DESI host'), (0.3, 'object z'), (0.21, 'DESI'), (0.4, 'Lens · Hsu+2025')]


def test_capped_and_empty():
    many = [{'catalog_name': 'DESI', 'is_host': False, 'z': 0.01 * (i + 1), 'match_data': {}} for i in range(10)]
    assert len(detect_z_axes(many)) == MAX_Z_AXES
    assert detect_z_axes([], own_z=None) == []


def _layout(**kw):
    phot = [{'id': i, 'mjd': 61000 + i, 'magnitude': 19 + 0.1 * i, 'magnitude_error': 0.05, 'filter': 'r', 'telescope': 'X'}
            for i in range(3)]
    return json.loads(DataVisualization.create_photometry_plot_from_db(phot, as_json=True, **kw))['layout']


def test_plot_gets_an_axis_per_redshift_shifted_by_its_own_distance():
    axes = detect_z_axes(ROWS)
    lay = _layout(redshift=axes[0]['z'], z_axes=axes)
    rights = [lay[f'yaxis{i}'] for i in range(2, 2 + len(axes))]
    assert f'yaxis{2 + len(axes)}' not in lay
    assert rights[0]['title']['text'] == 'M · z=0.0523 DESI host' and 'anchor' not in rights[0]
    assert all(a['anchor'] == 'free' and a['autoshift'] for a in rights[1:])
    # farther galaxies make the same apparent magnitude brighter (more negative M)
    tops = [a['range'][1] for a in rights]
    assert tops[0] > tops[1] > tops[2]
    assert lay['margin']['r'] > 60


def test_without_redshifts_the_single_axis_is_unchanged():
    lay = _layout()
    assert lay['yaxis2']['title']['text'] == 'Abs Mag (z N/A)' and 'yaxis3' not in lay
    lay = _layout(redshift=0.05)
    assert lay['yaxis2']['title']['text'] == 'Abs Mag' and 'yaxis3' not in lay
