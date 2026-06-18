import pytest
from redtube_api import Client


@pytest.mark.asyncio
async def test_all():
    client = Client()
    playlist = await client.get_playlist("https://de.redtube.com/playlist/4237321")

    assert isinstance(playlist.title, str) and len(playlist.title) > 0
    assert isinstance(playlist.author, str) and len(playlist.author) > 0
    assert isinstance(playlist.rating_count, str) and len(playlist.rating_count) > 0
    assert isinstance(playlist.rating_percent, str) and len(playlist.rating_percent) > 0
    assert isinstance(playlist.video_count, str) and len(playlist.video_count) > 0
    assert isinstance(playlist.views, str) and len(playlist.views) > 0


    idx = 0
    async for video in playlist.get_videos():
        idx += 1

        assert isinstance(video.title, str)

        if idx >= 3:
            break