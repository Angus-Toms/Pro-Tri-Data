import os

from pathlib import Path
import sys 

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import FEMALE_SHORT_DIR

for f in os.listdir(FEMALE_SHORT_DIR):
    if f.endswith(" 2.csv"):
        os.remove(os.path.join(FEMALE_SHORT_DIR, f))