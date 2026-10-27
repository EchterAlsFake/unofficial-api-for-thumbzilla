import pytest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from thumbzilla_api import api


def test_search_query_is_one_value():
    client = object.__new__(api.Client)
    client.core = object()
    with patch.object(api, "scrape_stream") as stream:
        client.search("a&b/# 日本", pages=2)
    urls = stream.call_args.kwargs["target_page_urls"]
    assert len(urls) == len(set(urls)) == 2
    for url in urls:
        assert parse_qs(urlsplit(url).query)["query"] == ["a&b/# 日本"]
        assert not urlsplit(url).fragment


@pytest.mark.parametrize(
    "html",
    [
        "",
        "<h1 id='playlist_title'>Empty</h1>",
        "<span class='playlist_stats_value'>1</span>",
    ],
)
def test_partial_playlist_does_not_crash(html):
    data = api.Playlist._extract_html(html)
    assert data["videos_count"] is None


@pytest.mark.asyncio
async def test_cli_closes_session_and_reports_false_download(capsys, tmp_path):
    from unittest.mock import AsyncMock, MagicMock
    from base_api import BaseCore
    from base_api.modules.config import RuntimeConfig

    core = BaseCore(RuntimeConfig())
    video = MagicMock(title="Example", length="10", url="https://example.com/video")
    video.load_fields = AsyncMock()
    video.download = AsyncMock(return_value=False)
    client = MagicMock()
    client.get_video = AsyncMock(return_value=video)
    with (
        patch.object(api, "BaseCore", return_value=core),
        patch.object(api, "Client", return_value=client),
    ):
        await api.run_main(
            ["--download", "https://example.com/video", "--output", str(tmp_path)]
        )
    assert core.session is None
    output = capsys.readouterr().out
    assert "Download complete:" not in output
    assert "Done ->" not in output
    assert "Download did not complete" in output


def test_complete_playlist_metadata():
    html = '<h1 id="playlist_title">Example</h1><p class="playlist_desc"><a>Author</a></p><div class="rating_percent js_rating_percent">98%</div><span class="playlist_stats_value">3</span><span class="playlist_stats_value">100</span><span class="playlist_stats_value">2</span>'
    data = api.Playlist._extract_html(html)
    assert data == {
        "title": "Example",
        "author_name": "Author",
        "rating_percent": "98%",
        "rating_count": "3",
        "views": "100",
        "videos_count": "2",
    }


def test_playlist_pagination_preserves_filters():
    playlist = api.Playlist(
        url="https://www.thumbzilla.com/playlist/123/?sort=recent&page=8", core=object()
    )
    with patch.object(api, "scrape_stream") as stream:
        playlist.get_videos(pages=2)
    queries = [
        parse_qs(urlsplit(u).query) for u in stream.call_args.kwargs["target_page_urls"]
    ]
    assert [q["page"] for q in queries] == [["1"], ["2"]]
    assert all(q["sort"] == ["recent"] for q in queries)
