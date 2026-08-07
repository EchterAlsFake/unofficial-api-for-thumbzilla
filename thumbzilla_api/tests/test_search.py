import pytest
from thumbzilla_api import Client


@pytest.mark.asyncio
async def test_search():
    client = Client()
    idx = 0

    async for video in client.search(query="nancy a"):
        idx += 1
        item = video.unwrap()
        assert isinstance(item.title, str) and len(item.title) > 0

        if idx >= 3:
            break
