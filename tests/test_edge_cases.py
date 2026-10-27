"""
Comprehensive unit tests covering edge cases, URL normalization, HTML/JSON extractions,
multilingual parsing, and fallback behaviors for redtube_api.
"""
import unittest
import json
from unittest.mock import AsyncMock, MagicMock, patch

from base_api import BaseCore, DownloadConfigHLS
from redtube_api import Client, Video, Playlist, Channel, Pornstar, Amateur
from redtube_api.api import User, UserHelper, run_main
from redtube_api.modules.consts import extractor_html, extractor_playlist_json


class TestUrlNormalizationEdgeCases(unittest.TestCase):
    def setUp(self):
        self.core = MagicMock(spec=BaseCore)

    def test_video_id_normalization(self):
        v1 = Video(url="191071081", core=self.core)
        self.assertEqual(v1.url, "https://www.redtube.com/191071081")

        v2 = Video(url="/191071081", core=self.core)
        self.assertEqual(v2.url, "https://www.redtube.com/191071081")

        v3 = Video(url="https://de.redtube.com/191071081", core=self.core)
        self.assertEqual(v3.url, "https://de.redtube.com/191071081")

    def test_playlist_id_normalization(self):
        p1 = Playlist(url="4237321", core=self.core)
        self.assertEqual(p1.url, "https://www.redtube.com/playlist/4237321")

        p2 = Playlist(url="/playlist/4237321", core=self.core)
        self.assertEqual(p2.url, "https://www.redtube.com/playlist/4237321")

        p3 = Playlist(url="https://www.redtube.com/playlist/4237321", core=self.core)
        self.assertEqual(p3.url, "https://www.redtube.com/playlist/4237321")

    def test_channel_singular_to_plural_normalization(self):
        c = Channel(url="https://www.redtube.com/channel/brazzers", core=self.core)
        self.assertEqual(c.url, "https://www.redtube.com/channels/brazzers")

    def test_pornstar_plural_to_singular_normalization(self):
        p = Pornstar(url="https://www.redtube.com/pornstars/eva+elfie", core=self.core)
        self.assertEqual(p.url, "https://www.redtube.com/pornstar/eva+elfie")

    def test_amateur_plural_to_singular_normalization(self):
        a = Amateur(url="https://www.redtube.com/amateurs/cumatozz-ph", core=self.core)
        self.assertEqual(a.url, "https://www.redtube.com/amateur/cumatozz-ph")

    def test_user_plural_to_singular_normalization(self):
        u = User(url="https://www.redtube.com/users/emilscc", core=self.core)
        self.assertEqual(u.url, "https://www.redtube.com/user/emilscc")

    def test_profile_subpath_stripping(self):
        # /videos subpath is stripped to base profile
        c = Channel(url="https://www.redtube.com/channels/freeuse/videos", core=self.core)
        self.assertEqual(c.url, "https://www.redtube.com/channels/freeuse")

    def test_profile_shallow_url_raises_value_error(self):
        with self.assertRaises(ValueError):
            Channel(url="https://www.redtube.com/channels", core=self.core)


class TestVideoExtractionEdgeCases(unittest.TestCase):
    def setUp(self):
        self.core = MagicMock(spec=BaseCore)

    def test_meta_tag_fallbacks_when_dom_and_config_missing(self):
        html = """
        <div id="redtube_layout">
            <meta property="og:title" content="Fallback Meta Title">
            <meta property="og:video:duration" content="750">
            <meta property="og:image" content="https://example.com/fallback_og.jpg">
            <div id="video_info_wrap">
                <a class="video-infobox-link" href="/channels/studio-hub">Studio Hub</a>
                <a class="subscribe_button" data-item-id="88214" data-item-type="channel">Subscribe</a>
                <a class="tm_pornstar_name" href="/pornstar/jane+doe">Jane Doe</a>
                <a class="tm_pornstar_name" href="/pornstar/jane+doe">Jane Doe</a>
                <a class="ps_info_name" href="/pornstar/john+smith">John Smith</a>
            </div>
        </div>
        """
        video = Video(url="https://www.redtube.com/987654", core=self.core)
        data = video._extract_html(html)

        self.assertEqual(data["video_id"], "987654")
        self.assertEqual(data["title"], "Fallback Meta Title")
        self.assertEqual(data["duration"], 750)
        self.assertEqual(data["thumbnail"], "https://example.com/fallback_og.jpg")
        self.assertEqual(data["author_name"], "Studio Hub")
        self.assertEqual(data["author_url"], "https://www.redtube.com/channels/studio-hub")
        self.assertEqual(data["uploader_id"], "88214")
        self.assertEqual(data["uploader_type"], "channel")
        # Performers deduplicated and clean
        self.assertEqual(data["pornstars_names"], ["Jane Doe", "John Smith"])
        self.assertEqual(
            data["pornstars_urls"],
            ["https://www.redtube.com/pornstar/jane+doe", "https://www.redtube.com/pornstar/john+smith"]
        )

    def test_action_tags_parsing_variants(self):
        video = Video(url="https://www.redtube.com/111", core=self.core)

        # 1. String format: "Tag1:120,Tag2:450"
        html1 = """
        <script>
        page_params.generalVideoConfig = {
            "actionTags": "Blowjob:120, Doggystyle:450"
        };
        </script>
        """
        data1 = video._extract_html(html1)
        self.assertEqual(data1["action_tags"], {"Blowjob": 120, "Doggystyle": 450})

        # 2. Dict format
        html2 = """
        <script>
        page_params.generalVideoConfig = {
            "actionTags": {"Blowjob": 120, "Cowgirl": 300}
        };
        </script>
        """
        data2 = video._extract_html(html2)
        self.assertEqual(data2["action_tags"], {"Blowjob": 120, "Cowgirl": 300})

        # 3. Malformed action tags string does not crash
        html3 = """
        <script>
        page_params.generalVideoConfig = {
            "actionTags": "InvalidFormatWithoutColons, another"
        };
        </script>
        """
        data3 = video._extract_html(html3)
        self.assertEqual(data3["action_tags"], {})


class TestVideoAuthorRouting(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.core = MagicMock(spec=BaseCore)

    async def test_author_resolution_for_all_types(self):
        test_cases = [
            ("https://www.redtube.com/channels/brazzers", Channel),
            ("https://www.redtube.com/channel/brazzers", Channel),
            ("https://www.redtube.com/amateur/cumatozz-ph", Amateur),
            ("https://www.redtube.com/pornstar/eva+elfie", Pornstar),
            ("https://www.redtube.com/user/31618721", User),
            ("https://www.redtube.com/members/john", User),
            ("https://www.redtube.com/unknown/profile", User),  # fallback
        ]

        for author_url, expected_cls in test_cases:
            with self.subTest(author_url=author_url, expected_cls=expected_cls):
                video = Video(url="https://www.redtube.com/123", core=self.core)
                object.__setattr__(video, "author_url", author_url)
                author = await video.author(load_html=False)
                self.assertIsInstance(author, expected_cls)

    async def test_author_missing_raises_value_error(self):
        video = Video(url="https://www.redtube.com/123", core=self.core)
        object.__setattr__(video, "author_url", None)
        with self.assertRaises(ValueError):
            await video.author(load_html=False)


class TestPlaylistExtractionEdgeCases(unittest.TestCase):
    def test_multilingual_playlist_stats(self):
        # French stats
        fr_html = """
        <div id="playlist_header">
            <h1 id="playlist_title">Liste Française</h1>
            <p class="playlist_desc">
                <a href="/user/123">Créateur</a> (45 Vidéos)
            </p>
        </div>
        <div id="playlist_details">
            <div class="playlist_stats">
                <div class="playlist_stats_col">
                    <span class="playlist_stats_text">Évaluations</span>
                    <span class="playlist_stats_value">150</span>
                </div>
                <div class="playlist_stats_col">
                    <span class="playlist_stats_text">Vues</span>
                    <span class="playlist_stats_value">10,500</span>
                </div>
                <div class="playlist_stats_col">
                    <span class="playlist_stats_text">Vidéos</span>
                    <span class="playlist_stats_value">45</span>
                </div>
            </div>
        </div>
        """
        data = Playlist._extract_html(fr_html)
        self.assertEqual(data["title"], "Liste Française")
        self.assertEqual(data["rating_count"], "150")
        self.assertEqual(data["views"], "10,500")
        self.assertEqual(data["video_count"], "45")

        # Spanish stats
        es_html = """
        <div id="playlist_header">
            <h1 id="playlist_title">Lista Española</h1>
            <p class="playlist_desc">
                <a href="/user/456">Creador</a> (80 Videos)
            </p>
        </div>
        <div id="playlist_details">
            <div class="playlist_stats">
                <div class="playlist_stats_col">
                    <span class="playlist_stats_text">Calificaciones</span>
                    <span class="playlist_stats_value">320</span>
                </div>
                <div class="playlist_stats_col">
                    <span class="playlist_stats_text">Reproducciones</span>
                    <span class="playlist_stats_value">50,000</span>
                </div>
                <div class="playlist_stats_col">
                    <span class="playlist_stats_text">Videos</span>
                    <span class="playlist_stats_value">80</span>
                </div>
            </div>
        </div>
        """
        data_es = Playlist._extract_html(es_html)
        self.assertEqual(data_es["title"], "Lista Española")
        self.assertEqual(data_es["rating_count"], "320")
        self.assertEqual(data_es["views"], "50,000")
        self.assertEqual(data_es["video_count"], "80")


class TestUserHelperExtractionEdgeCases(unittest.TestCase):
    def test_multilingual_videos_count_subtitle(self):
        cases = [
            ("Anzeige 1 - 26 von 69", "69"),
            ("Showing 1 - 26 of 1,234", "1,234"),
            ("Affichage 1 - 26 sur 500", "500"),
            ("Affichage de 1 - 8 de 209", "209"),
            ("Visualizzazione 1 - 26 di 320", "320"),
            ("Visualizzazione di 1 - 8 su 209", "209"),
            ("Mostrando 1 - 26 de 89", "89"),
            ("Mostrando 1 - 8 de 209", "209"),
            ("1 - 20 / 45", "45"),
        ]
        for sub_text, expected_count in cases:
            with self.subTest(sub_text=sub_text):
                html = f"""
                <div id="profileInfo">
                    <h1 class="name-title">TestModel</h1>
                    <span class="videos_count_subtitle">{sub_text}</span>
                </div>
                """
                data = UserHelper._extract_html(html)
                self.assertEqual(data["videos_count"], expected_count)

    def test_multilingual_stats_bar(self):
        # French stats bar
        fr_html = """
        <div id="profileInfo">
            <h1 class="name-title">Modèle Français</h1>
            <div class="main-stats-bar">
                <div class="info-stat">
                    <span class="info-stat-label">Rang du modèle</span>
                    <span class="info-stat-data">2nd</span>
                </div>
                <div class="info-stat">
                    <span class="info-stat-label">Vidéos</span>
                    <span class="info-stat-data">5.3K</span>
                </div>
                <div class="info-stat">
                    <span class="info-stat-label">Abonnés</span>
                    <span class="info-stat-data">206K</span>
                </div>
                <div class="info-stat">
                    <span class="info-stat-label">Vues</span>
                    <span class="info-stat-data">750M</span>
                </div>
            </div>
        </div>
        """
        data_fr = UserHelper._extract_html(fr_html)
        self.assertEqual(data_fr["rank"], "2nd")
        self.assertEqual(data_fr["videos_count"], "5.3K")
        self.assertEqual(data_fr["subscribers_count"], "206K")
        self.assertEqual(data_fr["views"], "750M")

        # Italian stats bar
        it_html = """
        <div id="profileInfo">
            <h1 class="name-title">Modello Italiano</h1>
            <div class="main-stats-bar">
                <div class="info-stat">
                    <span class="info-stat-label">Classifica</span>
                    <span class="info-stat-data">1st</span>
                </div>
                <div class="info-stat">
                    <span class="info-stat-label">Video</span>
                    <span class="info-stat-data">120</span>
                </div>
                <div class="info-stat">
                    <span class="info-stat-label">Iscritti</span>
                    <span class="info-stat-data">45K</span>
                </div>
                <div class="info-stat">
                    <span class="info-stat-label">Visualizzazioni</span>
                    <span class="info-stat-data">30M</span>
                </div>
            </div>
        </div>
        """
        data_it = UserHelper._extract_html(it_html)
        self.assertEqual(data_it["rank"], "1st")
        self.assertEqual(data_it["videos_count"], "120")
        self.assertEqual(data_it["subscribers_count"], "45K")
        self.assertEqual(data_it["views"], "30M")

    def test_data_uri_avatar_and_banner_are_ignored(self):
        html = """
        <div id="profileInfo">
            <h1 class="name-title">TestModel</h1>
            <div class="banner-wrapper">
                <img class="banner-image" data-src="https://cdn.example.com/real_banner.jpg" src="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7">
            </div>
            <div class="avatar-wrapper">
                <img class="avatar-image" src="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7">
            </div>
        </div>
        """
        data = UserHelper._extract_html(html)
        self.assertEqual(data["banner_url"], "https://cdn.example.com/real_banner.jpg")
        self.assertIsNone(data["avatar_url"])

    def test_title_fallback_for_name(self):
        html = """
        <html>
            <head><title>AwesomeCreator&apos;s Videos - RedTube</title></head>
            <body><div id="profileInfo"></div></body>
        </html>
        """
        data = UserHelper._extract_html(html)
        self.assertEqual(data["name"], "AwesomeCreator")


class TestExtractorHtmlEdgeCases(unittest.TestCase):
    def test_srcset_and_data_src_parsing(self):
        # data-srcset with multiple descriptors should yield a single clean URL
        html = """
        <ul class="videos_grid">
            <li data-video-id="999">
                <a class="video_link" href="/999">
                    <img data-srcset="https://cdn.example.com/thumb_1x.jpg 1x, https://cdn.example.com/thumb_2x.jpg 2x"
                         src="data:image/png;base64,placeholder">
                </a>
                <span class="video_duration">12:34</span>
                <div class="thumb-info-wrapper">
                    <a class="video-title-text" href="/999">Card Title Inner Text</a>
                    <div class="performers-list">
                        <a href="/pornstar/star1">Star One, </a>
                        <a href="/pornstar/star1">Star One</a>
                        <a href="/pornstar/star2">Star Two</a>
                    </div>
                </div>
            </li>
        </ul>
        """
        results = extractor_html(html, base_url="https://www.redtube.com")
        self.assertEqual(len(results), 1)
        item = results[0]
        self.assertEqual(item["video_id"], "999")
        self.assertEqual(item["thumbnail"], "https://cdn.example.com/thumb_2x.jpg")
        self.assertEqual(item["duration"], "12:34")
        self.assertEqual(item["title"], "Card Title Inner Text")
        self.assertEqual(item["pornstars_names"], ["Star One", "Star Two"])
        self.assertEqual(
            item["pornstars_urls"],
            ["https://www.redtube.com/pornstar/star1", "https://www.redtube.com/pornstar/star2"]
        )

    def test_direct_data_src_preferred(self):
        html = """
        <ul class="videos_grid">
            <li data-video-id="123">
                <a class="video_link" href="/123">
                    <img data-src="https://cdn.example.com/direct_thumb.jpg">
                </a>
                <div class="thumb-info-wrapper">
                    <a class="video-title-text" title="Direct Title" href="/123"></a>
                </div>
            </li>
        </ul>
        """
        results = extractor_html(html)
        self.assertEqual(results[0]["thumbnail"], "https://cdn.example.com/direct_thumb.jpg")
        self.assertEqual(results[0]["title"], "Direct Title")


class TestExtractorPlaylistJsonEdgeCases(unittest.TestCase):
    def test_nested_data_dict(self):
        data = {
            "data": {
                "data": [
                    {"title": "PL 1", "url": "/playlist/1", "playlistVideoCount": "10"}
                ]
            }
        }
        res = extractor_playlist_json(data)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["title"], "PL 1")
        self.assertEqual(res[0]["url"], "https://www.redtube.com/playlist/1")

    def test_flat_data_list(self):
        data = {
            "data": [
                {"title": "PL Flat", "url": "/playlist/2", "playlistVideoCount": "5"}
            ]
        }
        res = extractor_playlist_json(data)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["title"], "PL Flat")

    def test_direct_list(self):
        data = [
            {"title": "PL Direct", "url": "/playlist/3", "playlistVideoCount": "20"}
        ]
        res = extractor_playlist_json(data)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["title"], "PL Direct")

    def test_invalid_json_returns_empty(self):
        self.assertEqual(extractor_playlist_json("not valid json"), [])
        self.assertEqual(extractor_playlist_json({}), [])


class TestSearchQueryEncoding(unittest.TestCase):
    def test_search_url_encoding(self):
        client = Client(core=MagicMock(spec=BaseCore))
        with patch("redtube_api.api.scrape_stream") as mock_scrape:
            client.search("rock & roll", pages=2)
            urls = mock_scrape.call_args.kwargs["target_page_urls"]
            self.assertEqual(
                urls,
                [
                    "https://www.redtube.com/?search=rock+%26+roll&page=1",
                    "https://www.redtube.com/?search=rock+%26+roll&page=2",
                ]
            )

        with patch("redtube_api.api.scrape_stream") as mock_scrape:
            client.search("100% natural", pages=1)
            urls = mock_scrape.call_args.kwargs["target_page_urls"]
            self.assertEqual(
                urls,
                [
                    "https://www.redtube.com/?search=100%25+natural&page=1",
                ]
            )


class TestClientContextManager(unittest.IsolatedAsyncioTestCase):
    async def test_async_with_client(self):
        core = BaseCore()
        async with Client(core=core) as client:
            self.assertIsNotNone(client.core.session)
        # Session is closed on exit
        self.assertTrue(core.session is None or core.session.closed)


class TestCliEdgeCases(unittest.IsolatedAsyncioTestCase):
    async def test_run_main_nonexistent_file(self):
        # Should gracefully print error and not raise FileNotFoundError
        await run_main(["--file", "/nonexistent/path/urls.txt", "--output", "/tmp/out"])


if __name__ == "__main__":
    unittest.main()
