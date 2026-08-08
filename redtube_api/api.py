"""
Copyright (C) 2026 Johannes Habel

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""
from __future__ import annotations

import os
import re
import copy
import json
import logging
import chompjs
import asyncio

from typing import AsyncGenerator, ClassVar
from dataclasses import dataclass
from curl_cffi import AsyncSession
from selectolax.lexbor import LexborHTMLParser
from base_api.modules.type_hints import DownloadReport
from base_api.modules.config import IteratorConfig
from base_api import (
    BaseCore,
    BaseMedia,
    DownloadConfigHLS,
    ErrorAction,
    ErrorMode,
    Helper,
    MediaLoadError,
    MediaLoadErrors,
    RetryPolicy,
    ScrapeErrorContext,
    ScrapeResult,
    media_field,
)
from base_api.modules.errors import (
    BotProtectionDetected,
    HTTPStatusError,
    InvalidProxy,
    NetworkRequestError,
    ResourceGone,
    UnknownError,
)

from redtube_api.modules.consts import HEADERS, extractor_html, extractor_playlist_json, COOKIES
from redtube_api.modules.errors import (BotDetection, NetworkError, NotFound, UnknownNetworkError, ProxyError,
                                        DownloadFailed)

logger = logging.getLogger("Redtube API")
logger.addHandler(logging.NullHandler())


def make_iterator_config() -> IteratorConfig:
    return IteratorConfig(
        load_specific_sources=("html",),
        item_retry=RetryPolicy(max_attempts=3),
        page_retry=RetryPolicy(max_attempts=3),
        page_error_mode=ErrorMode.SKIP,
        item_error_handler=None,
        page_error_handler=None,
    )


def _contains_resource_gone(error: BaseException) -> bool:
    if isinstance(error, ResourceGone):
        return True
    if isinstance(error, MediaLoadError):
        return _contains_resource_gone(error.original_error)
    if isinstance(error, MediaLoadErrors):
        return any(_contains_resource_gone(item) for item in error.errors)
    return False


async def on_error(context: ScrapeErrorContext) -> ErrorAction:
    logger.error(
        "URL: %s, ERROR: %s, Attempt: %s",
        context.url,
        context.error,
        context.attempt,
    )

    if _contains_resource_gone(context.error):
        return ErrorAction.SKIP

    return ErrorAction.RETRY


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
    title: str | None = media_field("html")
    duration: int | str | None = media_field("html")
    thumbnail: str | None = media_field("html")
    embed_code: str | None = media_field("html")
    locale: str | None = media_field("html")
    media_definitions: list[dict] | None = media_field("html")
    is_auto_play_enabled: bool | None = media_field("html")
    is_vr: bool | None = media_field("html")
    author_url: str | None = media_field("html")
    m3u8_source_url: str | None = media_field("html")
    mp4_url: str | None = media_field("html")
    action_tags_raw: object = media_field("html")
    action_tags: dict | None = media_field("html")
    m3u8_base_url: str | None = media_field("html")
    author_name: str | None = media_field("html")

    # Optional
    uploader_id: str | None = None
    uploader_type: str | None = None
    preview_video_url: str | None = None
    pornstars_names: list[str] | None = None
    pornstars_urls: list[str] | None = None

    loader_methods: ClassVar[dict[str, str]] = {"html": "_load_html"}

    async def _load_html(self) -> dict[str, object]:
        html_content = await get_html_content(core=self.core, url=self.url)
        data: dict = await asyncio.to_thread(self._extract_html, html_content)
        m3u8_source_url = data["m3u8_source_url"]
        if not isinstance(m3u8_source_url, str):
            raise ValueError(f"No HLS metadata URL found for {self.url}")
        m3u8_content = await get_html_content(core=self.core, url=m3u8_source_url)
        data["m3u8_base_url"] = self._build_m3u8(m3u8_content)
        return data


    def _extract_html(self, html_content: str) -> dict:
        parser = LexborHTMLParser(html_content)
        script = self._parse_script(parser)
        video_id = script.get('eventTracking', {}).get('params', {}).get('videoId', '')
        title = script.get('mainRoll', {}).get('title', '')
        duration = script.get('mainRoll', {}).get('duration', 0)
        thumbnail = script.get('mainRoll', {}).get('poster', '')
        embed_code = script.get('features', {}).get('embedCode', '')
        locale = script.get('locale', '')
        media_definitions = script.get('mainRoll', {}).get('mediaDefinition', [])
        is_auto_play_enabled = script.get('autoplay', {}).get('enabled', False)
        is_vr = script.get('isVr', False)
        author_name = parser.css_first("a.video-infobox-link").text(strip=True)
        _link = parser.css_first("a.video-infobox-link").attributes.get("href")
        author_url = f"https://www.redtube.com{_link}"

        m3u8_source_url = None
        for media in media_definitions:
            if media.get('format') == 'hls':
                m3u8_source_url = "https://redtube.com" + str(media.get('videoUrl'))


        mp4_url = None
        for media in media_definitions:
            if media.get('format') == 'mp4':
                mp4_url = media.get('videoUrl', None)


        action_tags_raw = script.get('mainRoll', {}).get('actionTags', '')

        tags_str = action_tags_raw
        if not tags_str:
            action_tags_raw = {}

        parsed_tags = {}
        try:
            for item in tags_str.split(','):
                if ':' in item:
                    tag_name, timestamp = item.rsplit(':', 1)
                    parsed_tags[tag_name.strip()] = int(timestamp)
        except Exception:
            pass  # Return whatever was parsed up to failure, or empty dict
        action_tags = parsed_tags

        return {
            "video_id": video_id,
            "title": title,
            "duration": duration,
            "thumbnail": thumbnail,
            "embed_code": embed_code,
            "locale": locale,
            "media_definitions": media_definitions,
            "is_auto_play_enabled": is_auto_play_enabled,
            "is_vr": is_vr,
            "author_name": author_name,
            "author_url": author_url,
            "m3u8_source_url": m3u8_source_url,
            "mp4_url": mp4_url,
            "action_tags": action_tags,
            "action_tags_raw": action_tags_raw,

        }

    async def author(self, load_html: bool = False) -> Amateur | Pornstar | Channel:
        url = await self.get_field("author_url")
        if not isinstance(url, str):
            raise ValueError(f"No author URL found for {self.url}")

        match url: # Wanted to use this one time in my life lol
            case _ if "amateur" in url:
                amateur = Amateur(url=url, core=self.core)
                if load_html:
                    await amateur.load_sources("html")
                return amateur

            case _ if "pornstar" in url:
                pornstar = Pornstar(url=url, core=self.core)
                if load_html:
                    await pornstar.load_sources("html")
                return pornstar

            case _ if "channel" in url:
                channel = Channel(url=url, core=self.core)
                if load_html:
                    await channel.load_sources("html")
                return channel

            case _:
                raise ValueError("Couldn't determine Author type, please report this")

    @staticmethod
    def _parse_script(parser: LexborHTMLParser):
        """
        Extracts the script element from HTML and parses the `generalVideoConfig`
        object into a native Python dictionary.
        """

        script_text = None

        for script in parser.css('script'):
            if script.text() and "// Disable preroll ads for VR videos" in script.text():
                script_text = script.text()
                break

        if not script_text:
            raise ValueError("Target script tag containing video configs not found.")

        def extract_js_object_string(text, start_marker):
            start_idx = text.find(start_marker)
            if start_idx == -1:
                return None

            brace_idx = text.find('{', start_idx)
            if brace_idx == -1:
                return None

            bracket_count = 0
            for i in range(brace_idx, len(text)):
                if text[i] == '{':
                    bracket_count += 1
                elif text[i] == '}':
                    bracket_count -= 1
                    if bracket_count == 0:
                        return text[brace_idx:i + 1]
            return None

        # 2. Extract nextVideoObj string literal
        next_video_raw = extract_js_object_string(script_text, "nextVideoObj =")

        # 3. Extract the primary generalVideoConfig object literal
        config_raw = extract_js_object_string(script_text, "page_params.generalVideoConfig =")

        if not config_raw:
            raise ValueError("Could not isolate page_params.generalVideoConfig structure.")

        # 4. Sanitize Javascript expressions so that chompjs can safely parse it
        # Replace variable pointer with the actual extracted object string
        if next_video_raw:
            config_raw = config_raw.replace('nextVideoObj', next_video_raw)

        # Replace the autoPlayValue reference with a boolean literal
        config_raw = re.sub(r'\bautoPlayValue\b', 'false', config_raw)

        # Clean up ternary operator expressions
        config_raw = re.sub(r'\(?page_params\.holiday_promo\s*\?\s*[\'"]hls[\'"]\s*:\s*[\'"]mp4[\'"]\)?', "'mp4'",
                            config_raw)
        config_raw = re.sub(r'_adRolls\s*\?\s*_adRolls\s*:\s*\[\]', '[]', config_raw)

        # Clean up browser runtime function calls
        config_raw = re.sub(r'isAutoFullscreenAndroid\(\)', 'true', config_raw)
        config_raw = re.sub(r'isAutoFullscreenIOS\(\)', 'false', config_raw)
        config_raw = re.sub(r'\(?isIOS\(\)\s*\|\|\s*isIPad_macOS\(\)\)?', 'false', config_raw)

        # 5. Parse the sanitized JS object string into a native Python Dictionary
        try:
            video_config_dict = chompjs.parse_js_object(config_raw)
            return video_config_dict
        except Exception as e:
            raise ValueError(f"Failed to parse sanitized JS object: {e}")

    @staticmethod
    def _build_m3u8(content: str):
        data = json.loads(content)

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
        await self.load_fields("title", "m3u8_base_url")
        config = copy.deepcopy(configuration)
        config.m3u8_base_url = self.m3u8_base_url
        if not config.no_title:
            config.path = os.path.join(config.path, f"{self.title}.mp4")

        try:
            return await self.core.download(configuration=config)
        except Exception as e:
            raise DownloadFailed(str(e))


@dataclass(kw_only=True, slots=True)
class Playlist(BaseMedia):
    url: str
    core: BaseCore
    title: str | None = media_field("html")
    author_url: str | None = media_field("html")
    author_name: str | None = media_field("html")
    rating_percent: str | None = media_field("html")
    rating_count: str | None = media_field("html")
    views: str | None = media_field("html")
    video_count: str | None = media_field("html")

    # Optional
    updated_at: str | None = None
    status: str | None = None

    loader_methods: ClassVar[dict[str, str]] = {"html": "_load_html"}

    async def _load_html(self) -> dict[str, object]:
        html_content = await get_html_content(core=self.core, url=self.url)
        return await asyncio.to_thread(self._extract_html, html_content)

    @staticmethod
    def _extract_html(html_content: str) -> dict:
        parser = LexborHTMLParser(html_content)
        title = parser.css_first("h1#playlist_title").text(strip=True)
        author_url = parser.css_first("p.playlist_desc").css_first("a").attributes.get("href")
        author_name = parser.css_first("p.playlist_desc").css_first("a").text(strip=True)
        rating_percent = parser.css_first("div.rating_percent.js_rating_percent").text(strip=True)
        rating_count = parser.css_first("span.playlist_stats_value").text(strip=True)
        views = parser.css("span.playlist_stats_value")[1].text(strip=True)
        video_count = parser.css("span.playlist_stats_value")[2].text(strip=True)

        return {
            "title": title,
            "author_url": author_url,
            "author_name": author_name,
            "rating_percent": rating_percent,
            "rating_count": rating_count,
            "views": views,
            "video_count": video_count,
        }

    async def get_author(self, load_html: bool = False):
        author_url = await self.get_field("author_url")
        user = User(core=self.core, url=f"https://www.redtube.com{author_url}")
        if load_html:
            await user.load_sources("html")
        return user

    async def get_videos(
        self,
        pages: int = 2,
        iterator_config: IteratorConfig | None = None,
    ) -> AsyncGenerator[ScrapeResult, None]:
        # I am too lazy to implement search filters
        url = self.url
        helper = Helper(core=self.core, constructor=Video)
        page_urls = [f"{url}&page={page}" for page in range(1, pages + 1)]
        if iterator_config is None:
            iterator_config = make_iterator_config()

        stream = helper.iterator(
            target_page_urls=page_urls,
            item_extractor=extractor_html,
            iterator_config=iterator_config,
        )
        async with stream:
            async for result in stream:
                yield result


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

    async def get_videos(
        self,
        pages: int = 2,
        iterator_config: IteratorConfig | None = None,
    ) -> AsyncGenerator[ScrapeResult, None]:

        url = self.url
        helper = Helper(core=self.core, constructor=Video)
        page_urls = [f"{url}?page={page}" for page in range(1, pages + 1)]
        if iterator_config is None:
            iterator_config = make_iterator_config()

        stream = helper.iterator(
            target_page_urls=page_urls,
            item_extractor=extractor_html,
            iterator_config=iterator_config,
        )
        async with stream:
            async for result in stream:
                yield result


@dataclass(kw_only=True, slots=True)
class User(UserHelper):

    async def get_playlists(
        self,
        pages: int = 2,
        iterator_config: IteratorConfig | None = None,
    ) -> AsyncGenerator[ScrapeResult, None]:
        name = await self.get_field("name")
        if not isinstance(name, str) or not name:
            raise ValueError("Cannot fetch playlists, because you have not populated the html yet")

        helper = Helper(core=self.core, constructor=Playlist)
        page_urls = [f"https://redtube.com/user/{name}/playlists-data?page={page}" for page in range(1, pages + 1)]
        if iterator_config is None:
            iterator_config = make_iterator_config()

        stream = helper.iterator(
            target_page_urls=page_urls,
            item_extractor=extractor_playlist_json,
            iterator_config=iterator_config,
        )
        async with stream:
            async for result in stream:
                yield result


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
class Channel(BaseMedia):
    url: str
    core: BaseCore
    name: str | None = media_field("html")
    rank: str | None = media_field("html")
    views: str | None = media_field("html")
    videos_count: str | None = media_field("html")
    subscribers_count: str | None = media_field("html")

    loader_methods: ClassVar[dict[str, str]] = {"html": "_load_html"}

    async def _load_html(self) -> dict[str, object]:
        html_content = await get_html_content(core=self.core, url=self.url)
        return await asyncio.to_thread(self._extract_html, html_content)

    @staticmethod
    def _extract_html(html_content: str) -> dict:
        parser = LexborHTMLParser(html_content)

        name = parser.css_first("h1.name-title").text(strip=True)
        rank = parser.css_first("p.info-stat-data").text(strip=True)
        videos_count = parser.css("p.info-stat-data")[1].text(strip=True)
        subscribers_count = parser.css("p.info-stat-data")[2].text(strip=True)
        views = parser.css("p.info-stat-data")[3].text(strip=True)

        return {
            "name": name,
            "rank": rank,
            "videos_count": videos_count,
            "subscribers_count": subscribers_count,
            "views": views,
        }

    async def get_videos(
        self,
        pages: int = 2,
        iterator_config: IteratorConfig | None = None,
    ) -> AsyncGenerator[ScrapeResult, None]:

        url = self.url
        helper = Helper(core=self.core, constructor=Video)
        page_urls = [f"{url}?page={page}" for page in range(1, pages + 1)]
        if iterator_config is None:
            iterator_config = make_iterator_config()

        stream = helper.iterator(
            target_page_urls=page_urls,
            item_extractor=extractor_html,
            iterator_config=iterator_config,
        )
        async with stream:
            async for result in stream:
                yield result


class Client:
    def __init__(self, core: BaseCore = BaseCore()):
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

    async def get_user(self, url: str, load_html: bool = True) -> User:
        user = User(core=self.core, url=url)
        if load_html:
            await user.load_sources("html")
        return user

    async def search(
        self,
        query: str,
        pages: int = 2,
        iterator_config: IteratorConfig | None = None,
    ) -> AsyncGenerator[ScrapeResult, None]:
        # I am too lazy to implement search filters
        helper = Helper(core=self.core, constructor=Video)
        page_urls = [f"https://redtube.com/?search={query}&page={page}" for page in range(1, pages + 1)]
        if iterator_config is None:
            iterator_config = make_iterator_config()

        stream = helper.iterator(
            target_page_urls=page_urls,
            item_extractor=extractor_html,
            iterator_config=iterator_config,
        )
        async with stream:
            async for result in stream:
                yield result
