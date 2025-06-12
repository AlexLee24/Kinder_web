from datetime import datetime

MJD_OFFSET = 2400000.5

def convert_mjd_to_date(mjd):
    """Convert Modified Julian Date to common date"""
    jd_calc = mjd + MJD_OFFSET
    a = int(jd_calc + 0.5)
    b = a + 1537
    c = int((b - 122.1) / 365.25)
    d = int(365.25 * c)
    e = int((b - d) / 30.6001)
    
    day = b - d - int(30.6001 * e)
    month = e - 1 if e < 14 else e - 13
    year = c - 4716 if month > 2 else c - 4715
    
    frac = (jd_calc + 0.5) - a
    hours = frac * 24
    hour = int(hours)
    minutes = (hours - hour) * 60
    minute = int(minutes)
    seconds = (minutes - minute) * 60
    
    dt = datetime(year, month, day, hour, minute, int(seconds))
    
    return {
        'mjd': mjd,
        'jd': round(jd_calc, 6),
        'common_date': dt.strftime('%Y-%m-%d %H:%M:%S'),
        'source': 'mjd'
    }

def convert_jd_to_date(jd):
    """Convert Julian Date to common date"""
    mjd_calc = jd - MJD_OFFSET
    return convert_mjd_to_date(mjd_calc)

def convert_common_date_to_jd(common_date):
    """Convert common date to Julian Date"""
    dt = datetime.fromisoformat(common_date.replace('T', ' '))
    
    year = dt.year
    month = dt.month
    day = dt.day
    
    if month <= 2:
        year -= 1
        month += 12
    
    a = int(year / 100)
    b = 2 - a + int(a / 4)
    
    jd_calc = int(365.25 * (year + 4716)) + int(30.6001 * (month + 1)) + day + b - 1524.5
    time_fraction = (dt.hour + dt.minute/60 + dt.second/3600) / 24
    jd_calc += time_fraction
    
    mjd_calc = jd_calc - MJD_OFFSET
    
    return {
        'mjd': round(mjd_calc, 6),
        'jd': round(jd_calc, 6),
        'common_date': dt.strftime('%Y-%m-%d %H:%M:%S'),
        'source': 'common_date'
    }