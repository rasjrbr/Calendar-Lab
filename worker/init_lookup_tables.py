"""
Initialize PostgreSQL lookup tables from JSON configuration files.
Run once at container startup to populate reference data.
"""

import os
import json
import psycopg2
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

DB_HOST = os.getenv("DB_HOST", "postgres")
DB_NAME = os.getenv("DB_NAME", "calendardb")
DB_USER = os.getenv("DB_USER", "calendar")
DB_PASSWORD = os.getenv("DB_PASSWORD", "calendarpass")

APP_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_DIR = os.path.join(APP_DIR, "config")


def connect_with_retry(max_retries=60):
    """Connect to PostgreSQL with retry logic."""
    for attempt in range(max_retries):
        try:
            conn = psycopg2.connect(
                host=DB_HOST,
                dbname=DB_NAME,
                user=DB_USER,
                password=DB_PASSWORD
            )
            logger.info("Connected to PostgreSQL")
            return conn
        except psycopg2.OperationalError as e:
            if attempt < max_retries - 1:
                logger.debug(f"Connection attempt {attempt + 1} failed, retrying...")
                import time
                time.sleep(1)
            else:
                raise


def load_day_off_codes(conn):
    """Load day-off codes from JSON."""
    filepath = os.path.join(CONFIG_DIR, "day_off_codes.json")
    with open(filepath, "r", encoding="utf-8") as f:
        codes = json.load(f)
    
    cur = conn.cursor()
    for code, label_pt in codes.items():
        cur.execute(
            """
            INSERT INTO lookup_day_off_codes (code, label_pt)
            VALUES (%s, %s)
            ON CONFLICT (code) DO NOTHING
            """,
            (code, label_pt)
        )
    conn.commit()
    cur.close()
    logger.info(f"Loaded {len(codes)} day-off codes")


def load_homebases(conn):
    """Load airport/homebase data from JSON."""
    filepath = os.path.join(CONFIG_DIR, "homebases.json")
    with open(filepath, "r", encoding="utf-8") as f:
        homebases = json.load(f)
    
    cur = conn.cursor()
    for code, details in homebases.items():
        cur.execute(
            """
            INSERT INTO lookup_homebases (code, airport_name, city, state, country, address, coordinates, notes)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (code) DO NOTHING
            """,
            (
                code,
                details.get("airport_name"),
                details.get("city"),
                details.get("state"),
                details.get("country"),
                details.get("address"),
                json.dumps(details.get("coordinates")) if details.get("coordinates") else None,
                details.get("notes")
            )
        )
    conn.commit()
    cur.close()
    logger.info(f"Loaded {len(homebases)} homebases")


def load_ground_activities(conn):
    """Load activity codes from JSON."""
    filepath = os.path.join(CONFIG_DIR, "ground_activities.json")
    with open(filepath, "r", encoding="utf-8") as f:
        activities = json.load(f)
    
    cur = conn.cursor()
    for code, details in activities.items():
        cur.execute(
            """
            INSERT INTO lookup_ground_activities (code, name, type, location, is_validated)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (code) DO NOTHING
            """,
            (
                code,
                details.get("name"),
                details.get("type"),
                details.get("location"),
                True  # All pre-loaded activities are validated
            )
        )
    conn.commit()
    cur.close()
    logger.info(f"Loaded {len(activities)} ground activity codes")


def main():
    """Initialize all lookup tables."""
    try:
        conn = connect_with_retry()
        
        # Load all lookup tables
        load_day_off_codes(conn)
        load_homebases(conn)
        load_ground_activities(conn)
        
        conn.close()
        logger.info("Lookup tables initialized successfully")
        return True
    except Exception as e:
        logger.error(f"Failed to initialize lookup tables: {e}")
        raise


if __name__ == "__main__":
    main()
