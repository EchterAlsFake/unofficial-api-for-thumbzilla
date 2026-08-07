import pytest
from thumbzilla_api import Client

@pytest.mark.asyncio
async def test_all():
    client = Client()
    channel = await client.get_channel("https://www.thumbzilla.com/channel/brazzers/")

    assert isinstance(channel.name, str) and len(channel.name) > 0
    assert isinstance(channel.views, str) and len(channel.views) > 0
    assert isinstance(channel.rank, str) and len(channel.rank) > 0
    assert isinstance(channel.videos_count, str) and len(channel.videos_count) > 0

    idx = 0
    async for video in channel.get_videos():
        idx += 1
        item = video.unwrap()
        assert isinstance(item.title, str) and len(item.title) > 0

        if idx >= 3:
            break
