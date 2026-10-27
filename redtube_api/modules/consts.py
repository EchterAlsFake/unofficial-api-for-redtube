from urllib.parse import urljoin
import json
from selectolax.lexbor import LexborHTMLParser


HEADERS = {
    'Accept': '*/*',
    'Connection': 'keep-alive',
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/114.0',
    'Referer': 'https://www.redtube.com/',
    'Origin': 'https://www.redtube.com',
}

COOKIES = {
    'accessAgeDisclaimerPH': '1',
    'accessAgeDisclaimerUK': '1',
    'accessRT': '1',
    'age_verified': '1',
    'cookieBannerState': '1',
    'platform': 'pc'
}


def extractor_html(html_content: str, base_url: str = "https://www.redtube.com") -> list:
    videos_lol = []
    parser = LexborHTMLParser(html_content)

    # Ensure the parent element exists before querying its children
    stuff = parser.css_first("ul#playlist_videos") or parser.css_first("ul.videos_grid")
    if not stuff:
        return videos_lol

    videos = stuff.css("li[data-video-id]")

    for video in videos:
        # Attributes from the main wrapper
        video_id = video.attributes.get("data-video-id")
        uploader_id = video.attributes.get("data-uploader-id")
        uploader_type = video.attributes.get("data-uploader-type")
        author_name = video.attributes.get("data-uploader-name")

        # Safe extraction for the main link and image
        a_tag = video.css_first("a.video_link")
        link = a_tag.attributes.get("href") if a_tag else None

        img_tag = a_tag.css_first("img") if a_tag else None
        thumbnail = None
        if img_tag:
            thumbnail = (
                img_tag.attributes.get("data-src")
                or img_tag.attributes.get("data-o_thumb")
                or img_tag.attributes.get("data-thumb_url")
            )
            if not thumbnail:
                srcset = img_tag.attributes.get("data-srcset") or img_tag.attributes.get("srcset")
                if srcset:
                    # In srcset: "url1 1x, url2 2x" -> take the last (highest resolution) or first URL
                    urls = [p.strip().split()[0] for p in srcset.split(",") if p.strip()]
                    thumbnail = urls[-1] if urls else None
            if not thumbnail:
                src = img_tag.attributes.get("src")
                if src and not src.startswith("data:"):
                    thumbnail = src

        preview_video_url = img_tag.attributes.get("data-mediabook") if img_tag else None

        # Safe duration extraction
        dur_tag = video.css_first("span.tm_video_duration, span.video_duration, span.duration")
        duration = dur_tag.text(strip=True) if dur_tag else None

        # Meta wrapper
        meta = video.css_first("div.thumb-info-wrapper")
        if not meta:
            continue

        title_tag = meta.css_first("a.video-title-text")
        title = (title_tag.attributes.get("title") or title_tag.text(strip=True)) if title_tag else None

        # Targeted author link extraction (avoiding index relying like meta.css("a")[1])
        author_tag = meta.css_first("div.author-title-container a, div.video-infobox-uploader a")
        _author_link = author_tag.attributes.get("href") if author_tag else None
        author_link = urljoin(base_url, _author_link) if _author_link else None

        pornstars_names = []
        pornstars_urls = []

        # Scoped performer extraction
        _pornstars = meta.css_first("div.performers-list")
        if _pornstars:
            # Query ONLY inside the performers list
            pornstars = _pornstars.css("a")
            for star in pornstars:
                star_name = star.text(strip=True).rstrip(",").strip()
                if not star_name or star_name in pornstars_names:
                    continue
                pornstars_names.append(star_name)
                star_href = star.attributes.get('href')
                if star_href:
                    pornstars_urls.append(urljoin(base_url, star_href))

        video_data = {
            "url": urljoin(base_url, link) if link else None,
            "video_id": video_id,
            "uploader_id": uploader_id,
            "author_name": author_name,
            "uploader_type": uploader_type,
            "thumbnail": thumbnail,
            "preview_video_url": preview_video_url,
            "duration": duration,
            "title": title,
            "author_url": author_link,
            "pornstars_names": pornstars_names,
            "pornstars_urls": pornstars_urls,
        }
        if video_data["url"]:
            videos_lol.append(video_data)

    return videos_lol


def extractor_playlist_json(content: str | dict, base_url: str = "https://www.redtube.com") -> list:
    if isinstance(content, str):
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            return []
    else:
        data = content

    playlist_urls = []

    # Safely navigate to the list of playlists
    if isinstance(data, dict):
        raw_data = data.get("data", [])
        if isinstance(raw_data, dict):
            playlists = raw_data.get("data", [])
        elif isinstance(raw_data, list):
            playlists = raw_data
        else:
            playlists = []
    elif isinstance(data, list):
        playlists = data
    else:
        playlists = []

    for playlist in playlists:
        if not isinstance(playlist, dict):
            continue

        # Extract fields directly from the playlist item dictionary
        views = playlist.get("views", None)
        author = playlist.get("username", None)
        videos_count = playlist.get("playlistVideoCount", None)
        vote_percentage = playlist.get("votePercentage", None)
        status = playlist.get("status", None)
        updated_at = playlist.get("updated", None)
        title = playlist.get("title", None)
        url = playlist.get("url", None)

        # Build the absolute URL for the playlist
        playlist_url = urljoin(base_url, url) if url else None

        playlist_data = {
            "views": views,
            "author_name": author,
            "updated_at": updated_at,
            "title": title,
            "url": playlist_url,
            "video_count": videos_count,
            "rating_percent": vote_percentage,
            "status": status,
        }
        if playlist_data["url"]:
            playlist_urls.append(playlist_data)

    return playlist_urls
