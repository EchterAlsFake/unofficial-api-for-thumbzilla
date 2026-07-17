import pytest

from thumbzilla_api import Client
from base_api import DownloadConfigHLS


@pytest.mark.asyncio
async def test_all():
    client = Client()
    video = await client.get_video("https://www.thumbzilla.com/watch/231853081/")

    assert isinstance(video.title, str) and len(video.title) > 0
    assert isinstance(video.video_id, str) and len(video.video_id) > 0
    assert isinstance(video.media_definitions, list) and len(video.media_definitions) > 0
    assert isinstance(video.duration, int) and len(str(video.duration)) > 0
    assert isinstance(video.thumbnail, str) and len(video.thumbnail) > 0
    assert isinstance(video.author_name, str) and len(video.author_name) > 0

    config = DownloadConfigHLS(quality="worst", return_report=True)
    stuff = await video.download(config)
    assert stuff.status == "completed"