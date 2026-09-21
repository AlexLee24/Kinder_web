"""Jinja template filters registered on the app."""
import re


def regex_search(s, pattern):
    """``{{ value | regex_search('...') }}`` -> tuple of groups, or None."""
    if not s:
        return None
    match = re.search(pattern, s)
    if match:
        return match.groups()
    return None


def register_template_filters(app) -> None:
    app.add_template_filter(regex_search, 'regex_search')
