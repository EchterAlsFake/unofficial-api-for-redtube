"""Playlist markup differs from the profile video grid."""
import unittest

from redtube_api.modules.consts import extractor_html


class PlaylistExtractionTests(unittest.TestCase):
    def test_playlist_and_profile_containers_preserve_video_metadata(self):
        # Minimal structure of a real public playlist card, with neutral content.
        card = '''<li data-video-id="123" data-uploader-name="Studio">
          <a class="video_link" href="/123?pkey=456"><img data-srcset="https://cdn.invalid/image.jpg" /></a>
          <span class="tm_video_duration">09:30</span>
          <div class="thumb-info-wrapper">
            <a class="video-title-text" title="Example / 日本語 | title" href="/123?pkey=456">Example</a>
            <div class="author-title-container"><a href="/channels/studio">Studio</a></div>
          </div></li>'''
        for container in ('id="playlist_videos"', 'class="videos_grid"'):
            with self.subTest(container=container):
                rows = extractor_html(f'<ul {container}>{card}<li>advertisement</li></ul>',
                                      base_url="https://www.redtube.com/playlist/456")
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["url"], "https://www.redtube.com/123?pkey=456")
                self.assertEqual(rows[0]["video_id"], "123")
                self.assertEqual(rows[0]["title"], "Example / 日本語 | title")
                self.assertEqual(rows[0]["duration"], "09:30")
                self.assertEqual(rows[0]["author_url"], "https://www.redtube.com/channels/studio")

    def test_empty_playlist_does_not_collect_unrelated_recommendations(self):
        recommendations = '''<ul class="videos_grid"><li data-video-id="999">
          <a class="video_link" href="/999"></a><div class="thumb-info-wrapper"></div>
          </li></ul>'''
        self.assertEqual(len(extractor_html(recommendations)), 1)
        self.assertEqual(extractor_html(recommendations + '<ul id="playlist_videos"></ul>'), [])
