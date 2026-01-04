import json
from datetime import datetime, timedelta
import ephem
import os
from modules.postgres_database import get_tns_db_connection

# ========================= Function ========================================

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
            return "Too faint to observe"
        if mag < 12:
            return {"up": '60sec*1', "gp": '30sec*1', "rp": '30sec*1', "ip": '30sec*1', "zp": '30sec*1'}
        return exposure_times.get(mag, "Invalid magnitude")
    except:
        mag = str(mag)
        if mag == ">22":
            return "Too faint to observe"
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
    return filter


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
    return filter


# Generate Trigger Script
def generate_single_script(name, ra, dec, mag, priority, is_lot="False", Repeat=0, auto_exp=True, filter_input=None, exp_time=None, count=None, info=None):
    # Defensive coding: Ensure RA/Dec are strings if they are passed as dictionaries
    if isinstance(ra, dict) and 'ra_hms' in ra:
        ra = ra['ra_hms']
    if isinstance(dec, dict) and 'dec_dms' in dec:
        dec = dec['dec_dms']

    telescope = "LOT" if is_lot == "True" else "SLT"
    
    if auto_exp:
        exposure_times = exposure_time(mag)
        if exposure_times == "Invalid magnitude":
            return f"; Error: Invalid magnitude entered for {name}."
        elif exposure_times == "Too faint to observe":
            return f"; Error: {name} is too faint to observe."
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
                else:
                    full_filter_name = filter_name
                    
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
            filter_list = [f.strip() for f in str(filter_input).split(",")]
            exp_time_list = [e.strip() for e in str(exp_time).split(",")]
            count_list = [c.strip() for c in str(count).split(",")]
            
            # If lists are different lengths, take the minimum length or handle appropriately
            # Here we assume user inputs matching lengths or single values
            
            all_bins_list = []
            all_filters_list = []
            
            for f in filter_list:
                all_bins_list.append("1")
                if telescope == "LOT":
                    all_filters_list.append(check_filter_LOT(f))
                elif telescope == "SLT":
                    all_filters_list.append(check_filter(f))
                else:
                    all_filters_list.append(f)
            
            all_bins = ", ".join(all_bins_list)
            all_filters = ", ".join(all_filters_list)
            all_exp_times = ", ".join(exp_time_list)
            all_count = ", ".join(count_list)
            
        except Exception as e:
            return f"; Error processing filters and exposures for {name}: {e}"
    
    # ACP Script
    script = ""
    
    if info and str(info).strip():
        script += f";Info: {str(info).strip()}\n"

    if priority == "None" or not priority:
        header = f";==={telescope}===\n"
    elif priority == "Urgent":
        header = f";==={telescope}_Urgent_priority. Immediately Observe When Possible ===\n"
    else:
        header = f";==={telescope}_{priority}_priority===\n"
        
    script += header
    script += "\n"
    if int(Repeat) > 0:
        script += f"#REPEAT {Repeat}\n"
        
    script += f"#BINNING {all_bins}\n"
    script += f"#FILTER {all_filters}\n"
    script += f"#INTERVAL {all_exp_times}\n"
    script += f"#COUNT {all_count}\n"
    script += f";# mag: {mag} mag\n"
    script += f"{name}\t{ra}\t{dec}\n"
    script += "#WAITFOR 1\n\n\n"
    
    return script

def get_followup_targets_json():
    conn = get_tns_db_connection()
    cursor = conn.cursor()
    try:
        # Query for follow-up targets
        cursor.execute("""
            SELECT name, ra, declination, discoverymag 
            FROM tns_objects 
            WHERE follow = 1 AND finish_follow = 0
        """)
        rows = cursor.fetchall()
        
        targets = []
        for row in rows:
            name, ra, dec, mag = row
            
            # Format RA/Dec to ensure they are strings
            # Assuming they are stored as floats or strings in DB. 
            # If floats, we might need to convert to HMS/DMS if that's what the script expects.
            # Trigger_LOT_SLT.py seems to take whatever is passed. 
            # But usually scripts expect HMS/DMS or Decimal. 
            # Let's assume the DB has them in a usable format or we convert them.
            # Based on previous context, RA/Dec in DB are likely floats (degrees).
            # We should probably convert to HMS/DMS for the script if the telescope expects it.
            # However, the example JSON shows HMS/DMS.
            
            # Let's import conversion functions if needed.
            # For now, I'll pass them as is, but I should check if conversion is needed.
            # The example JSON has "08:12:39.4" and "+10:56:18.88".
            
            targets.append({
                "object name": name,
                "RA": ra, # This might need conversion if it's decimal in DB
                "Dec": dec,
                "Mag": str(mag) if mag else "unknown",
                "Priority": "Urgent",
                "Exp_By_Mag": "True",
                "Filter": "rp",
                "Exp_Time": "300",
                "Num_of_Frame": "3",
                "Repeat": 0
            })
            
        return {
            "settings": {
                "IS_LOT": "True",
                "send_to_control_room": "True"
            },
            "targets": targets
        }
    finally:
        conn.close()

def process_observation_request(data):
    settings = data.get('settings', {})
    targets = data.get('targets', [])
    
    is_lot = settings.get('IS_LOT', "True")
    
    full_script = ""
    
    for target in targets:
        name = target.get('object name')
        ra = target.get('RA')
        dec = target.get('Dec')
        mag = target.get('Mag')
        priority = target.get('Priority')
        exp_by_mag = target.get('Exp_By_Mag') == "True"
        filter_input = target.get('Filter')
        exp_time = target.get('Exp_Time')
        count = target.get('Num_of_Frame')
        repeat = target.get('Repeat', 0)
        info = target.get('Info', '')
        
        # Convert RA/Dec if they are decimal (simple check)
        # If RA is a float/int, convert to HMS. If string and has ':', assume HMS.
        # Actually, let's rely on the frontend or user to provide correct format, 
        # OR convert here if we know the DB returns decimal.
        # The DB usually stores RA/Dec as decimal degrees.
        
        from modules.coordinate_converter import convert_ra_decimal_to_hms, convert_dec_decimal_to_dms
        
        try:
            if isinstance(ra, (float, int)) or (isinstance(ra, str) and ':' not in ra):
                ra_result = convert_ra_decimal_to_hms(float(ra))
                ra = ra_result['ra_hms']
            if isinstance(dec, (float, int)) or (isinstance(dec, str) and ':' not in dec):
                dec_result = convert_dec_decimal_to_dms(float(dec))
                dec = dec_result['dec_dms']
        except:
            pass # Keep as is if conversion fails
            
        script = generate_single_script(
            name, ra, dec, mag, priority, 
            is_lot=is_lot, 
            Repeat=repeat, 
            auto_exp=exp_by_mag, 
            filter_input=filter_input, 
            exp_time=exp_time, 
            count=count,
            info=info
        )
        full_script += script
        
    return full_script
