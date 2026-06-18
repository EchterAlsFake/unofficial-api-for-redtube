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

    author = await playlist.author()
    assert isinstance(author.name, str) and len(author.name) > 0

    idx = 0
    async for playlist in author.get_playlists():
        idx += 1
        assert isinstance(playlist.title, str) and len(playlist.title) > 0

        if idx >= 3:
            break


    idx = 0
    async for video in playlist.get_videos():
        idx += 1

        assert isinstance(video.title, str)

        if idx >= 3:
            break