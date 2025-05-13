import logging
import logging.handlers
import os
from datetime import datetime

LOG_DIR = "logs"
def setup_logging(log_level=logging.INFO, tool_name=None):
    if not os.path.exists(LOG_DIR):
        os.makedirs(LOG_DIR)

    log_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    log_formatter.converter = lambda *args:datetime.utcnow().timetuple()
    
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(log_formatter)
    console_handler.setLevel(log_level)

    if tool_name:
        log_file_name = os.path.join(LOG_DIR, f"{tool_name.lower().replace(' ', '_')}.log")
    else:
        log_file_name = os.path.join(LOG_DIR,"app.log")
    
    file_handler = logging.handlers.TimedRotatingFileHandler(
        log_file_name, when="midnight", interval=1, backupCount=7, encoding="utf-8",
    )
    file_handler.setFormatter(log_formatter)
    file_handler.setLevel(log_level)

    app_logger = logging.getLogger()
    if not app_logger.handlers:
        app_logger.setLevel(log_level)
        app_logger.addHandler(console_handler)
        app_logger.addHandler(file_handler)
        app_logger.info(f"Logging setup complete. Log level: {logging.getLevelName(log_level)}. Logging to: {log_file_name}")
    else:
        app_logger.setLevel(log_level)
        #might need to revisit depending on how i call the logging function per agent


def get_tool_logger(tool_name: str, level=logging.INFO):
    logger = logging.getLogger(tool_name)
    return logger
