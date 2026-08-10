import os
import json
from datetime import datetime, timedelta

# Obsplan
# import obsplanning as obs
import obsplan as obs
import ephem
import matplotlib

matplotlib.use('Agg')


# ========================= Function ========================================

# read json file
def read_json(file):
    with open(file, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data


# Exposure time
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
            return "Too faint to observe, please use LOT for follow-up observation"
        if mag < 12:
            return {"up": '60sec*1', "gp": '30sec*1', "rp": '30sec*1', "ip": '30sec*1', "zp": '30sec*1'}
        return exposure_times.get(mag, "Invalid magnitude")
    except:
        mag = str(mag)
        if mag == ">22":
            return "Too faint to observe, please use LOT for follow-up observation"
        return "Invalid magnitude"


# Check Filter SLT
def check_filter(filter):
    if filter == "up":
        return "up_Astrodon_2018"
    elif filter == "gp":
        return "gp_Astrodon_2018"
    elif filter == "rp":
        return "rp_Astrodon_2018"
    elif filter == "ip":
        return "ip_Astrodon_2018"
    elif filter == "zp":
        return "zp_Astrodon_2018"


# Check Filter LOT
def check_filter_LOT(filter):
    if filter == "up":
        return "up_Astrodon_2017"
    elif filter == "gp":
        return "gp_Astrodon_2019"
    elif filter == "rp":
        return "rp_Astrodon_2019"
    elif filter == "ip":
        return "ip_Astrodon_2019"
    elif filter == "zp":
        return "zp_Astrodon_2019"


# Generate Trigger Script
def generate_script(name, ra, dec, mag, priority, priority_message, is_lot="False", Repeat=0, auto_exp=True,
                    filter_input=None, exp_time=None, count=None):
    telescope = "LOT" if is_lot == "True" else "SLT"
    priority_message = priority_message or ""
    print(f"Telescope: {telescope}")
    if auto_exp:
        exposure_times = exposure_time(mag)
        if exposure_times == "Invalid magnitude":
            return f";= {name}: invalid magnitude entered ({mag}) =\n\n"
        elif exposure_times == "Too faint to observe":
            return f";= {name}: too faint to observe (mag {mag}) =\n\n"
        else:
            all_bins = ""
            all_filters = ""
            all_exp_times = ""
            all_count = ""
            for filter_name, time in exposure_times.items():
                if telescope == "LOT":
                    full_filter_name = check_filter_LOT(filter_name)
                elif telescope == "SLT":
                    full_filter_name = check_filter(filter_name)
                part = time.split("sec*")
                time_val = part[0]
                count_val = part[1]
                all_bins += "1, "
                all_filters += f"{full_filter_name}, "
                all_exp_times += f"{time_val}, "
                all_count += f"{count_val}, "
            all_bins = all_bins[:-2]
            all_filters = all_filters[:-2]
            all_exp_times = all_exp_times[:-2]
            all_count = all_count[:-2]
    else:
        try:
            filter_list = [f.strip() for f in filter_input.split(",")]
            exp_time_list = [e.strip() for e in exp_time.split(",")]
            count_list = [c.strip() for c in count.split(",")]

            min_length = min(len(filter_list), len(exp_time_list), len(count_list))
            filter_list = filter_list[:min_length]
            exp_time_list = exp_time_list[:min_length]
            count_list = count_list[:min_length]

            all_bins = ", ".join(["1"] * min_length)

            all_filters = []
            for f in filter_list:
                if telescope == "LOT":
                    all_filters.append(check_filter_LOT(f))
                elif telescope == "SLT":
                    all_filters.append(check_filter(f))
            all_filters = ", ".join(all_filters)

            all_exp_times = ", ".join(exp_time_list)
            all_count = ", ".join(count_list)

        except Exception as e:
            print(f"Error processing filters and exposures: {e}")
            if telescope == "LOT":
                full_filter_name = check_filter_LOT(filter_input)
            elif telescope == "SLT":
                full_filter_name = check_filter(filter_input)

            all_bins = "1"
            all_filters = full_filter_name
            all_exp_times = exp_time
            all_count = count

    base_script = (f"#BINNING {all_bins}\n"
                   f"#FILTER {all_filters}\n"
                   f"#INTERVAL {all_exp_times}\n"
                   f"#COUNT {all_count}\n"
                   f";= mag: {mag} mag =\n"
                   f"{name}\t{ra}\t{dec}\n"
                   )

    end_script = "#WAITFOR 1\n\n\n"
    repeat_script = f"#REPEAT {Repeat}\n"

    if priority == "None":
        priority_script = f";= {name} {telescope}_Normal_priority {priority_message} =\n\n"
    else:
        priority_script = f";= {name} {telescope}_{priority}_priority {priority_message} =\n\n"

    # ACP Script
    if Repeat > 0:
        script = priority_script + base_script + repeat_script + end_script
    else:
        script = priority_script + base_script + end_script

    return script


# Join per-target scripts into one message, separated so each target's block is
# clearly delimited when multiple targets are triggered together.
TARGET_SEPARATOR = ";====================\n\n"


def generate_full_script(targets, telescope):
    """
    targets: list of dicts, each with keys matching generate_script()'s params:
        name, ra, dec, mag, priority, priority_message, repeat, auto_exp,
        filter_input, exp_time, count.
    telescope: "SLT" or "LOT", applied to every target in the list.
    """
    is_lot = "True" if telescope == "LOT" else "False"
    parts = []
    for t in targets:
        parts.append(generate_script(
            name=t.get('name'),
            ra=t.get('ra'),
            dec=t.get('dec'),
            mag=t.get('mag'),
            priority=t.get('priority') or 'Normal',
            priority_message=t.get('priority_message'),
            is_lot=is_lot,
            Repeat=t.get('repeat', 0) or 0,
            auto_exp=t.get('auto_exp', True),
            filter_input=t.get('filter_input'),
            exp_time=t.get('exp_time'),
            count=t.get('count'),
        ))
    # Each target block (and TARGET_SEPARATOR) ends in trailing blank lines meant
    # to separate it from the next one — but after the very last target there's
    # nothing left to separate from, so trim the dangling newlines off the end.
    return TARGET_SEPARATOR.join(parts).rstrip('\n')


# generate image
def generate_img(date, target_list, plot_path=None):
    if plot_path is None:
        path_now = os.getcwd()
        obs_img_dir = os.path.join(path_now, "obs_img")
        if not os.path.exists(obs_img_dir):
            os.makedirs(obs_img_dir)
            print(f"Create folder: {obs_img_dir}")
        plot_path = os.path.join(obs_img_dir, "Trigger_observing_tracks.jpg")

    lulin_obs = obs.create_ephem_observer('Lulin Observatory', '120:52:21.5', '23:28:10.0', 2800)
    sunset, twi_civil, twi_naut, twi_astro = obs.calculate_twilight_times(
        lulin_obs, '2024/01/01 23:59:00'
    )
    next_obs_date = (datetime.strptime(date, "%Y-%m-%d") + timedelta(days=1)).date()
    obs_start = ephem.Date(f'{date} 17:00:00')
    obs_end = ephem.Date(f'{next_obs_date} 09:00:00')

    obs_start_local_dt = obs.dt_naive_to_dt_aware(obs_start.datetime(), 'Asia/Taipei')
    obs_end_local_dt = obs.dt_naive_to_dt_aware(obs_end.datetime(), 'Asia/Taipei')

    obs.plot_night_observing_tracks(
        target_list,
        lulin_obs,
        obs_start_local_dt,
        obs_end_local_dt,
        simpletracks=True,
        toptime='local',
        timezone='calculate',
        n_steps=1000,
        savepath=plot_path
    )
    return plot_path
