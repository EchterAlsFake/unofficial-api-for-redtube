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

import os
import re
import json

import chompjs
import logging
import asyncio

from curl_cffi import Response, AsyncSession
from functools import cached_property
from typing import Any, List, Dict, AsyncGenerator
from base_api.modules.type_hints import DownloadReport
from base_api.base import BaseCore, setup_logger, Helper
from base_api.modules.errors import InvalidProxy, UnknownError, NetworkingError, BotProtectionDetected, ResourceGone
try:
    import lxml
    parser = "lxml" # Faster speeds, but more dependencies

except (ModuleNotFoundError, ImportError):
    parser = "html.parser" # Fallback to classic HTML parser (will work fine)

try:
    from modules.consts import *
    from modules.errors import *
    from modules.type_hints import *

except (ModuleNotFoundError, ImportError):
    from .modules.consts import *
    from .modules.errors import *
    from .modules.type_hints import *


def get_element_safe(stuff):
    try:
        return stuff.text

    except AttributeError:
        return None


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

    except NetworkingError as e:
        raise NetworkError(str(e)) from e

    except InvalidProxy as e:
        raise ProxyError(str(e)) from e

    except BotProtectionDetected as e:
        raise BotDetection(str(e)) from e

    except UnknownError as e:
        raise UnknownNetworkError(str(e)) from e

class Video:
    def __init__(self, url: str, core: BaseCore, html_content: str | None = None):
        self.core = core
        self.url = url
        self.html_content = html_content
        self._soup = None
        self.logger = setup_logger(name="RedTube API - [Video]", level=logging.ERROR)

    def enable_logging(self, log_file: str | None = None, level: int | None =None, log_ip: str | None = None, log_port: int | None = None):
        if not level:
            level = logging.DEBUG

        self.logger = setup_logger(name="RedTube API - [Client]", log_file=log_file, level=level, http_ip=log_ip,
                                   http_port=log_port)

    @property
    def soup(self) -> BeautifulSoup:
        if not self._soup:
            raise ValueError("You probably forgot to call init")

        return self._soup

    async def init(self):
        if not self.html_content:
            self.html_content = await get_html_content(core=self.core, url=self.url)

        assert isinstance(self.html_content, str)
        self._soup = BeautifulSoup(self.html_content, parser)
        self.script = self.parse_script()
        return self

    def parse_script(self):
        """
        Extracts the script element from HTML and parses the `generalVideoConfig` 
        object into a native Python dictionary.
        """

        script_text = None

        for script in self.soup.find_all('script'):
            if script.string and "// Disable preroll ads for VR videos" in script.string:
                script_text = script.string
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

    @cached_property
    def video_id(self) -> str:
        """Extracts the unique video ID."""
        return self.script.get('eventTracking', {}).get('params', {}).get('videoId', '')

    @cached_property
    def title(self) -> str:
        """Returns the main video title."""
        return self.script.get('mainRoll', {}).get('title', '')

    @cached_property
    def duration(self) -> int:
        """Returns the video duration in seconds."""
        return self.script.get('mainRoll', {}).get('duration', 0)

    @cached_property
    def thumbnail(self) -> str:
        """Returns the main preview image/poster URL."""
        return self.script.get('mainRoll', {}).get('poster', '')

    @cached_property
    def video_url(self) -> str:
        """Returns the canonical page URL of the video."""
        return self.script.get('mainRoll', {}).get('videoUrl', '')

    @cached_property
    def embed_code(self) -> str:
        """Returns the raw iframe HTML string for embedding the video."""
        return self.script.get('features', {}).get('embedCode', '')

    @cached_property
    def locale(self) -> str:
        """Returns the regional language code setting (e.g., 'de')."""
        return self.script.get('locale', '')

    # --- Video Streams & Formats ---

    @cached_property
    def media_definitions(self) -> List[Dict[str, Any]]:
        """Returns the raw list of dictionaries containing video streams (HLS, MP4)."""
        return self.script.get('mainRoll', {}).get('mediaDefinition', [])

    async def m3u8_base_url(self) -> str | None:
        """Convenience property to quickly get the main HLS adaptive stream path."""
        url = None
        for media in self.media_definitions:
            if media.get('format') == 'hls':
                url = "https://redtube.com" + str(media.get('videoUrl'))


        stuff = await get_html_content(core=self.core, url=url)
        assert isinstance(stuff, str)
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

    @cached_property
    def mp4_url(self) -> str | None:
        """Convenience property to quickly get the fallback progressive MP4 stream path."""
        for media in self.media_definitions:
            if media.get('format') == 'mp4':
                return media.get('videoUrl')
        return None

    # --- Player Configurations ---

    @cached_property
    def is_autoplay_enabled(self) -> bool:
        """Checks if the player is configured to start playing automatically."""
        return self.script.get('autoplay', {}).get('enabled', False)

    @cached_property
    def is_vr(self) -> bool:
        """Checks if the video is a 360/VR playback variant."""
        return self.script.get('isVr', False)

    # --- Interactive Features & Thumbnails ---

    @cached_property
    def action_tags_raw(self) -> str:
        """Returns the unparsed timeline action tags string."""
        return self.script.get('mainRoll', {}).get('actionTags', '')

    @cached_property
    def action_tags(self) -> Dict[str, int]:
        """
        Parses the comma-separated action timeline tags into a clean Python dictionary.
        Example: {'Pussy Licking': 492, 'Fingering': 595}
        """
        tags_str = self.action_tags_raw
        if not tags_str:
            return {}

        parsed_tags = {}
        try:
            for item in tags_str.split(','):
                if ':' in item:
                    tag_name, timestamp = item.rsplit(':', 1)
                    parsed_tags[tag_name.strip()] = int(timestamp)
        except Exception:
            pass  # Return whatever was parsed up to failure, or empty dict
        return parsed_tags

    async def download(self, quality, path="./", callback: callback_hint=None, no_title=False, remux: bool = False,
                 callback_remux: callback_hint=None, start_segment: int = 0, stop_event: asyncio.Event | None = None,
                 segment_state_path: str | None = None, segment_dir: str | None = None,
                 return_report: bool = False, cleanup_on_stop: bool = True, keep_segment_dir: bool = False
                 ) -> bool | DownloadReport:
        """
        :param callback:
        :param quality:
        :param path:
        :param no_title:
        :param remux:
        :param callback_remux:
        :param start_segment:
        :param stop_event:
        :param segment_state_path:
        :param segment_dir:
        :param return_report:
        :param cleanup_on_stop:
        :param keep_segment_dir:
        :return:
        """
        if not no_title:
            path = os.path.join(path, f"{self.title}.mp4")

        return await self.core.download(video=self, quality=quality, path=path, callback=callback, remux=remux,
                                         callback_remux=callback_remux, start_segment=start_segment,
                                         stop_event=stop_event,
                                         segment_state_path=segment_state_path, segment_dir=segment_dir,
                                         return_report=return_report,
                                         cleanup_on_stop=cleanup_on_stop, keep_segment_dir=keep_segment_dir)


class Playlist(Helper):
    def __init__(self, url: str, core: BaseCore):
        super().__init__(core=core, video_constructor=Video)
        self.core = core
        self.url = url
        self._soup = None
        self.html_content = None
        self.logger = setup_logger(name="RedTube API - [Playlist]", log_file=None, level=logging.ERROR)

    def enable_logging(self, log_file: str | None = None, level: int | None =None, log_ip: str | None = None, log_port: int | None = None):
        if not level:
            level = logging.DEBUG

        self.logger = setup_logger(name="RedTube API - [Playlist]", log_file=log_file, level=level, http_ip=log_ip,
                                   http_port=log_port)

    @property
    def soup(self) -> BeautifulSoup:
        if not self._soup:
            raise ValueError("You probably forgot to call init")

        return self._soup

    async def init(self):
        self.html_content = await get_html_content(core=self.core, url=self.url)

        assert isinstance(self.html_content, str)
        self._soup = BeautifulSoup(self.html_content, parser)
        return self

    @cached_property
    def title(self) -> str:
        return self.soup.find("h1", attrs={"id": "playlist_title"}).text

    @cached_property
    def author(self) -> str:
        return self.soup.find("p", class_="playlist_desc").find("a").text

    @cached_property
    def rating_percent(self) -> str:
        return self.soup.find("div", class_="rating_percent js_rating_percent").text

    @cached_property
    def rating_count(self) -> str:
        return self.soup.find("span", class_="playlist_stats_value").text

    @cached_property
    def viwws(self) -> str:
        return self.soup.find_all("span", class_="playlist_stats_value")[1].text

    @cached_property
    def video_count(self) -> str:
        return self.soup.find_all("span", class_="playlist_stats_value")[2].text

    async def get_videos(self, pages: int = 2,
                     videos_concurrency: int | None = None,
                     pages_concurrency: int | None = None,
                     on_video_error: on_error_hint = on_error,
                     on_page_error: on_error_hint = None
                     ) -> AsyncGenerator[Video, None]:
        # I am too lazy to implement search filters

        page_urls = [f"{self.url}&page={page}" for page in range(1, pages + 1)]
        videos_concurrency = videos_concurrency or self.core.configuration.videos_concurrency
        pages_concurrency = pages_concurrency or self.core.configuration.pages_concurrency
        assert videos_concurrency and pages_concurrency

        async for video in self.iterator(target_page_urls=page_urls, max_video_concurrency=videos_concurrency,
                                         max_page_concurrency=pages_concurrency, video_link_extractor=extractor_html,
                                         on_video_error=on_video_error,
                                         on_page_error=on_page_error):
            yield video


class Pornstar(Helper):
    def __init__(self, url: str, core: BaseCore, html_content: str | None = None):
        super().__init__(core=core, video_constructor=Video)
        self.url = url
        self.core = core
        self.html_content = html_content
        self.logger = setup_logger(name="RedTube API - [Pornstar]", log_file=None, level=logging.ERROR)

    def enable_logging(self, log_file: str | None = None, level: int | None =None, log_ip: str | None = None, log_port: int | None = None):
        if not level:
            level = logging.DEBUG

        self.logger = setup_logger(name="RedTube API - [Pornstar]", log_file=log_file, level=level, http_ip=log_ip,
                                   http_port=log_port)

    @property
    def soup(self) -> BeautifulSoup:
        if not self._soup:
            raise ValueError("You probably forgot to call init")

        return self._soup

    async def init(self):
        if not self.html_content:
            self.html_content = await get_html_content(core=self.core, url=self.url)

        assert isinstance(self.html_content, str)
        self._soup = BeautifulSoup(self.html_content, parser)
        return self

    @cached_property
    def name(self) -> str:
        return self.soup.find("h1", class_="name-title").text

    @cached_property
    def pornstar_information(self) -> dict:
        thing = {}
        keys = self.soup.find_all("p", class_="info-stat-label")
        values = self.soup.find_all("p", class_="info-stat-data")

        for key, value in zip(keys, values):
            thing.update({key.text: value.text})

        return thing


    async def get_videos(self, pages: int = 2,
                     videos_concurrency: int | None = None,
                     pages_concurrency: int | None = None,
                     on_video_error: on_error_hint = on_error,
                     on_page_error: on_error_hint = None
                     ) -> AsyncGenerator[Video, None]:

        page_urls = [f"{self.url}?page={page}" for page in range(1, pages + 1)]
        videos_concurrency = videos_concurrency or self.core.configuration.videos_concurrency
        pages_concurrency = pages_concurrency or self.core.configuration.pages_concurrency
        assert videos_concurrency and pages_concurrency
        async for video in self.iterator(target_page_urls=page_urls, max_video_concurrency=videos_concurrency,
                                         max_page_concurrency=pages_concurrency, video_link_extractor=extractor_html,
                                         on_video_error=on_video_error,
                                         on_page_error=on_page_error):
            yield video


class Channel(Helper):
    def __init__(self, url: str, core: BaseCore):
        super().__init__(core=core, video_constructor=Video)
        self.core = core
        self.url = url
        self._soup = None
        self.html_content = None
        self.logger = setup_logger(name="RedTube API - [Channel]", log_file=None, level=logging.ERROR)

    def enable_logging(self, log_file: str | None = None, level: int | None = None, log_ip: str | None = None,
                       log_port: int | None = None):
        if not level:
            level = logging.DEBUG

        self.logger = setup_logger(name="RedTube API - [Channel]", log_file=log_file, level=level, http_ip=log_ip,
                                   http_port=log_port)

    @property
    def soup(self) -> BeautifulSoup:
        if not self._soup:
            raise ValueError("You probably forgot to call init")

        return self._soup


    async def init(self):
        if not self.html_content:
            self.html_content = await get_html_content(core=self.core, url=self.url)

        assert isinstance(self.html_content, str)
        self._soup = BeautifulSoup(self.html_content, parser)
        return self

    @cached_property
    def name(self) -> str:
        return self.soup.find("h1", class_="name-title").text

    @cached_property
    def rank(self) -> str:
        return self.soup.find_all("p", class_="info-stat-data")[0].text

    @cached_property
    def videos_count(self) -> str:
        return self.soup.find_all("p", class_="info-stat-data")[1].text

    @cached_property
    def subscribers_count(self) -> str:
        return self.soup.find_all("p", class_="info-stat-data")[2].text

    @cached_property
    def views(self) -> str:
        return self.soup.find_all("p", class_="info-stat-data")[3].text

    async def get_videos(self, pages: int = 2,
                     videos_concurrency: int | None = None,
                     pages_concurrency: int | None = None,
                     on_video_error: on_error_hint = on_error,
                     on_page_error: on_error_hint = None
                     ) -> AsyncGenerator[Video, None]:

        page_urls = [f"{self.url}?page={page}" for page in range(1, pages + 1)]
        videos_concurrency = videos_concurrency or self.core.configuration.videos_concurrency
        pages_concurrency = pages_concurrency or self.core.configuration.pages_concurrency
        assert videos_concurrency and pages_concurrency
        async for video in self.iterator(target_page_urls=page_urls, max_video_concurrency=videos_concurrency,
                                         max_page_concurrency=pages_concurrency, video_link_extractor=extractor_html,
                                         on_video_error=on_video_error,
                                         on_page_error=on_page_error):
            yield video



class Client(Helper):
    def __init__(self, core: BaseCore = BaseCore()):
        super().__init__(core=core, video_constructor=Video)
        self.core = core or BaseCore()
        self.core.initialize_session()
        assert isinstance(self.core.session, AsyncSession)
        self.core.session.headers.update(HEADERS)
        self.core.session.cookies.update(COOKIES)
        self.logger = setup_logger(name="RedTube API - [Client]", log_file=None, level=logging.ERROR)


    def enable_logging(self, log_file: str | None = None, level: int | None =None, log_ip: str | None = None, log_port: int | None = None):
        if not level:
            level = logging.DEBUG

        self.logger = setup_logger(name="RedTube API - [Client]", log_file=log_file, level=level, http_ip=log_ip,
                                   http_port=log_port)


    async def get_video(self, url: str) -> Video:
        video = Video(core=self.core, url=url)
        return await video.init()

    async def get_pornstar(self, url: str) -> Pornstar:
        pornstar = Pornstar(core=self.core, url=url)
        return await pornstar.init()

    async def get_playlist(self, url: str) -> Playlist:
        playlist = Playlist(core=self.core, url=url)
        return await playlist.init()

    async def get_channel(self, url: str) -> Channel:
        channel = Channel(core=self.core, url=url)
        return await channel.init()

    async def search(self, query: str, pages: int = 2,
                     videos_concurrency: int | None = None,
                     pages_concurrency: int | None = None,
                     on_video_error: on_error_hint = on_error,
                     on_page_error: on_error_hint = None
                     ) -> AsyncGenerator[Video, None]:
        # I am too lazy to implement search filters

        page_urls = [f"https://redtube.com/?search={query}&page={page}" for page in range(1, pages + 1)]
        videos_concurrency = videos_concurrency or self.core.configuration.videos_concurrency
        pages_concurrency = pages_concurrency or self.core.configuration.pages_concurrency
        assert videos_concurrency and pages_concurrency

        async for video in self.iterator(target_page_urls=page_urls, max_video_concurrency=videos_concurrency,
                                         max_page_concurrency=pages_concurrency, video_link_extractor=extractor_playlist,
                                         on_video_error=on_video_error,
                                         on_page_error=on_page_error):
            yield video
