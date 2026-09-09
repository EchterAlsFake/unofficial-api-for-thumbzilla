from __future__ import annotations
import os
import re
import copy
import json
import asyncio
import logging
import argparse
import urllib.parse

from base_api.modules.logger import configure_app_logging

from base_api.modules.static_functions import str_to_bool

from dataclasses import dataclass
from curl_cffi import AsyncSession
from typing import AsyncGenerator, ClassVar
from selectolax.lexbor import LexborHTMLParser
from base_api.modules.config import IteratorConfig
from base_api.modules.type_hints import DownloadReport
from base_api import (BaseCore, BaseMedia, DownloadConfigHLS, ErrorAction, ErrorMode, Helper,
    MediaLoadError, MediaLoadErrors, ScrapeErrorContext, ScrapeResult, media_field,
    make_iterator_config, is_resource_gone, default_on_error, scrape_stream, build_m3u8_master,
    parse_duration,
)
from base_api.modules.errors import (DownloadCancelled, BotProtectionDetected, HTTPStatusError, InvalidProxy, NetworkRequestError,
                                     ResourceGone, UnknownError,
)
from thumbzilla_api.modules.errors import (NotFound, ProxyError, NetworkError, UnknownNetworkError, BotDetection,
                                           DownloadFailed)
from thumbzilla_api.modules.consts import HEADERS, COOKIES, extractor_search

logger = logging.getLogger("Thumbzilla API")


_contains_resource_gone = is_resource_gone
on_error = default_on_error


async def get_html_content(core: BaseCore, url: str) -> str:
    try:
        return await core.fetch_text(url)

    except HTTPStatusError as e:
        logger.exception("Request failed for %s: %s", url, e)
        if e.status_code == 404:
            raise NotFound(f"Server returned 404 for: {url}") from e
        raise NetworkError(f"Request failed for {url}: {e}") from e

    except NetworkRequestError as e:
        logger.exception("Request failed for %s: %s", url, e)
        raise NetworkError(f"Request failed for {url}: {e}") from e

    except InvalidProxy as e:
        logger.exception("Request failed for %s: %s", url, e)
        raise ProxyError(f"Request failed for {url}: {e}") from e

    except BotProtectionDetected as e:
        logger.exception("Request failed for %s: %s", url, e)
        raise BotDetection(f"Request failed for {url}: {e}") from e

    except UnknownError as e:
        logger.exception("Request failed for %s: %s", url, e)
        raise UnknownNetworkError(f"Request failed for {url}: {e}") from e

    except Exception:
        logger.exception("Failed to fetch or decode response for %s", url)
        raise

@dataclass(kw_only=True, slots=True)
class Video(BaseMedia):
    url: str
    core: BaseCore
    video_id: str | None = media_field("html")
    duration: str | int | None = media_field("html")
    thumbnail: str | None = media_field("html")
    embed_url: str | None = media_field("html")
    views: str | None = media_field("html")
    publish_date: str | None = media_field("html")
    publish_date_thumbnail: str | None = media_field("html")
    description: str | None = media_field("html")
    title: str | None = media_field("html")
    author_name: str | None = media_field("html")
    m3u8_url: str | None = media_field("html")
    m3u8_base_url: str | None = media_field("html")
    media_definitions: list[dict] | None = media_field("html")

    # Optional
    preview_video_url: str | None = None
    performers: list[str] | None = None
    uploader_url: str | None = None

    loader_methods: ClassVar[dict[str, str]] = {"html": "_load_html"}
    LAYOUT_ANCHORS: ClassVar[tuple[str, ...]] = (
        "#mainContent",
        "#watch-container",
        "#videoContainer",
    )

    async def _load_html(self) -> dict[str, object]:
        html_content = await get_html_content(url=self.url, core=self.core)
        data: dict = await asyncio.to_thread(self._extract_html, html_content)
        m3u8_url = data.get("m3u8_url")
        if not isinstance(m3u8_url, str):
            logger.warning("No HLS metadata URL found for %s", self.url)
            data["m3u8_base_url"] = None
        else:
            try:
                stuff = await get_html_content(core=self.core, url=m3u8_url)
                data["m3u8_base_url"] = self.get_m3u8_base_url(stuff)
            except Exception as e:
                logger.warning("Failed to fetch or build master m3u8 for %s: %s", self.url, e)
                data["m3u8_base_url"] = None
        return data

    def _parse_player_config(self, html_content: str) -> dict:
        idx = html_content.find("playervars:")
        if idx != -1:
            brace_idx = html_content.find("{", idx)
            if brace_idx != -1:
                try:
                    obj, _ = json.JSONDecoder().raw_decode(html_content[brace_idx:])
                    if isinstance(obj, dict):
                        return obj
                except Exception as e:
                    logger.warning("Failed to decode playervars JSON for %s: %s", self.url, e)

        match = re.search(r"mediaDefinitions?\s*:\s*(\[)", html_content)
        if match:
            try:
                arr, _ = json.JSONDecoder().raw_decode(html_content[match.start(1):])
                if isinstance(arr, list):
                    return {"mediaDefinitions": arr}
            except Exception as e:
                logger.warning("Failed to decode mediaDefinitions for %s: %s", self.url, e)

        return {}

    def _extract_html(self, html_content: str) -> dict:
        parser = LexborHTMLParser(html_content)

        # Verify layout anchors to detect page layout changes
        for anchor in self.LAYOUT_ANCHORS:
            if not parser.css_first(anchor):
                logger.warning(
                    "Layout anchor '%s' not found for %s. Page structure may have changed.",
                    anchor,
                    self.url,
                )

        config = self._parse_player_config(html_content)

        # Parse application/ld+json metadata if available
        video_obj: dict = {}
        image_obj: dict = {}
        ld_script = parser.css_first('script[type="application/ld+json"]')
        if ld_script:
            try:
                ld_data = json.loads(ld_script.text())
                graph = ld_data.get("@graph", [])
                if isinstance(graph, list):
                    for item in graph:
                        if isinstance(item, dict):
                            item_type = item.get("@type")
                            if item_type == "VideoObject":
                                video_obj = item
                            elif item_type == "ImageObject":
                                image_obj = item
                elif isinstance(ld_data, dict) and ld_data.get("@type") == "VideoObject":
                    video_obj = ld_data
            except Exception as e:
                logger.warning("Failed to parse application/ld+json for %s: %s", self.url, e)

        # Video ID
        video_id = None
        watch_el = parser.css_first("#watch-container, div[data-video-id]")
        if watch_el:
            video_id = watch_el.attributes.get("data-video-id")
        if not video_id:
            video_id = config.get("viewkey")
        if not video_id and config.get("link_url"):
            m = re.search(r'watch/(\d+)', config["link_url"])
            if m:
                video_id = m.group(1)
        if not video_id:
            m = re.search(r'viewkey\s*:\s*[\'"](\d+)[\'"]', html_content)
            if m:
                video_id = m.group(1)
        if not video_id and self.url:
            m = re.search(r'(?:watch|video)/(\d+)', self.url)
            if m:
                video_id = m.group(1)
        if not video_id:
            logger.warning("Could not extract video_id for %s", self.url)

        # Title
        title = config.get("video_title") or video_obj.get("name") or image_obj.get("name")
        if not title:
            title_el = parser.css_first("h1.videoTitle, h1.tm_videoTitle, h1")
            title = title_el.text(strip=True) if title_el else None
        if not title:
            m = re.search(r'(?:video_title|title)\s*:\s*[\'"]([^\'"]+)[\'"]', html_content)
            if m:
                title = m.group(1)
        if not title:
            logger.warning("Could not extract title for %s", self.url)

        # Duration
        raw_duration = config.get("video_duration") or config.get("duration") or video_obj.get("duration")
        if raw_duration is None:
            m = re.search(r'(?:video_duration|duration)\s*:\s*[\'"]?(\d+)[\'"]?', html_content)
            if m:
                raw_duration = m.group(1)
        duration = None
        if raw_duration is not None:
            duration = parse_duration(raw_duration)
        if duration is None:
            dur_el = parser.css_first("span.mgp_duration, .video-properties .video-duration span")
            if dur_el:
                duration = parse_duration(dur_el.text(strip=True))
        if duration is None:
            logger.warning("Could not extract duration for %s", self.url)

        # Thumbnail
        thumbnail = (
            config.get("image_url")
            or config.get("poster")
            or video_obj.get("thumbnailUrl")
            or image_obj.get("contentUrl")
            or image_obj.get("thumbnail")
        )
        if not thumbnail:
            poster_el = parser.css_first("link[as='image'], img.videoElementPoster, .mgp_videoPoster img")
            if poster_el:
                thumbnail = poster_el.attributes.get("href") or poster_el.attributes.get("src")
        if not thumbnail:
            m = re.search(r'(?:image_url|poster)\s*:\s*[\'"]([^\'"]+)[\'"]', html_content)
            if m:
                thumbnail = m.group(1)
        if not thumbnail:
            logger.warning("Could not extract thumbnail for %s", self.url)

        # Embed URL
        embed_url = video_obj.get("embedUrl")
        if not embed_url:
            embed_code = config.get("embedCode")
            if not embed_code:
                textarea = parser.css_first("textarea.embed-textarea")
                if textarea:
                    embed_code = textarea.text()
            if embed_code:
                m = re.search(r'src=[\'"]([^\'"]+)[\'"]', embed_code)
                if m:
                    src = m.group(1)
                    embed_url = src if src.startswith("http") else f"https://www.thumbzilla.com{src}"
        if not embed_url and video_id:
            embed_url = f"https://www.thumbzilla.com/embed/{video_id}/"
        if not embed_url:
            logger.warning("Could not extract embed_url for %s", self.url)

        # Views
        views = None
        view_el = parser.css_first(".feature-actionViews span.infoValue, span.tm_infoValue")
        if view_el:
            views = view_el.text(strip=True)
        elif video_obj.get("interactionCount") is not None:
            views = str(video_obj.get("interactionCount"))
        if not views:
            logger.warning("Could not extract views for %s", self.url)

        # Publish date
        publish_date = None
        date_el = parser.css_first("span.publishedDate")
        if date_el:
            publish_date = date_el.text(strip=True)
        elif video_obj.get("uploadDate"):
            publish_date = video_obj.get("uploadDate")
        if not publish_date:
            logger.warning("Could not extract publish_date for %s", self.url)

        publish_date_thumbnail = image_obj.get("datePublished") or publish_date

        # Description
        description = video_obj.get("description") or image_obj.get("description")
        if not description:
            meta_desc = parser.css_first("meta[name='description'], meta[property='og:description']")
            if meta_desc:
                description = meta_desc.attributes.get("content")

        # Author name
        author_name = image_obj.get("author") or video_obj.get("author")
        author_el = parser.css_first(".video-uploaderInfoPanel .submitByLink a, .submitByLink a")
        if not author_name and author_el:
            author_name = author_el.text(strip=True)
        if not author_name:
            avatar_el = parser.css_first("img.userAvatar")
            if avatar_el:
                author_name = avatar_el.attributes.get("alt")
        if not author_name:
            logger.warning("Could not extract author_name for %s", self.url)

        # Media definitions
        media_definitions = config.get("mediaDefinitions") or config.get("mediaDefinition") or []
        if not media_definitions:
            match = re.search(r"mediaDefinitions?\s*:\s*(\[)", html_content)
            if match:
                try:
                    arr, _ = json.JSONDecoder().raw_decode(html_content[match.start(1):])
                    if isinstance(arr, list):
                        media_definitions = arr
                except Exception as e:
                    logger.warning("Failed to decode mediaDefinitions for %s: %s", self.url, e)
        if not media_definitions:
            logger.warning("No media definitions found for %s", self.url)

        # HLS m3u8 URL
        m3u8_url = None
        for media in media_definitions:
            if isinstance(media, dict) and media.get("format") == "hls":
                video_url = media.get("videoUrl")
                if video_url:
                    m3u8_url = video_url if str(video_url).startswith("http") else f"https://www.thumbzilla.com{video_url}"
                    break
        if not m3u8_url:
            logger.warning("No HLS videoUrl found for %s", self.url)

        return {
            "video_id": video_id,
            "duration": duration,
            "thumbnail": thumbnail,
            "embed_url": embed_url,
            "views": views,
            "publish_date": publish_date,
            "publish_date_thumbnail": publish_date_thumbnail,
            "description": description,
            "title": title,
            "author_name": author_name,
            "m3u8_url": m3u8_url,
            "media_definitions": media_definitions,
        }

    @staticmethod
    def get_m3u8_base_url(stuff) -> str | None:
        """Convenience property to quickly get the main HLS adaptive stream path."""
        return build_m3u8_master(stuff)

    async def download(self, configuration: DownloadConfigHLS) -> bool | DownloadReport:
        try:
            await self.load_fields("title", "m3u8_base_url")
            if not self.m3u8_base_url:
                raise DownloadFailed(f"Cannot download video without m3u8_base_url: {self.url}")
            config = copy.deepcopy(configuration)
            config.m3u8_base_url = self.m3u8_base_url

            if not config.no_title:
                config.path = os.path.join(config.path, f"{self.title}.mp4")

            return await self.core.download(config)
        except DownloadCancelled:
            raise
        except Exception as e:
            logger.exception("Download failed for %s: %s", self.url, e)
            raise DownloadFailed(f"Download failed for {self.url}: {e}") from e


@dataclass(kw_only=True, slots=True)
class Playlist(BaseMedia):
    url: str
    core: BaseCore
    title: str | None = media_field("html")
    author_name: str | None = media_field("html")
    rating_percent: str | None = media_field("html")
    rating_count: str | None = media_field("html")
    views: str | None = media_field("html")
    videos_count: str | None = media_field("html")

    loader_methods: ClassVar[dict[str, str]] = {"html": "_load_html"}

    async def _load_html(self) -> dict[str, object]:
        html_content = await get_html_content(url=self.url, core=self.core)
        return await asyncio.to_thread(self._extract_html, html_content)

    @staticmethod
    def _extract_html(html_content: str) -> dict:
        parser = LexborHTMLParser(html_content)

        title = parser.css_first("h1#playlist_title").text(strip=True)
        author_name = parser.css_first("p.playlist_desc").css_first("a").text(strip=True)
        rating_percent = parser.css_first("div.rating_percent.js_rating_percent").text(strip=True)
        rating_count = parser.css_first("span.playlist_stats_value").text(strip=True)
        views = parser.css("span.playlist_stats_value")[1].text(strip=True)
        video_count = parser.css("span.playlist_stats_value")[2].text(strip=True)

        return {
            "title": title,
            "author_name": author_name,
            "rating_percent": rating_percent,
            "rating_count": rating_count,
            "views": views,
            "videos_count": video_count
        }

    def get_videos(self, pages: int = 2, iterator_config: IteratorConfig | None = None) -> AsyncGenerator[ScrapeResult[Video], None]:
        url = self.url
        page_urls = [f"{url}&page={page}" for page in range(1, pages + 1)]
        return scrape_stream(
            core=self.core,
            constructor=Video,
            target_page_urls=page_urls,
            item_extractor=extractor_search,
            iterator_config=iterator_config,
        )


@dataclass(kw_only=True, slots=True)
class UserHelper(BaseMedia):
    url: str
    core: BaseCore
    name: str | None = media_field("html")
    rank: str | None = media_field("html")
    views: str | None = media_field("html")
    videos_count: str | None = media_field("html")
    banner_url: str | None = media_field("html")
    avatar_url: str | None = media_field("html")
    bio: str | None = media_field("html")
    verified: bool = media_field("html")

    loader_methods: ClassVar[dict[str, str]] = {"html": "_load_html"}
    LAYOUT_ANCHORS: ClassVar[tuple[str, ...]] = (
        "#mainContent",
        ".header-banner-wrapper",
        ".main-information",
    )

    async def _load_html(self) -> dict[str, object]:
        html_content = await get_html_content(core=self.core, url=self.url)
        return await asyncio.to_thread(self._extract_html, html_content)

    def _extract_html(self, html_content: str) -> dict[str, object]:
        parser = LexborHTMLParser(html_content)

        # Verify layout anchors to detect page layout changes
        for anchor in self.LAYOUT_ANCHORS:
            if not parser.css_first(anchor):
                logger.warning(
                    "Layout anchor '%s' not found for %s. Page structure may have changed.",
                    anchor,
                    self.url,
                )

        # Name
        name = None
        name_el = parser.css_first("h1.name-title, .name-wrapper h1, h1")
        if name_el:
            name = name_el.text(strip=True)
        if not name:
            match = re.search(r'username:\s*["\']([^"\']+)["\']', html_content)
            if match:
                name = match.group(1)
        if not name:
            meta_title = parser.css_first("meta[property='og:title'], meta[name='twitter:title']")
            if meta_title:
                name = meta_title.attributes.get("content")
        if not name:
            logger.warning("Could not extract name for %s: %s", self.__class__.__name__, self.url)

        # Banner URL
        banner_el = parser.css_first(".banner-wrapper img, .header-banner-wrapper .banner-wrapper img")
        banner_url = (banner_el.attributes.get("data-src") or banner_el.attributes.get("src")) if banner_el else None

        # Avatar / Logo URL
        avatar_el = parser.css_first(".avatar-wrapper img, .logo-wrapper img")
        avatar_url = (avatar_el.attributes.get("data-src") or avatar_el.attributes.get("src")) if avatar_el else None

        # Verified badge
        verified = bool(
            parser.css_first(
                ".name-wrapper .icon-checkmark-recommended, .name-wrapper .icon-checkmark, .icon-checkmark-recommended"
            )
        )

        # Stats: rank, views, videos_count
        rank = None
        views = None
        videos_count = None

        for stat in parser.css(".main-stats-bar .info-stat, .stats-bar-wrapper .info-stat"):
            lbl_el = stat.css_first(".info-stat-label")
            val_el = stat.css_first(".info-stat-data")
            if not val_el:
                continue
            val = val_el.text(strip=True)
            lbl = lbl_el.text(strip=True).lower() if lbl_el else ""
            if "rank" in lbl:
                rank = val
            elif "view" in lbl:
                views = val
            elif "video" in lbl:
                videos_count = val

        # Bio / description
        bio_el = parser.css_first(".profile-bio, #aboutChannel .channel-description, #DrawerProfileInfo .profile-bio")
        bio = bio_el.text(strip=True) if bio_el else None

        return {
            "name": name,
            "rank": rank,
            "views": views,
            "videos_count": videos_count,
            "banner_url": banner_url,
            "avatar_url": avatar_url,
            "bio": bio,
            "verified": verified,
        }

    def get_videos(
        self,
        pages: int = 2,
        iterator_config: IteratorConfig | None = None,
        iterator_configuration: IteratorConfig | None = None,
    ) -> AsyncGenerator[ScrapeResult[Video], None]:
        config = iterator_config or iterator_configuration
        if config is None:
            config = make_iterator_config()
        url = self.url
        sep = "&" if "?" in url else "?"
        page_urls = [f"{url}{sep}page={page}" for page in range(1, pages + 1)]
        return scrape_stream(
            core=self.core,
            constructor=Video,
            target_page_urls=page_urls,
            item_extractor=extractor_search,
            iterator_config=config,
        )


@dataclass(kw_only=True, slots=True)
class Pornstar(UserHelper):
    pornstar_information: dict[str, str] | None = media_field("html")
    featured_in: list[str] | None = media_field("html")
    more_of_me: str | None = media_field("html")

    LAYOUT_ANCHORS: ClassVar[tuple[str, ...]] = (
        "#mainContent",
        "#profileInfo",
        ".header-banner-wrapper",
        ".main-information",
    )

    def _extract_html(self, html_content: str) -> dict[str, object]:
        data = UserHelper._extract_html(self, html_content)
        parser = LexborHTMLParser(html_content)

        # Full stats / profile info (from profile-info and main-stats-bar)
        info: dict[str, str] = {}
        for stat in parser.css(".info-stat"):
            lbl = stat.css_first(".info-stat-label")
            val = stat.css_first(".info-stat-data")
            if lbl and val:
                k = lbl.text(strip=True)
                v = val.text(strip=True)
                if k and v:
                    info[k] = v
        data["pornstar_information"] = info

        # Featured in (channels)
        data["featured_in"] = list(
            dict.fromkeys(
                a.text(strip=True)
                for a in parser.css(".known-for-tag a, .known-for-wrapper a")
                if a.text(strip=True)
            )
        )

        # More of Me external link
        more_el = parser.css_first(".profile-more-of-me a, .more-of-me a")
        more_url = None
        if more_el:
            raw_href = more_el.attributes.get("href", "")
            if "/redirect/" in raw_href:
                more_url = urllib.parse.unquote(raw_href.split("/redirect/", 1)[1])
            else:
                more_url = raw_href
        data["more_of_me"] = more_url

        return data


@dataclass(kw_only=True, slots=True)
class Amateur(UserHelper):
    pass


@dataclass(kw_only=True, slots=True)
class Channel(UserHelper):
    join_url: str | None = media_field("html")

    LAYOUT_ANCHORS: ClassVar[tuple[str, ...]] = (
        "#mainContent",
        ".header-banner-wrapper",
        ".main-information",
    )

    def _extract_html(self, html_content: str) -> dict[str, object]:
        data = UserHelper._extract_html(self, html_content)
        parser = LexborHTMLParser(html_content)

        join_btn = parser.css_first(".channel-buttons-wrapper a.join-wrapper, .join-us a.join-wrapper, a.join-wrapper")
        data["join_url"] = join_btn.attributes.get("href") if join_btn else None

        return data


class Client:
    def __init__(self, core: BaseCore | None = None):
        if core is None:
            core = BaseCore()
        self.core = core
        self.core.initialize_session()
        assert isinstance(self.core.session, AsyncSession)
        self.core.session.headers.update(HEADERS)
        self.core.session.cookies.update(COOKIES)

    async def get_video(self, url: str, load_html: bool = True) -> Video:
        video = Video(core=self.core, url=url)
        if load_html:
            await video.load_sources("html")
        return video

    async def get_pornstar(self, url: str, load_html: bool = True) -> Pornstar:
        pornstar = Pornstar(core=self.core, url=url)
        if load_html:
            await pornstar.load_sources("html")
        return pornstar

    async def get_playlist(self, url: str, load_html: bool = True) -> Playlist:
        playlist = Playlist(core=self.core, url=url)
        if load_html:
            await playlist.load_sources("html")
        return playlist

    async def get_channel(self, url: str, load_html: bool = True) -> Channel:
        channel = Channel(core=self.core, url=url)
        if load_html:
            await channel.load_sources("html")
        return channel

    async def get_amateur(self, url: str, load_html: bool = True) -> Amateur:
        amateur = Amateur(core=self.core, url=url)
        if load_html:
            await amateur.load_sources("html")
        return amateur

    def search(
            self,
            query: str,
            pages: int = 2,
            iterator_config: IteratorConfig | None = None,
            iterator_configuration: IteratorConfig | None = None) -> AsyncGenerator[ScrapeResult[Video], None]:
        config = iterator_config or iterator_configuration
        page_urls = [f"https://thumbzilla.com/search/?query={query}&page={page}" for page in range(1, pages + 1)]
        return scrape_stream(
            core=self.core,
            constructor=Video,
            target_page_urls=page_urls,
            item_extractor=extractor_search,
            iterator_config=config,
        )



def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Thumbzilla API Command Line Interface")
    parser.add_argument("--download", metavar="URL", type=str, help="URL to download from")
    parser.add_argument("--quality", metavar="best|half|worst", type=str, default="best", help="The video quality (best, half, worst)")
    parser.add_argument("--file", metavar="FILE", type=str, help="(Optional) Specify a file with URLs (separated with new lines)")
    parser.add_argument("--output", metavar="DIR", type=str, required=True, help="The output path (with filename or directory)")
    parser.add_argument("--no-title", metavar="True,False", type=str, nargs="?", const="True", default="False",
                        help="Whether to apply video title automatically to output path or not")
    return parser


async def run_main(args_list: list[str] | None = None):
    parser = create_parser()
    args = parser.parse_args(args_list)
    no_title = str_to_bool(args.no_title) if isinstance(args.no_title, str) else bool(args.no_title)
    config = DownloadConfigHLS(quality=args.quality, path=args.output, no_title=no_title)

    urls: list[str] = []
    if args.download:
        urls.append(args.download)
    if args.file:
        with open(args.file, "r") as f:
            urls.extend([line.strip() for line in f if line.strip()])

    if not urls:
        parser.print_help()
        return

    client = Client()
    for url in urls:
        print(f"Fetching video information for: {url}")
        try:
            video = await client.get_video(url, load_html=True)
            title = getattr(video, "title", None) or url
            print(f"Starting download for: {title}")
            await video.download(configuration=config)
            print(f"Download complete: {title}")
        except Exception as e:
            logger.exception("CLI failed while processing %s", url)
            print(f"Error downloading {url}: {e}")


def main():
    configure_app_logging(level=logging.INFO)
    try:
        asyncio.run(run_main())
    except KeyboardInterrupt:
        print("\nOperation cancelled by user.")


if __name__ == "__main__":
    main()
