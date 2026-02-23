"""
Fifth transformation stage: ICS publication.

Generates RFC 5545 compliant ICS from processed_events.
- Uses clean_title for event summary
- Includes synthetic events (Checkout events)
- UTC timestamps with Z suffix
- Preserves #roquescript-modified tags in description
- Writes to /var/www/calendars/{user_id}.ics for NGINX serving
"""

import os
import json
import logging
from pathlib import Path
from datetime import timezone as tz, timedelta
from icalendar import Calendar, Event, Alarm

from utils.db_utils import get_connection
from utils.logging_utils import setup_logging, log_event_processing

logger = logging.getLogger(__name__)

USER_ID = os.getenv("USER_ID", "roque")
OUT_DIR = os.getenv("OUT_DIR", "/var/www/calendars")

def main():
    """
    Query processed_events and generate final ICS file.
    
    Process:
    1. Connect to database with auto-schema-init
    2. Query all processed_events for user (including synthetics)
    3. Create Calendar with proper RFC 5545 headers
    4. Add each event with clean_title, notes, tags
    5. Write to /var/www/calendars/{user_id}.ics
    """
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        
        logger.info(f"Publishing ICS for user: {USER_ID}")
        
        # Query processed_events in chronological order
        # Include synthetic events (is_synthetic=TRUE) for Checkout events
        cur.execute("""
        SELECT 
            source_uid,
            start_utc,
            end_utc,
            clean_title,
            notes,
            tags,
            modifications,
            event_type,
            is_synthetic,
            location_code,
            location_details,
            event_url
        FROM processed_events
        WHERE user_id = %s
        ORDER BY start_utc
        """, (USER_ID,))
        
        rows = cur.fetchall()
        logger.info(f"Found {len(rows)} processed events to publish (includes synthetics)")
        
        # Create Calendar with RFC 5545 headers
        cal = Calendar()
        cal.add("prodid", "-//Calendar Lab//Processed//EN")
        cal.add("version", "2.0")
        cal.add("calscale", "GREGORIAN")
        cal.add("method", "PUBLISH")
        cal.add("x-wr-calname", f"Calendário de {USER_ID} (Processado)")
        cal.add("x-wr-timezone", "America/Sao_Paulo")
        
        event_count = 0
        
        for row in rows:
            (source_uid, start_utc, end_utc, clean_title, notes, 
             tags, modifications, event_type, is_synthetic, location_code, location_details, event_url) = row
            
            try:
                ev = Event()
                
                # RFC 5545: DTSTART/DTEND with Z (UTC) suffix
                ev.add("dtstart", start_utc.replace(tzinfo=tz.utc))
                ev.add("dtend", end_utc.replace(tzinfo=tz.utc))
                
                # Unique identifier with synthetic indicator
                if is_synthetic:
                    uid = f"{source_uid}-synthetic"
                else:
                    uid = str(source_uid)
                ev.add("uid", uid)
                
                # Event summary from cleaned title
                ev.add("summary", clean_title or "(sem título)")
                
                # Event location (for Reserva: address from lookup_homebases)
                location_text = None
                parsed_location_details = location_details
                if isinstance(parsed_location_details, str):
                    try:
                        parsed_location_details = json.loads(parsed_location_details)
                    except Exception:
                        parsed_location_details = None
                if isinstance(parsed_location_details, dict):
                    location_text = (
                        parsed_location_details.get("address")
                        or parsed_location_details.get("airport_name")
                        or parsed_location_details.get("code")
                    )
                if not location_text and location_code:
                    location_text = location_code
                if location_text:
                    ev.add("location", location_text)
                if event_url:
                    ev.add("url", event_url)
                
                # Add reminder for Reserva/ASB events.
                if event_type == "RESERVA" or (clean_title and clean_title.startswith("Reserva")):
                    alarm = Alarm()
                    alarm.add("action", "DISPLAY")
                    alarm.add("description", "Reserva reminder")
                    alarm.add("trigger", timedelta(minutes=-5))
                    ev.add_component(alarm)

                # Add reminders for key synthetic markers.
                if clean_title == "Checkout":
                    alarm = Alarm()
                    alarm.add("action", "DISPLAY")
                    alarm.add("description", "Checkout reminder")
                    alarm.add("trigger", timedelta(minutes=-10))
                    ev.add_component(alarm)
                elif clean_title in ("Horário Corte (d)", "Horário Corte (i)"):
                    alarm = Alarm()
                    alarm.add("action", "DISPLAY")
                    alarm.add("description", clean_title)
                    alarm.add("trigger", timedelta(minutes=-20))
                    ev.add_component(alarm)
                
                # Description with notes and tags
                desc_parts = []
                if notes:
                    desc_parts.append(notes)
                if tags and isinstance(tags, list):
                    desc_parts.append(" ".join(tags))
                description = "\n".join(desc_parts)
                if description:
                    ev.add("description", description)
                
                # Custom properties for tool-aware clients
                if event_type:
                    ev.add("x-roquescript-event-type", event_type)
                if is_synthetic:
                    ev.add("x-roquescript-synthetic", "TRUE")
                
                # Modifications history as JSON comment (RFC 5545 doesn't support JSON well)
                if modifications and isinstance(modifications, list):
                    ev.add("x-roquescript-modifications-count", str(len(modifications)))
                
                cal.add_component(ev)
                event_count += 1
                
                log_event_processing(
                    logger=logger,
                    event_uid=source_uid,
                    user_id=USER_ID,
                    action="publish_ics",
                    status="success",
                    details={
                        "synthetic": bool(is_synthetic),
                        "title": clean_title,
                        "event_type": event_type,
                    },
                )
                
            except Exception as e:
                logger.error(
                    f"Error publishing event {source_uid}: {str(e)}",
                    extra={
                        "user_id": USER_ID,
                        "event_uid": source_uid,
                        "title": clean_title,
                    }
                )
                continue
        
        # Write ICS file to output directory
        out_dir = Path(OUT_DIR)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{USER_ID}.ics"
        
        ics_bytes = cal.to_ical()
        out_path.write_bytes(ics_bytes)
        
        logger.info(
            f"Published ICS file: {out_path}",
            extra={
                "user_id": USER_ID,
                "event_count": event_count,
                "file_size_bytes": len(ics_bytes),
            }
        )
        
        cur.close()
        return {
            "status": "success",
            "events_published": event_count,
            "output_file": str(out_path),
        }
        
    except Exception as e:
        logger.error(f"Fatal error in publish_ics: {str(e)}", extra={"user_id": USER_ID})
        raise
    finally:
        if conn:
            conn.close()


if __name__ == "__main__":
    logger = setup_logging(__name__)
    result = main()
    logger.info(f"publish_ics complete: {result}")
