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
    # Round once to the display precision (0.01 s) and split with carry, so values
    # such as 29.9999958 deg become 02:00:00.00 rather than 01:59:60.00.
    total_cs = int(round(hours_total * 3600 * 100)) % (24 * 3600 * 100)
    total_s, cs = divmod(total_cs, 100)
    hours, rem = divmod(total_s, 3600)
    minutes, secs = divmod(rem, 60)

    ra_hms_calc = f"{hours:02d}:{minutes:02d}:{secs:02d}.{cs:02d}"
    
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
    
    # Round the absolute value once to 0.01 arcsec, then split with carry; the sign is
    # kept separately so -0.x deg still renders as "-00:..".
    total_cs = int(round(abs(dec_decimal) * 3600 * 100))
    is_negative = dec_decimal < 0 and total_cs > 0
    total_s, cs = divmod(total_cs, 100)
    degrees, rem = divmod(total_s, 3600)
    minutes, secs = divmod(rem, 60)

    sign = '-' if is_negative else '+'
    dec_dms_calc = f"{sign}{degrees:02d}:{minutes:02d}:{secs:02d}.{cs:02d}"
    
    return {
        'dec_dms': dec_dms_calc,
        'dec_decimal': dec_decimal,
        'source': 'decimal'
    }