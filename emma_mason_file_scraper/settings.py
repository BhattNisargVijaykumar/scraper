import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

BOT_NAME = 'emma_mason_file_scraper'

FETCHER_MODULES = ['emma_mason_file_scraper.fetcher']
NEWFETCHER_MODULE = 'emma_mason_file_scraper.fetcher'

ROBOTSTXT_OBEY = False

CONCURRENT_REQUESTS = int(os.getenv('MAX_WORKERS', '16'))
CONCURRENT_REQUESTS_PER_DOMAIN = 8

DOWNLOAD_DELAY = float(os.getenv('DOWNLOAD_DELAY', '0.5'))
RANDOMIZE_DOWNLOAD_DELAY = True

COOKIES_ENABLED = False

HTTPCACHE_ENABLED = False

REQUEST_FINGERPRINTER_IMPLEMENTATION = '2.7'
TWISTED_REACTOR = 'twisted.internet.asyncioreactor.AsyncioSelectorReactor'
FEED_EXPORT_ENCODING = 'utf-8'

LOG_LEVEL = 'INFO'
LOG_ENABLED = True
LOG_FILE = None
LOG_FORMAT = '%(asctime)s [%(name)s] %(levelname)s: %(message)s'
LOG_DATEFORMAT = '%Y-%m-%d %H:%M:%S'
LOG_STDOUT = True

FTP_HOST = os.getenv('FTP_HOST', '')
FTP_USER = os.getenv('FTP_USER', '')
FTP_PASS = os.getenv('FTP_PASS', '')
FTP_PATH = os.getenv('FTP_PATH', '/uploads/')

OUTPUT_DIR = 'output'
