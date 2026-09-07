from __future__ import annotations
import os
import re
import copy
import json
import asyncio
import logging
import argparse

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
)
from base_api.modules.errors import (BotProtectionDetected, HTTPStatusError, InvalidProxy, NetworkRequestError,
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
        if e.status_code == 404:
            raise NotFound(f"Server returned 404 for: {url}") from e
        raise NetworkError(str(e)) from e

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

    async def _load_html(self) -> dict[str, object]:
        html_content = await get_html_content(url=self.url, core=self.core)
        data: dict = await asyncio.to_thread(self._extract_html, html_content)
        m3u8_url = data["m3u8_url"]
        if not isinstance(m3u8_url, str):
            raise ValueError(f"No HLS metadata URL found for {self.url}")
        stuff = await get_html_content(core=self.core, url=m3u8_url)
        data["m3u8_base_url"] = self.get_m3u8_base_url(stuff)
        return data

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
        return build_m3u8_master(stuff)


    async def download(self, configuration: DownloadConfigHLS) -> bool | DownloadReport:
        await self.load_fields("title", "m3u8_base_url")
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

    loader_methods: ClassVar[dict[str, str]] = {"html": "_load_html"}

    async def _load_html(self) -> dict[str, object]:
        html_content = await get_html_content(core=self.core, url=self.url)
        return await asyncio.to_thread(self._extract_html, html_content)

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

    def get_videos(self, pages: int = 2,
                         iterator_config: IteratorConfig | None = None,
                         iterator_configuration: IteratorConfig | None = None) -> AsyncGenerator[ScrapeResult[Video], None]:
        config = iterator_config or iterator_configuration
        url = self.url
        page_urls = [f"{url}?page={page}" for page in range(1, pages + 1)]
        return scrape_stream(
            core=self.core,
            constructor=Video,
            target_page_urls=page_urls,
            item_extractor=extractor_search,
            iterator_config=config,
        )



@dataclass(kw_only=True, slots=True)
class Pornstar(UserHelper):
    pornstar_information: dict | None = media_field("html")

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
    name: str | None = media_field("html")
    rank: str | None = media_field("html")
    views: str | None = media_field("html")
    videos_count: str | None = media_field("html")

    loader_methods: ClassVar[dict[str, str]] = {"html": "_load_html"}

    async def _load_html(self) -> dict[str, object]:
        html_content = await get_html_content(core=self.core, url=self.url)
        return await asyncio.to_thread(self._extract_html, html_content)

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
            print(f"Error downloading {url}: {e}")


def main():
    try:
        asyncio.run(run_main())
    except KeyboardInterrupt:
        print("\nOperation cancelled by user.")


if __name__ == "__main__":
    main()

