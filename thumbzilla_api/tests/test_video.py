import os
import pytest

from thumbzilla_api import Client
from base_api import DownloadConfigHLS

DOWNLOAD_MODE = int(os.environ.get("DOWNLOAD_MODE", 2))

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

    if DOWNLOAD_MODE == 1:
        config = DownloadConfigHLS(quality="worst", return_report=True)
        stuff = await video.download(config)
        assert stuff.status == "completed"
    else:
        await video.load_fields("m3u8_base_url")
        segments = await video.core.get_segments(m3u8_url_master=video.m3u8_base_url, quality="worst")
        assert isinstance(segments, list)
        assert len(segments) > 0