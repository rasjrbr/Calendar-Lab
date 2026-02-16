"""
Structured logging utility for Calendar Lab worker.
"""

import logging
import json
from datetime import datetime


class StructuredFormatter(logging.Formatter):
    """Format logs as structured JSON for easier parsing."""
    
    def format(self, record):
        log_data = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        
        # Add custom fields if present
        if hasattr(record, "user_id"):
            log_data["user_id"] = record.user_id
        if hasattr(record, "cycle_id"):
            log_data["cycle_id"] = record.cycle_id
        if hasattr(record, "event_uid"):
            log_data["event_uid"] = record.event_uid
        
        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        
        return json.dumps(log_data)


def setup_logging(name, level=logging.INFO):
    """
    Set up structured logging for a module.
    
    Args:
        name: Logger name (usually __name__)
        level: Logging level (default INFO)
        
    Returns:
        Logger instance
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)
    
    # Console handler with structured formatting
    handler = logging.StreamHandler()
    handler.setFormatter(StructuredFormatter())
    logger.addHandler(handler)
    
    return logger


def log_event_processing(logger, event_uid, user_id, action, status, details=None):
    """
    Log an event processing step with consistent format.
    
    Args:
        logger: Logger instance
        event_uid: Source event UID
        user_id: User ID
        action: Action performed (e.g., "init_parsing", "checkout_creator")
        status: Status (e.g., "success", "skip", "error")
        details: Optional dict of additional details
    """
    extra = {
        "user_id": user_id,
        "event_uid": event_uid,
    }
    
    message = f"[{action}] {status}"
    if details:
        message += f": {json.dumps(details)}"
    
    logger.info(message, extra=extra)
