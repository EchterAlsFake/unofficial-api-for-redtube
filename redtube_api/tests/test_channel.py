import pytest
from redtube_api import Client

@pytest.mark.asyncio
async def test_all():
    client = Client()
    channel = await client.get_channel("https://de.redtube.com/channels/freeuse")

    assert isinstance(channel.name, str) and len(channel.name) > 0
    assert isinstance(channel.views, str) and len(channel.views) > 0
    assert isinstance(channel.rank, str) and len(channel.rank) > 0
    assert isinstance(channel.subscribers_count, str) and len(channel.subscribers_count) > 0
    assert isinstance(channel.videos_count, str) and len(channel.videos_count) > 0

    idx = 0
    async for video in channel.get_videos():
        idx += 1
        item = video.unwrap()
        assert isinstance(item.title, str) and len(item.title) > 0

        if idx >= 3:
            break


CHANNEL_HTML_SNIPPET = """
<div class="channel_page">
    <div class="channel_profile_overview">
        <div id="profileInfo">
            <div class="header-banner-wrapper">
                <div class="banner-wrapper">
                    <img alt="AllGirlMassage" src="https://example.com/channel_banner.jpg">
                </div>
                <div class="logo-wrapper">
                    <img alt="AllGirlMassage" src="https://example.com/channel_logo.jpg">
                </div>
            </div>
            <div class="main-information">
                <div class="name-wrapper">
                    <h1 class="name-title">AllGirlMassage</h1>
                </div>
                <div class="stats-bar-wrapper">
                    <div class="main-stats-bar">
                        <ul class="main-stats-wrapper">
                            <li class="info-stat">
                                <p class="info-stat-label">Rang</p>
                                <p class="info-stat-data">89th</p>
                            </li>
                            <li class="info-stat">
                                <p class="info-stat-label">VIDEOS</p>
                                <p class="info-stat-data">1.1K</p>
                            </li>
                            <li class="info-stat">
                                <p class="info-stat-label">Abonnenten</p>
                                <p class="info-stat-data">12.8K</p>
                            </li>
                            <li class="info-stat">
                                <p class="info-stat-label">Ansichten</p>
                                <p class="info-stat-data">70.4M</p>
                            </li>
                        </ul>
                    </div>
                    <div class="channel-buttons-wrapper">
                        <div class="channel-subscribe">
                            <a class="subscribe_button" data-item-id="145238" data-item-type="channel">Abonnieren</a>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>
</div>
"""


def test_channel_extract_html():
    from redtube_api.api import Channel

    data = Channel._extract_html(CHANNEL_HTML_SNIPPET)
    assert data["name"] == "AllGirlMassage"
    assert data["rank"] == "89th"
    assert data["videos_count"] == "1.1K"
    assert data["subscribers_count"] == "12.8K"
    assert data["views"] == "70.4M"
    assert data["banner_url"] == "https://example.com/channel_banner.jpg"
    assert data["avatar_url"] == "https://example.com/channel_logo.jpg"
    assert data["user_id"] == "145238"


def test_channel_missing_anchors_and_fallbacks():
    from redtube_api.api import Channel

    data = Channel._extract_html("<div>Empty page</div>")
    assert data["name"] is None
    assert data["rank"] is None
    assert data["views"] is None
    assert data["videos_count"] is None
    assert data["subscribers_count"] is None
    assert data["banner_url"] is None
    assert data["avatar_url"] is None
    assert data["user_id"] is None
