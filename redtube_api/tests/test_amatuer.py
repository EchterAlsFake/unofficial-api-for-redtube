import pytest
from redtube_api import Client


@pytest.mark.asyncio
async def test_all():
    client = Client()
    amateur = await client.get_amateur("https://de.redtube.com/amateur/texas-milf-pov")

    assert isinstance(amateur.name, str) and len(amateur.name) > 0

    idx = 0
    async for video in amateur.get_videos():
        idx += 1

        assert isinstance(video.title, str)

        if idx >= 3:
            break