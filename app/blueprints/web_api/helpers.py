"""JSON API used by the marshal/object pages and external API-key clients — helpers (split from web_api_routes.py)."""
import math
import re


def _limit_decimal_4(value):
    """Limit decimal precision to at most 4 digits after decimal point."""
    if isinstance(value, bool) or value is None:
        return value

    if isinstance(value, (int, float)):
        if not math.isfinite(float(value)):
            return value
        return round(float(value), 4)

    if isinstance(value, str):
        s = value.strip()
        # Keep sexagesimal or non-numeric strings unchanged.
        if ':' in s:
            return value
        if re.fullmatch(r'[-+]?\d+(\.\d+)?', s):
            n = float(s)
            if math.isfinite(n):
                return f"{n:.4f}".rstrip('0').rstrip('.')
        return value

    return value

def _normalize_target_precision(target: dict) -> dict:
    out = dict(target or {})
    out['ra'] = _limit_decimal_4(out.get('ra'))
    out['dec'] = _limit_decimal_4(out.get('dec'))
    out['mag'] = _limit_decimal_4(out.get('mag'))

    filters = out.get('filters') or []
    if isinstance(filters, list):
        normalized_filters = []
        for f in filters:
            if isinstance(f, dict):
                ff = dict(f)
                ff['exp'] = _limit_decimal_4(ff.get('exp'))
                normalized_filters.append(ff)
            else:
                normalized_filters.append(f)
        out['filters'] = normalized_filters
    return out
