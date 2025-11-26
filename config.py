from pathlib import Path

# Get the directory where config.py is located (the root of your project)
ROOT_DIR = Path(__file__).parent.resolve()

# Data served to site in static
STATIC_DIR = ROOT_DIR / "static"
DATA_DIR = STATIC_DIR / "data"
ATHLETES_DIR = DATA_DIR / "athletes"
ATHLETE_LOOKUP = DATA_DIR / "athlete_lookup.pkl"
ATHLETE_IMG_DIR = STATIC_DIR / "athlete_imgs"
FEMALE_SHORT_LEADERBOARD = DATA_DIR / "female_short_leaderboard.pkl"
MALE_SHORT_LEADERBOARD = DATA_DIR / "male_short_leaderboard.pkl"

RACES_DIR = DATA_DIR / "races"
RACE_LOOKUP = DATA_DIR / "race_lookup.pkl"

# Raw data used to learn ELO 
SOURCE_DIR = ROOT_DIR / "stats" / "data"
EVENT_CATEGORIES_CSV = SOURCE_DIR / "event_categories.csv"
EVENT_SPECIFICATIONS_CSV = SOURCE_DIR / "event_specifications.csv"
ALL_EVENTS = SOURCE_DIR / "events.csv"
FEMALE_SHORT_EVENTS = SOURCE_DIR / "female_short.csv"
MALE_SHORT_EVENTS = SOURCE_DIR / "male_short.csv"
FEMALE_SHORT_DIR = SOURCE_DIR / "female_short"
MALE_SHORT_DIR = SOURCE_DIR / "male_short"
CORRECTIONS = SOURCE_DIR / "corrections.csv"

# Constants 
ELITE_START_RATING = 1500
AG_START_RATING = 250