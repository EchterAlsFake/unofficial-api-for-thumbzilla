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


def test_extract_html_snippet():
    from base_api import BaseCore
    from thumbzilla_api.api import Channel

    html_sample = """<div class="main_content tm_main_content" id="mainContent">
    <div class="container">
        <div class="header-banner-wrapper">
            <div class="banner-wrapper">
                <img alt="PUBA" title="PUBA" src="https://fi1-ph.ypncdn.com/pics/sites/cover.jpg">
            </div>
            <div class="logo-wrapper">
                <img alt="PUBA" title="PUBA" src="https://fi1-ph.ypncdn.com/pics/sites/avatar.jpg">
            </div>
        </div>
        <div class="main-information">
            <div class="name-wrapper">
                <h1 class="name-title">PUBA</h1>
            </div>
            <div class="stats-bar-wrapper">
                <div class="main-stats-bar">
                    <ul class="main-stats-wrapper">
                        <li class="info-stat">
                            <p class="info-stat-label">Rank</p>
                            <p class="info-stat-data">82</p>
                        </li>
                        <li class="info-stat">
                            <p class="info-stat-label">Views</p>
                            <p class="info-stat-data">145K</p>
                        </li>
                        <li class="info-stat">
                            <p class="info-stat-label">Videos</p>
                            <p class="info-stat-data">7K</p>
                        </li>
                    </ul>
                </div>
                <div class="channel-buttons-wrapper">
                    <button class="button button-pink join-us">
                        <a href="http://join.puba.com/track/MjU4LjE0" class="join-wrapper" target="_blank" rel="noopener nofollow">
                            <span>Join now</span>
                        </a>
                    </button>
                </div>
            </div>
        </div>
        <div id="aboutChannel">
            <div class="profile-bio channel-description">PUBA.com is a network with a variety of websites.</div>
        </div>
    </div>
</div>"""

    channel = Channel(url="https://www.thumbzilla.com/channel/puba/", core=BaseCore())
    data = channel._extract_html(html_sample)

    assert data["name"] == "PUBA"
    assert data["rank"] == "82"
    assert data["views"] == "145K"
    assert data["videos_count"] == "7K"
    assert data["banner_url"] == "https://fi1-ph.ypncdn.com/pics/sites/cover.jpg"
    assert data["avatar_url"] == "https://fi1-ph.ypncdn.com/pics/sites/avatar.jpg"
    assert data["bio"] == "PUBA.com is a network with a variety of websites."
    assert data["verified"] is False
    assert data["join_url"] == "http://join.puba.com/track/MjU4LjE0"
