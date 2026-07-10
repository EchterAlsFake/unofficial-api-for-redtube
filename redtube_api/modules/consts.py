import json
from selectolax.lexbor import LexborHTMLParser


HEADERS = {
    'Accept': '*/*',
    'Accept-Language': 'en,en-US',
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


def extractor_html(html_content: str) -> list:
    videos_lol = []
    parser = LexborHTMLParser(html_content)

    # Ensure the parent element exists before querying its children
    stuff = parser.css_first("ul.videos_grid")
    if not stuff:
        return videos_lol

    videos = stuff.css("li")

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
        # Often lazy-loaded images hold the actual URL in 'data-src' or 'data-srcset'
        thumbnail = img_tag.attributes.get("data-srcset") or img_tag.attributes.get("srcset") if img_tag else None
        preview_video_url = img_tag.attributes.get("data-mediabook") if img_tag else None

        # Safe duration extraction
        dur_tag = video.css_first("span.tm_video_duration")
        duration = dur_tag.text(strip=True) if dur_tag else None

        # Meta wrapper
        meta = video.css_first("div.thumb-info-wrapper")
        if not meta:
            continue

        title_tag = meta.css_first("a.video-title-text")
        title = title_tag.attributes.get("title") if title_tag else None

        # Targeted author link extraction (avoiding index relying like meta.css("a")[1])
        author_tag = meta.css_first("div.author-title-container a")
        _author_link = author_tag.attributes.get("href") if author_tag else None
        author_link = f"https://www.redtube.com{_author_link}" if _author_link else None

        pornstars_names = []
        pornstars_urls = []

        # Scoped performer extraction
        _pornstars = meta.css_first("div.performers-list")
        if _pornstars:
            # Query ONLY inside the performers list
            pornstars = _pornstars.css("a")
            for star in pornstars:
                pornstars_names.append(star.text(strip=True))
                # Fixed the f-string quote collision by using single quotes inside
                star_href = star.attributes.get('href')
                if star_href:
                    pornstars_urls.append(f"https://www.redtube.com{star_href}")

        videos_lol.append({
            "url": f"https://www.redtube.com{link}" if link else None,
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
        })

    return videos_lol


def extractor_playlist_json(content: str | dict) -> list:
    if isinstance(content, str):
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            return []
    else:
        data = content

    playlist_urls = []

    # Safely navigate to the nested list of playlists (data -> data)
    playlists = data.get("data", {}).get("data", []) if isinstance(data, dict) else []

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
        playlist_url = f"https://www.redtube.com{url}" if url else None

        playlist_urls.append({
            "views": views,
            "author_name": author,
            "updated_at": updated_at,
            "title": title,
            "url": playlist_url,
            "video_count": videos_count,
            "rating_percent": vote_percentage,
            "status": status,
        })

    return playlist_urls
