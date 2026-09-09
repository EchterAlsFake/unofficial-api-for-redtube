import pytest
from base_api import DownloadConfigHLS

from redtube_api import Client


@pytest.mark.asyncio
async def test_all():
    client = Client()
    video = await client.get_video("https://de.redtube.com/191071081")

    assert isinstance(video.title, str) and len(video.title) > 0
    assert isinstance(video.video_id, str) and len(video.video_id) > 0
    assert isinstance(video.media_definitions, list) and len(video.media_definitions) > 0
    assert isinstance(video.duration, int) and len(str(video.duration)) > 0
    assert isinstance(video.thumbnail, str) and len(video.thumbnail) > 0
    assert isinstance(video.embed_code, str) and len(video.embed_code) > 0
    assert isinstance(video.is_auto_play_enabled, bool)
    assert isinstance(video.is_vr, bool)
    assert isinstance(video.author_name, str) and len(video.author_name) > 0
    assert isinstance(video.views, str) and len(video.views) > 0
    assert isinstance(video.rating_percent, str) and len(video.rating_percent) > 0
    assert isinstance(video.tags, list) and len(video.tags) > 0
    assert isinstance(video.categories, list) and len(video.categories) > 0
    assert isinstance(video.uploader_avatar, str) and len(video.uploader_avatar) > 0
    assert isinstance(video.is_verified, bool)

    author = await video.author(True)
    assert isinstance(author.name, str) and len(author.name) > 0

    config = DownloadConfigHLS(quality="worst", return_report=True)

    stuff = await video.download(config)
    assert stuff.status == "completed"


def test_video_extraction_unit():
    from base_api import BaseCore
    from redtube_api.api import Video

    core = BaseCore()
    video = Video(url="https://redtube.com/261423801", core=core)
    html = """
    <div id="redtube_layout">
        <div id="redtube-player" data-video-id="261423801"></div>
        <div id="video_info_wrap">
            <h1 class="video_page_title tm_videoTitle">Test Video Title</h1>
            <div class="video_view_count"><span class="video_view_count_item">100K Views</span></div>
            <div class="rating_percent">98%</div>
            <div id="video-infobox">
                <a class="video-infobox-link" href="/amateur/testuser">testuser</a>
                <span class="video-infobox-date-added">January 1, 2026</span>
                <img class="video-infobox-uploader-avatar" src="https://example.com/avatar.jpg">
                <span class="verified-icon"></span>
            </div>
            <div id="video_tags_carousel">
                <a class="video_carousel_tag" href="#">tag1</a>
                <a class="video_carousel_category" href="#">cat1</a>
            </div>
        </div>
        <script id="tm_pc_player_setup">
            page_params.video_player_id = "261423801";
            page_params.video_player_setup = {
                playerDiv_261423801: {
                    playervars: {
                        "video_title": "Test Video Title",
                        "video_duration": 300,
                        "image_url": "https://example.com/thumb.jpg",
                        "embedCode": "<iframe></iframe>",
                        "autoplay": true,
                        "language": "en",
                        "mediaDefinitions": [{"format": "hls", "videoUrl": "/media/hls?s=123"}]
                    }
                }
            };
        </script>
    </div>
    """
    data = video._extract_html(html)
    assert data["video_id"] == "261423801"
    assert data["title"] == "Test Video Title"
    assert data["duration"] == 300
    assert data["thumbnail"] == "https://example.com/thumb.jpg"
    assert data["embed_code"] == "<iframe></iframe>"
    assert data["views"] == "100K Views"
    assert data["rating_percent"] == "98%"
    assert data["tags"] == ["tag1"]
    assert data["categories"] == ["cat1"]
    assert data["is_verified"] is True
    assert data["uploader_avatar"] == "https://example.com/avatar.jpg"
    assert data["author_name"] == "testuser"
    assert data["author_url"] == "https://www.redtube.com/amateur/testuser"
    assert data["m3u8_source_url"] == "https://redtube.com/media/hls?s=123"


def test_video_missing_anchors():
    from base_api import BaseCore
    from redtube_api.api import Video

    core = BaseCore()
    video = Video(url="https://redtube.com/99999", core=core)
    data = video._extract_html("<div>Empty page</div>")
    assert data["video_id"] == "99999"
    assert data["title"] is None
    assert data["thumbnail"] is None
    assert data["media_definitions"] == []