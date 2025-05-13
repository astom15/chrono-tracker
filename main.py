import asyncio
import logging
from core.logging_config import setup_logging
from core.config_loader import load_configurations, get_setting

async def main_async_logic():
    logger = logging.getLogger(__name__)
    logger.info("Main app started.")
    app_name = get_setting('General', 'app_name', default='DefaultMCPApp')
    logger.info(f"Application Name from config: {app_name}")
    await asyncio.sleep(1)
    logger.info("Main app finishing.")

if __name__ == "__main__":
    load_configurations()
    log_level_strength = get_setting("General", "log_level", is_int=True).upper()
    numeric_log_level = getattr(logging, log_level_strength, logging.INFO)
    setup_logging(numeric_log_level)
    app_logger = logging.getLogger("MainApp")
    try:
        asyncio.run(main_async_logic())
    except KeyboardInterrupt:
        app_logger.info("Main app interrupted by user. Exiting...")
    except Exception as e:
        app_logger.error(f"An error occurred: {e}")
