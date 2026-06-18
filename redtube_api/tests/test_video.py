import pytest
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
    assert isinstance(video.is_autoplay_enabled, bool)
    assert isinstance(video.is_vr, bool)


    stuff = await video.download(quality="best", return_report=True)
    assert stuff["status"] == "completed"