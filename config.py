import os
from pathlib import Path

# Project paths
PROJECT_ROOT = Path(__file__).resolve().parent
STATIC_DIR = PROJECT_ROOT / "static"
STATIC_DATA_DIR = Path(os.getenv("DATA_ROOT", STATIC_DIR / "data"))

# Actual data served to site
SITE_ATHLETES_DIR = STATIC_DATA_DIR / "athletes"
SITE_RACES_DIR = STATIC_DATA_DIR / "races"
SITE_ATHLETE_IMAGES_DIR = STATIC_DATA_DIR / "athlete_imgs"

SITE_ATHLETE_LOOKUP_PATH = STATIC_DATA_DIR / "athlete_lookup.pkl"
SITE_FEMALE_SHORT_LEADERBOARD_PATH = STATIC_DATA_DIR / "female_short_leaderboard.pkl"
SITE_MALE_SHORT_LEADERBOARD_PATH = STATIC_DATA_DIR / "male_short_leaderboard.pkl"
SITE_RACE_LOOKUP_PATH = STATIC_DATA_DIR / "race_lookup.pkl"
SITE_COUNTRY_LIST_PATH = STATIC_DATA_DIR / "countries.pkl"

# About content
ABOUT_DIR = STATIC_DIR / "about"
ABOUT_QA_PATH = ABOUT_DIR / "qa.json"
ABOUT_BLOG_DIR = ABOUT_DIR / "blogs"

# Raw data used to learn ELO
STATS_DATA_DIR = PROJECT_ROOT / "stats" / "data"
EVENT_CATEGORIES_CSV_PATH = STATS_DATA_DIR / "event_categories.csv"
EVENT_SPECIFICATIONS_CSV_PATH = STATS_DATA_DIR / "event_specifications.csv"
EVENTS_CSV_PATH = STATS_DATA_DIR / "events.csv"
FEMALE_SHORT_EVENTS_CSV_PATH = STATS_DATA_DIR / "female_short.csv"
MALE_SHORT_EVENTS_CSV_PATH = STATS_DATA_DIR / "male_short.csv"
FEMALE_SHORT_RESULTS_DIR = STATS_DATA_DIR / "female_short"
MALE_SHORT_RESULTS_DIR = STATS_DATA_DIR / "male_short"
CORRECTIONS_CSV_PATH = STATS_DATA_DIR / "corrections.csv"
IGNORED_RACES_CSV_PATH = STATS_DATA_DIR / "ignored.csv"
WARNINGS_CSV_PATH = STATS_DATA_DIR / "warnings.csv"
DUPLICATES_CSV_PATH = STATS_DATA_DIR / "duplicates.csv"

# Constants
ELITE_START_RATING = 1750
AG_START_RATING = 0
