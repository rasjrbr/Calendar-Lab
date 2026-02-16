"""
Database utility functions for PostgreSQL connection and schema management.
"""

import os
import time
import logging
import psycopg2

logger = logging.getLogger(__name__)

DB_HOST = os.getenv("DB_HOST", "postgres")
DB_NAME = os.getenv("DB_NAME", "calendardb")
DB_USER = os.getenv("DB_USER", "calendar")
DB_PASSWORD = os.getenv("DB_PASSWORD", "calendarpass")


def connect_with_retry(max_retries=60):
    """
    Connect to PostgreSQL with exponential backoff retry logic.
    
    Args:
        max_retries: Maximum number of connection attempts
        
    Returns:
        psycopg2 connection object
    """
    last_error = None
    for attempt in range(max_retries):
        try:
            conn = psycopg2.connect(
                host=DB_HOST,
                dbname=DB_NAME,
                user=DB_USER,
                password=DB_PASSWORD
            )
            logger.info(f"Connected to PostgreSQL on {DB_HOST}")
            return conn
        except psycopg2.OperationalError as e:
            last_error = e
            msg = str(e).lower()
            if "could not connect" in msg or "connection refused" in msg or "starting up" in msg:
                if attempt < max_retries - 1:
                    wait_time = min(2 ** attempt, 10)  # exponential backoff, max 10s
                    logger.debug(f"Connection attempt {attempt + 1}/{max_retries} failed, retrying in {wait_time}s...")
                    time.sleep(wait_time)
                    continue
            raise
    
    raise last_error or psycopg2.OperationalError("Failed to connect after retries")


def initialize_schema(conn):
    """
    Initialize the database schema from schema.sql.
    Safe to run multiple times (uses CREATE TABLE IF NOT EXISTS).
    
    Args:
        conn: PostgreSQL connection object
    """
    try:
        schema_path = os.path.join(os.path.dirname(__file__), "..", "schema.sql")
        with open(schema_path, "r", encoding="utf-8") as f:
            schema_sql = f.read()
        
        cur = conn.cursor()
        cur.execute(schema_sql)
        conn.commit()
        cur.close()
        logger.info("Database schema initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize schema: {e}")
        raise


def ensure_schema_compatibility(conn):
    """
    Apply additive, backward-compatible schema migrations for existing databases.
    """
    try:
        cur = conn.cursor()
        cur.execute(
            """
            ALTER TABLE processed_events
            ADD COLUMN IF NOT EXISTS event_url TEXT
            """
        )
        conn.commit()
        cur.close()
    except Exception as e:
        logger.error(f"Failed to apply compatibility migrations: {e}")
        raise


def check_tables_exist(conn):
    """
    Check if core tables exist.
    
    Args:
        conn: PostgreSQL connection object
        
    Returns:
        Boolean indicating if tables exist
    """
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_name = 'raw_events'
            )
        """)
        exists = cur.fetchone()[0]
        cur.close()
        return exists
    except Exception as e:
        logger.error(f"Failed to check tables: {e}")
        return False


def get_connection():
    """
    Get a database connection, initializing schema if needed.
    
    Returns:
        PostgreSQL connection object
    """
    conn = connect_with_retry()
    
    if not check_tables_exist(conn):
        logger.info("Schema not initialized, creating now...")
        initialize_schema(conn)
    
    ensure_schema_compatibility(conn)
    
    return conn
