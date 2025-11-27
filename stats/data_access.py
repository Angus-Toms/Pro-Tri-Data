import requests
import pandas as pd
from time import sleep
from ast import literal_eval
import os
from pathlib import Path
import sys

root_dir = Path(__file__).parent.parent
sys.path.insert(0, str(root_dir))

from config import (
    FEMALE_SHORT_EVENTS,
    MALE_SHORT_EVENTS,
    ALL_EVENTS,
    MALE_SHORT_DIR,
    FEMALE_SHORT_DIR
)

pd.set_option('display.max_columns', None)
pd.set_option('display.width', 1000)

HEADERS = { "apikey": "aac0df989cb613114241670ca2f5ff75"}

def update_all_events():
    BASE_URL = "https://api.triathlon.org/v1/events?per_page=500"
    
    all_events = []
    page = 1

    while True:
        response = requests.get(BASE_URL, params = {"page": page}, headers = HEADERS)
        data = response.json()
        print(data)

        if 'data' not in data or not data['data']:
            break

        all_events.extend(data['data'])
        
        # Go to next page
        if not data.get('next_page_url'):
            break

        page += 1
        sleep(0.3)
    
    cols = ["event_id", "event_title", "event_slug", "event_venue", "event_website", "event_date", "event_country", "event_region_id", "event_country_id", "event_latitude", "event_longitude", "event_categories", "event_specifications"]
    df = pd.json_normalize(all_events)[cols]

    df.to_csv(ALL_EVENTS, index = False)

def get_new_male_short_progs():
    # Get all events
    events = pd.read_csv(ALL_EVENTS, header = 0)
    
    # Filter by events with short course tri progs
    valid_cat_ids = [376, 377]
    male_short_events = []
    for _, event in events.iterrows():
        try:
            specs = literal_eval(event['event_specifications'])
            if any(spec.get('cat_id', 0) in valid_cat_ids for spec in specs):
                male_short_events.append(event)
        except (ValueError, SyntaxError):
            continue 
        
    all_male_short_df = pd.DataFrame(male_short_events)
    existing_male_short = pd.read_csv(MALE_SHORT_EVENTS, header = 0)
    
    # Check event_prog against existing
    existing_event_ids = set(existing_male_short['event_id'])
    idx = 0
    for _, event in all_male_short_df.iterrows():
        print(f"Checking event {event['event_id']} ({idx / len(all_male_short_df) * 100:.2f}%)")
        idx += 1
        if event['event_id'] not in existing_event_ids:
            prog_url = f"https://api.triathlon.org/v1/events/{event['event_id']}/programs"
            response = requests.get(prog_url, headers = HEADERS)
            data = response.json().get('data', [])
            
            if data is None: continue
            data = pd.json_normalize(data)
            
            prog_cols = ['prog_id', 'event_id', 'prog_name', 'is_race', 'prog_date', 'prog_gender', 'results', 'team']
            
            # Filter for elite male results
            for _, row in data.iterrows():
                male_progs = set(['Elite Men', 'U23 Men', 'Junior Men', '16-17 Male AG', '17-18 Male AG', '16-19 Male AG', '20-24 Male AG', '25-29 Male AG', '30-34 Male AG', '35-39 Male AG', '40-44 Male AG', '45-49 Male AG', '50-54 Male AG', '55-59 Male AG', '60-64 Male AG', '65-69 Male AG', '70-74 Male AG', '75-79 Male AG', '80-84 Male AG', '85-89 Male AG', '90-94 Male AG'])
                if row['prog_name'] in male_progs and row['results'] and row['is_race']:
                    print(f"Getting results for event {event['event_id']} - {row['prog_name']}")

                    # Save to results dir
                    get_male_short_result(row['event_id'], row['prog_id'])
                    
                    # Save program details
                    prog_details = row[prog_cols]
                    prog_details["race_title"] = event["event_title"]

                    # Remove quotes from venue and country, where possible
                    venue = event.get("event_venue", "")
                    prog_details["race_venue"] = "" if pd.isna(venue) else str(venue).replace("'", "").replace('"', "").capitalize()
                    country = event.get("event_country", "")
                    prog_details["race_country"] = "" if pd.isna(country) else str(country).replace("'", "").replace('"', "").capitalize()
                    
                    existing_male_short.loc[len(existing_male_short)] = prog_details
                    existing_male_short.to_csv(MALE_SHORT_EVENTS, index = False)

def get_male_short_result(event_id, prog_id):
    """
    Gets results for a male short event
    """
    # Request 
    request_url = f"https://api.triathlon.org/v1/events/{event_id}/programs/{prog_id}/results"
    response = requests.get(request_url, headers = HEADERS)
    data = response.json().get('data', {}).get('results', [])
    
    if data is None or data == []: return
    data = pd.json_normalize(data)
    
    # Add to results dir 
    result_cols = ['athlete_id', 'athlete_title', 'athlete_country_name', 'athlete_yob', 'splits', 'position', 'total_time', 'start_num', 'athlete_profile_image']
    fname = MALE_SHORT_DIR / f"{prog_id}.csv"
    data[result_cols].to_csv(fname, index = False)
    
def get_new_female_short_progs():
    # Get all events
    events = pd.read_csv(ALL_EVENTS, header = 0)
    
    # Filter by events with short course tri progs
    valid_cat_ids = [376, 377]
    female_short_events = []
    for _, event in events.iterrows():
        try:
            specs = literal_eval(event['event_specifications'])
            if any(spec.get('cat_id', 0) in valid_cat_ids for spec in specs):
                female_short_events.append(event)
        except (ValueError, SyntaxError):
            continue

    all_female_short_df = pd.DataFrame(female_short_events)
    existing_female_short = pd.read_csv(FEMALE_SHORT_EVENTS, header = 0)
    
    # Check event_prog against existing
    existing_event_ids = set(existing_female_short['event_id'])
    idx = 0
    for _, event in all_female_short_df.iterrows():
        print(f"Checking event {event['event_id']} ({idx / len(all_female_short_df) * 100:.2f}%)")
        idx += 1
        if event['event_id'] not in existing_event_ids:
            prog_url = f"https://api.triathlon.org/v1/events/{event['event_id']}/programs"
            response = requests.get(prog_url, headers = HEADERS)
            data = response.json().get('data', [])
            
            if data is None: continue
            data = pd.json_normalize(data)
            
            prog_cols = ['prog_id', 'event_id', 'prog_name', 'is_race', 'prog_date', 'prog_gender', 'results', 'team']

            # Filter for elite female results
            for _, row in data.iterrows():
                female_progs = set(['Elite Women', 'U23 Women', 'Junior Women', '16-17 Female AG', '17-18 Female AG', '16-19 Female AG', '20-24 Female AG', '25-29 Female AG', '30-34 Female AG', '35-39 Female AG', '40-44 Female AG', '45-49 Female AG', '50-54 Female AG', '55-59 Female AG', '60-64 Female AG', '65-69 Female AG', '70-74 Female AG', '75-79 Female AG', '80-84 Female AG', '85-89 Female AG', '90-94 Female AG'])
                if row['prog_name'] in female_progs and row['results'] and row['is_race']:
                    print(f"Found new result for event {event['event_id']} - {row['prog_name']}")

                    # Save to results dir
                    get_female_short_result(row['event_id'], row['prog_id'])
                    # Save program details
                    prog_details = row[prog_cols]
                    prog_details["race_title"] = event["event_title"]

                    # Remove quotes from venue and country, where possible
                    venue = event.get("event_venue", "")
                    prog_details["race_venue"] = "" if pd.isna(venue) else str(venue).replace("'", "").replace('"', "").capitalize()
                    country = event.get("event_country", "")
                    prog_details["race_country"] = "" if pd.isna(country) else str(country).replace("'", "").replace('"', "").capitalize()
                    
                    existing_female_short.loc[len(existing_female_short)] = prog_details
                    existing_female_short.to_csv(FEMALE_SHORT_EVENTS, index = False)

def get_female_short_result(event_id, prog_id):
    # Request 
    request_url = f"https://api.triathlon.org/v1/events/{event_id}/programs/{prog_id}/results"
    response = requests.get(request_url, headers = HEADERS)
    data = response.json().get('data', {}).get('results', [])
    
    if data is None or data == []: return
    data = pd.json_normalize(data)
    
    # Add to results dir 
    result_cols = ['athlete_id', 'athlete_title', 'athlete_country_name', 'athlete_yob', 'splits', 'position', 'total_time', 'start_num', 'athlete_profile_image']
    fname = FEMALE_SHORT_DIR / f"{prog_id}.csv"
    data[result_cols].to_csv(fname, index = False)

def main():
    get_new_female_short_progs()
    get_new_male_short_progs()

if __name__ == "__main__":
    main()