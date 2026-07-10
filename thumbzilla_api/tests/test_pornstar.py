import pytest
from thumbzilla_api import Client


@pytest.mark.asyncio
async def test_all():
    client = Client()
    pornstar = await client.get_pornstar("https://www.thumbzilla.com/pornstar/nancy-a/")

    idx = 0
    async for video in pornstar.get_videos():
        idx += 1

        assert isinstance(video.video.title, str) and len(video.video.title) > 0

        if idx >= 3:
            break