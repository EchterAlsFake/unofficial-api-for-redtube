import pytest
from redtube_api import Client


@pytest.mark.asyncio
async def test_all():
    client = Client()
    playlist = await client.get_playlist("https://de.redtube.com/playlist/4237321")

    assert isinstance(playlist.title, str) and len(playlist.title) > 0
    assert isinstance(playlist.author_name, str) and len(playlist.author_name) > 0
    assert isinstance(playlist.rating_count, str) and len(playlist.rating_count) > 0
    assert isinstance(playlist.rating_percent, str) and len(playlist.rating_percent) > 0
    assert isinstance(playlist.video_count, str) and len(playlist.video_count) > 0
    assert isinstance(playlist.views, str) and len(playlist.views) > 0

    author = await playlist.get_author(True)

    idx = 0
    async for _playlist in author.get_playlists():
        idx += 1
        item = _playlist.unwrap()
        assert isinstance(item.title, str) and len(item.title) > 0

        if idx >= 3:
            break


    idx = 0
    async for video in playlist.get_videos():
        idx += 1

        assert isinstance(video.unwrap().title, str)

        if idx >= 3:
            break


PLAYLIST_HTML_SNIPPET = """
<div id="content_wrapper" class="removeAdLink">
    <div id="playlist_header">
        <div class="playlist_info">
            <h1 id="playlist_title" class="playlist_title">Perfect tits</h1>
            <p class="playlist_desc">
                <span class="playlist_desc_label">Playlist by</span>
                <a href="/user/31618721?tab=playlists"> emilscc</a> (720Videos)
            </p>
            <p class="playlist_desc">
                <span class="playlist_desc_label">Tags</span>
                <span id="playlist_taglist">
                    <a href="/?search=big+tits">Big Tits,</a>
                    <a href="/?search=milf">MILF,</a>
                    <a href="/?search=natural+tits">Natural Tits,</a>
                </span>
            </p>
            <a href="/213989831?pkey=2348321" class="rt_btn_style_two watch_playlist_btn">Wiedergabeliste ansehen</a>
        </div>
    </div>
    <div id="playlist_details" class="clearfix">
        <div class="playlist_details_wrap">
            <div class="ratingSystem">
                <div class="rating_percent js_rating_percent" data-percent="85">
                    85%
                </div>
            </div>
            <div class="playlist_stats">
                <div class="playlist_stats_col">
                    <span class="playlist_stats_text">Bewertungen</span>
                    <span class="playlist_stats_value">9064</span>
                </div>
                <div class="playlist_stats_col">
                    <span class="playlist_stats_text">Ansichten</span>
                    <span class="playlist_stats_value">7,439,537</span>
                </div>
                <div class="playlist_stats_col">
                    <span class="playlist_stats_text">VIDEOS</span>
                    <span class="playlist_stats_value">720</span>
                </div>
            </div>
        </div>
    </div>
    <div id="playlist_tabs"></div>
    <script>
        page_params = {};
        page_params.favorite_system_setup = {
            object_id: "2348321",
            object_type: "Playlist",
        };
    </script>
</div>
"""


def test_playlist_extract_html():
    from redtube_api.api import Playlist

    data = Playlist._extract_html(PLAYLIST_HTML_SNIPPET)
    assert data["title"] == "Perfect tits"
    assert data["author_name"] == "emilscc"
    assert data["author_url"] == "https://www.redtube.com/user/31618721?tab=playlists"
    assert data["rating_percent"] == "85%"
    assert data["rating_count"] == "9064"
    assert data["views"] == "7,439,537"
    assert data["video_count"] == "720"
    assert data["tags"] == ["Big Tits", "MILF", "Natural Tits"]
    assert data["playlist_id"] == "2348321"
    assert data["watch_playlist_url"] == "https://www.redtube.com/213989831?pkey=2348321"


def test_playlist_missing_anchors_and_fallbacks():
    from redtube_api.api import Playlist

    data = Playlist._extract_html("<div>Empty or broken page</div>")
    assert data["title"] is None
    assert data["author_name"] is None
    assert data["author_url"] is None
    assert data["rating_percent"] is None
    assert data["rating_count"] is None
    assert data["views"] is None
    assert data["video_count"] is None
    assert data["tags"] == []
    assert data["playlist_id"] is None
    assert data["watch_playlist_url"] is None


def test_playlist_video_count_desc_fallback():
    from redtube_api.api import Playlist

    html = """
    <div id="playlist_header">
        <p class="playlist_desc">
            <span class="playlist_desc_label">Playlist by</span>
            <a href="/user/12345">user1</a> (450Videos)
        </p>
    </div>
    <div id="playlist_details"></div>
    <div id="playlist_tabs"></div>
    """
    data = Playlist._extract_html(html)
    assert data["video_count"] == "450"
    assert data["author_name"] == "user1"
    assert data["author_url"] == "https://www.redtube.com/user/12345"
