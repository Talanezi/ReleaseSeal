# ReleaseSeal Product Specification

## 1. Product goal

ReleaseSeal is a local-first pre-publish QA system for video creators. Given a finished video and its upload metadata, it will inspect the local media and package and return a deterministic, structured report with an overall status of `READY`, `NEEDS_REVIEW`, or `BLOCKED` and timestamped findings where applicable.

The core product must run without paid APIs, platform APIs, accounts, cloud storage, or external services. FFmpeg and FFprobe are the core media inspection tools. The CLI and web interface must use the same scanning engine so that equivalent inputs and configuration produce equivalent results.

Milestone 0 creates only the repository, documentation, configuration, and installable/buildable application skeletons. It does not implement scanning.

## 2. Supported inputs

The planned P0 scan accepts one local upload package containing:

- exactly one finished local video file;
- a required title supplied as text;
- a required description supplied as text, which may be empty;
- an optional local captions file.

Caption inputs support UTF-8 SubRip (`.srt`) and WebVTT (`.vtt`) content. Validity is determined from file content rather than extension alone. Supported video containers and codecs are limited to formats that the installed FFmpeg/FFprobe build can read; the application reports unsupported or unreadable files rather than attempting transcoding. Inputs are local files and text only. Online URLs are not supported.

## 3. Normalized finding schema

Every detector will emit findings using one normalized shape. Fields marked optional may be omitted or `null` in serialized output.

| Field | Type | Required | Meaning |
| --- | --- | --- | --- |
| `code` | string | yes | Stable, machine-readable finding identifier. |
| `severity` | enum | yes | `info`, `warning`, or `error`. |
| `status` | enum | yes | Contribution to the report: `READY`, `NEEDS_REVIEW`, or `BLOCKED`. |
| `message` | string | yes | Concise human-readable explanation. |
| `source` | string | yes | Detector or validation component that produced the finding. |
| `timestamp_start_seconds` | number | no | Inclusive location in the video, in seconds from zero. |
| `timestamp_end_seconds` | number | no | Exclusive end location, in seconds from zero; never earlier than the start. |
| `details` | object | no | Structured diagnostic values suitable for machines and UI display. |
| `suggestion` | string | no | A concrete corrective action when one is known. |

Report status uses the highest-impact finding: any `BLOCKED` finding makes the report `BLOCKED`; otherwise any `NEEDS_REVIEW` finding makes it `NEEDS_REVIEW`; otherwise it is `READY`. Report output will also contain a schema version, scan metadata, normalized input summary, ordered findings, and a deterministic summary count. Findings will be ordered by timestamp when present and then by stable code.

## 4. P0 requirements

P0 is the first usable, entirely local product milestone after scaffolding.

- Provide one shared Python scanning engine used by both CLI and web paths.
- Accept and validate the supported local input package without copying it to cloud or remote storage.
- Use FFprobe to extract machine-readable container, stream, duration, frame-rate, resolution, and audio metadata.
- Use FFmpeg/FFprobe-based checks for unreadable media, missing video or audio streams, invalid or zero duration, frozen/black video intervals, silence intervals, clipping risk, and basic output constraints defined in YAML.
- Validate title and description against configurable presence and length rules.
- Parse and validate optional UTF-8 SRT or WebVTT captions, including cue timing, ordering, overlaps, gaps, and media-duration bounds.
- Normalize every result into the finding schema and compute the overall report status deterministically.
- Include timestamps for findings tied to a media interval.
- Provide machine-readable JSON output and a readable CLI report.
- Provide a local FastAPI endpoint that invokes the shared engine and returns the same normalized report.
- Provide a minimal local web interface for selecting local inputs, entering metadata, running a scan, and viewing the status and findings.
- Keep configuration in a versioned YAML file with validated defaults and actionable configuration errors.
- Do not require a network connection after dependencies and system packages are installed.
- Cover configuration, input validation, report aggregation, and detector behavior with pytest tests and small local fixtures.
- Handle temporary files predictably and avoid retaining user media after the invoking process or request no longer needs it.

## 5. P1 requirements

- Export a self-contained human-readable report file in addition to JSON.
- Add configurable platform-oriented rule profiles that remain purely local and do not call platform APIs.
- Improve caption checks for overlaps, excessive reading speed, long lines, and long cue duration.
- Add configurable checks for loudness range, integrated loudness, true peak, and extended silence.
- Add configurable checks for aspect ratio, resolution, frame-rate consistency, and bitrate guidance.
- Support saved local scan configuration selection without introducing accounts or a database.
- Provide optional local `faster-whisper` transcription for caption comparison, advisory evidence recovery, and explicit machine-caption draft generation. It is isolated behind an optional dependency, never required by the core scan, never downloads a model implicitly, and machine output never becomes trusted supplied-caption evidence.
- Improve accessibility of the web report and keyboard-only workflow.

## 6. Stretch features

- Compare an optional locally supplied thumbnail image against configurable dimensions and file limits without generating a thumbnail.
- Generate a portable static HTML report with timeline navigation.
- Offer additional local caption formats through explicit parsers.
- Provide a watch-folder mode implemented within the single-process application.
- Package the application for simplified local desktop installation.

## 7. Explicit out-of-scope features

The following are explicitly outside the product scope:

- authentication;
- accounts;
- databases;
- payments;
- OAuth;
- YouTube, TikTok, or Instagram APIs;
- uploading to social platforms;
- commenting;
- social scraping;
- downloading online media;
- thumbnail generation;
- SEO generation;
- cloud storage;
- microservices;
- queues;
- Redis;
- Celery;
- LangChain;
- retrieval-augmented generation (RAG);
- vector databases;
- custom model training;
- legal compliance guarantees;
- content moderation;
- browser extensions;
- mobile apps.
