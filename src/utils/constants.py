import os

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../'))
DATA_DIR = os.path.join(ROOT_DIR, 'data')
CONFIG_PATH = os.path.join(DATA_DIR, 'config.json')
LOCAL_MIRROR_PATH = os.path.join(DATA_DIR, 'local_mirror.db')
LOGS_DIR = os.path.join(DATA_DIR, 'logs')
