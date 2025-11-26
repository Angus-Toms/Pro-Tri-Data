import requests
import pandas as pd
from time import sleep
from ast import literal_eval
import os

def get_events():
    # API base URL
    BASE_URL = "https://api.triathlon.org/v1/events?per_page=100"
    HEADERS = { "apikey": "aac0df989cb613114241670ca2f5ff75" }

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
        

    df = pd.json_normalize(all_events)

    cols = ["event_id", "event_title", "event_slug", "event_venue", "event_website", "event_date", "event_country", "event_region_id", "event_country_id", "event_latitude", "event_longitude", "event_categories", "event_specifications", "event_api_listing"]
    df = df[cols]

    df.to_csv("data/events.csv", index = False)
    
def get_event_categories():
    BASE_URL = "https://api.triathlon.org/v1/events/categories"
    HEADERS = { "apikey": "aac0df989cb613114241670ca2f5ff75" }
    
    response = requests.get(BASE_URL, headers = HEADERS)
    data = response.json()['data']
    
    df = pd.json_normalize(data)
    df.to_csv("data/event_categories.csv", index = False)
    
def get_event_specifications():
    BASE_URL = "https://api.triathlon.org/v1/events/specifications"
    HEADERS = { "apikey": "aac0df989cb613114241670ca2f5ff75" }
    
    response = requests.get(BASE_URL, headers = HEADERS)
    data = response.json()['data']
    
    df = pd.json_normalize(data)
    df.sort_values("cat_name", inplace = True)
    df.to_csv("data/event_specifications.csv", index = False)
    
def get_program_listing(event_id):
    BASE_URL = f"https://api.triathlon.org/v1/events/{event_id}/programs"
    HEADERS = { "apikey": "aac0df989cb613114241670ca2f5ff75" }
    
    # sleep(0.5)
    response = requests.get(BASE_URL, headers = HEADERS)
    data = response.json()['data']
    
    return data or [] # Catch if data is None
    
def get_all_program_listings():
    events = pd.read_csv("data/events.csv")
    ids = events[['event_id', 'event_specifications']]

    all_progs = []
    
    for i, row in ids.iterrows():
        try:
            id, spec = row['event_id'], literal_eval(row['event_specifications'])
            for event in spec:
                cat_id = event.get('cat_id', 0)
                if cat_id == 376 or cat_id == 377: # Check for standard / sprint triathlon
                    all_progs.extend(get_program_listing(id))
                    print(f"Got {id} ({round(100 * i / len(ids), 2)}%)")
        except:
            print(f"Failed get")
        
    df = pd.json_normalize(all_progs)
        
    cols = ["prog_id", "event_id", "prog_name", "is_race", "prog_date", "prog_timezone_offset", "prog_gender", "prog_notes", "results", "team"]
    
    df = df[cols]
    df.to_csv("data/short_tri_programs.csv", index = False)

def save_event_results(event_id: int, prog_id: int):
    BASE_URL = f"https://api.triathlon.org/v1/events/{event_id}/programs/{prog_id}/results"
    HEADERS = { "apikey": "aac0df989cb613114241670ca2f5ff75" }
    
    if os.path.exists(f"data/male_results/{event_id}_{prog_id}.csv"):
        print(f"Results for {event_id}_{prog_id} already exist, skipping.")
        return
    
    response = requests.get(BASE_URL, headers = HEADERS)
    data = response.json()['data']
    if data is not None and isinstance(data, dict):
        data = data['results']
    
    if data is None: return
    
    df = pd.json_normalize(data)
    cols = ["athlete_id", "athlete_first", "athlete_last", "splits", "position", "total_time", "start_num", "athlete_gender", "athlete_profile_image", "athlete_country_id"]
    df = df[cols]
    
    df.to_csv(f"data/male_short/{event_id}_{prog_id}.csv", index = False)

def get_male_short_results():
    progs = pd.read_csv("data/short_tri_programs.csv")
    
    male_prog_names = ['Elite Men', 'Junior Men', 'U23 Men']
    male_events = progs[
        (progs['prog_name'].isin(male_prog_names)) & 
        (progs['is_race'] == True) & 
        (progs['results'] == True)
    ][['event_id', 'prog_id']].drop_duplicates()
    
    for idx, (_, row) in enumerate(male_events.iterrows()):
        event_id, prog_id = int(row['event_id']), int(row['prog_id'])
        fname = f"data/male_short/{event_id}_{prog_id}.csv"
        
        if os.path.exists(fname):
            print(f"Results for {event_id}_{prog_id} already exist, skipping.")
            continue
        
        try:
            save_event_results(int(event_id), int(prog_id))
            print(f"Saved results for {event_id}_{prog_id} ({round(100 * idx / len(male_events), 2)}%)")
        except Exception as e:
            print(f"Failed to save results for {event_id}_{prog_id}: {e}")
    
if __name__ == "__main__":
    get_male_short_results()