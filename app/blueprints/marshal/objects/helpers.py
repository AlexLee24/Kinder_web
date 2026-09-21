"""Object detail page and per-object data APIs (blueprint name 'marshal_bp') — helpers (split from object_routes.py)."""
import math


# ===============================================================================
# OBJECT DATA API
# ===============================================================================
def sanitize_for_json(data):
    """Convert NaN and Inf values to None for JSON serialization"""
    if isinstance(data, list):
        return [sanitize_for_json(item) for item in data]
    elif isinstance(data, dict):
        return {key: sanitize_for_json(value) for key, value in data.items()}
    elif isinstance(data, float):
        if math.isnan(data) or math.isinf(data):
            return None
        return data
    return data
