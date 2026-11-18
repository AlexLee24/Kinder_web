"""
Filter color utilities.
Single source of truth: app/resources/filter_colors.json (hex, no alpha), tracked in git so a deploy updates every
page. There is no per-server copy: an old app/data/filter_colors.json (the dark 2026-04 colours) is not read.
"""
import json
import os

from app.paths import RESOURCES_DIR

COLORS_FILE = os.path.join(RESOURCES_DIR, 'filter_colors.json')
_DEFAULT_HEX = '#808080'

def _load():
    with open(COLORS_FILE, 'r') as f:
        data = json.load(f)
    # Remove comment key if present
    return {k: v for k, v in data.items() if not k.startswith('_')}

_COLORS: dict[str, str] = _load()


def get_hex(filter_name: str) -> str:
    """Return hex color for a filter, e.g. '#ff6464'."""
    return _COLORS.get(filter_name, _DEFAULT_HEX)


def get_rgba(filter_name: str, alpha: float = 1.0) -> str:
    """Return CSS rgba() string for a filter with given alpha."""
    hex_color = _COLORS.get(filter_name, _DEFAULT_HEX)
    hex_color = hex_color.lstrip('#')
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)
    return f'rgba({r},{g},{b},{alpha})'


def all_colors() -> dict[str, str]:
    """Return a copy of the full hex color map (for template injection)."""
    return dict(_COLORS)
