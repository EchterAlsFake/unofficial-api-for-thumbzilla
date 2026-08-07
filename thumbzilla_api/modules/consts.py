import logging
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

# Set up logging configuration
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_text_safe(node, selector):
    """Safely extract and strip text from a CSS selector."""
    target = node.css_first(selector)
    if target:
        text = target.text(strip=True)
        return text if text else None
    return None


def get_attr_safe(node, selector, attr):
    """Safely extract an attribute from a CSS selector."""
    target = node.css_first(selector) if selector else node
    if target and target.attributes:
        val = target.attributes.get(attr)
        return val if val else None
    return None


def extractor_search(html_content: str) -> list:
    """
    Extracts comprehensive video attributes from HTML search results.
    Returns a list of dictionaries.
    """
    results = []
    parser = LexborHTMLParser(html_content)

    # 1. Locate the main container gracefully
    stuff = parser.css_first("div.searchResults.full-row-thumbs.js_video_row.tm_search_result_videos")
    if not stuff:
        stuff = parser.css_first("div.full-row-thumbs")
    if not stuff:
        stuff = parser.css_first("ul.videos_grid")

    if not stuff:
        logger.error("Main video container not found in HTML. Aborting extraction.")
        return results

    # 2. Locate the video boxes
    videos = stuff.css("article.video-box.pc.js_video-box.js-pop")
    if not videos:
        videos = stuff.css("a.video_link.tm_video_link.js_wrap_trigger_login.js_mpop.js-pop")

    if not videos:
        logger.warning("Container found, but no video elements were matched inside.")
        return results
    # 3. Iterate and Extract
    for index, video in enumerate(videos, start=1):
        # Base extraction using data-attributes (most reliable) and falling back to text/children
        video_data = {
            "video_id": get_attr_safe(video, None, "data-video-id"),
            "title": get_attr_safe(video, None, "aria-label") or get_text_safe(video, ".video-title-text span"),
            "video_url": get_attr_safe(video, "a", "href"),
            "duration": get_text_safe(video, ".video-duration span"),
            "author_name": get_attr_safe(video, None, "data-uploader-name") or get_text_safe(video,
                                                                                               ".author-title-text"),
            "uploader_url": get_attr_safe(video, ".author-title-text", "href"),
            "thumbnail": get_attr_safe(video, "img.thumb-image", "data-src") or get_attr_safe(video,
                                                                                                  "img.thumb-image",
                                                                                                  "src"),
            "preview_video_url": get_attr_safe(video, "img.thumb-image", "data-mediabook"),
        }

        # Extract the list of performers separately
        performer_nodes = video.css(".channel-performer")
        performers = [p.text(strip=True) for p in performer_nodes] if performer_nodes else []
        video_data["performers"] = performers if performers else None
        # Clean up and validate specific fields

        if video_data["video_url"]:
            video_data["url"] = f"https://www.thumbzilla.com{video_data['video_url']}"

        # 4. Handle Edge Cases & Logging
        missing_attrs = [key for key, value in video_data.items() if value is None]
        video_data.pop("video_url")
        if missing_attrs:
            # Create a useful identifier for the log (use video_id if it exists, else the loop index)
            identifier = video_data.get('video_id') or f"Index #{index}"
            logger.warning(f"Video [{identifier}] is missing attributes: {', '.join(missing_attrs)}")
        if video_data.get("url"):
            results.append(video_data)

    return results
