"""The photo of an artist when the first service refuses the picture (Deezer's image server answers 403 to some connections):
YouTube Music's artist search is the second place. No real network."""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image  # noqa: E402

from apis.catalog_info import ArtistInfo  # noqa: E402
from apis.ytmusic import YouTubeMusic, parse_artists  # noqa: E402
from autotag import AutoTagger  # noqa: E402
from exceptions import MetadataRefused  # noqa: E402


def item(title, details, thumbnail):
    def column(text):
        return {"musicResponsiveListItemFlexColumnRenderer": {"text": {"runs": [{"text": text}]}}}
    return {"musicResponsiveListItemRenderer": {"flexColumns": [column(title), column(details)],
            "thumbnail": {"musicThumbnailRenderer": {"thumbnail": {"thumbnails": [{"url": thumbnail}]}}}}}


ANSWER = {"contents": [item("Feid", "Artista • 34,4 M usuarios mensuales", "https://yt3/feid=w120-h120-l90-rj"),
                       item("Feid (Live)", "Álbum • Feid • 2023", "https://yt3/live=w120-h120-l90-rj"),
                       item("Feid Jr", "Artist • 12 K monthly listeners", "https://yt3/jr=w120-h120-l90-rj")]}


def test_artists_are_told_apart_from_albums_and_songs_in_the_search_answer():
    assert parse_artists(ANSWER) == [("Feid", "https://yt3/feid=w120-h120-l90-rj"), ("Feid Jr", "https://yt3/jr=w120-h120-l90-rj")]


def test_the_photo_of_the_artist_with_exactly_that_name_is_asked_big_and_a_similar_name_is_not_taken():
    yt = YouTubeMusic(client=object())
    yt._search = lambda query, params: ANSWER
    assert yt.artist_picture_urls("Feid") == ("https://yt3/feid=w1000-h1000-l90-rj", "https://yt3/feid=w120-h120-l90-rj")
    assert yt.artist_picture_urls("Fei") == ()                  # not the same artist: no photo is better than a wrong one


def jpeg():
    out = io.BytesIO()
    Image.new("RGB", (250, 250), "blue").save(out, "JPEG")
    return out.getvalue()


class Images:
    """Deezer's image server refuses; everything else downloads."""
    def __init__(self):
        self.asked = []

    def get_image(self, url):
        self.asked.append(url)
        if "dzcdn" in url:
            raise MetadataRefused("403")
        return jpeg()


def tagger_with(ytmusic_urls):
    yt = type("Y", (), {"artist_picture_urls": lambda self, name: ytmusic_urls})()
    images = Images()
    return AutoTagger(musicbrainz=object(), deezer=object(), itunes=object(), ytmusic=yt, images=images, covers=object()), images


def test_the_autotagger_falls_back_to_youtube_music_for_the_photo_and_remembers_it():
    tagger, images = tagger_with(("https://yt3/feid=w1000-h1000-l90-rj",))
    assert tagger.preview_picture("https://cdn-images.dzcdn.net/a.jpg") is None          # the first service refuses
    photo = tagger.picture_from_youtube_music("Feid")
    assert photo.startswith("data:image/jpeg;base64,")
    assert tagger.picture_from_youtube_music("Feid") == photo and images.asked.count("https://yt3/feid=w1000-h1000-l90-rj") == 1


def test_no_photo_when_youtube_music_does_not_know_the_artist():
    tagger, _ = tagger_with(())
    assert tagger.picture_from_youtube_music("Nadie") is None


def test_the_window_uses_the_second_service_only_when_the_first_gave_nothing(tmp_path, monkeypatch):
    import const
    import downloader
    monkeypatch.setattr(const, "data_dir", lambda: str(tmp_path))
    monkeypatch.setattr(downloader, "DOWNLOADS_DIR", str(tmp_path / "dl"))
    from gui.backend import Api
    api = Api()
    artist = ArtistInfo(source="deezer", id="1", name="Feid", picture_url="https://cdn-images.dzcdn.net/a.jpg")
    asked = []
    api._cover_tagger = type("T", (), {"preview_picture": lambda self, url: None,
                                       "picture_from_youtube_music": lambda self, name: asked.append(name) or "data:image/jpeg;base64,YT"})()
    assert api._artist_picture(artist) == "data:image/jpeg;base64,YT" and asked == ["Feid"]
    api._cover_tagger = type("T", (), {"preview_picture": lambda self, url: "data:image/jpeg;base64,DZ",
                                       "picture_from_youtube_music": lambda self, name: asked.append("no debía pedirse")})()
    assert api._artist_picture(artist) == "data:image/jpeg;base64,DZ" and asked == ["Feid"]
