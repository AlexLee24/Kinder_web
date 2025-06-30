from datetime import datetime, timezone
import re
from modules.calendar_database import get_calendar_events

def format_datetime_for_ics(dt_str, all_day=False):
    try:
        dt = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
        if all_day:
            return dt.strftime('%Y%m%d')
        else:
            return dt.strftime('%Y%m%dT%H%M%SZ')
    except:
        dt = datetime.now(timezone.utc)
        if all_day:
            return dt.strftime('%Y%m%d')
        else:
            return dt.strftime('%Y%m%dT%H%M%SZ')

def escape_ics_text(text):
    if not text:
        return ''
    text = str(text)
    text = text.replace('\\', '\\\\')
    text = text.replace('\n', '\\n')
    text = text.replace('\r', '\\r')
    text = text.replace(',', '\\,')
    text = text.replace(';', '\\;')
    return text

def generate_ics_calendar(start_date=None, end_date=None, category=None):
    events = get_calendar_events(start_date, end_date, category)
    
    ics_content = []
    ics_content.append('BEGIN:VCALENDAR')
    ics_content.append('VERSION:2.0')
    ics_content.append('PRODID:-//GREAT Lab//Lab Calendar//EN')
    ics_content.append('CALSCALE:GREGORIAN')
    ics_content.append('METHOD:PUBLISH')
    ics_content.append('X-WR-CALNAME:GREAT Lab Calendar')
    ics_content.append('X-WR-CALDESC:Laboratory events and schedules')
    ics_content.append('X-WR-TIMEZONE:UTC')
    
    for event in events:
        ics_content.append('BEGIN:VEVENT')
        ics_content.append(f'UID:{event["id"]}@greatlab.calendar')
        
        if event['all_day']:
            ics_content.append(f'DTSTART;VALUE=DATE:{format_datetime_for_ics(event["start_date"], True)}')
            end_date_dt = datetime.fromisoformat(event["end_date"].replace('Z', '+00:00'))
            end_date_dt = end_date_dt.replace(hour=23, minute=59, second=59)
            ics_content.append(f'DTEND;VALUE=DATE:{format_datetime_for_ics(end_date_dt.isoformat(), True)}')
        else:
            ics_content.append(f'DTSTART:{format_datetime_for_ics(event["start_date"])}')
            ics_content.append(f'DTEND:{format_datetime_for_ics(event["end_date"])}')
        
        ics_content.append(f'SUMMARY:{escape_ics_text(event["title"])}')
        
        if event['description']:
            ics_content.append(f'DESCRIPTION:{escape_ics_text(event["description"])}')
        
        if event['location']:
            ics_content.append(f'LOCATION:{escape_ics_text(event["location"])}')
        
        ics_content.append(f'CATEGORIES:{escape_ics_text(event["category"].upper())}')
        ics_content.append(f'CREATED:{format_datetime_for_ics(event["created_at"])}')
        ics_content.append(f'LAST-MODIFIED:{format_datetime_for_ics(event["updated_at"])}')
        ics_content.append(f'DTSTAMP:{format_datetime_for_ics(datetime.now(timezone.utc).isoformat())}')
        
        if event['recurrence_rule']:
            ics_content.append(f'RRULE:{event["recurrence_rule"]}')
        
        ics_content.append('END:VEVENT')
    
    ics_content.append('END:VCALENDAR')
    
    return '\r\n'.join(ics_content)