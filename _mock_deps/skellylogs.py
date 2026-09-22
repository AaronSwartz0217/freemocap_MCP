import logging
class LogLevels:
    TRACE = logging.DEBUG
    DEBUG = logging.DEBUG
    INFO = logging.INFO
    WARNING = logging.WARNING
    ERROR = logging.ERROR
def configure_logging(level=None):
    logging.basicConfig(level=level or logging.INFO)
