from base_api.modules.logger import get_logger
from selectolax.lexbor import LexborHTMLParser

HEADERS = {
    'Accept': '*/*',
    'Accept-Language': 'en,en-US',
    'Connection': 'keep-alive',
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/114.0',
    'Referer': 'https://www.thumbzilla.com/',
    'Origin': 'https://www.thumbzilla.com',
}

COOKIES = {
    'access': '1',
    'cookieConsent': '1',
    'platform': 'pc'
}

logger = get_logger(__name__)


from base_api.modules.static_functions import extract_video_grid



def extractor_search(html_content: str) -> list:
    return extract_video_grid(LexborHTMLParser(html_content), "https://www.thumbzilla.com", logger)
