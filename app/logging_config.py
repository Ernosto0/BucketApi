import os
import logging.config
from pythonjsonlogger import jsonlogger

def setup_logging():
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    log_format = os.getenv("LOG_FORMAT", "json")

    handlers = ['console']

    config = {
        'version': 1,
        'disable_existing_loggers': False,
        'formatters': {
            'json': {
                '()': jsonlogger.JsonFormatter,
                'format': '%(asctime)s %(name)s %(levelname)s %(message)s'
            },
            'simple': {
                'format': '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            }
        },
        'handlers': {
            'console': {
                'class': 'logging.StreamHandler',
                'formatter': log_format if log_format == 'json' else 'simple',
            }
        },
        'root': {
            'handlers': handlers,
            'level': log_level
        },
        'loggers': {
            'uvicorn': {
                'handlers': handlers,
                'level': log_level,
                'propagate': False
            },
            'gunicorn.error': {
                'handlers': handlers,
                'level': log_level,
                'propagate': False
            }
        }
    }

    logging.config.dictConfig(config)
