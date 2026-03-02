"""
A Python module for astronomical observation planning.
Original Code is written by Phil Cigan
Link of the original code: https://github.com/pjcigan/obsplanning
"""

import pytz
import ephem
import numpy as np

from datetime import datetime, timedelta

import matplotlib
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
matplotlib.use('Agg')  # Use Agg backend for non-interactive plotting
# matplotlib.rcParams['axes.prop_cycle'] = matplotlib.cycler(color=plt.cm.tab20b(np.linspace(0,1,20)))

from timezonefinder import TimezoneFinder

# -----------------------------------------------------------------------------
# Utility function to wrap an angle (in degrees) into the [-180, 180) range.
# -----------------------------------------------------------------------------
def wrap_pm180(val):
    """
    Wrap the input angle (in degrees) to the range [-180, 180).

    Parameters:
        val (float): Angle in degrees.

    Returns:
        float: Angle wrapped to [-180, 180).
    """
    return ((val + 180) % 360) - 180

# -----------------------------------------------------------------------------
# Extend ephem.Observer to include a timezone attribute.
# -----------------------------------------------------------------------------
class Observer_with_timezone(ephem.Observer):
    """
    A subclass of ephem.Observer that supports storing a timezone attribute.
    """
    def __init__(self):
        super().__init__()
        self.timezone = None  # Timezone string (e.g., 'Asia/Taipei')

# -----------------------------------------------------------------------------
# Automatically determine the local timezone from the observer's coordinates.
# -----------------------------------------------------------------------------
def autocalculate_observer_timezone(observer):
    """
    Determine the local timezone from the observer's longitude and latitude.

    Parameters:
        observer (ephem.Observer): Observer with defined 'lon' and 'lat' attributes.

    Returns:
        str: The timezone name (e.g., 'Asia/Taipei').
    """
    tf = TimezoneFinder()
    # Convert radians to degrees and wrap longitude to [-180, 180)
    lon_deg = wrap_pm180(observer.lon * 180 / np.pi)
    lat_deg = observer.lat * 180 / np.pi
    timezone = tf.timezone_at(lng=lon_deg, lat=lat_deg)
    return timezone

# -----------------------------------------------------------------------------
# Create an ephem.Observer object with timezone information.
# -----------------------------------------------------------------------------
def create_ephem_observer(namestring, longitude, latitude, elevation, decimal_format='deg', timezone=None):
    """
    Create an ephem.Observer instance with location and timezone information.

    Parameters:
        namestring (str): Identifier for the observer (e.g., observatory name).
        longitude (float or str): Longitude value; if 'deg' in decimal_format, assumed in degrees.
        latitude (float or str): Latitude value; if 'deg' in decimal_format, assumed in degrees.
        elevation (float): Elevation (in meters) of the observer.
        decimal_format (str): Format of coordinate input; 'deg' means degrees.
        timezone (str): Timezone string or 'auto'/'calculate' to determine automatically.

    Returns:
        Observer_with_timezone: Observer object with location and timezone.
    """
    # Convert degrees to radians if necessary
    if not isinstance(longitude, str) and 'deg' in decimal_format.lower():
        longitude = float(longitude) * np.pi / 180
    if not isinstance(latitude, str) and 'deg' in decimal_format.lower():
        latitude = float(latitude) * np.pi / 180

    obs_obj = Observer_with_timezone()
    obs_obj.name = namestring
    obs_obj.lon = longitude
    obs_obj.lat = latitude
    obs_obj.elevation = elevation

    # Set timezone: auto-calculate if specified
    if timezone is not None:
        if isinstance(timezone, str) and (timezone.lower() in ['auto', 'calculate']):
            obs_obj.timezone = autocalculate_observer_timezone(obs_obj)
        else:
            obs_obj.timezone = timezone
    return obs_obj

# -----------------------------------------------------------------------------
# Create an ephem.FixedBody target using given RA and DEC.
# -----------------------------------------------------------------------------
def create_ephem_target(namestring, RA, DEC, decimal_format='deg'):
    """
    Create a fixed celestial target using provided Right Ascension (RA) and Declination (DEC).

    Parameters:
        namestring (str): Target name.
        RA (float or str): Right Ascension; if 'deg' in decimal_format, value is in degrees.
        DEC (float or str): Declination; if 'deg' in decimal_format, value is in degrees.
        decimal_format (str): Coordinate format, default 'deg' for degrees.

    Returns:
        ephem.FixedBody: Target object with RA and DEC initialized.
    """
    # Convert RA and DEC from degrees to radians if not provided as strings
    if type(RA) not in [str, np.str_] and 'deg' in decimal_format.lower():
        RA = float(RA) * np.pi / 180
    if type(DEC) not in [str, np.str_] and 'deg' in decimal_format.lower():
        DEC = float(DEC) * np.pi / 180
    
    ephemobj = ephem.FixedBody()  # Create a blank FixedBody object
    ephemobj.name = namestring 
    # Set RA and DEC using ephem.hours and ephem.degrees conversion
    ephemobj._ra = ephem.hours(RA)
    ephemobj._dec = ephem.degrees(DEC)
    ephemobj.compute()  # Initialize computed parameters
    return ephemobj

# -----------------------------------------------------------------------------
# Convert an altitude (in degrees) to its corresponding airmass.
# -----------------------------------------------------------------------------
def alt2airmass(altitude):
    """
    Convert altitude (in degrees) to airmass (approximation as secant of zenith angle).

    Parameters:
        altitude (float): Altitude in degrees.

    Returns:
        float: Computed airmass.
    """
    return 1.0 / np.cos(np.deg2rad(90 - altitude))

# -----------------------------------------------------------------------------
# Generate an array of observation times between a start and end datetime.
# -----------------------------------------------------------------------------
def create_obstime_array(timestart, timeend, timezone_string='UTC', output_as_utc=False, n_steps=100):
    """
    Create an array of datetime objects between timestart and timeend.

    Parameters:
        timestart (str or datetime): Start time ('%Y/%m/%d %H:%M:%S') or datetime.
        timeend (str or datetime): End time ('%Y/%m/%d %H:%M:%S') or datetime.
        timezone_string (str): Timezone to localize input times.
        output_as_utc (bool): If True, output times converted to UTC.
        n_steps (int): Number of time steps.

    Returns:
        list: List of localized datetime objects.
    """
    # Parse times if provided as strings
    if isinstance(timestart, datetime):
        tstart_local = timestart
    else:
        tstart_local = datetime.strptime(timestart, '%Y/%m/%d %H:%M:%S')
    if isinstance(timeend, datetime):
        tend_local = timeend
    else:
        tend_local = datetime.strptime(timeend, '%Y/%m/%d %H:%M:%S')
    tz = pytz.timezone(timezone_string)
    tstart_local = tz.localize(tstart_local)
    tend_local = tz.localize(tend_local)
    delta = (tend_local - tstart_local) / (n_steps - 1)
    times_arr = [tstart_local + i * delta for i in range(n_steps)]
    if output_as_utc:
        times_arr = [t.astimezone(pytz.utc) for t in times_arr]
    return times_arr

# -----------------------------------------------------------------------------
# Compute the Sun's altitude track between two times for a given observer.
# -----------------------------------------------------------------------------
def compute_sun_tracks(observer, obsstart, obsend, nsteps=1000):
    """
    Compute the altitude of the Sun over a series of times.

    Parameters:
        observer (ephem.Observer): Observer object.
        obsstart (ephem.Date): Observation start time.
        obsend (ephem.Date): Observation end time.
        nsteps (int): Number of time steps.

    Returns:
        tuple: (Array of Sun altitudes in degrees, None)
    """
    times = np.linspace(obsstart, obsend, nsteps)
    alts = []
    for t in times:
        observer.date = t
        sun = ephem.Sun()
        sun.compute(observer)
        alts.append(sun.alt)
    return np.array(alts) * 180 / np.pi, None

# -----------------------------------------------------------------------------
# Compute the Moon's altitude track between two times.
# -----------------------------------------------------------------------------
def compute_moon_tracks(observer, obsstart, obsend, nsteps=1000):
    """
    Compute the altitude of the Moon over a series of times.

    Parameters:
        observer (ephem.Observer): Observer object.
        obsstart (ephem.Date): Start time.
        obsend (ephem.Date): End time.
        nsteps (int): Number of sampling steps.

    Returns:
        tuple: (Array of Moon altitudes in degrees, None)
    """
    times = np.linspace(obsstart, obsend, nsteps)
    alts = []
    for t in times:
        observer.date = t
        moon = ephem.Moon()
        moon.compute(observer)
        alts.append(moon.alt)
    return np.array(alts) * 180 / np.pi, None

# -----------------------------------------------------------------------------
# Compute the Moon's phase at a given time.
# -----------------------------------------------------------------------------
def compute_moonphase(obstime, return_fmt='percent'):
    """
    Compute the Moon phase at a specified time.

    Parameters:
        obstime (ephem.Date): Observation time.
        return_fmt (str): Format to return ('percent' returns percentage).

    Returns:
        float: Moon phase as a percentage or fraction.
    """
    moon = ephem.Moon()
    moon.compute(obstime)
    phase = moon.moon_phase
    if return_fmt.lower() in ['percent', 'perc']:
        return phase * 100
    else:
        return phase

# -----------------------------------------------------------------------------
# Calculate moonrise and moonset times for a given date.
# -----------------------------------------------------------------------------
def calculate_moon_times(observer, startdate, outtype='dt'):
    """
    Calculate moonrise and moonset times based on the observer's location.

    Parameters:
        observer (ephem.Observer): Observer object.
        startdate (ephem.Date or str): Date from which to calculate.
        outtype (str): Output format ('dt' for datetime objects).

    Returns:
        list: [moonrise, moonset] in specified format.
    """
    observer.date = ephem.Date(startdate)
    moonrise = observer.previous_rising(ephem.Moon(), use_center=True)
    # If the computed moonrise is earlier than the current date, use next rising
    if moonrise < observer.date:
        moonrise = observer.next_rising(ephem.Moon(), use_center=True)
    observer.date = moonrise
    moonset = observer.next_setting(ephem.Moon(), use_center=True)
    if outtype == 'dt':
        return [moonrise.datetime(), moonset.datetime()]
    else:
        return [moonrise, moonset]

# -----------------------------------------------------------------------------
# Convert an ephem.Date to a timezone-aware UTC datetime object.
# -----------------------------------------------------------------------------
def convert_ephem_datetime(ephem_date_in):
    """
    Convert an ephem.Date to a timezone-aware datetime (UTC).

    Parameters:
        ephem_date_in (ephem.Date): Input ephem date.

    Returns:
        datetime: Timezone-aware datetime in UTC.
    """
    tmp_dt = ephem_date_in.datetime()
    obstime_dt = datetime(tmp_dt.year, tmp_dt.month, tmp_dt.day,
                          tmp_dt.hour, tmp_dt.minute, tmp_dt.second,
                          tmp_dt.microsecond, tzinfo=pytz.timezone('UTC'))
    return obstime_dt

# -----------------------------------------------------------------------------
# Fill twilight regions on a matplotlib axis based on computed twilight times.
# -----------------------------------------------------------------------------
def fill_twilights(axin, obsframe, startdate, offsetdatetime=0., timetype='offset', bgcolor='k'):
    """
    Fill different twilight phases on a plot using computed twilight times.

    Parameters:
        axin (matplotlib.axes.Axes): Axis on which to fill regions.
        obsframe (ephem.Observer): Observer for twilight time calculations.
        startdate (ephem.Date): Reference date.
        offsetdatetime (float): Time offset for conversion.
        timetype (str): 'offset' or 'abs' determines time handling.
        bgcolor (str): Background color for twilight fills.
    """
    sunset, t_civil, t_naut, t_astro = calculate_twilight_times(obsframe, startdate)
    if timetype == 'abs':
        s_m = [convert_ephem_datetime(ephem.Date(sunset[0])), convert_ephem_datetime(ephem.Date(sunset[1]))]
        tc_m = [convert_ephem_datetime(ephem.Date(t_civil[0])), convert_ephem_datetime(ephem.Date(t_civil[1]))]
        tn_m = [convert_ephem_datetime(ephem.Date(t_naut[0])), convert_ephem_datetime(ephem.Date(t_naut[1]))]
        ta_m = [convert_ephem_datetime(ephem.Date(t_astro[0])), convert_ephem_datetime(ephem.Date(t_astro[1]))]
    else:
        s_m = (sunset - offsetdatetime) / ephem.hour
        tc_m = (t_civil - offsetdatetime) / ephem.hour
        tn_m = (t_naut - offsetdatetime) / ephem.hour
        ta_m = (t_astro - offsetdatetime) / ephem.hour
    axin.axvspan(*s_m, color=bgcolor, alpha=0.1, zorder=-10, ec=None)
    axin.axvspan(*tc_m, color=bgcolor, alpha=0.3, zorder=-9, ec=None)
    axin.axvspan(*tn_m, color=bgcolor, alpha=0.5, zorder=-8, ec=None)
    axin.axvspan(*ta_m, color=bgcolor, alpha=0.7, zorder=-7, ec=None)
    # Annotate key twilight times if using absolute time format
    if timetype == 'abs':
        axin.text(convert_ephem_datetime(ephem.Date(sunset[0]-7./60./24)), 80.5,
                  'Sunset %s' % (s_m[0].time().strftime('%H:%M')), color='k', fontsize=6,
                  rotation=90, va='bottom')
        axin.text(convert_ephem_datetime(ephem.Date(t_astro[0]-7./60./24)), 80.5,
                  'Ast.Twi. %s' % (ta_m[0].time().strftime('%H:%M')), color='w', fontsize=6,
                  rotation=90, va='bottom')
        axin.text(convert_ephem_datetime(ephem.Date(t_astro[1]-7./60./24)), 80.5,
                  'Ast.Twi. %s' % (ta_m[1].time().strftime('%H:%M')), color='w', fontsize=6,
                  rotation=90, va='bottom')
        axin.text(convert_ephem_datetime(ephem.Date(sunset[1]-7./60./24)), 80.5,
                  'Sunrise %s' % (s_m[1].time().strftime('%H:%M')), color='k', fontsize=6,
                  rotation=90, va='bottom')

# -----------------------------------------------------------------------------
# Fill twilight regions with a light color for improved visual clarity.
# -----------------------------------------------------------------------------
def fill_twilights_light(axin, obsframe, startdate, plottimerange, offsetdatetime=0., bgcolor='#95D0FC', timetype='offset'):
    """
    Similar to fill_twilights(), but uses a lighter color scheme to fill twilight regions.

    Parameters:
        axin (matplotlib.axes.Axes): Axis on which to fill regions.
        obsframe (ephem.Observer): Observer for twilight calculations.
        startdate (ephem.Date): Reference date.
        plottimerange (list/array): Time range for the plot.
        offsetdatetime (float): Time offset for conversion.
        bgcolor (str): Background color for the fill.
        timetype (str): 'offset' or 'abs' determines how time is handled.
    """
    midtime = (ephem.Date(plottimerange[0]) + ephem.Date(plottimerange[-1])) / 2.
    sunset, t_civil, t_naut, t_astro = calculate_twilight_times(obsframe, midtime)
    if timetype == 'abs':
        s_m = [convert_ephem_datetime(ephem.Date(sunset[0])), convert_ephem_datetime(ephem.Date(sunset[1]))]
        tc_m = [convert_ephem_datetime(ephem.Date(t_civil[0])), convert_ephem_datetime(ephem.Date(t_civil[1]))]
        tn_m = [convert_ephem_datetime(ephem.Date(t_naut[0])), convert_ephem_datetime(ephem.Date(t_naut[1]))]
        ta_m = [convert_ephem_datetime(ephem.Date(t_astro[0])), convert_ephem_datetime(ephem.Date(t_astro[1]))]
    else:
        s_m = (sunset - offsetdatetime) / ephem.hour
        tc_m = (t_civil - offsetdatetime) / ephem.hour
        tn_m = (t_naut - offsetdatetime) / ephem.hour
        ta_m = (t_astro - offsetdatetime) / ephem.hour
    axin.axvspan(plottimerange[0], s_m[0], color=bgcolor, zorder=-10, alpha=1.0, ec=None)
    axin.axvspan(s_m[0], tc_m[0], color=bgcolor, zorder=-10, alpha=0.7, ec=None)
    axin.axvspan(tc_m[0], tn_m[0], color=bgcolor, zorder=-10, alpha=0.5, ec=None)
    axin.axvspan(tn_m[0], ta_m[0], color=bgcolor, zorder=-10, alpha=0.2, ec=None)
    axin.axvspan(ta_m[1], tn_m[1], color=bgcolor, zorder=-10, alpha=0.2, ec=None)
    axin.axvspan(tn_m[1], tc_m[1], color=bgcolor, zorder=-10, alpha=0.5, ec=None)
    axin.axvspan(tc_m[1], s_m[1], color=bgcolor, zorder=-10, alpha=0.7, ec=None)
    axin.axvspan(s_m[1], plottimerange[-1], color=bgcolor, zorder=-10, alpha=1.0, ec=None)
    if timetype == 'abs':
        if ephem.Date(s_m[0]) > ephem.Date(plottimerange[0]):
            axin.text(convert_ephem_datetime(ephem.Date(sunset[0]-7./60./24)), 80.5,
                      'Sunset %s' % (s_m[0].time().strftime('%H:%M')), color='k', fontsize=6,
                      rotation=90, va='bottom')
        if ephem.Date(t_astro[0]) > ephem.Date(plottimerange[0]):
            axin.text(convert_ephem_datetime(ephem.Date(t_astro[0]-7./60./24)), 80.5,
                      'Ast.Twi. %s' % (ta_m[0].time().strftime('%H:%M')), color='k', fontsize=6,
                      rotation=90, va='bottom')
        if ephem.Date(t_astro[1]) < ephem.Date(plottimerange[-1]):
            axin.text(convert_ephem_datetime(ephem.Date(t_astro[1]-7./60./24)), 80.5,
                      'Ast.Twi. %s' % (ta_m[1].time().strftime('%H:%M')), color='k', fontsize=6,
                      rotation=90, va='bottom')
        if ephem.Date(s_m[1]) < ephem.Date(plottimerange[-1]):
            axin.text(convert_ephem_datetime(ephem.Date(sunset[1]-7./60./24)), 80.5,
                      'Sunrise %s' % (s_m[1].time().strftime('%H:%M')), color='k', fontsize=6,
                      rotation=90, va='bottom')

# -----------------------------------------------------------------------------
# Compute the altitude and azimuth tracks for a target between two times.
# -----------------------------------------------------------------------------
def compute_target_altaz(target, observer, t1, t2, nsteps=1000):
    """
    Calculate the altitude and azimuth of a target over a time range.

    Parameters:
        target (ephem.FixedBody): Celestial target.
        observer (ephem.Observer): Observer with location and time.
        t1 (str or ephem.Date): Start time.
        t2 (str or ephem.Date): End time.
        nsteps (int): Number of steps for calculation.

    Returns:
        tuple: (Array of altitudes in degrees, Array of azimuths in degrees)
    """
    if isinstance(t1, str):
        t1 = ephem.Date(t1)
    if isinstance(t2, str):
        t2 = ephem.Date(t2)
    tmp_obs = observer.copy()
    tmp_tar = target.copy()
    alt_list = []
    az_list = []
    times = np.linspace(t1, t2, nsteps)
    for t in times:
        tmp_obs.date = t
        tmp_tar.compute(tmp_obs)
        alt_list.append(tmp_tar.alt)
        az_list.append(tmp_tar.az)
    alt_arr = np.array(alt_list) * 180 / np.pi
    az_arr = np.array(az_list) * 180 / np.pi
    return alt_arr, az_arr

# -----------------------------------------------------------------------------
# Calculate the transit time for a single target (when it crosses the local meridian).
# -----------------------------------------------------------------------------
def calculate_transit_time_single(target, observer, approximate_time, mode='nearest', return_fmt='str'):
    """
    Calculate the transit time (target's highest altitude) for a given target.

    Parameters:
        target (ephem.FixedBody): Celestial target.
        observer (ephem.Observer): Observer object.
        approximate_time (ephem.Date or str): Reference time near expected transit.
        mode (str): 'prev', 'next', or 'nearest' determines transit selection.
        return_fmt (str): Format of output ('str' returns formatted string, 'dt' for datetime).

    Returns:
        str/datetime/ephem.Date: Transit time in specified format, or empty string if target never rises.
    """
    tmp_obs = observer.copy()
    tmp_obs.date = ephem.Date(approximate_time)
    tmp_tar = target.copy()
    tmp_tar.compute(tmp_obs)
    
    if tmp_tar.neverup:
        return ""
    
    transits = np.array([tmp_obs.previous_transit(tmp_tar), tmp_obs.next_transit(tmp_tar)])
    if 'prev' in mode.lower():
        t_transit = ephem.Date(transits[0])
    elif 'next' in mode.lower():
        t_transit = ephem.Date(transits[1])
    elif 'near' in mode.lower():
        diff = np.abs(transits - ephem.Date(approximate_time))
        t_transit = ephem.Date(transits[np.argmin(diff)])
    
    if t_transit < ephem.Date("2000/01/01 00:00:00"):
         return ""
    
    if 'dt' in return_fmt.lower():
        return t_transit.datetime()
    elif 'str' in return_fmt.lower():
        return t_transit.datetime().strftime('%Y/%m/%d %H:%M:%S')
    else:
        return t_transit

# -----------------------------------------------------------------------------
# Compute the angular separation between the Moon and a target at a given time.
# -----------------------------------------------------------------------------
def moonsep_single(target, observer, obstime):
    """
    Calculate the angular separation (in degrees) between the Moon and the target.

    Parameters:
        target (ephem.FixedBody): Celestial target.
        observer (ephem.Observer): Observer object.
        obstime (ephem.Date or datetime): Time of observation.

    Returns:
        float: Separation in degrees.
    """
    tmp_obs = observer.copy()
    tmp_obs.date = ephem.Date(obstime)
    tmp_tar = target.copy()
    tmp_tar.compute(tmp_obs)
    moon = ephem.Moon()
    moon.compute(tmp_obs)
    return ephem.separation(moon, tmp_tar) * 180 / np.pi

# -----------------------------------------------------------------------------
# Compute the angular separation between the Sun and a target at a given time.
# -----------------------------------------------------------------------------
def sunsep_single(target, observer, obstime):
    """
    Calculate the angular separation (in degrees) between the Sun and the target.

    Parameters:
        target (ephem.FixedBody): Celestial target.
        observer (ephem.Observer): Observer object.
        obstime (ephem.Date or datetime): Time of observation.

    Returns:
        float: Separation in degrees.
    """
    tmp_obs = observer.copy()
    tmp_obs.date = ephem.Date(obstime)
    tmp_tar = target.copy()
    tmp_tar.compute(tmp_obs)
    sun = ephem.Sun()
    sun.compute(tmp_obs)
    return ephem.separation(sun, tmp_tar) * 180 / np.pi

# -----------------------------------------------------------------------------
# Calculate the mean transit time for a list of targets.
# -----------------------------------------------------------------------------
def calculate_targets_mean_transit_time(target_list, observer, approximate_time, weights=None):
    """
    Calculate the (optionally weighted) mean transit time for multiple targets.

    Parameters:
        target_list (list): List of ephem.FixedBody objects.
        observer (ephem.Observer): Observer object.
        approximate_time (ephem.Date or str): Reference time.
        weights (array-like, optional): Weights for averaging transit times.

    Returns:
        str: Mean transit time as a formatted string.
    """
    tmp_obs = observer.copy()
    tmp_obs.date = ephem.Date(approximate_time)
    transit_times = []
    for target in target_list:
        tmp_tar = target.copy()
        tmp_tar.compute(tmp_obs)
        transit_time = calculate_transit_time_single(tmp_tar, tmp_obs, approximate_time, mode='nearest', return_fmt='ephem')
        transit_times.append(transit_time)
    transit_times = np.array(transit_times, dtype=float)
    if weights is not None:
        mean_transit = np.average(transit_times[~np.isnan(transit_times)], weights=weights)
    else:
        mean_transit = np.nanmean(transit_times)
    return ephem.Date(mean_transit).datetime().strftime('%Y/%m/%d %H:%M:%S')

# -----------------------------------------------------------------------------
# Convert a naive datetime object to a timezone-aware datetime using a local timezone.
# -----------------------------------------------------------------------------
def dt_naive_to_dt_aware(datetime_naive, local_timezone):
    """
    Convert a naive datetime to a timezone-aware datetime.

    Parameters:
        datetime_naive (datetime): Naive datetime (without timezone).
        local_timezone (str or pytz.timezone): Local timezone.

    Returns:
        datetime: Timezone-aware datetime.
    """
    if isinstance(local_timezone, str):
        local_timezone = pytz.timezone(local_timezone)
    return local_timezone.localize(datetime_naive)

# -----------------------------------------------------------------------------
# Retrieve the observer's timezone; auto-calculate if not set.
# -----------------------------------------------------------------------------
def tz_from_observer(observer):
    """
    Get the timezone from the observer, calculating it automatically if necessary.

    Parameters:
        observer (Observer_with_timezone): Observer object.

    Returns:
        str: Timezone string.
    """
    if observer.timezone is not None:
        return observer.timezone
    else:
        return autocalculate_observer_timezone(observer)

# -----------------------------------------------------------------------------
# Calculate the UTC offset (in hours) for a naive datetime given a local timezone.
# -----------------------------------------------------------------------------
def calculate_dtnaive_utcoffset(datetime_naive, local_timezone):
    """
    Compute the UTC offset in hours for a naive datetime.

    Parameters:
        datetime_naive (datetime): Naive datetime.
        local_timezone (str or pytz.timezone): Local timezone.

    Returns:
        float: UTC offset in hours.
    """
    dt_aware = dt_naive_to_dt_aware(datetime_naive, local_timezone)
    return dt_aware.utcoffset().total_seconds() / 3600.0

# -----------------------------------------------------------------------------
# Compute the local sidereal time for an observer at a given time.
# -----------------------------------------------------------------------------
def compute_sidereal_time(observer, t1, as_type='datetime'):
    """
    Compute the sidereal time for a given time.

    Parameters:
        observer (ephem.Observer): Observer object.
        t1 (ephem.Date or datetime): Time for which to compute sidereal time.
        as_type (str): Output type; 'datetime' returns a datetime object.

    Returns:
        datetime or ephem.Angle: Sidereal time.
    """
    tmp_obs = observer.copy()
    t1 = ephem.Date(t1)
    tmp_obs.date = t1
    LST_rad = tmp_obs.sidereal_time()
    if as_type == 'datetime':
        LST_str = str(LST_rad)
        return datetime.strptime(LST_str, '%H:%M:%S.%f')
    else:
        return LST_rad

# -----------------------------------------------------------------------------
# Convert local time to Local Mean Sidereal Time (LMST) using the observer's longitude.
# -----------------------------------------------------------------------------
def LST_from_local(dt_local, observer_lon_deg):
    """
    Convert a local datetime to Local Mean Sidereal Time (LMST).

    Parameters:
        dt_local (datetime): Local datetime.
        observer_lon_deg (float): Observer's longitude in degrees.

    Returns:
        list: [hour, minute] of LMST.
    """
    gmst = compute_sidereal_time(None, dt_local, as_type='datetime')
    return [gmst.hour, gmst.minute]

# -----------------------------------------------------------------------------
# Calculate twilight times (sunset, civil, nautical, astronomical) for a given date.
# -----------------------------------------------------------------------------
def calculate_twilight_times(obsframe, startdate, verbose=False):
    """
    Calculate different twilight phases for a given date based on the observer's location.

    Parameters:
        obsframe (ephem.Observer): Observer object.
        startdate (ephem.Date): Date for twilight calculation.
        verbose (bool): If True, print sunset and sunrise times.

    Returns:
        tuple: Arrays of [sunset, civil twilight, nautical twilight, astronomical twilight] times.
    """
    tmp_obs = obsframe.copy()
    tmp_obs.date = startdate
    sunset = [tmp_obs.previous_setting(ephem.Sun(), use_center=True),
              tmp_obs.next_rising(ephem.Sun(), use_center=True)]
    tmp_obs.horizon = '-6'
    t_civil = [tmp_obs.previous_setting(ephem.Sun(), use_center=True),
               tmp_obs.next_rising(ephem.Sun(), use_center=True)]
    tmp_obs.horizon = '-12'
    t_naut = [tmp_obs.previous_setting(ephem.Sun(), use_center=True),
              tmp_obs.next_rising(ephem.Sun(), use_center=True)]
    tmp_obs.horizon = '-18'
    t_astro = [tmp_obs.previous_setting(ephem.Sun(), use_center=True),
               tmp_obs.next_rising(ephem.Sun(), use_center=True)]
    if verbose:
        print('Sunset: %s, Sunrise: %s' % (sunset[0], sunset[1]))
    return np.array(sunset), np.array(t_civil), np.array(t_naut), np.array(t_astro)

# -----------------------------------------------------------------------------
# Plot the observing tracks for targets along with sun/moon tracks and twilight regions.
# -----------------------------------------------------------------------------
def plot_observing_tracks(target_list, observer, obsstart, obsend, weights=None, mode='nearest', plotmeantransit=False, toptime='local', timezone='auto', n_steps=1000, simpletracks=False, azcmap='rainbow', light_fill=False, bgcolor='k', xaxisformatter=mdates.DateFormatter('%H:%M'), figsize=(14,8), dpi=200, savepath='', showplot=False):
    """
    Plot altitude tracks for one or more targets over a night, including:
      - Target altitude tracks (optionally colored by azimuth)
      - Sun and Moon altitude tracks
      - Twilight regions with annotations
      - Transit time markers and mean transit time (if desired)

    Parameters:
        target_list (list or single target): List of ephem.FixedBody targets.
        observer (ephem.Observer): Observer object.
        obsstart (ephem.Date): Observation start time.
        obsend (ephem.Date): Observation end time.
        weights (array-like, optional): Weights for mean transit time calculation.
        mode (str): Mode for transit time ('prev', 'next', or 'nearest').
        plotmeantransit (bool): If True, plot the mean transit time.
        toptime (str): X-axis time type ('local' or 'LMST').
        timezone (str): Timezone ('auto', 'calculate', or specific timezone).
        n_steps (int): Number of time steps.
        simpletracks (bool): If True, plot simple line tracks; otherwise use scatter.
        azcmap (str): Colormap for azimuth.
        light_fill (bool): If True, use light color fill for twilight.
        bgcolor (str): Background color for twilight fills.
        xaxisformatter (mdates.DateFormatter): Formatter for the x-axis.
        figsize (tuple): Figure size.
        dpi (int): Dots per inch for saved figure.
        savepath (str): Path to save the figure.
        showplot (bool): If True, display the plot interactively.

    Returns:
        None
    """
    obsstart = ephem.Date(obsstart)
    obsend = ephem.Date(obsend)
    if obsend < obsstart:
        raise Exception('plot_observing_tracks(): obsend is earlier than obsstart!')
    if np.ndim(target_list) == 0:
        target_list = [target_list]
    
    fig1 = plt.figure(1, figsize=figsize)
    axin = fig1.add_subplot(111)
    
    # Generate an array of UTC times for plotting
    times_utc = create_obstime_array(obsstart.datetime().strftime('%Y/%m/%d %H:%M:%S'),
                                     obsend.datetime().strftime('%Y/%m/%d %H:%M:%S'),
                                     timezone_string='UTC', n_steps=n_steps)
    meanobstime = np.mean([obsstart, obsend])
    obsday = obsstart.datetime().strftime('%Y/%m/%d')[:10]
    
    # Compute sun and moon altitude tracks and moon phase/time
    sun_alts, _ = compute_sun_tracks(observer, obsstart, obsend, nsteps=n_steps)
    moon_alts, _ = compute_moon_tracks(observer, obsstart, obsend, nsteps=n_steps)
    moonphase_perc = compute_moonphase(obsstart, return_fmt='percent')
    moontimes = calculate_moon_times(observer, obsstart, outtype='dt')
    
    # Fill twilight regions on the plot
    if light_fill == True:
        fill_twilights_light(axin, observer, meanobstime, times_utc, bgcolor='#FEFFCA', timetype='abs')
    elif light_fill == False:
        fill_twilights(axin, observer, meanobstime, timetype='abs', bgcolor=bgcolor)
    
    transit_times = np.zeros(len(target_list), dtype=str)
    for target, i in zip(target_list, range(len(target_list))):
        # Compute target altitude and azimuth over the observation period
        alts, azs = compute_target_altaz(target, observer, obsstart, obsend, nsteps=n_steps)
        # Calculate the transit time (when target is highest)
        transit_time_str = calculate_transit_time_single(target, observer, meanobstime, return_fmt='str', mode=mode)
        transit_times[i] = transit_time_str

        '''if transit_time_str:
            try:
                transit_dt = datetime.strptime(transit_time_str, '%Y/%m/%d %H:%M:%S')
                # Draw a vertical line at the transit time
                axin.axvline(transit_dt, ls=':', color='0.5', zorder=-1)
                # Annotate the transit time on the plot
                axin.annotate(f"Transit time of {target.name} =  {transit_time_str[-8:]} (UTC)",
                              xy=[transit_dt, 50.],
                              xytext=[transit_dt + timedelta(minutes=-25), 50.],
                              va='center', rotation=90, color='0.5')
            except Exception as e:
                print(f"{target.name}, {transit_time_str}, Error：{e}")'''

        label_str = f"{target.name} (RA: {target._ra}, DEC: {target._dec})"
        if simpletracks == True:
            axin.plot(times_utc, alts, lw=1.5, label=label_str, zorder=5)
        else:
            colortrack = axin.scatter(times_utc, alts, c=azs, label=label_str,
                                      lw=0, s=10, cmap=azcmap, zorder=5)

    if simpletracks == False:
        fig1.colorbar(colortrack, ax=axin, pad=0.12).set_label('Azimuth [deg]')
    
    # Plot moon and sun tracks
    axin.plot(times_utc, moon_alts, color='0.6', lw=0.8, ls='--', alpha=0.7, zorder=1)
    axin.plot(times_utc, sun_alts, color='r', lw=0.8, ls='--', alpha=0.5, zorder=1)
    
    # Set legend position based on number of targets
    if len(target_list) > 5:
        axin.legend(loc='center left', bbox_to_anchor=(1.075, 0.5), borderaxespad=0.)
    else:
        axin.legend(loc='upper left')
    
    plt.subplots_adjust(right=0.75)
    
    axin.set_ylim(0, 90)
    axin.xaxis.set_major_formatter(xaxisformatter)
    axin.xaxis.set_minor_locator(mdates.HourLocator())
    axin.set_xlabel(f"UTC Time, for Local Starting Night {obsday}")
    plt.ylabel("Altitude [deg]")
    plt.grid(True, color='0.92')
    
    # Optionally plot mean transit time
    if plotmeantransit == True:
        meantransit = calculate_targets_mean_transit_time(target_list, observer, meanobstime, weights=weights)
        try:
            meantransit_dt = datetime.strptime(meantransit, '%Y/%m/%d %H:%M:%S')
            axin.axvline(meantransit_dt, ls='--', color='0.5', zorder=-1)
            axin.annotate(f"{'' if weights is None else 'Weighted '}Mean of target transit times =  {meantransit[-8:]} (UTC)",
                          xy=[meantransit_dt, 85.],
                          xytext=[meantransit_dt + timedelta(minutes=-25), 85.],
                          va='top', rotation=90, color='0.5')
        except Exception as e:
            print(f"{meantransit}, Error：{e}")
    
    axin.set_xlim(times_utc[0], times_utc[-1])
    
    # Create a secondary y-axis for airmass values
    axin2 = axin.twinx()
    axin2.set_ylim(axin.get_ylim())
    axin2.set_yticks([10, 30, 50, 70, 90])
    axin2.set_yticklabels(np.round(alt2airmass(np.array([10, 30, 50, 70, 90])), decimals=2))
    axin2.set_ylabel("Airmass [sec(z)]", rotation=-90, va='bottom')
    
    # Create a twin x-axis for local time or LMST display
    axin3 = axin.twiny()
    if 'loc' in toptime.lower():
        timezone = tz_from_observer(observer)
        utcoffset = calculate_dtnaive_utcoffset(ephem.Date(meanobstime).datetime(), local_timezone=timezone)
        times_local = np.zeros_like(times_utc)
        for i in range(len(times_utc)):
            times_local[i] = times_utc[i].astimezone(pytz.timezone(timezone))
        axin3.set_xlim(times_local[0], times_local[-1], auto=True)
        axin3.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M', tz=times_local[0].tzinfo))
        axin3.xaxis.set_minor_locator(mdates.HourLocator(tz=times_local[0].tzinfo))
        axin3.set_xlabel("Local Time →", x=-0.08, va='top')
        axin3.text(-0.04, 0.95, f"({times_local[0].tzinfo.zone})\nUTC offset = {utcoffset}",
                   va='bottom', ha='right', transform=axin3.transAxes, color='k', fontsize=8)
    elif toptime.upper() == 'LMST':
        axin3.set_xlim(times_utc[0], times_utc[-1])
        axin3.xaxis.set_major_formatter(xaxisformatter)
        fig1.canvas.draw()
        utctime0 = compute_sidereal_time(observer, times_utc[0], as_type='datetime')
        utc_ticks = axin3.get_xticklabels()
        xtl = []
        for t in utc_ticks:
            t_utc = datetime.strptime(obsday + " " + t.get_text(), '%Y/%m/%d %H:%M').replace(tzinfo=pytz.utc)
            if t_utc.time() < utctime0.time():
                t_utc = t_utc.replace(day=t_utc.day + 1)
            t_lst = LST_from_local(t_utc, observer.lon * 180 / np.pi)
            xtl.append(f"{t_lst[0]}:{t_lst[1]}")
        axin3.xaxis.set_ticklabels(xtl)
        axin3.set_xlabel("LMST →", x=-0.05, va='top')
    axin3.text(-0.05, 0.8, f"Moonrise {moontimes[0].strftime('%H:%M')}\nMoonset {moontimes[1].strftime('%H:%M')}\n Moon phase = {moonphase_perc:.1f}%",
               va='bottom', ha='right', transform=axin.transAxes, color='k', fontsize=10)
    
    plt.savefig(savepath, bbox_inches='tight', dpi=dpi)
    if showplot:
        plt.show()
    plt.clf()
    plt.close('all')

# -----------------------------------------------------------------------------
# Wrapper function to plot night observing tracks with light_fill disabled.
# -----------------------------------------------------------------------------
def plot_night_observing_tracks(target_list, observer, obsstart, obsend, weights=None, mode='nearest', plotmeantransit=False, toptime='local', timezone='auto', n_steps=1000, simpletracks=False, azcmap='rainbow', bgcolor='k', xaxisformatter=mdates.DateFormatter('%H:%M'), figsize=(14,8), dpi=200, savepath='', showplot=False):
    """
    Wrapper for plot_observing_tracks with light_fill set to False.

    Parameters:
        (Same as plot_observing_tracks)
    """
    plot_observing_tracks(target_list, observer, obsstart, obsend, weights=weights, mode=mode,
                          plotmeantransit=plotmeantransit, toptime=toptime, timezone=timezone,
                          n_steps=n_steps, simpletracks=simpletracks, azcmap=azcmap,
                          light_fill=False, bgcolor=bgcolor, xaxisformatter=xaxisformatter,
                          figsize=figsize, dpi=dpi, savepath=savepath, showplot=showplot)

# -----------------------------------------------------------------------------

def get_timezone_name(offset):
        timezone_dict = {
            0: 'UTC',
            1: 'Europe/Paris',
            2: 'Europe/Amsterdam',
            3: 'Europe/Moscow',
            4: 'Asia/Dubai',
            5: 'Asia/Karachi',
            6: 'Asia/Kolkata',
            7: 'Asia/Kuala_Lumpur',
            8: 'Asia/Taipei',
            9: 'Asia/Tokyo',
            10: 'Australia/Sydney',
            11: 'Pacific/Guam',         
            12: 'Pacific/Fiji',        
            -1: 'Atlantic/Azores',
            -2: 'Atlantic/Cape_Verde',
            -3: 'America/Argentina/Buenos_Aires',
            -4: 'America/New_York',
            -5: 'America/Chicago',
            -6: 'America/Mexico_City',
            -7: 'America/Denver',
            -8: 'America/Los_Angeles',
            -9: 'America/Anchorage',
            -10: 'Pacific/Honolulu',  
            -11: 'Pacific/Midway',      
            -12: 'Pacific/Kwajalein'  
        }
        return timezone_dict.get(offset)