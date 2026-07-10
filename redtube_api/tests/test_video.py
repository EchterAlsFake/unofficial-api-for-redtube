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

    author = await video.author(True)
    assert isinstance(author.name, str) and len(author.name) > 0

    config = DownloadConfigHLS(quality="worst", return_report=True)

    stuff = await video.download(config)
    assert stuff.status == "completed"