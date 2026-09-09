import pytest
from redtube_api import Client


@pytest.mark.asyncio
async def test_all():
    client = Client()
    pornstar = await client.get_pornstar("https://de.redtube.com/pornstar/leny+evil")

    idx = 0
    async for video in pornstar.get_videos():
        idx += 1

        item = video.unwrap()
        assert isinstance(item.title, str) and len(item.title) > 0

        if idx >= 3:
            break


PORNSTAR_HTML_SNIPPET = """
<div id="pornstar_videos_overview" class="content_limit">
    <div id="profileInfo">
        <div class="header-banner-wrapper">
            <div class="banner-wrapper">
                <img class="banner-image" src="https://example.com/banner.jpg">
            </div>
            <div class="avatar-wrapper">
                <img class="avatar-image" src="https://example.com/avatar.jpg">
            </div>
        </div>
        <div class="main-information">
            <div class="name-wrapper">
                <h1 class="name-title">Melody Jordan</h1>
            </div>
            <div class="subscribe-btn">
                <a class="subscribe_button" data-item-id="21961" data-item-type="pornstar">Abonnieren</a>
            </div>
            <div class="main-stats-bar">
                <ul class="main-stats-wrapper">
                    <li class="info-stat">
                        <p class="info-stat-label">Model Rank</p>
                        <p class="info-stat-data">3,181st</p>
                    </li>
                    <li class="info-stat">
                        <p class="info-stat-label">Ansichten</p>
                        <p class="info-stat-data">411K</p>
                    </li>
                    <li class="info-stat">
                        <p class="info-stat-label">Abonnenten</p>
                        <p class="info-stat-data">1,884</p>
                    </li>
                </ul>
            </div>
        </div>
        <div id="DrawerProfileInfo">
            <div class="profile-bio">Sample bio of Melody Jordan.</div>
            <ul class="profile-info">
                <li class="info-stat">
                    <p class="info-stat-label">Geburtsdatum</p>
                    <p class="info-stat-data">1991-10-05</p>
                </li>
                <li class="info-stat">
                    <p class="info-stat-label">Höhe</p>
                    <p class="info-stat-data">5 ft 9 in (175 cm)</p>
                </li>
            </ul>
            <div class="known-for-wrapper">
                <ul class="known-for-tags-wrapper">
                    <li class="known-for-tag"><a class="known-for-text" href="/channels/siripornstar">Siri Pornstar</a></li>
                    <li class="known-for-tag"><a class="known-for-text" href="/channels/banging-beauties">Banging Beauties</a></li>
                </ul>
            </div>
        </div>
    </div>
    <span class="videos_count_subtitle">Anzeige 1 - 26 von 69</span>
</div>
"""


def test_pornstar_extract_html():
    from redtube_api.api import Pornstar

    data = Pornstar._extract_html(PORNSTAR_HTML_SNIPPET)
    assert data["name"] == "Melody Jordan"
    assert data["rank"] == "3,181st"
    assert data["views"] == "411K"
    assert data["subscribers_count"] == "1,884"
    assert data["videos_count"] == "69"
    assert data["banner_url"] == "https://example.com/banner.jpg"
    assert data["avatar_url"] == "https://example.com/avatar.jpg"
    assert data["user_id"] == "21961"
    assert data["bio"] == "Sample bio of Melody Jordan."
    assert data["known_for"] == ["Siri Pornstar", "Banging Beauties"]
    assert data["pornstar_information"]["Geburtsdatum"] == "1991-10-05"
    assert data["pornstar_information"]["Höhe"] == "5 ft 9 in (175 cm)"


def test_pornstar_missing_anchors_and_fallbacks():
    from redtube_api.api import Pornstar

    data = Pornstar._extract_html("<div>Empty page</div>")
    assert data["name"] is None
    assert data["rank"] is None
    assert data["views"] is None
    assert data["videos_count"] is None
    assert data["subscribers_count"] is None
    assert data["banner_url"] is None
    assert data["avatar_url"] is None
    assert data["user_id"] is None
    assert data["bio"] is None
    assert data["known_for"] == []
    assert data["pornstar_information"] == {}
