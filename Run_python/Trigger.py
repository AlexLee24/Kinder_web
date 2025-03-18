import uuid
import Run_python.new_obsplan as obs
import ephem
import re
import os
from astropy.time import Time, TimeDelta
from astropy.coordinates import EarthLocation
from datetime import datetime, timezone

def exposure_time(mag):
    exposure_times = {
        12: {"up": '60sec*1', "gp": '30sec*1', "rp": '30sec*1', "ip": '30sec*1', "zp": '30sec*1'},
        13: {"up": '60sec*2', "gp": '60sec*1', "rp": '60sec*1', "ip": '60sec*1', "zp": '60sec*1'},
        14: {"up": '60sec*2', "gp": '60sec*1', "rp": '60sec*1', "ip": '60sec*1', "zp": '60sec*1'},
        15: {"up": '150sec*2', "gp": '150sec*1', "rp": '150sec*1', "ip": '150sec*1', "zp": '150sec*1'},
        16: {"up": '150sec*2', "gp": '150sec*1', "rp": '150sec*1', "ip": '150sec*1', "zp": '150sec*1'},
        17: {"up": '300sec*2', "gp": '300sec*1', "rp": '300sec*1', "ip": '300sec*1', "zp": '300sec*1'},
        18: {"up": '300sec*2', "gp": '300sec*1', "rp": '300sec*1', "ip": '300sec*1', "zp": '300sec*1'},
        19: {"up": '300sec*2', "gp": '300sec*1', "rp": '300sec*1', "ip": '300sec*1', "zp": '300sec*1'},
        20: {"rp": '300sec*6'},
        21: {"rp": '300sec*12'},
        22: {"rp": '300sec*36'}
    }
    try:
        mag = int(float(mag))
        if mag > 22:
            return "Too faint to observe"
        if mag < 12:
            return {"up": '60sec*1', "gp": '30sec*1', "rp": '30sec*1', "ip": '30sec*1', "zp": '30sec*1'}
        return exposure_times.get(mag, "Invalid magnitude")
    except:
        mag = str(mag)
        if mag == ">22":
            return "Too faint to observe"
    

def get_yes_or_no(prompt, default="yes"):
    while True:
        user_input = input(f"{prompt} (yes/no) [default: {default}]: ").strip().lower()
        if user_input == "":
            return default == "yes"
        elif user_input in ["yes", "no"]:
            return user_input == "yes"
        else:
            print("Please enter 'yes' or 'no'.")

def lulin_lst():
    Lulin = EarthLocation(lat=23.47, lon=120.87, height=2800)

    now = datetime.now() 
    midnight_local = now.replace(hour=0, minute=0, second=0, microsecond=0)
    midnight_utc = midnight_local.astimezone(timezone.utc)
    midnight_utc_time = Time(midnight_utc)

    lst = midnight_utc_time.sidereal_time('apparent', Lulin.lon)
    
    hours = int(lst.hour)
    minutes = int((lst.hour - hours) * 60)
    seconds = int(((lst.hour - hours) * 60 - minutes) * 60)
    #return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    
    total_seconds = hours * 3600 + minutes * 60 + seconds
    return total_seconds

def convert_to_seconds(ra):
    time_parts = ra.split(':')
    
    hours = int(time_parts[0])
    minutes = int(time_parts[1])
    seconds = float(time_parts[2])
    
    total_seconds = hours * 3600 + minutes * 60 + seconds
    return total_seconds

class Generate:
    def generate_message(name, ra, dec, mag, HPo):
        exposure_times = exposure_time(mag)
        if exposure_times == "Invalid magnitude":
            return "Invalid magnitude entered."
        elif exposure_times == "Too faint to observe":
            return "Too faint to observe."
        else:
            all_filters = ""
            all_exp_times = ""
            for filters, time in exposure_times.items():
                all_filters += f"{filters},"
                all_exp_times += f"{filters}={time},"
            all_filters = all_filters[:-1]
            all_exp_times = all_exp_times[:-1]
        
        if HPo:
            message = f"== SLT === Higher Priority ===\nObject: {name}\nRA: {ra}\nDec: {dec}\nFilter: {all_filters}\nExposure Time: {all_exp_times}\nMag: {mag} mag\n\n"
        else:
            message = f"== SLT ===\nObject: {name}\nRA: {ra}\nDec: {dec}\nFilter: {all_filters}\nExposure Time: {all_exp_times}\nMag: {mag} mag\n\n"
        return message

    def generate_plot(target_list, plot_folder):
        unique_filename = f"observing_tracks_{uuid.uuid4().hex}.jpg"
        ephem_targets = []
        for i in target_list:
            name = i['object_name']
            ra = i['ra']
            dec = i['dec']
            
            ra = re.sub(r"[hH]", ":", ra)
            ra = re.sub(r"[mM]", ":", ra)
            ra = re.sub(r"[sS]", "", ra).strip()

            dec = re.sub(r"[dD°]", ":", dec)
            dec = re.sub(r"[mM′']", ":", dec)
            dec = re.sub(r"[sS″\"]", "", dec).strip()
            
            name = f"{name}\nRA: {ra}\nDEC: {dec}"
            
            ephem_target = obs.create_ephem_target(name, ra, dec)
            ephem_targets.append(ephem_target)
        
        timezone = 'Asia/Taipei'
        obs_site = obs.create_ephem_observer('Lulin Observatory', '120:52:21.5', '23:28:10.0', 2800)
        now = datetime.now()
        date = now.strftime("%Y%m%d")
        
        obs_date = str(int(date))
        next_obs_date = str(int(date) + 1)
        
        obs_date = f"{obs_date[:4]}/{obs_date[4:6]}/{obs_date[6:]}"
        next_obs_date = f"{next_obs_date[:4]}/{next_obs_date[4:6]}/{next_obs_date[6:]}"
        
        obs_start = ephem.Date(f'{obs_date} 17:00:00')
        obs_end = ephem.Date(f'{next_obs_date} 09:00:00')
        
        obs_start_local_dt = obs.dt_naive_to_dt_aware(obs_start.datetime(), timezone)
        obs_end_local_dt = obs.dt_naive_to_dt_aware(obs_end.datetime(), timezone)
        
        plot_path = os.path.join(plot_folder, unique_filename)
        
        obs.plot_night_observing_tracks(
            ephem_targets, obs_site, obs_start_local_dt, obs_end_local_dt, simpletracks=True, toptime='local',
            timezone='calculate', n_steps=1000, savepath=plot_path
        )
        
        return unique_filename
    
    def observe_priority(ra):
        lst = lulin_lst()
        ra = convert_to_seconds(ra)
        time_diff = int(ra-lst)
        #if time_diff < 0:
            #time_diff += 24 * 3600 
        return time_diff
    
if __name__ == "__main__":
    target_list = [{'object_name': 'SN 2024ggi', 'ra': '11h 18m 22.09s', 'dec': '-32d 50m 15.20s'}, {'object_name': 'SN2024rmj', 'ra': '01h 07m 52.76s', 'dec': '+03d 30m 39.8s'}] 
    '''
    HPo = get_yes_or_no("Is this a ToO?", default="no")
    name = input("Please enter the name (NAME): ")
    ra = input("Please enter the right ascension (RA): ")
    dec = input("Please enter the declination (DEC): ")
    mag = input("Please enter the magnitude (MAG): ")
    
    message = Generate.generate_message(name, ra, dec, mag, HPo)
    print(message)
    
    plot_folder = os.getcwd()
    unique_filename = Generate.generate_plot(target_list, plot_folder)
    print(unique_filename)
    '''
    ra_values = [
    '10:00:00',  # 10h 00m 00s
    '23:00:00',  # 23h 00m 00s
    '02:30:00',  # 02h 30m 00s (跨日情況)
    '15:45:30',  # 15h 45m 30s
    ]
    
    for ra in ra_values:
        priority = Generate.observe_priority(ra)
        print(f"RA: {ra}, Time diff in seconds: {priority}")