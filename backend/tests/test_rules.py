from pathlib import Path

import pytest

from releaseseal.config import CreatorRuleConfig
from releaseseal.models import MediaInspection, PublishingPackage
from releaseseal.rules import evaluate_package_rules, parse_chapters


@pytest.fixture
def media() -> MediaInspection:
    return MediaInspection(
        duration_seconds=120,
        format_name="mp4",
        file_size_bytes=1000,
        has_video=True,
        video_stream_count=1,
        video_codec="h264",
        width=1920,
        height=1080,
        display_aspect_ratio="16:9",
        frame_rate=30,
        pixel_format="yuv420p",
        has_audio=True,
        audio_stream_count=1,
        audio_codec="aac",
        channel_count=2,
        sample_rate=48000,
    )


def _codes(package: PublishingPackage, media: MediaInspection, config=None) -> list[str]:
    result = evaluate_package_rules(package, media, config or CreatorRuleConfig())
    return [finding.code for finding in result.findings]


def test_required_title_absent(media: MediaInspection) -> None:
    assert "TITLE_REQUIRED" in _codes(
        PublishingPackage(description="A description"), media
    )


def test_title_length_warning(media: MediaInspection) -> None:
    config = CreatorRuleConfig()
    config.title.maximum_recommended_length = 5
    result = evaluate_package_rules(
        PublishingPackage(title="Long title", description="Description"), media, config
    )

    finding = next(
        finding
        for finding in result.findings
        if finding.code == "TITLE_LENGTH_RECOMMENDATION"
    )
    assert finding.severity.value == "warning"
    assert finding.details["character_count"] == 10


def test_valid_title_has_no_title_finding(media: MediaInspection) -> None:
    codes = _codes(
        PublishingPackage(title="Valid title", description="Description"), media
    )
    assert not any(code.startswith("TITLE_") for code in codes)


def test_required_description_absent(media: MediaInspection) -> None:
    result = evaluate_package_rules(
        PublishingPackage(title="Title"), media, CreatorRuleConfig()
    )
    finding = next(
        finding for finding in result.findings if finding.code == "DESCRIPTION_REQUIRED"
    )

    assert finding.severity.value == "warning"
    assert finding.status.value == "NEEDS_REVIEW"
    assert finding.message == "The publishing package does not include a description."


def test_required_description_phrase_absent(media: MediaInspection) -> None:
    config = CreatorRuleConfig()
    config.description.required_phrases = ["Sources:"]
    assert "DESCRIPTION_REQUIRED_PHRASE_MISSING" in _codes(
        PublishingPackage(title="Title", description="No citations here"),
        media,
        config,
    )


def test_obviously_malformed_url_is_reported(media: MediaInspection) -> None:
    codes = _codes(
        PublishingPackage(
            title="Title", description="Broken link: https:// and http:/example.com"
        ),
        media,
    )
    assert "DESCRIPTION_URL_MALFORMED" in codes


def test_valid_description_urls_are_not_rejected(media: MediaInspection) -> None:
    codes = _codes(
        PublishingPackage(
            title="Title",
            description="See https://example.com/path?q=1 and www.openai.com/docs.",
        ),
        media,
    )
    assert "DESCRIPTION_URL_MALFORMED" not in codes


def test_valid_chapter_list_and_hour_form_parse() -> None:
    result = parse_chapters(
        "00:00 Introduction\n01:24 First topic\n1:02:03 Hour-form topic"
    )

    assert [chapter.timestamp_seconds for chapter in result.chapters] == [0, 84, 3723]
    assert result.invalid_entries == []


def test_duplicate_chapter_timestamps(media: MediaInspection) -> None:
    codes = _codes(
        PublishingPackage(
            title="Title", description="00:00 Intro\n00:00 Duplicate"
        ),
        media,
    )
    assert "CHAPTER_TIMESTAMPS_NOT_INCREASING" in codes


def test_backward_chapter_timestamps(media: MediaInspection) -> None:
    codes = _codes(
        PublishingPackage(
            title="Title", description="00:30 Later\n00:10 Earlier"
        ),
        media,
    )
    assert "CHAPTER_TIMESTAMPS_NOT_INCREASING" in codes


def test_chapter_beyond_media_duration(media: MediaInspection) -> None:
    codes = _codes(
        PublishingPackage(title="Title", description="00:00 Intro\n02:30 Too late"),
        media,
    )
    assert "CHAPTER_BEYOND_MEDIA_DURATION" in codes


def test_required_first_chapter_at_zero(media: MediaInspection) -> None:
    codes = _codes(
        PublishingPackage(title="Title", description="00:10 Introduction"), media
    )
    assert "CHAPTER_FIRST_NOT_ZERO" in codes


def test_ordinary_description_numbers_are_not_chapters(media: MediaInspection) -> None:
    description = "In 2024 we shipped 12 features. Version 1:24 remains supported."
    assert parse_chapters(description).chapters == []
    codes = _codes(PublishingPackage(title="Title", description=description), media)
    assert not any(code.startswith("CHAPTER_") for code in codes)


def test_malformed_chapter_like_line_is_reported(media: MediaInspection) -> None:
    codes = _codes(
        PublishingPackage(title="Title", description="01:99 Invalid chapter"), media
    )
    assert "CHAPTER_TIMESTAMP_INVALID" in codes


def test_required_captions_absent(media: MediaInspection) -> None:
    config = CreatorRuleConfig()
    config.captions.require = True
    assert "CAPTIONS_REQUIRED" in _codes(
        PublishingPackage(title="Title", description="Description"), media, config
    )


def test_caption_reference_satisfies_presence_rule(media: MediaInspection) -> None:
    config = CreatorRuleConfig()
    config.captions.require = True
    codes = _codes(
        PublishingPackage(
            title="Title",
            description="Description",
            captions_path=Path("captions.vtt"),
        ),
        media,
        config,
    )
    assert "CAPTIONS_REQUIRED" not in codes


def test_insufficient_resolution(media: MediaInspection) -> None:
    low_resolution = media.model_copy(update={"width": 640, "height": 360})
    codes = _codes(
        PublishingPackage(title="Title", description="Description"), low_resolution
    )
    assert "VIDEO_WIDTH_BELOW_MINIMUM" in codes
    assert "VIDEO_HEIGHT_BELOW_MINIMUM" in codes


def test_allowed_aspect_ratio_passes_and_disallowed_fails(
    media: MediaInspection,
) -> None:
    package = PublishingPackage(title="Title", description="Description")
    assert "VIDEO_ASPECT_RATIO_NOT_ALLOWED" not in _codes(package, media)

    four_by_three = media.model_copy(update={"width": 1440, "height": 1080})
    four_by_three.display_aspect_ratio = "4:3"
    assert "VIDEO_ASPECT_RATIO_NOT_ALLOWED" in _codes(package, four_by_three)


def test_display_aspect_ratio_is_preferred_for_anamorphic_media(
    media: MediaInspection,
) -> None:
    anamorphic = media.model_copy(
        update={"width": 1440, "height": 1080, "display_aspect_ratio": "16:9"}
    )
    codes = _codes(
        PublishingPackage(title="Title", description="Description"), anamorphic
    )
    assert "VIDEO_ASPECT_RATIO_NOT_ALLOWED" not in codes


def test_required_chapters_absent(media: MediaInspection) -> None:
    config = CreatorRuleConfig()
    config.chapters.require = True
    codes = _codes(
        PublishingPackage(title="Title", description="Description"), media, config
    )
    assert "CHAPTERS_REQUIRED" in codes
