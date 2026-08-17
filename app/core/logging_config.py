import logging
import json

class JSONFormatter(logging.Formatter):
    """
    Structured JSON logger for production.
    Masks sensitive fields to prevent credential leaking.
    """
    SENSITIVE_KEYS = {"access_token", "password", "whatsapp_access_token", "api_token"}

    def format(self, record):
        log_record = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage()
        }

        # Handle exception tracebacks securely
        if record.exc_info:
            log_record["exception"] = self.formatException(record.exc_info)
            # Extra safety: mask sensitive keys in exception strings
            for key in self.SENSITIVE_KEYS:
                if key in log_record["exception"]:
                    log_record["exception"] = log_record["exception"].replace(key, "[MASKED_KEY]")

        # Mask sensitive keys in extra fields if any were passed
        if hasattr(record, "extra_args") and isinstance(record.extra_args, dict):
            safe_args = {}
            for k, v in record.extra_args.items():
                if k.lower() in self.SENSITIVE_KEYS:
                    safe_args[k] = "***MASKED***"
                else:
                    safe_args[k] = v
            log_record["extra"] = safe_args

        return json.dumps(log_record)

def setup_logging():
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    
    # Remove existing handlers to avoid duplicates
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        
    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter())
    logger.addHandler(handler)
    
    return logger
