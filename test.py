import pytz

# Define a function to convert UTC offset to time zone name
def get_timezone_name(offset):
    # Define a dictionary mapping UTC offset to time zone name
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
        11: 'Pacific/Guam',         # UTC+11
        12: 'Pacific/Fiji',         # UTC+12
        -1: 'Atlantic/Azores',
        -2: 'Atlantic/Cape_Verde',
        -3: 'America/Argentina/Buenos_Aires',
        -4: 'America/New_York',
        -5: 'America/Chicago',
        -6: 'America/Mexico_City',
        -7: 'America/Denver',
        -8: 'America/Los_Angeles',
        -9: 'America/Anchorage',
        -10: 'Pacific/Honolulu',    # UTC-10
        -11: 'Pacific/Midway',      # UTC-11 (Midway Atoll, etc.)
        -12: 'Pacific/Kwajalein'    # UTC-12 (Kwajalein Atoll, etc.)
    }
    
    return timezone_dict.get(offset, 'Unknown')  # Default to 'Unknown' if no match

# Example usage
timezone_offset = -11  # UTC-11
timezone_name = get_timezone_name(timezone_offset)
print(timezone_name)  # Outputs: Pacific/Midway
