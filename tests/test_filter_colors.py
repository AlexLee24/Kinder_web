"""One filter colour map for the whole site: app/resources/filter_colors.json, tracked in git."""
import json

from app.paths import RESOURCES_DIR
from app.services.astro import filter_colors


def test_colours_come_from_the_tracked_file():
    tracked = {k: v for k, v in json.loads((RESOURCES_DIR / 'filter_colors.json').read_text()).items() if not k.startswith('_')}
    assert filter_colors.all_colors() == tracked
    assert filter_colors.COLORS_FILE == str(RESOURCES_DIR / 'filter_colors.json')


def test_no_dark_filter_on_the_dark_plot():
    """Every colour is light enough for the dark light-curve panel (the old L was #362511)."""
    for name, hex_ in filter_colors.all_colors().items():
        r, g, b = (int(hex_[i:i + 2], 16) / 255 for i in (1, 3, 5))
        lum = sum(c * w for c, w in zip([(x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4) for x in (r, g, b)],
                                         (0.2126, 0.7152, 0.0722)))
        assert (lum + 0.05) / (0.0 + 0.05) >= 4.5, name
