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
import argparse

from base_api.modules.logger import configure_app_logging

from base_api.modules.static_functions import str_to_bool
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
    make_iterator_config,
    is_resource_gone,
    default_on_error,
    scrape_stream,
    build_m3u8_master,
)
from base_api.modules.errors import (
    DownloadCancelled,
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
    publish_date: str | None = media_field("html")
    views: str | None = media_field("html")
    rating_percent: str | None = media_field("html")
    tags: list[str] | None = media_field("html")
    categories: list[str] | None = media_field("html")
    uploader_avatar: str | None = media_field("html")
    is_verified: bool | None = media_field("html")

    # Optional
    uploader_id: str | None = None
    uploader_type: str | None = None
    preview_video_url: str | None = None
    pornstars_names: list[str] | None = None
    pornstars_urls: list[str] | None = None

    loader_methods: ClassVar[dict[str, str]] = {"html": "_load_html"}
    LAYOUT_ANCHORS: ClassVar[tuple[str, ...]] = (
        "#redtube_layout",
        "#redtube-player",
        "#video_info_wrap",
    )

    async def _load_html(self) -> dict[str, object]:
        html_content = await get_html_content(core=self.core, url=self.url)
        data: dict = await asyncio.to_thread(self._extract_html, html_content)
        m3u8_source_url = data.get("m3u8_source_url")
        if not isinstance(m3u8_source_url, str):
            logger.warning("No HLS metadata URL found for %s", self.url)
            data["m3u8_base_url"] = None
        else:
            try:
                m3u8_content = await get_html_content(core=self.core, url=m3u8_source_url)
                data["m3u8_base_url"] = self._build_m3u8(m3u8_content)
            except Exception as e:
                logger.warning("Failed to fetch or build master m3u8 for %s: %s", self.url, e)
                data["m3u8_base_url"] = None
        return data

    def _extract_html(self, html_content: str) -> dict:
        parser = LexborHTMLParser(html_content)

        # Set anchors to determine whether the page changed its layout
        if not parser.css_first("#redtube_layout"):
            logger.warning(
                "Main layout anchor '#redtube_layout' not found for %s. Page structure may have changed.",
                self.url,
            )

        if not (parser.css_first("#redtube-player") or parser.css_first("#video_info_wrap")):
            logger.warning(
                "Video container anchors ('#redtube-player', '#video_info_wrap') not found for %s. Video page layout may have changed.",
                self.url,
            )

        config = self._parse_script(html_content)

        # Video ID: from page_params, data-video-id attribute, or URL fallback
        video_id = None
        vid_match = re.search(r"page_params\.video_player_id\s*=\s*['\"](\d+)['\"]", html_content)
        if vid_match:
            video_id = vid_match.group(1)
        else:
            player_el = parser.css_first("#redtube-player, div[data-video-id]")
            if player_el:
                video_id = player_el.attributes.get("data-video-id")
            if not video_id:
                url_match = re.search(r"/(\d+)", self.url)
                if url_match:
                    video_id = url_match.group(1)
                else:
                    logger.warning("Could not extract video ID for %s", self.url)

        # Title: from player config or DOM
        title = (
            config.get("video_title")
            or config.get("mainRoll", {}).get("title")
        )
        if not title:
            title_el = parser.css_first("h1.video_page_title, h1.tm_videoTitle")
            title = title_el.text(strip=True) if title_el else None
            if not title:
                logger.warning("Could not extract video title for %s", self.url)

        # Duration
        raw_duration = config.get("video_duration") or config.get("mainRoll", {}).get("duration")
        duration = None
        if raw_duration is not None:
            try:
                duration = int(raw_duration)
            except (ValueError, TypeError):
                duration = raw_duration
        if duration is None:
            dur_el = parser.css_first("span.mgp_duration, span.tm_video_duration")
            if dur_el:
                duration = dur_el.text(strip=True)
            else:
                logger.warning("Could not extract duration for %s", self.url)

        # Thumbnail / Poster
        thumbnail = (
            config.get("image_url")
            or config.get("mainRoll", {}).get("poster")
        )
        if not thumbnail:
            poster_el = parser.css_first("img.videoElementPoster, .mgp_videoPoster img")
            if poster_el:
                thumbnail = poster_el.attributes.get("src")
            else:
                logger.warning("Could not extract thumbnail for %s", self.url)

        # Embed code
        embed_code = (
            config.get("embedCode")
            or config.get("features", {}).get("embedCode")
        )
        if not embed_code and video_id:
            embed_code = f'<iframe src="https://embed.redtube.com/?id={video_id}" frameborder="0" width="560" height="340" scrolling="no" allowfullscreen></iframe>'

        # Locale
        locale = config.get("language") or config.get("locale")

        # Media definitions
        media_definitions = (
            config.get("mediaDefinitions")
            or config.get("mainRoll", {}).get("mediaDefinition", [])
        )
        if not media_definitions:
            logger.warning("No media definitions found for %s", self.url)

        # Autoplay
        autoplay_val = config.get("autoplay")
        if isinstance(autoplay_val, dict):
            is_auto_play_enabled = autoplay_val.get("enabled", False)
        elif isinstance(autoplay_val, bool):
            is_auto_play_enabled = autoplay_val
        else:
            is_auto_play_enabled = False

        # VR check
        is_vr = config.get("isVr", False)
        if not is_vr:
            is_vr = bool(re.search(r'\b(?:isVr|vrProps)\s*:\s*true\b', html_content, re.IGNORECASE))

        # Author name and URL
        author_el = parser.css_first("a.video-infobox-link, .video-infobox-uploader-name a")
        if author_el:
            author_name = author_el.text(strip=True) or None
            href = author_el.attributes.get("href")
            author_url = f"https://www.redtube.com{href}" if href and not href.startswith("http") else href
        else:
            logger.warning("Could not extract author info for %s", self.url)
            author_name = None
            author_url = None

        # Publish date
        date_el = parser.css_first("span.video-infobox-date-added")
        publish_date = date_el.text(strip=True) if date_el else None

        # HLS and MP4 URLs
        m3u8_source_url = None
        mp4_url = None
        for media in media_definitions:
            fmt = media.get("format")
            video_url = media.get("videoUrl")
            if not video_url:
                continue
            full_url = video_url if str(video_url).startswith("http") else f"https://redtube.com{video_url}"
            if fmt == "hls" and not m3u8_source_url:
                m3u8_source_url = full_url
            elif fmt == "mp4" and not mp4_url:
                mp4_url = full_url

        # Action tags
        action_tags_raw = config.get("actionTags") or config.get("mainRoll", {}).get("actionTags", "")
        action_tags = {}
        if isinstance(action_tags_raw, str) and action_tags_raw:
            try:
                for item in action_tags_raw.split(","):
                    if ":" in item:
                        tag_name, timestamp = item.rsplit(":", 1)
                        action_tags[tag_name.strip()] = int(timestamp)
            except (AttributeError, ValueError):
                logger.warning("Failed to parse action tag timestamps for video %s", video_id, exc_info=True)
        elif isinstance(action_tags_raw, dict):
            action_tags = action_tags_raw

        # Additional useful metadata
        view_el = parser.css_first("div.video_view_count span.video_view_count_item")
        views = view_el.text(strip=True) if view_el else None

        rating_el = parser.css_first("div.rating_percent")
        rating_percent = rating_el.text(strip=True) if rating_el else None

        tags = [el.text(strip=True) for el in parser.css("a.video_carousel_tag") if el.text(strip=True)]
        categories = [el.text(strip=True) for el in parser.css("a.video_carousel_category") if el.text(strip=True)]

        avatar_el = parser.css_first("img.video-infobox-uploader-avatar")
        uploader_avatar = avatar_el.attributes.get("src") if avatar_el else None

        is_verified = bool(parser.css_first(".showpage_video_infobox_badge, .verified-icon"))

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
            "publish_date": publish_date,
            "views": views,
            "rating_percent": rating_percent,
            "tags": tags,
            "categories": categories,
            "uploader_avatar": uploader_avatar,
            "is_verified": is_verified,
        }

    async def author(self, load_html: bool = False) -> Amateur | Pornstar | Channel | User:
        url = await self.get_field("author_url")
        if not isinstance(url, str):
            raise ValueError(f"No author URL found for {self.url}")

        if "amateur" in url:
            amateur = Amateur(url=url, core=self.core)
            if load_html:
                await amateur.load_sources("html")
            return amateur

        if "pornstar" in url:
            pornstar = Pornstar(url=url, core=self.core)
            if load_html:
                await pornstar.load_sources("html")
            return pornstar

        if "channel" in url:
            channel = Channel(url=url, core=self.core)
            if load_html:
                await channel.load_sources("html")
            return channel

        if "user" in url or "members" in url:
            user = User(url=url, core=self.core)
            if load_html:
                await user.load_sources("html")
            return user

        logger.warning("Could not determine Author type from URL '%s' on %s, defaulting to User", url, self.url)
        user = User(url=url, core=self.core)
        if load_html:
            await user.load_sources("html")
        return user

    @staticmethod
    def _parse_script(html_content: str) -> dict:
        """
        Extracts player configuration dictionary from HTML.
        Prioritizes the pre-evaluated JSON 'playervars' object from player setup,
        falling back to 'page_params.generalVideoConfig' or regex matching.
        """
        # 1. Primary: extract playervars object from player setup
        idx = html_content.find("playervars:")
        if idx != -1:
            try:
                return chompjs.parse_js_object(html_content[idx + len("playervars:"):])
            except Exception as e:
                logger.warning("Failed to parse playervars JS object: %s", e)

        # 2. Fallback: try generalVideoConfig
        idx = html_content.find("page_params.generalVideoConfig =")
        if idx != -1:
            try:
                return chompjs.parse_js_object(html_content[idx + len("page_params.generalVideoConfig ="):])
            except Exception as e:
                logger.warning("Failed to parse generalVideoConfig fallback: %s", e)

        # 3. Fallback: regex search for mediaDefinitions
        match = re.search(r"['\"]?mediaDefinitions['\"]?\s*:\s*(\[\s*\{.*?\}\s*\])", html_content, re.DOTALL)
        if match:
            try:
                return {"mediaDefinitions": json.loads(match.group(1))}
            except Exception as e:
                logger.warning("Failed to parse mediaDefinitions regex fallback: %s", e)

        return {}

    @staticmethod
    def _build_m3u8(content: str) -> str:
        return build_m3u8_master(content)

    async def download(self, configuration: DownloadConfigHLS) -> bool | DownloadReport:
        try:
            await self.load_fields("title", "m3u8_base_url")
            if not self.m3u8_base_url:
                raise DownloadFailed(f"No HLS stream available to download for {self.url}")
            config = copy.deepcopy(configuration)
            config.m3u8_base_url = self.m3u8_base_url
            if not config.no_title:
                config.path = os.path.join(config.path, f"{self.title}.mp4")

            return await self.core.download(configuration=config)
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
    author_url: str | None = media_field("html")
    author_name: str | None = media_field("html")
    rating_percent: str | None = media_field("html")
    rating_count: str | None = media_field("html")
    views: str | None = media_field("html")
    video_count: str | None = media_field("html")
    tags: list[str] | None = media_field("html")
    playlist_id: str | None = media_field("html")
    watch_playlist_url: str | None = media_field("html")

    # Optional
    updated_at: str | None = None
    status: str | None = None

    LAYOUT_ANCHORS: ClassVar[tuple[str, ...]] = (
        "#playlist_header",
        "#playlist_details",
        "#playlist_tabs",
    )

    loader_methods: ClassVar[dict[str, str]] = {"html": "_load_html"}

    async def _load_html(self) -> dict[str, object]:
        html_content = await get_html_content(core=self.core, url=self.url)
        return await asyncio.to_thread(self._extract_html, html_content)

    @classmethod
    def _extract_html(cls, html_content: str) -> dict[str, object]:
        parser = LexborHTMLParser(html_content)

        # Check layout anchors to detect page layout changes early
        for anchor in cls.LAYOUT_ANCHORS:
            if not parser.css_first(anchor):
                logger.warning(
                    "Layout anchor '%s' missing on playlist page; site layout may have changed.",
                    anchor,
                )

        # Title
        title_node = parser.css_first("h1#playlist_title, .playlist_title, h1")
        title = title_node.text(strip=True) if title_node else None
        if not title:
            logger.warning("Failed to extract playlist title from HTML")

        # Author
        author_node = parser.css_first("p.playlist_desc a, .playlist_desc a")
        author_name = author_node.text(strip=True) if author_node else None
        author_href = author_node.attributes.get("href") if author_node else None
        author_url = (
            f"https://www.redtube.com{author_href}"
            if author_href and author_href.startswith("/")
            else author_href
        )

        # Rating percent
        rating_percent_node = parser.css_first("div.rating_percent.js_rating_percent, .rating_percent")
        rating_percent = None
        if rating_percent_node:
            rating_percent = rating_percent_node.text(strip=True) or rating_percent_node.attributes.get("data-percent")
            if rating_percent and not rating_percent.endswith("%"):
                rating_percent = f"{rating_percent}%"

        # Stats (Ratings count, Views, Video count)
        rating_count = None
        views = None
        video_count = None

        stats_cols = parser.css(".playlist_stats .playlist_stats_col")
        if stats_cols:
            for i, col in enumerate(stats_cols):
                val_node = col.css_first(".playlist_stats_value")
                val = val_node.text(strip=True) if val_node else None
                if not val:
                    continue
                text_node = col.css_first(".playlist_stats_text")
                label = text_node.text(strip=True).lower() if text_node else ""
                if any(k in label for k in ("bewertung", "rating", "vote")):
                    rating_count = val
                elif any(k in label for k in ("ansicht", "view", "vue", "vista")):
                    views = val
                elif any(k in label for k in ("video",)):
                    video_count = val
                else:
                    if i == 0 and rating_count is None:
                        rating_count = val
                    elif i == 1 and views is None:
                        views = val
                    elif i == 2 and video_count is None:
                        video_count = val
        else:
            stat_values = [s.text(strip=True) for s in parser.css("span.playlist_stats_value") if s.text(strip=True)]
            if len(stat_values) > 0:
                rating_count = stat_values[0]
            if len(stat_values) > 1:
                views = stat_values[1]
            if len(stat_values) > 2:
                video_count = stat_values[2]

        # Fallback for video_count from playlist description e.g. "(720Videos)"
        if not video_count:
            desc_node = parser.css_first("p.playlist_desc")
            if desc_node:
                match = re.search(r"\((\d+)\s*Videos?\)", desc_node.text())
                if match:
                    video_count = match.group(1)

        # Tags
        tag_nodes = parser.css("#playlist_taglist a") or parser.css(".playlist_desc a[href*='search=']")
        tags = [t.text(strip=True).rstrip(",").strip() for t in tag_nodes if t.text(strip=True)]
        tags = [t for t in tags if t]

        # Playlist ID
        id_match = re.search(r'(?:playlist_id|itemId|object_id)\s*:\s*["\'](\d+)["\']', html_content)
        playlist_id = id_match.group(1) if id_match else None
        if not playlist_id:
            url_match = re.search(r'/playlist/(?:[a-zA-Z0-9_\-]+/)?(\d+)|pkey=(\d+)', html_content)
            if url_match:
                playlist_id = url_match.group(1) or url_match.group(2)

        # Watch playlist URL (first video link with playlist context)
        watch_btn = parser.css_first("a.watch_playlist_btn")
        watch_href = watch_btn.attributes.get("href") if watch_btn else None
        watch_playlist_url = (
            f"https://www.redtube.com{watch_href}"
            if watch_href and watch_href.startswith("/")
            else watch_href
        )

        return {
            "title": title,
            "author_url": author_url,
            "author_name": author_name,
            "rating_percent": rating_percent,
            "rating_count": rating_count,
            "views": views,
            "video_count": video_count,
            "tags": tags,
            "playlist_id": playlist_id,
            "watch_playlist_url": watch_playlist_url,
        }

    async def get_author(self, load_html: bool = False) -> User:
        author_url = await self.get_field("author_url")
        if not author_url:
            raise ValueError(f"No author URL found for playlist {self.url}")
        user_url = author_url if author_url.startswith("http") else f"https://www.redtube.com{author_url}"
        user = User(core=self.core, url=user_url)
        if load_html:
            await user.load_sources("html")
        return user

    async def get_videos(
        self,
        pages: int = 2,
        iterator_config: IteratorConfig | None = None,
    ) -> AsyncGenerator[ScrapeResult[Video], None]:
        # I am too lazy to implement search filters
        url = self.url
        helper = Helper(core=self.core, constructor=Video)
        sep = "&" if "?" in url else "?"
        page_urls = [f"{url}{sep}page={page}" for page in range(1, pages + 1)]
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
    rank: str | None = media_field("html")
    views: str | None = media_field("html")
    videos_count: str | None = media_field("html")
    subscribers_count: str | None = media_field("html")
    banner_url: str | None = media_field("html")
    avatar_url: str | None = media_field("html")
    user_id: str | None = media_field("html")

    LAYOUT_ANCHORS: ClassVar[tuple[str, ...]] = ("#profileInfo",)
    loader_methods: ClassVar[dict[str, str]] = {"html": "_load_html"}

    async def _load_html(self) -> dict[str, object]:
        html_content = await get_html_content(core=self.core, url=self.url)
        return await asyncio.to_thread(self._extract_html, html_content)

    @classmethod
    def _extract_html(cls, html_content: str) -> dict[str, object]:
        parser = LexborHTMLParser(html_content)

        # Check layout anchors
        for anchor in cls.LAYOUT_ANCHORS:
            if not parser.css_first(anchor):
                logger.warning(
                    "Layout anchor '%s' missing on %s page; site layout may have changed.",
                    anchor,
                    cls.__name__,
                )

        # Name
        name_node = parser.css_first("h1.name-title, .name-title, h1")
        name = name_node.text(strip=True) if name_node and name_node.text(strip=True) else None
        if not name:
            matches = [m for m in re.findall(r'username\s*:\s*["\']([^"\']+)["\']', html_content) if m]
            if matches:
                name = matches[-1]
        if not name:
            logger.warning("Failed to extract name for %s", cls.__name__)

        # Banner & Avatar
        banner_el = parser.css_first(".banner-wrapper img, .header-banner-wrapper img.banner-image")
        banner_url = (banner_el.attributes.get("data-src") or banner_el.attributes.get("src")) if banner_el else None

        avatar_el = parser.css_first(".avatar-wrapper img, .logo-wrapper img, img.avatar-image, img.channel_logo")
        avatar_url = (avatar_el.attributes.get("data-src") or avatar_el.attributes.get("src")) if avatar_el else None

        # User / Channel / Pornstar ID
        btn = parser.css_first(".subscribe_button, a.subscribe, .subscribe_button_wrap a")
        user_id = btn.attributes.get("data-item-id") if btn else None
        if not user_id:
            m = re.search(r'data-item-id\s*=\s*["\'](\d+)["\']', html_content)
            if m:
                user_id = m.group(1)

        # Stats (Rank, Views, Videos, Subscribers)
        rank = None
        views = None
        videos_count = None
        subscribers_count = None

        for stat in parser.css(".main-stats-bar .info-stat"):
            lbl_node = stat.css_first(".info-stat-label")
            val_node = stat.css_first(".info-stat-data")
            if not val_node:
                continue
            val = val_node.text(strip=True)
            lbl = lbl_node.text(strip=True).lower() if lbl_node else ""
            if any(k in lbl for k in ("rank", "rang")):
                rank = val
            elif any(k in lbl for k in ("view", "ansicht", "vue", "vista")):
                views = val
            elif any(k in lbl for k in ("subscriber", "abonnent", "abo")):
                subscribers_count = val
            elif any(k in lbl for k in ("video",)):
                videos_count = val

        # Fallback for videos_count (e.g. from subtitle "Anzeige 1 - 26 von 69")
        if not videos_count:
            sub = parser.css_first(".videos_count_subtitle")
            if sub:
                m = re.search(r"(?:von|of)\s+([0-9.,KMBkmb]+)", sub.text(strip=True), re.IGNORECASE)
                if m:
                    videos_count = m.group(1)

        return {
            "name": name,
            "rank": rank,
            "views": views,
            "videos_count": videos_count,
            "subscribers_count": subscribers_count,
            "banner_url": banner_url,
            "avatar_url": avatar_url,
            "user_id": user_id,
        }

    def get_videos(
        self,
        pages: int = 2,
        iterator_config: IteratorConfig | None = None,
    ) -> AsyncGenerator[ScrapeResult[Video], None]:
        url = self.url
        sep = "&" if "?" in url else "?"
        page_urls = [f"{url}{sep}page={page}" for page in range(1, pages + 1)]
        return scrape_stream(
            core=self.core,
            constructor=Video,
            target_page_urls=page_urls,
            item_extractor=extractor_html,
            iterator_config=iterator_config,
        )


@dataclass(kw_only=True, slots=True)
class User(UserHelper):
    LAYOUT_ANCHORS: ClassVar[tuple[str, ...]] = ("#user_profile_container",)

    async def get_playlists(
        self,
        pages: int = 2,
        iterator_config: IteratorConfig | None = None,
    ) -> AsyncGenerator[ScrapeResult[Playlist], None]:
        name = await self.get_field("name")
        if not isinstance(name, str) or not name:
            raise ValueError("Cannot fetch playlists, because you have not populated the html yet")

        page_urls = [f"https://redtube.com/user/{name}/playlists-data?page={page}" for page in range(1, pages + 1)]
        stream = scrape_stream(
            core=self.core,
            constructor=Playlist,
            target_page_urls=page_urls,
            item_extractor=extractor_playlist_json,
            iterator_config=iterator_config,
        )
        async for result in stream:
            yield result


@dataclass(kw_only=True, slots=True)
class Pornstar(UserHelper):
    pornstar_information: dict[str, str] | None = media_field("html")
    bio: str | None = media_field("html")
    known_for: list[str] | None = media_field("html")
    aliases: list[str] | None = media_field("html")

    LAYOUT_ANCHORS: ClassVar[tuple[str, ...]] = ("#profileInfo", ".main-information")

    @classmethod
    def _extract_html(cls, html_content: str) -> dict[str, object]:
        data = UserHelper._extract_html(html_content)
        parser = LexborHTMLParser(html_content)

        # Detailed stats / attributes (profile-info and main-stats-bar)
        pornstar_info: dict[str, str] = {}
        for stat in parser.css(".profile-info .info-stat, .main-stats-bar .info-stat"):
            lbl_el = stat.css_first(".info-stat-label")
            val_el = stat.css_first(".info-stat-data")
            if lbl_el and val_el:
                k = lbl_el.text(strip=True)
                v = val_el.text(strip=True)
                if k and v:
                    pornstar_info[k] = v
        data["pornstar_information"] = pornstar_info

        # Bio text
        bio_node = parser.css_first(".profile-bio, #DrawerProfileInfo .profile-bio")
        data["bio"] = bio_node.text(strip=True) if bio_node else None

        # Known for (channels)
        tag_nodes = parser.css(".known-for-tags-wrapper .known-for-tag a") or parser.css(".known-for-wrapper a")
        data["known_for"] = [a.text(strip=True) for a in tag_nodes if a.text(strip=True)]

        # Aliases
        alias_node = parser.css_first(".alias_names_wrapper .alias_names, .alias_names")
        alias_text = alias_node.text(strip=True) if alias_node else ""
        data["aliases"] = [a.strip() for a in alias_text.split(",") if a.strip()] if alias_text else []

        return data


@dataclass(kw_only=True, slots=True)
class Amateur(UserHelper):
    LAYOUT_ANCHORS: ClassVar[tuple[str, ...]] = ("#profileInfo", ".main-information")


@dataclass(kw_only=True, slots=True)
class Channel(UserHelper):
    LAYOUT_ANCHORS: ClassVar[tuple[str, ...]] = ("#profileInfo", ".main-information")


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

    async def get_user(self, url: str, load_html: bool = True) -> User:
        user = User(core=self.core, url=url)
        if load_html:
            await user.load_sources("html")
        return user

    def search(
        self,
        query: str,
        pages: int = 2,
        iterator_config: IteratorConfig | None = None,
    ) -> AsyncGenerator[ScrapeResult[Video], None]:
        # I am too lazy to implement search filters
        page_urls = [f"https://redtube.com/?search={query}&page={page}" for page in range(1, pages + 1)]
        return scrape_stream(
            core=self.core,
            constructor=Video,
            target_page_urls=page_urls,
            item_extractor=extractor_html,
            iterator_config=iterator_config,
        )



def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="RedTube API Command Line Interface")
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
