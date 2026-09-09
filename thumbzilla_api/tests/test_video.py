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


def test_extract_html_snippet():
    from base_api import BaseCore
    from thumbzilla_api.api import Video

    html_sample = """<div class="main_content tm_main_content" id="mainContent">
    <div id="watch-container" class="container tm_container adblock-active" data-video-id="267053941">
        <div class="watch-contentWrapper">
            <div id="videoContainer" data-testid="video_player_container" class="mgp_desktop">
                <script id="tm_pc_player_setup">
                    page_params.video_player_setup = {
                        playervars: {"disable_sharebar":1,"htmlPauseRoll":"true","htmlPostRoll":"false","embedCode":"<iframe src=\\"/embed/267053941/\\" frameborder=\\"0\\" width=\\"560\\" height=\\"340\\" scrolling=\\"no\\" allowfullscreen></iframe>","autoplay":true,"autoreplay":"false","hidePostPauseRoll":"false","video_unavailable":"false","pauseroll_url":"","postroll_url":"","video_duration":"901","actionTags":"","link_url":"https://www.thumbzilla.com/watch/267053941/","related_url":"https://www.thumbzilla.com/video/player_related_datas?id=267053941","image_url":"https://fi1-ph.ypncdn.com/videos/202409/09/457546761/original/(m=eaSaaTbWx)(mh=xm_9XbcTJV7-qvLE)12.jpg","video_title":"JOI Foot Tease with Sahara Skye","defaultQuality":[720,480,240,1080],"vcServerUrl":"/svvt/add?stype=svv&svalue=267053941&snonce=ctj0pl1qkfzfy5hp&skey=7141124e7a53b7d9b0fe66f0a3070e7e8b6332fab725c76adfc32e8f32aa3b85&stime=1788952762","mediaDefinitions":[{"format":"hls","videoUrl":"https://www.thumbzilla.com/media/hls/?s=eyJ2a2V5IjoyNjcwNTM5NDEsInMiOiIxZTYxNTBhZmU5Y2M3ZGUwODZiMTFiZTZiNWMxM2Q5NGJmZmQ3MDI0NDI3YWRlZGUyY2UyZmYxMzA5MDNkYWJjIiwiZ3QiOjE3ODg5NTI3NjIsImUiOmZhbHNlfQ","remote":true,"segmentFormats":{"video":"fmp4","audio":"aac"}},{"format":"mp4","videoUrl":"https://www.thumbzilla.com/media/mp4/?s=eyJ2a2V5IjoyNjcwNTM5NDEsInMiOiIxZTYxNTBhZmU5Y2M3ZGUwODZiMTFiZTZiNWMxM2Q5NGJmZmQ3MDI0NDI3YWRlZGUyY2UyZmYxMzA5MDNkYWJjIiwiZ3QiOjE3ODg5NTI3NjIsImUiOmZhbHNlfQ","remote":true,"segmentFormats":{"video":"mp4","audio":"aac"}}]}
                    };
                </script>
            </div>
            <div class="watch-metadata">
                <h1 class="videoTitle tm_videoTitle">
                    JOI Foot Tease with Sahara Skye
                </h1>
                <div class="video-actionsWrapper">
                    <div id="js_videoLikeDislikeWrapper" class="action-section tm_action-section" data-video-id="267053941">
                        <div class="feature-action feature-actionViews">
                            <span class="infoValue tm_infoValue">63</span> <span class="infoViews">Views</span>
                        </div>
                    </div>
                </div>
                <div class="video-uploaderInfoWrapper">
                    <div class="video-uploaderInfoPanel">
                        <div class="submitByLink">
                            <a href="/channel/love-her-feet/">LoveHerFeet</a>
                        </div>
                        <span class="publishedDate">Published on September 9, 2026</span>
                    </div>
                </div>
            </div>
        </div>
    </div>
</div>"""

    video = Video(url="https://www.thumbzilla.com/watch/267053941/", core=BaseCore())
    data = video._extract_html(html_sample)

    assert data["video_id"] == "267053941"
    assert data["title"] == "JOI Foot Tease with Sahara Skye"
    assert data["duration"] == 901
    assert data["thumbnail"] == "https://fi1-ph.ypncdn.com/videos/202409/09/457546761/original/(m=eaSaaTbWx)(mh=xm_9XbcTJV7-qvLE)12.jpg"
    assert data["author_name"] == "LoveHerFeet"
    assert data["views"] == "63"
    assert data["publish_date"] == "Published on September 9, 2026"
    assert data["embed_url"] == "https://www.thumbzilla.com/embed/267053941/"
    assert len(data["media_definitions"]) == 2
    assert data["m3u8_url"].startswith("https://www.thumbzilla.com/media/hls/")