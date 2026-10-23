"""Constants for the Extended Web Search integration."""

DOMAIN = "extended_web_search"
ADDON_NAME = "Extended Web Search"
API_NAME = "Extended Web Search"

# Configuration keys
CONF_SEARXNG_URL = "searxng_url"
CONF_NUM_RESULTS = "num_results"
CONF_MAX_CONTENT_LENGTH = "max_content_length"
CONF_REQUEST_TIMEOUT = "request_timeout"

# Defaults
DEFAULT_NUM_RESULTS = 5
DEFAULT_MAX_CONTENT_LENGTH = 8000
DEFAULT_REQUEST_TIMEOUT = 10

# Maximum number of bytes downloaded from a single page
MAX_DOWNLOAD_BYTES = 2_000_000

# Maximum number of redirects followed when fetching a page
MAX_REDIRECTS = 5

# Search results requested from SearXNG per wanted result, so failed fetches
# can be replaced by the next candidate
CANDIDATE_FACTOR = 2

# Time ranges and categories accepted by the search_web tool
TIME_RANGES = ["day", "week", "month", "year"]
CATEGORIES = ["general", "news", "science", "it"]
