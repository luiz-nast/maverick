import unittest

from maverick.mpris import Player


def player(url="", art=""):
    return Player("org.mpris.MediaPlayer2.firefox.instance_1", "Playing", "t", url, art)


class YoutubeDetectionTest(unittest.TestCase):
    def test_direct(self):
        self.assertTrue(player("https://www.youtube.com/watch?v=dQw4w9WgXcQ").is_youtube)
        self.assertTrue(player("https://m.youtube.com/shorts/aloYE6N6h8Q").is_youtube)
        self.assertTrue(player(art="https://i.ytimg.com/vi/x/hq.jpg").is_youtube)

    def test_embedded_in_search(self):
        google = ("https://www.google.com/search?client=ubuntu-sn&channel=fs&q=hellcat+vs+mustang"
                  "#fpstate=ive&vld=cid:8d46609a,vid:v12vqnb0dAE,st:0")
        ddg = "https://duckduckgo.com/?q=x&iax=videos&ia=videos&iai=https%3A%2F%2Fwww.youtube.com%2Fwatch%3Fv%3Dv12vqnb0dAE"
        self.assertTrue(player(google).is_youtube)
        self.assertTrue(player(ddg).is_youtube)

    def test_not_youtube(self):
        for url in ("https://www.google.com/search?q=youtube+premium+price",
                    "https://br.pinterest.com/pin/1/",
                    "https://example.com/?vid:short",
                    "https://vimeo.com/76979871"):
            self.assertFalse(player(url).is_youtube, url)


if __name__ == "__main__":
    unittest.main()
