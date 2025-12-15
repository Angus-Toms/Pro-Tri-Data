import requests
import pandas as pd
from time import sleep
from ast import literal_eval
import os
from pathlib import Path
import sys
import shutil

root_dir = Path(__file__).parent.parent
sys.path.insert(0, str(root_dir))

pd.set_option('display.max_columns', None)
pd.set_option('display.width', 1000)

from config import (
    FEMALE_SHORT_EVENTS,
    MALE_SHORT_EVENTS,
    ALL_EVENTS,
    MALE_SHORT_DIR,
    FEMALE_SHORT_DIR
)

HEADERS = {"apikey": "aac0df989cb613114241670ca2f5ff75"}
VALID_CAT_IDS = [376, 377]

class DataFetcher:
    """Fetches and manages triathlon event data from the triathlon.org API"""
    
    PROG_CATEGORIES = {
        'male': {
            'Elite Men', 'U23 Men', 'Junior Men', '16-17 Male AG', '17-18 Male AG', 
            '16-19 Male AG', '20-24 Male AG', '25-29 Male AG', '30-34 Male AG', 
            '35-39 Male AG', '40-44 Male AG', '45-49 Male AG', '50-54 Male AG', 
            '55-59 Male AG', '60-64 Male AG', '65-69 Male AG', '70-74 Male AG', 
            '75-79 Male AG', '80-84 Male AG', '85-89 Male AG', '90-94 Male AG'
        },
        'female': {
            'Elite Women', 'U23 Women', 'Junior Women', '16-17 Female AG', '17-18 Female AG',
            '16-19 Female AG', '20-24 Female AG', '25-29 Female AG', '30-34 Female AG',
            '35-39 Female AG', '40-44 Female AG', '45-49 Female AG', '50-54 Female AG',
            '55-59 Female AG', '60-64 Female AG', '65-69 Female AG', '70-74 Female AG',
            '75-79 Female AG', '80-84 Female AG', '85-89 Female AG', '90-94 Female AG'
        }
    }
    
    RESULT_COLS = [
        'athlete_id', 'athlete_title', 'athlete_country_name', 'athlete_yob', 
        'splits', 'position', 'total_time', 'start_num', 'athlete_profile_image'
    ]
    
    PROG_COLS = [
        'prog_id', 'event_id', 'prog_name', 'is_race', 'prog_date', 
        'prog_gender', 'results', 'team'
    ]

    def __init__(self):
        self.base_url = "https://api.triathlon.org/v1"
    
    @staticmethod
    def clear_data(gender):
        """
        Clears existing data for a specific gender with user confirmation
        
        Args:
            gender: 'male' or 'female'
        """
        events_file = MALE_SHORT_EVENTS if gender == 'male' else FEMALE_SHORT_EVENTS
        results_dir = MALE_SHORT_DIR if gender == 'male' else FEMALE_SHORT_DIR
        
        print(f"\n⚠️  WARNING: This will delete all {gender} short course data!")
        print(f"   - Events file: {events_file}")
        print(f"   - Results directory: {results_dir}")
        
        confirmation = input("\nType 'yes' to confirm deletion: ").strip().lower()
        
        if confirmation == 'yes':
            # Clear results directory
            if results_dir.exists():
                shutil.rmtree(results_dir)
                results_dir.mkdir(parents=True, exist_ok=True)
                print(f"Cleared {results_dir}")
            
            # Clear events file
            if events_file.exists():
                pd.DataFrame(columns=DataFetcher.PROG_COLS + [
                    'race_title', 'race_venue', 'race_country', 'cat_id', 'cat_name'
                ]).to_csv(events_file, index=False)
                print(f"Cleared {events_file}")
            
            print(f"All {gender} data cleared successfully!")
        else:
            print("Deletion cancelled")
    
    def update_all_events(self):
        """Fetches all events from the API and saves to CSV"""
        print("Fetching all events from API...")
        
        all_events = []
        page = 1

        while True:
            response = requests.get(
                f"{self.base_url}/events",
                params={"page": page, "per_page": 500},
                headers=HEADERS
            )
            data = response.json()

            if 'data' not in data or not data['data']:
                break

            all_events.extend(data['data'])
            print(f"Fetched page {page} ({len(all_events)} events so far)")
            
            if not data.get('next_page_url'):
                break

            page += 1
            sleep(0.3)
        
        cols = [
            "event_id", "event_title", "event_slug", "event_venue", "event_website",
            "event_date", "event_country", "event_region_id", "event_country_id",
            "event_latitude", "event_longitude", "event_categories", "event_specifications"
        ]
        df = pd.json_normalize(all_events)[cols]
        df.to_csv(ALL_EVENTS, index=False)
        
        print(f"Saved {len(df)} events to {ALL_EVENTS}")
    
    def _filter_short_course_events(self):
        """Returns events that have short course triathlon programs"""
        events = pd.read_csv(ALL_EVENTS, header=0)
        
        short_course_events = []
        for _, event in events.iterrows():
            try:
                specs = literal_eval(event['event_specifications'])
                if any(spec.get('cat_id', 0) in VALID_CAT_IDS for spec in specs):
                    short_course_events.append(event)
            except (ValueError, SyntaxError):
                continue
        
        return pd.DataFrame(short_course_events)
    
    def _get_category_info(self, event):
        """Extracts category ID and name from event"""
        try:
            cat_list = literal_eval(event['event_categories'])
            return [cat['cat_id'] for cat in cat_list], [cat['cat_name'] for cat in cat_list]
        except Exception:
            return [-1], [""]
    
    def _clean_field(self, value):
        """Removes quotes and capitalizes field value"""
        if pd.isna(value):
            return ""
        cleaned = str(value).replace("'", "").replace('"', '').strip()
        return cleaned.title() if cleaned else ""
    
    def _get_event_programs(self, event_id):
        """Fetches programs for a specific event"""
        prog_url = f"{self.base_url}/events/{event_id}/programs"
        response = requests.get(prog_url, headers=HEADERS)
        data = response.json().get('data', [])
        
        if data is None:
            return pd.DataFrame()
        
        return pd.json_normalize(data)
    
    def _save_result(self, event_id, prog_id, results_dir):
        """Fetches and saves results for a specific program"""
        request_url = f"{self.base_url}/events/{event_id}/programs/{prog_id}/results"
        response = requests.get(request_url, headers=HEADERS)
        data = response.json().get('data', {}).get('results', [])
        
        if data is None or data == []:
            return
        
        data = pd.json_normalize(data)
        fname = results_dir / f"{prog_id}.csv"
        data[self.RESULT_COLS].to_csv(fname, index=False)
    
    def get_new_short_progs(self, gender):
        """
        Fetches new short course programs for specified gender
        
        Args:
            gender: 'male' or 'female'
        """
        events_file = MALE_SHORT_EVENTS if gender == 'male' else FEMALE_SHORT_EVENTS
        results_dir = MALE_SHORT_DIR if gender == 'male' else FEMALE_SHORT_DIR
        prog_categories = self.PROG_CATEGORIES[gender]
        
        print(f"\nFetching {gender} short course programs...")
        
        # Get all short course events
        all_short_events = self._filter_short_course_events()
        
        # Load existing programs
        existing_progs = pd.read_csv(events_file, header=0)
        
        # Check event_ids - skip events we've already processed
        existing_event_ids = set(existing_progs['event_id'].unique())
        
        new_count = 0
        for i, event in all_short_events.iterrows():
            event_id = event['event_id']
            
            print(f"Checking event {event_id} ({i + 1}/{len(all_short_events)}, {(i / len(all_short_events) * 100):.1f}%)")
            
            if event_id in existing_event_ids:
                continue
            
            # Get category info
            cat_id, cat_name = self._get_category_info(event)
            
            # Fetch programs for this event
            programs = self._get_event_programs(event_id)
            if programs.empty:
                continue
            
            # Process each program
            for _, prog in programs.iterrows():
                if (prog['prog_name'] in prog_categories and 
                    prog['results'] and 
                    prog['is_race']):
                    
                    print(f"  - Found new result: {prog['prog_name']}")
                    
                    # Save results
                    self._save_result(event_id, prog['prog_id'], results_dir)
                    
                    # Build program details
                    prog_details = prog[self.PROG_COLS].copy()
                    prog_details["race_title"] = event["event_title"]
                    prog_details["race_venue"] = self._clean_field(event.get("event_venue", ""))
                    prog_details["race_country"] = self._clean_field(event.get("event_country", ""))
                    prog_details["cat_id"] = str(cat_id)
                    prog_details["cat_name"] = str(cat_name)
                    
                    # Append and save
                    existing_progs.loc[len(existing_progs)] = prog_details
                    existing_progs.to_csv(events_file, index=False, quoting=1) # Minimal quotes
                    
                    new_count += 1
            
            # Mark this event as processed
            existing_event_ids.add(event_id)
        
        print(f"Added {new_count} new {gender} programs")


def main():
    fetcher = DataFetcher()
    
    fetcher.clear_data('male')
    fetcher.clear_data('female')
    
    # Update all events first
    # fetcher.update_all_events()
    
    # Fetch new programs
    fetcher.get_new_short_progs("male")
    fetcher.get_new_short_progs("female")


if __name__ == "__main__":
    main()