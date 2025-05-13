# core/config_loader.py
import configparser
import os
from dotenv import load_dotenv
import logging
logger = logging.getLogger(__name__)

_config_ini = None
_env_loaded = False

def load_configurations(config_file_path='config/main_config.ini', env_file_path=None):
    """
    Loads configurations from the .env file and the specified INI config file.
    Environment variables will override INI file settings if keys conflict.
    This function should ideally be called once at application startup.

    Args:
        config_file_path (str): Path to the main INI configuration file.
        env_file_path (str, optional): Path to the .env file. If None, dotenv
                                       will try to find it automatically.
    """
    global _config_ini, _env_loaded

    if not _env_loaded:
        if env_file_path:
            loaded = load_dotenv(dotenv_path=env_file_path, override=True)
            logger.debug(f".env file loaded from specified path: {env_file_path}, Loaded: {loaded}")
        else:
            loaded = load_dotenv(override=True)
            logger.debug(f".env file loaded from default path. Loaded: {loaded}")
        _env_loaded = True


    if _config_ini is None:
        _config_ini = configparser.ConfigParser()
        if not os.path.exists(config_file_path):
            logger.warning(f"INI config file not found at {config_file_path}. Proceeding without INI settings.")
            return
        try:
            _config_ini.read(config_file_path)
            logger.debug(f"INI config file '{config_file_path}' loaded successfully.")
        except configparser.Error as e:
            logger.error(f"Error reading INI config file {config_file_path}: {e}")
            _config_ini = configparser.ConfigParser()

def get_setting(section: str, key: str, default: str = None,
                is_bool: bool = False, is_int: bool = False, is_float: bool = False):
    """
    Retrieves a configuration setting.
    It first checks environment variables (format: SECTION_KEY or just KEY if section is 'General'),
    then the loaded INI configuration, and finally returns a default if provided.

    Args:
        section (str): The section in the INI file (e.g., 'General', 'Chrono24ScraperTool').
        key (str): The key within the section.
        default (str, optional): The default value to return if the key is not found.
        is_bool (bool, optional): If True, attempts to convert the value to a boolean.
        is_int (bool, optional): If True, attempts to convert the value to an integer.
        is_float (bool, optional): If True, attempts to convert the value to a float.

    Returns:
        The configuration value (str, bool, int, float, or the type of default).
    """
    if not _env_loaded or _config_ini is None :
        logger.debug("Configurations not loaded yet by get_setting. Loading now with default paths.")
        load_configurations()
    env_var_names_to_check = []
    env_var_key_upper = key.upper()
    section_upper = section.upper()

    if section_upper == 'GENERAL':
        env_var_names_to_check.append(env_var_key_upper) 
    env_var_names_to_check.append(f"{section_upper}_{env_var_key_upper}")

    value = None
    source = "default"

    for env_var_name in env_var_names_to_check:
        env_value = os.getenv(env_var_name)
        if env_value is not None:
            value = env_value
            source = f"env ('{env_var_name}')"
            break

    if value is None and _config_ini and _config_ini.has_option(section, key):
        value = _config_ini.get(section, key)
        source = f"ini ('{section}.{key}')"

    if value is None:
        if default is not None:
            value = default
            source = "default_value"
        else:
            logger.warning(f"Setting '{key}' in section '{section}' (env vars: {env_var_names_to_check}) not found and no default provided.")
            return None

    logger.debug(f"Setting '{section}.{key}': Found in '{source}'. Raw value: '{value}'")

    if value is not None:
        try:
            if is_bool:
                if isinstance(value, bool): return value
                return str(value).lower() in ['true', '1', 't', 'y', 'yes', 'on']
            elif is_int:
                return int(value)
            elif is_float:
                return float(value)
        except ValueError:
            logger.error(f"Could not convert '{value}' for '{section}.{key}' to specified type. Returning raw value or default if applicable.")
            if source == "default_value":
                 return default
            return value

    return value
if __name__ == "__main__":
    # This block is for testing the config_loader.py module independently.

    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    logger.info("--- Testing config_loader.py ---")

    test_env_file = ".env_test_cfg_loader"
    with open(test_env_file, "w") as f:
        f.write("APP_LOG_LEVEL=DEBUG\n")
        f.write("GENERAL_APP_NAME=WatchAgentSystemFromEnv\n")
        f.write("CHRONO24SCRAPERTOOL_MAX_RETRIES_PER_REQUEST=5\n")

    test_ini_dir = "config"
    test_ini_file = os.path.join(test_ini_dir, "main_config_test.ini")
    if not os.path.exists(test_ini_dir):
        os.makedirs(test_ini_dir)

    dummy_ini_content = """
[General]
app_name = WatchAgentSystemFromINI
default_request_timeout_seconds = 30
log_level = INFO

[Chrono24ScraperTool]
default_search_path = /search/index.htm
max_retries_per_request = 3
request_delay_seconds = 7.0
    """
    with open(test_ini_file, "w") as f:
        f.write(dummy_ini_content)

    load_configurations(config_file_path=test_ini_file, env_file_path=test_env_file)

    print("\nFetching settings:")
    app_name_env = get_setting('General', 'app_name')
    print(f"App Name: {app_name_env} (Expected: WatchAgentSystemFromEnv)")

    timeout_ini = get_setting('General', 'default_request_timeout_seconds', is_int=True)
    print(f"Default Timeout: {timeout_ini} (Expected: 30 from INI)")

    search_path_ini = get_setting('Chrono24ScraperTool', 'default_search_path')
    print(f"Search Path: {search_path_ini} (Expected: /search/index.htm from INI)")

    max_retries_env = get_setting('Chrono24ScraperTool', 'max_retries_per_request', is_int=True)
    print(f"Max Retries: {max_retries_env} (Expected: 5 from .env)")

    log_level_env = get_setting('General', 'log_level') # Checks APP_LOG_LEVEL or GENERAL_LOG_LEVEL in .env
    print(f"Log Level: {log_level_env} (Expected: DEBUG from .env)")

    delay_ini = get_setting('Chrono24ScraperTool', 'request_delay_seconds', is_float=True)
    print(f"Request Delay: {delay_ini} (Expected: 7.0 from INI, as not in .env_test_cfg_loader)")

    non_existent_setting = get_setting('NonExistentSection', 'non_existent_key')
    print(f"Non-existent setting (no default): {non_existent_setting} (Expected: None)")

    non_existent_with_default = get_setting('NonExistentSection', 'non_existent_key_default', default="my_default_value")
    print(f"Non-existent setting (with default): {non_existent_with_default} (Expected: my_default_value)")

    try:
        os.remove(test_env_file)
        os.remove(test_ini_file)
    except OSError as e:
        logger.warning(f"Could not remove test config files: {e}")
    logger.info("\n--- End of config_loader.py test ---")
