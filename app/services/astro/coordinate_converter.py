def convert_ra_hms_to_decimal(ra_hms):
    """Convert RA from HMS format to decimal degrees"""
    parts = ra_hms.replace(':', ' ').split()
    if len(parts) != 3:
        raise ValueError('Invalid HMS format. Use hh:mm:ss.ss')
    
    hours = float(parts[0])
    minutes = float(parts[1])
    seconds = float(parts[2])
    
    if not (0 <= hours < 24 and 0 <= minutes < 60 and 0 <= seconds < 60):
        raise ValueError('Invalid time values')
    
    decimal_degrees = (hours + minutes/60 + seconds/3600) * 15
    
    return {
        'ra_hms': ra_hms,
        'ra_decimal': round(decimal_degrees, 6),
        'ra_hours': round(decimal_degrees / 15, 6),
        'source': 'hms'
    }

def convert_ra_decimal_to_hms(ra_decimal):
    """Convert RA from decimal degrees to HMS format"""
    ra_decimal = ra_decimal % 360
    
    hours_total = ra_decimal / 15
    hours = int(hours_total)
    minutes_total = (hours_total - hours) * 60
    minutes = int(minutes_total)
    seconds = (minutes_total - minutes) * 60
    
    ra_hms_calc = f"{hours:02d}:{minutes:02d}:{seconds:05.2f}"
    
    return {
        'ra_hms': ra_hms_calc,
        'ra_decimal': ra_decimal,
        'ra_hours': round(hours_total, 6),
        'source': 'decimal'
    }

def convert_dec_dms_to_decimal(dec_dms):
    """Convert Dec from DMS format to decimal degrees"""
    is_negative = dec_dms.strip().startswith('-')
    clean_dms = dec_dms.replace('-', '').replace('+', '').strip()
    
    parts = clean_dms.replace(':', ' ').split()
    if len(parts) != 3:
        raise ValueError('Invalid DMS format. Use ±dd:mm:ss.ss')
    
    degrees = float(parts[0])
    minutes = float(parts[1])
    seconds = float(parts[2])
    
    if not (0 <= degrees <= 90 and 0 <= minutes < 60 and 0 <= seconds < 60):
        raise ValueError('Invalid angle values')
    
    decimal_degrees = degrees + minutes/60 + seconds/3600
    if is_negative:
        decimal_degrees = -decimal_degrees
    
    return {
        'dec_dms': dec_dms,
        'dec_decimal': round(decimal_degrees, 6),
        'source': 'dms'
    }

def convert_dec_decimal_to_dms(dec_decimal):
    """Convert Dec from decimal degrees to DMS format"""
    if not (-90 <= dec_decimal <= 90):
        raise ValueError('Declination must be between -90 and +90 degrees')
    
    is_negative = dec_decimal < 0
    abs_decimal = abs(dec_decimal)
    
    degrees = int(abs_decimal)
    minutes_total = (abs_decimal - degrees) * 60
    minutes = int(minutes_total)
    seconds = (minutes_total - minutes) * 60
    
    sign = '-' if is_negative else '+'
    dec_dms_calc = f"{sign}{degrees:02d}:{minutes:02d}:{seconds:05.2f}"
    
    return {
        'dec_dms': dec_dms_calc,
        'dec_decimal': dec_decimal,
        'source': 'decimal'
    }