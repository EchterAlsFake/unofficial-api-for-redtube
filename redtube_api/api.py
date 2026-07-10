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
import json
import chompjs
import asyncio

from typing import AsyncGenerator
from dataclasses import dataclass, fields
from curl_cffi import Response, AsyncSession
from selectolax.lexbor import LexborHTMLParser
from base_api.modules.type_hints import DownloadReport
from base_api import BaseCore, Helper, BaseMedia, ScrapeResult, DownloadConfigHLS
from base_api.modules.errors import InvalidProxy, UnknownError, NetworkRequestError, BotProtectionDetected, ResourceGone

from redtube_api.modules.consts import HEADERS, extractor_html, extractor_playlist_json, COOKIES
from redtube_api.modules.errors import (BotDetection, NetworkError, NotFound, UnknownNetworkError, ProxyError,
                                        DownloadFailed)
from redtube_api.modules.type_hints import on_error_hint


async def on_error(url: str, error: Exception, attempt: int) -> bool:
    print(f"URL: {url}, ERROR: {error}, Attempt: {attempt}")

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
    title: str | None = None
    duration: int | None = None
    thumbnail: str | None = None
    embed_code: str | None = None
    locale: str | None = None
    media_definitions: dict | None = None
    is_auto_play_enabled: bool | None = None
    is_vr: bool | None = None
    author_url: str | None = None
    m3u8_source_url: str | None = None
    mp4_url: str | None = None
    action_tags_raw: dict | None = None
    action_tags: dict | None = None
    m3u8_base_url: str | None = None
    author_name: str | None = None

    # Optional
    uploader_id: str | None = None
    uploader_type: str | None = None
    preview_video_url: str | None = None
    pornstars_names: list[str] | None = None
    pornstars_urls: list[str] | None = None

    async def _perform_load(self, api: bool, html: bool, anything_else: bool):
        if html:
            await asyncio.gather(self._fetch_html())

    async def _fetch_html(self):
        html_content = await get_html_content(core=self.core, url=self.url)
        assert isinstance(html_content, str)
        data: dict = await asyncio.to_thread(self._extract_html, html_content)
        allowed_fields = [field.name for field in fields(self)]

        for key, value in data.items():
            if key in allowed_fields:
                setattr(self, key, value)

        m3u8_content = await get_html_content(core=self.core, url=self.m3u8_source_url)
        self.m3u8_base_url = self._build_m3u8(m3u8_content)


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
        url = self.author_url

        match self.author_url: # Wanted to use this one time in my life lol
            case _ if "amateur" in url:
                amateur = Amateur(url=url, core=self.core)
                return await amateur.load(html=load_html)

            case _ if "pornstar" in url:
                pornstar = Pornstar(url=url, core=self.core)
                return await pornstar.load(html=load_html)

            case _ if "channel" in url:
                channel = Channel(url=url, core=self.core)
                return await channel.load(html=load_html)

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
        config = configuration
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
    title: str | None = None
    author_url: str | None = None
    author_name: str | None = None
    rating_percent: str | None = None
    rating_count: str | None = None
    views: str | None = None
    video_count: str | None = None

    # Optional
    updated_at: str | None = None
    status: str | None = None

    async def _perform_load(self, api: bool, html: bool, anything_else: bool):
        if html:
            await asyncio.gather(self._fetch_html())

    async def _fetch_html(self):
        html_content = await get_html_content(core=self.core, url=self.url)
        assert isinstance(html_content, str)
        data: dict = await asyncio.to_thread(self._extract_html, html_content)
        allowed_fields = [field.name for field in fields(self)]

        for key, value in data.items():
            if key in allowed_fields:
                setattr(self, key, value)

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
        user = User(core=self.core, url=f"https://www.redtube.com{self.author_url}")
        return await user.load(html=load_html)

    async def get_videos(self, pages: int = 2,
                     videos_concurrency: int | None = None,
                     pages_concurrency: int | None = None,
                     on_video_error: on_error_hint = on_error,
                     on_page_error: on_error_hint = None,
                     keep_original_order: bool = False,
                     load_html: bool = False,
                     ) -> AsyncGenerator[ScrapeResult, None]:
        # I am too lazy to implement search filters
        helper = Helper(core=self.core, constructor=Video)
        page_urls = [f"{self.url}&page={page}" for page in range(1, pages + 1)]
        videos_concurrency = videos_concurrency or self.core.configuration.videos_concurrency
        pages_concurrency = pages_concurrency or self.core.configuration.pages_concurrency
        assert videos_concurrency and pages_concurrency

        async for result in helper.iterator(target_page_urls=page_urls, max_video_concurrency=videos_concurrency,
                                         max_page_concurrency=pages_concurrency, video_link_extractor=extractor_html,
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
        allowed_fields = [field.name for field in fields(self)]

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
        page_urls = [f"{self.url}?page={page}" for page in range(1, pages + 1)]
        videos_concurrency = videos_concurrency or self.core.configuration.videos_concurrency
        pages_concurrency = pages_concurrency or self.core.configuration.pages_concurrency
        assert videos_concurrency and pages_concurrency
        async for result in helper.iterator(target_page_urls=page_urls, max_video_concurrency=videos_concurrency,
                                         max_page_concurrency=pages_concurrency, video_link_extractor=extractor_html,
                                         on_video_error=on_video_error, keep_original_order=keep_original_order,
                                         on_page_error=on_page_error, fetch_html=load_html):
            yield result


@dataclass(kw_only=True, slots=True)
class User(UserHelper):

    async def get_playlists(self, pages: int = 2,
                            videos_concurrency: int | None = None,
                            pages_concurrency: int | None = None,
                            on_video_error: on_error_hint = on_error,
                            on_page_error: on_error_hint = None,
                            keep_original_order: bool = False,
                            load_html: bool = True,
                            ) -> AsyncGenerator[ScrapeResult, None]:
        if not self.name:
            raise ValueError("Cannot fetch playlists, because you have not populated the html yet")

        helper = Helper(core=self.core, constructor=Playlist)
        page_urls = [f"https://redtube.com/user/{self.name}/playlists-data?page={page}" for page in range(1, pages + 1)]
        videos_concurrency = videos_concurrency or self.core.configuration.videos_concurrency
        pages_concurrency = pages_concurrency or self.core.configuration.pages_concurrency
        assert videos_concurrency and pages_concurrency

        async for result in helper.iterator(target_page_urls=page_urls, max_video_concurrency=videos_concurrency,
                                         max_page_concurrency=pages_concurrency, video_link_extractor=extractor_playlist_json,
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
class Channel(BaseMedia):
    url: str
    core: BaseCore
    name: str | None = None
    rank: str | None = None
    views: str | None = None
    videos_count: str | None = None
    subscribers_count: str | None = None

    async def _perform_load(self, api: bool, html: bool, anything_else: bool):
        if html:
            await asyncio.gather(self._fetch_html())

    async def _fetch_html(self):
        html_content = await get_html_content(core=self.core, url=self.url)
        assert isinstance(html_content, str)
        data: dict = await asyncio.to_thread(self._extract_html, html_content)
        allowed_fields = [field.name for field in fields(self)]
        for key, value in data.items():
            if key in allowed_fields:
                setattr(self, key, value)

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

    async def get_videos(self, pages: int = 2,
                     videos_concurrency: int | None = None,
                     pages_concurrency: int | None = None,
                     on_video_error: on_error_hint = on_error,
                     on_page_error: on_error_hint = None,
                     keep_original_order: bool = True,
                     load_html: bool = False,
                     ) -> AsyncGenerator[ScrapeResult, None]:

        helper = Helper(core=self.core, constructor=Video)
        page_urls = [f"{self.url}?page={page}" for page in range(1, pages + 1)]
        videos_concurrency = videos_concurrency or self.core.configuration.videos_concurrency
        pages_concurrency = pages_concurrency or self.core.configuration.pages_concurrency
        assert videos_concurrency and pages_concurrency
        async for result in helper.iterator(target_page_urls=page_urls, max_video_concurrency=videos_concurrency,
                                         max_page_concurrency=pages_concurrency, video_link_extractor=extractor_html,
                                         on_video_error=on_video_error, keep_original_order=keep_original_order,
                                         on_page_error=on_page_error, fetch_html=load_html):
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

    async def get_user(self, url: str, load_html: bool = True) -> User:
        user = User(core=self.core, url=url)
        return await user.load(html=load_html)

    async def search(self, query: str, pages: int = 2,
                     videos_concurrency: int | None = None,
                     pages_concurrency: int | None = None,
                     on_video_error: on_error_hint = on_error,
                     on_page_error: on_error_hint = None,
                     keep_original_order: bool = False,
                     load_html: bool = False
                     ) -> AsyncGenerator[ScrapeResult, None]:
        # I am too lazy to implement search filters
        helper = Helper(core=self.core, constructor=Video)
        page_urls = [f"https://redtube.com/?search={query}&page={page}" for page in range(1, pages + 1)]
        videos_concurrency = videos_concurrency or self.core.configuration.videos_concurrency
        pages_concurrency = pages_concurrency or self.core.configuration.pages_concurrency
        assert videos_concurrency and pages_concurrency

        async for result in helper.iterator(target_page_urls=page_urls, max_video_concurrency=videos_concurrency,
                                         max_page_concurrency=pages_concurrency, video_link_extractor=extractor_html,
                                         on_video_error=on_video_error, keep_original_order=keep_original_order,
                                         on_page_error=on_page_error, fetch_html=load_html):
            yield result
