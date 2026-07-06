"""Shared helpers for validating numeric query-string parameters."""
import math
from flask import request

DEFAULT_MIN = -999999
DEFAULT_MAX = 999999


class ParamOutOfRangeError(ValueError):
    """Raised when a numeric request parameter is malformed or outside the allowed range."""

    def __init__(self, name, value, min_val, max_val):
        super().__init__(
            f"Parameter '{name}' has an invalid value ({value!r}); "
            f"expected a number between {min_val} and {max_val}"
        )
        self.name = name


def get_int_arg(name, default=None, min_val=DEFAULT_MIN, max_val=DEFAULT_MAX):
    raw = request.args.get(name)
    if raw is None or raw == '':
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ParamOutOfRangeError(name, raw, min_val, max_val)
    if value < min_val or value > max_val:
        raise ParamOutOfRangeError(name, value, min_val, max_val)
    return value


def get_float_arg(name, default=None, min_val=DEFAULT_MIN, max_val=DEFAULT_MAX):
    raw = request.args.get(name)
    if raw is None or raw == '':
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise ParamOutOfRangeError(name, raw, min_val, max_val)
    if math.isnan(value) or math.isinf(value):
        raise ParamOutOfRangeError(name, raw, min_val, max_val)
    if value < min_val or value > max_val:
        raise ParamOutOfRangeError(name, value, min_val, max_val)
    return value
