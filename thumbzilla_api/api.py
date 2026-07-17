from __future__ import annotations
import os
import re
import copy
import json
import asyncio
import logging

from typing import AsyncGenerator
from dataclasses import dataclass, fields
from curl_cffi import Response, AsyncSession
from selectolax.lexbor import LexborHTMLParser
from base_api.modules.type_hints import DownloadReport
from base_api import BaseCore, Helper, BaseMedia, DownloadConfigHLS, ScrapeResult
from base_api.modules.errors import InvalidProxy, UnknownError, NetworkRequestError, BotProtectionDetected, ResourceGone

from thumbzilla_api.modules.errors import (NotFound, ProxyError, NetworkError, UnknownNetworkError, BotDetection,
                                           DownloadFailed)
from thumbzilla_api.modules.consts import HEADERS, COOKIES, extractor_search
from thumbzilla_api.modules.type_hints import on_error_hint

logger = logging.getLogger("Thumbzilla API")

async def on_error(url: str, error: Exception, attempt: int) -> bool:
    logger.warning(f"URL: {url}, ERROR: {error}, Attempt: {attempt}")

    if isinstance(error, ResourceGone):
        return False

    return True


async def get_html_content(core: BaseCore, url: str) -> str | None | dict:
    try:
        content = await core.fetch(url)
        if isinstance(content, str):
            return content

        if isinstance(content, Response):
            if content.status_code == 404:
                raise NotFound(f"Server returned 404 for: {url}")

    except NetworkRequestError as e:
        raise NetworkError(str(e)) from e

    except InvalidProxy as e:
        raise ProxyError(str(e)) from e

    except BotProtectionDetected as e:
        raise BotDetection(str(e)) from e

    except UnknownError as e:
        raise UnknownNetworkError(str(e)) from e

@dataclass(kw_only=True, slots=True)
class Video(BaseMedia):
    url: str
    core: BaseCore
    video_id: str | None = None
    duration: str | None = None
    thumbnail: str | None = None
    embed_url: str | None = None
    views: str | None = None
    publish_date: str | None = None
    publish_date_thumbnail: str | None = None
    description: str | None = None
    title: str | None = None
    author_name: str | None = None
    m3u8_url: str | None = None
    m3u8_base_url: str | None = None
    media_definitions: dict | None = None

    # Optional
    preview_video_url: str | None = None
    performers: list[str] | None = None
    uploader_url: str | None = None

    async def _perform_load(self, api: bool, html: bool, anything_else: bool):
        if html:
            await asyncio.gather(self._fetch_html())

    async def _fetch_html(self):
        html_content = await get_html_content(url=self.url, core=self.core)
        assert isinstance(html_content, str)
        data: dict = await asyncio.to_thread(self._extract_html, html_content)
        allowed_fields = {field.name for field in fields(self)}

        for key, value in data.items():
            if key in allowed_fields:
                setattr(self, key, value)


        stuff = await get_html_content(core=self.core, url=self.m3u8_url)
        self.m3u8_base_url = self.get_m3u8_base_url(stuff)

    def _extract_html(self, html_content: str) -> dict:
        parser = LexborHTMLParser(html_content)

        stuff = parser.css_first('script[type="application/ld+json"]').text()
        script = json.loads(stuff).get("@graph")
        video_id = re.search(r'watch/(\d+)', self.url).group(1)
        duration = int(re.search(r'PT(\d+)S', script[1].get("duration")).group(1))
        thumbnail = script[1].get("thumbnailUrl")
        embed_url = script[1].get("embedUrl")
        views = script[1].get("interactionCount")
        publish_date = script[1].get("uploadDate")
        publish_date_thumbnail = script[0].get("datePublished")
        description = script[0].get("description")
        title = script[0].get("name")
        author_name = script[0].get("author")
        media_definitions = json.loads(re.search(r'"mediaDefinitions"\s*:\s*(\[.*?])', html_content).group(1))

        m3u8_url = None
        for media in media_definitions:
            if media.get('format') == 'hls':
                m3u8_url = media.get('videoUrl')

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
            "media_definitions": media_definitions
        }

    @staticmethod
    def get_m3u8_base_url(stuff) -> str | None:
        """Convenience property to quickly get the main HLS adaptive stream path."""
        data = json.loads(stuff)

        m3u8_lines = ["#EXTM3U", "#EXT-X-VERSION:3"]

        for stream in data:
            quality = stream.get("quality", "unknown")
            width = stream.get("width", 720)
            height = stream.get("height", 404)
            url = stream.get("videoUrl", "")

            if not url:
                continue

            # Rough bandwidth estimation based on standard stream naming conventions
            # (e.g., 4000K = 4,000,000 bps, 2000K = 2,000,000 bps)
            # If '1080P_4000K' is in the URL, we use 4000000. Default to a sensible fallback.
            bandwidth = 4000000
            if "4000K" in url:
                bandwidth = 4000000
            elif "2000K" in url:
                bandwidth = 2000000
            elif "1000K" in url:
                bandwidth = 1000000

            # Adjust dimensions safely if height changes per quality
            # Your JSON snippet showed height 404 for all, but typically:
            stream_height = int(quality) if quality.isdigit() else height
            # Rough 16:9 aspect ratio calculation for width if it's dynamic
            stream_width = int(stream_height * (16 / 9)) if quality.isdigit() else width

            # Append the stream info tag with attributes
            m3u8_lines.append(
                f'#EXT-X-STREAM-INF:BANDWIDTH={bandwidth},'
                f'RESOLUTION={stream_width}x{stream_height},'
                f'NAME="{quality}p"'
            )
            # The line immediately following the tag must be the URI
            m3u8_lines.append(url)

        return "\n".join(m3u8_lines)

    async def download(self, configuration: DownloadConfigHLS) -> bool | DownloadReport:
        config = copy.deepcopy(configuration)
        config.m3u8_base_url = self.m3u8_base_url

        if not config.no_title:
            config.path = os.path.join(config.path, f"{self.title}.mp4")

        try:
            return await self.core.download(config)

        except Exception as e:
            raise DownloadFailed(str(e))


@dataclass(kw_only=True, slots=True)
class Playlist(BaseMedia):
    url: str
    core: BaseCore
    title: str | None = None
    author_name: str | None = None
    rating_percent: str | None = None
    rating_count: str | None = None
    views: str | None = None
    videos_count: str | None = None

    async def _perform_load(self, api: bool, html: bool, anything_else: bool):
        if html:
            await asyncio.gather(self._fetch_html())

    async def _fetch_html(self):
        html_content = await get_html_content(url=self.url, core=self.core)
        assert isinstance(html_content, str)
        data: dict = await asyncio.to_thread(self._extract_html, html_content)
        allowed_fields = {field.name for field in fields(self)}

        for key, value in data.items():
            if key in allowed_fields:
                setattr(self, key, value)

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
            "video_count": video_count
        }

    async def get_videos(self, pages: int = 2,
                     videos_concurrency: int | None = None,
                     pages_concurrency: int | None = None,
                     on_video_error: on_error_hint = on_error,
                     on_page_error: on_error_hint = None,
                     keep_original_order: bool = False,
                     load_html: bool = False) -> AsyncGenerator[ScrapeResult, None]:
        url = self.url
        helper = Helper(core=self.core, constructor=Video)
        page_urls = [f"{url}&page={page}" for page in range(1, pages + 1)]
        videos_concurrency = videos_concurrency or self.core.configuration.videos_concurrency
        pages_concurrency = pages_concurrency or self.core.configuration.pages_concurrency
        assert videos_concurrency and pages_concurrency
        async for result in helper.iterator(target_page_urls=page_urls, max_video_concurrency=videos_concurrency,
                                         max_page_concurrency=pages_concurrency, video_link_extractor=extractor_search,
                                         on_video_error=on_video_error, keep_original_order=keep_original_order,
                                         on_page_error=on_page_error, fetch_html=load_html):
            yield result


@dataclass(kw_only=True, slots=True)
class UserHelper(BaseMedia):
    url: str
    core: BaseCore
    name: str | None = None

    async def _perform_load(self, api: bool, html: bool, anything_else: bool):
        if html:
            await asyncio.gather(self._fetch_html())

    async def _fetch_html(self):
        html_content = await get_html_content(core=self.core, url=self.url)
        assert isinstance(html_content, str)
        data: dict = await asyncio.to_thread(self._extract_html, html_content)
        allowed_fields = {field.name for field in fields(self)}

        for key, value in data.items():
            if key in allowed_fields:
                setattr(self, key, value)

    @staticmethod
    def _extract_html(html_content: str) -> dict:
        parser = LexborHTMLParser(html_content)
        try:
            name = parser.css_first("h1.name-title").text(strip=True)

        except AttributeError:
            name = re.findall(r'username: "(.*?)"', html_content)[1]

        return {
            "name": name,
        }

    async def get_videos(self, pages: int = 2,
                         videos_concurrency: int | None = None,
                         pages_concurrency: int | None = None,
                         on_video_error: on_error_hint = on_error,
                         on_page_error: on_error_hint = None,
                         keep_original_order: bool = False,
                         load_html: bool = False,
                         ) -> AsyncGenerator[ScrapeResult, None]:

        helper = Helper(core=self.core, constructor=Video)
        url = self.url
        page_urls = [f"{url}?page={page}" for page in range(1, pages + 1)]
        videos_concurrency = videos_concurrency or self.core.configuration.videos_concurrency
        pages_concurrency = pages_concurrency or self.core.configuration.pages_concurrency
        assert videos_concurrency and pages_concurrency
        async for result in helper.iterator(target_page_urls=page_urls, max_video_concurrency=videos_concurrency,
                                         max_page_concurrency=pages_concurrency, video_link_extractor=extractor_search,
                                         on_video_error=on_video_error, keep_original_order=keep_original_order,
                                         on_page_error=on_page_error, fetch_html=load_html):
            yield result


@dataclass(kw_only=True, slots=True)
class Pornstar(UserHelper):
    pornstar_information: dict | None = None

    @classmethod
    def _extract_html(cls, html_content: str) -> dict:
        data = super(Pornstar, cls)._extract_html(html_content)

        parser = LexborHTMLParser(html_content)

        thing = {}
        keys = parser.css("p.info-stat-label")
        values = parser.css("p.info-stat-data")

        for key, value in zip(keys, values):
            thing.update({key.text: value.text})

        data["pornstar_information"] = thing
        return data


@dataclass(kw_only=True, slots=True)
class Amateur(UserHelper):
    pass


@dataclass(kw_only=True, slots=True)
class Channel(UserHelper):
    url: str
    core: BaseCore
    name: str | None = None
    rank: str | None = None
    views: str | None = None
    videos_count: str | None = None

    async def _perform_load(self, api: bool, html: bool, anything_else: bool):
        if html:
            await asyncio.gather(self._fetch_html())

    async def _fetch_html(self):
        html_content = await get_html_content(core=self.core, url=self.url)
        assert isinstance(html_content, str)
        data: dict = await asyncio.to_thread(self._extract_html, html_content)
        allowed_fields = {field.name for field in fields(self)}
        for key, value in data.items():
            if key in allowed_fields:
                setattr(self, key, value)

    @staticmethod
    def _extract_html(html_content: str) -> dict:
        parser = LexborHTMLParser(html_content)
        name = parser.css_first("h1.name-title").text(strip=True)
        rank = parser.css_first("p.info-stat-data").text(strip=True)
        views = parser.css("p.info-stat-data")[1].text(strip=True)
        videos_count = parser.css("p.info-stat-data")[2].text(strip=True)

        return {
            "name": name,
            "rank": rank,
            "views": views,
            "videos_count": videos_count,
        }


class Client:
    def __init__(self, core: BaseCore = BaseCore()):
        self.core = core
        self.core.initialize_session()
        assert isinstance(self.core.session, AsyncSession)
        self.core.session.headers.update(HEADERS)
        self.core.session.cookies.update(COOKIES)

    async def get_video(self, url: str, load_html: bool = True) -> Video:
        video = Video(core=self.core, url=url)
        return await video.load(html=load_html)

    async def get_pornstar(self, url: str, load_html: bool = True) -> Pornstar:
        pornstar = Pornstar(core=self.core, url=url)
        return await pornstar.load(html=load_html)

    async def get_playlist(self, url: str, load_html: bool = True) -> Playlist:
        playlist = Playlist(core=self.core, url=url)
        return await playlist.load(html=load_html)

    async def get_channel(self, url: str, load_html: bool = True) -> Channel:
        channel = Channel(core=self.core, url=url)
        return await channel.load(html=load_html)

    async def get_amateur(self, url: str, load_html: bool = True) -> Amateur:
        amateur = Amateur(core=self.core, url=url)
        return await amateur.load(html=load_html)

    async def search(self, query: str, pages: int = 2,
                     videos_concurrency: int | None = None,
                     pages_concurrency: int | None = None,
                     on_video_error: on_error_hint = on_error,
                     on_page_error: on_error_hint = None
                     ) -> AsyncGenerator[Video, None]:
        # I am too lazy to implement search filters
        helper = Helper(core=self.core, constructor=Video)
        page_urls = [f"https://thumbzilla.com/search/?query={query}&page={page}" for page in range(1, pages + 1)]
        videos_concurrency = videos_concurrency or self.core.configuration.videos_concurrency
        pages_concurrency = pages_concurrency or self.core.configuration.pages_concurrency
        assert videos_concurrency and pages_concurrency

        async for video in helper.iterator(target_page_urls=page_urls, max_video_concurrency=videos_concurrency,
                                         max_page_concurrency=pages_concurrency, video_link_extractor=extractor_search,
                                         on_video_error=on_video_error,
                                         on_page_error=on_page_error):
            yield video
