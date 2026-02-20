from logger import setup_logger

logger = setup_logger(
    name="temperature-monitor",
    console_levels=["INFO", "ERROR", "CRITICAL"]  # Only these show in console, any of them can be removed.
)

# 'python3 import_log_example.py' to test output!
logger.info("System starting...")
logger.error("Sensor failed")
logger.critical("System shutdown")