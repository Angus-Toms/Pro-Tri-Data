import pandas as pd
import os
import re
import pickle
import requests

pd.set_option('display.max_rows', None)
pd.set_option('display.max_columns', None)
pd.set_option('display.width', None) 
pd.set_option('display.max_colwidth', None) 

HEADERS = { "apikey": "aac0df989cb613114241670ca2f5ff75"}

# TODO: If we access more info for the race guide (event name, venue, location), we can construct directly
# from ELOSystem.Races and put in as post-processing rather than seperate func w/ API calls

def main():
    """
    Construct dictionary for key race information for quick lookup, save to .pkl
    
    race_id -> (event_date, short_title, full_title, country_id)
    """
    race_dict = {}
    data_path = os.path.join("data", "events.csv")

    dtype = {
        "event_id": "Int64",         # nullable integer dtype to allow missing values
        "event_title": "string",
        "event_venue": "string",
        "event_country_id": "Int64",
    }

    all_events = pd.read_csv(
        data_path,
        dtype = dtype,
        parse_dates = ["event_date"],
        na_values = ["", "NA", "null"],
        keep_default_na = True,
        low_memory = False,
    )
    all_events['event_date'] = pd.to_datetime(all_events['event_date'], errors='coerce')
    
    for i, event in all_events.iterrows():
        print(f"Processing event {i+1} / {round((i+1) / len(all_events) * 100, 2)}%")
        year = int(event['event_date'].year) if not pd.isna(event['event_date']) else None
        
        # Simplified event_handle creation
        event_handle = None
        title_words = str(event.get('event_title', '')).split()
        year_suffix = f"{year%100:02d}" if year is not None else ''

        # 1) National champs like "Something USA Something"
        if len(title_words) > 1 and re.match(r'^[A-Z]{3}$', title_words[1]) and title_words[1] != "ITU":
            event_handle = f"{title_words[1]} National Champs{year_suffix}"

        # 2) Use short venue when appropriate
        if event_handle is None and pd.notna(event.get('event_venue')):
            # TODO: Stripping of quotes doesn't seem to have worked?
            venue_words = event['event_venue'].str.replace('"','').str.replace("'", "").split()
            if 0 < len(venue_words) <= 3:
                event_handle = ' '.join(w.capitalize() for w in venue_words) + year_suffix

        # 3) Fallback: build from title, skipping common filler words
        if event_handle is None:
            filler_words = {
                'world', 'triathlon', 'championships', 'americas', 'europe', 'africa', 'asia', 'oceania',
                'cup', 'american', 'european', 'asian', 'games', 't100', 'tour', 'winter', 'development',
                'regional', 'african', 'para', 'itu', 'etu', 'atu', 'fisu', 'university', 'junior', 'north', 
                'camtri', 'and', 'ntt', 'astc', 'premium'
            }
            candidates = [w for w in title_words[1:] if w and w.lower().strip('.,') not in filler_words]
            event_handle = ' '.join(w.capitalize() for w in candidates[:3]) + year_suffix if candidates else f"Event {event['event_id']}{year_suffix}"
        
        prog_url = f"https://api.triathlon.org/v1/events/{event['event_id']}/programs"
        response = requests.get(prog_url, headers = HEADERS)
        data = response.json().get('data', [])
        
        if data is None: continue
        data = pd.json_normalize(data)   
             
        # Iterate through programs
        valid_programs = set([
            'Elite Men', 'Elite Women', 'U23 Men', 'U23 Women', 'Junior Men', 'Junior Women'
        ])

        for _, prog in data.iterrows():
            try:
                if prog['prog_name'] not in valid_programs:
                    continue
                race_dict[int(prog['prog_id'])] = (
                    event['event_date'], # YYYY-MM-DD 
                    event_handle, # Short title
                    event['event_title'], # Full title
                    event['event_country_id'], # Country ID
                    prog['prog_name'] # Program name
                )
            except Exception as e:
                print(f"Error processing program {prog['prog_id']} for event {event['event_id']}: {e}")
                continue

    # Save race_dict
    with open(os.path.join("data", "quick_race_lookup.pkl"), 'wb') as f:
        pickle.dump(race_dict, f)
        
    race_dict.to_csv(os.path.join("data", "quick_race_lookup.csv"))

if __name__ == "__main__":
    main()