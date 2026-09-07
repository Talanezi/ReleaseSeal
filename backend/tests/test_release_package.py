from creator_preflight.models import CaptionSummary, MediaInspection, PublishingPackage
from creator_preflight.release_package import (
    PackageComponentState,
    ThumbnailCriticalRegion,
    evaluate_release_package,
    format_duration_badge,
)
from creator_preflight.thumbnails import ThumbnailInfo


def _media(duration=212.2):
    return MediaInspection(
        duration_seconds=duration, format_name="mp4", file_size_bytes=100,
        has_video=True, video_stream_count=1, video_codec="h264", width=1920,
        height=1080, has_audio=True, audio_stream_count=1, audio_codec="aac",
    )


def _evaluate(*, thumbnail=None, thumbnail_error=None, package=None, critical_regions=None):
    return evaluate_release_package(
        package=package or PublishingPackage(title="Yellowstone", description="00:00 Introduction"),
        media=_media(), thumbnail_info=thumbnail, thumbnail_error=thumbnail_error,
        caption_summary=None, caption_findings=[], package_findings=[],
        minimum_thumbnail_width=1280, minimum_thumbnail_height=720,
        target_aspect_ratio=16 / 9, aspect_ratio_tolerance=.02,
        maximum_thumbnail_file_size_bytes=5_000_000,
        critical_regions=critical_regions,
    )


def test_valid_thumbnail_builds_delivery_checks_and_actual_duration_preview():
    result = _evaluate(thumbnail=ThumbnailInfo(mime_type="image/jpeg", file_size_bytes=394_000, width=1280, height=720))
    assert result.summary.thumbnail.state is PackageComponentState.PRESENT_VALID
    assert [item.status.value for item in result.summary.thumbnail_checks] == ["PASS", "PASS", "PASS", "PASS"]
    assert result.summary.delivery_preview.duration_badge_text == "3:32"
    assert [(item.display_width, item.display_height) for item in result.summary.delivery_preview.surfaces] == [(168, 94), (246, 138), (168, 94), (320, 180)]
    assert result.findings == []
    assert result.summary.construction_seconds < .1


def test_png_is_supported_and_small_or_wrong_aspect_is_review_only():
    result = _evaluate(thumbnail=ThumbnailInfo(mime_type="image/png", file_size_bytes=40_000, width=640, height=640))
    assert [item.code for item in result.findings] == ["THUMBNAIL_RESOLUTION_LOW", "THUMBNAIL_ASPECT_RATIO_REVIEW"]
    assert all(item.status.value == "NEEDS_REVIEW" for item in result.findings)


def test_invalid_and_absent_thumbnail_states_are_truthful():
    invalid = _evaluate(package=PublishingPackage(title="Title", thumbnail_path="bad.jpg"), thumbnail_error="Thumbnail must be a readable PNG or JPEG image.")
    assert invalid.summary.thumbnail.state is PackageComponentState.PRESENT_INVALID
    assert invalid.findings[0].code == "THUMBNAIL_INVALID"
    absent = _evaluate(package=PublishingPackage(title="Title"))
    assert absent.summary.thumbnail.state is PackageComponentState.NOT_REQUIRED
    assert absent.findings == []


def test_package_presence_and_chapter_caption_validity_are_derived_from_trusted_state():
    captions = CaptionSummary(source_format="srt", cue_count=2, first_caption_seconds=0, last_caption_seconds=5, covered_duration_seconds=4, timeline_coverage_percent=50)
    package = PublishingPackage(title="Title", description="00:00 Start", captions_path="captions.srt")
    result = evaluate_release_package(
        package=package, media=_media(), thumbnail_info=None, thumbnail_error=None,
        caption_summary=captions, caption_findings=[], package_findings=[],
        minimum_thumbnail_width=1280, minimum_thumbnail_height=720,
        target_aspect_ratio=16 / 9, aspect_ratio_tolerance=.02,
        maximum_thumbnail_file_size_bytes=5_000_000,
    )
    assert result.summary.captions.state is PackageComponentState.PRESENT_VALID
    assert result.summary.chapters.state is PackageComponentState.PRESENT_VALID
    assert result.summary.description.state is PackageComponentState.PRESENT_VALID


def test_critical_regions_use_deterministic_badge_and_edge_geometry():
    result = _evaluate(
        thumbnail=ThumbnailInfo(mime_type="image/jpeg", file_size_bytes=100, width=1280, height=720),
        critical_regions=[
            ThumbnailCriticalRegion(label="logo", x=.8, y=.8, width=.1, height=.1),
            ThumbnailCriticalRegion(label="subject", x=.3, y=.2, width=.2, height=.4),
        ],
    )
    intersections = result.summary.delivery_preview.critical_region_intersections
    assert all(item.intersects_duration_badge for item in intersections if item.region_label == "logo")
    assert not any(item.intersects_duration_badge for item in intersections if item.region_label == "subject")


def test_duration_badge_supports_hour_plus_media():
    assert format_duration_badge(3721.4) == "1:02:01"
