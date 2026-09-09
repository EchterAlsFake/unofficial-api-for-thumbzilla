import pytest
from thumbzilla_api import Client


@pytest.mark.asyncio
async def test_all():
    client = Client()
    pornstar = await client.get_pornstar("https://www.thumbzilla.com/pornstar/nancy-a/")

    assert isinstance(pornstar.name, str) and len(pornstar.name) > 0
    assert isinstance(pornstar.pornstar_information, dict)

    idx = 0
    async for video in pornstar.get_videos():
        idx += 1

        item = video.unwrap()
        assert isinstance(item.title, str) and len(item.title) > 0

        if idx >= 3:
            break


def test_extract_html_snippet():
    from base_api import BaseCore
    from thumbzilla_api.api import Pornstar

    html_sample = """<div class="main_content tm_main_content" id="mainContent">
    <div class="container">
        <div id="profileInfo">
            <div class="header-banner-wrapper">
                <div class="banner-wrapper">
                    <img class="js_lazy" alt="Alina Angel" title="Alina Angel" src="https://ea.ypncdn.com/543de928d2c2edaf4104f456d1708811180d8920/thumbzilla/cdn_assets/images/shared/profile_banner.jpg">
                </div>
                <div class="avatar-wrapper">
                    <img class="js_lazy" alt="Alina Angel" title="Alina Angel" src="https://ei.phncdn.com/a08af4fd.jpg">
                </div>
            </div>
            <div class="main-information">
                <div class="name-wrapper">
                    <h1 class="name-title">Alina Angel</h1>
                    <i class="icon-checkmark-recommended"></i>
                </div>
                <div class="stats-bar-wrapper">
                    <div class="main-stats-bar">
                        <ul class="main-stats-wrapper">
                            <li class="info-stat">
                                <p class="info-stat-label">Model Rank</p>
                                <p class="info-stat-data">1</p>
                            </li>
                            <li class="info-stat">
                                <p class="info-stat-label">Views</p>
                                <p class="info-stat-data">0</p>
                            </li>
                        </ul>
                    </div>
                    <div class="profile-more-of-me">
                        <button class="button more-of-me">
                            <a href="/redirect/https%3A%2F%2Fwww.fanhub.com%2F%40alina-angel%2F%3Fsource%3Dwl"><span>More of Me</span></a>
                        </button>
                    </div>
                </div>
            </div>
            <div id="DrawerProfileInfo">
                <ul class="profile-info">
                    <li class="info-stat">
                        <p class="info-stat-label">Astrology</p>
                        <p class="info-stat-data">Capricorn</p>
                    </li>
                    <li class="info-stat">
                        <p class="info-stat-label">Years Active</p>
                        <p class="info-stat-data">2021 to Present</p>
                    </li>
                    <li class="info-stat">
                        <p class="info-stat-label">Measurements</p>
                        <p class="info-stat-data">34D--</p>
                    </li>
                </ul>
                <div class="known-for-wrapper">
                    <ul class="known-for-tags-wrapper">
                        <li class="known-for-tag">
                            <a class="known-for-text" href="/channel/she-seduced-me/">She Seduced Me</a>
                        </li>
                        <li class="known-for-tag">
                            <a class="known-for-text" href="/channel/adulttime/">Adult Time</a>
                        </li>
                    </ul>
                </div>
            </div>
        </div>
    </div>
</div>"""

    pornstar = Pornstar(url="https://www.thumbzilla.com/pornstar/alina-angel/", core=BaseCore())
    data = pornstar._extract_html(html_sample)

    assert data["name"] == "Alina Angel"
    assert data["rank"] == "1"
    assert data["views"] == "0"
    assert data["banner_url"] == "https://ea.ypncdn.com/543de928d2c2edaf4104f456d1708811180d8920/thumbzilla/cdn_assets/images/shared/profile_banner.jpg"
    assert data["avatar_url"] == "https://ei.phncdn.com/a08af4fd.jpg"
    assert data["verified"] is True
    assert data["pornstar_information"]["Astrology"] == "Capricorn"
    assert data["pornstar_information"]["Years Active"] == "2021 to Present"
    assert data["pornstar_information"]["Measurements"] == "34D--"
    assert data["featured_in"] == ["She Seduced Me", "Adult Time"]
    assert data["more_of_me"] == "https://www.fanhub.com/@alina-angel/?source=wl"
