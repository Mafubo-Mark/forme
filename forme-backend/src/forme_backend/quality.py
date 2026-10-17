from __future__ import annotations

import json
import subprocess
from pathlib import Path


class MediaError(Exception):
    pass


def probe_video(path: Path, ffprobe: str) -> dict:
    try:
        result = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration:stream=codec_type,codec_name,width,height", "-of", "json", str(path)],
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
        parsed = json.loads(result.stdout)
        video = next(s for s in parsed.get("streams", []) if s.get("codec_type") == "video")
        duration = float(parsed["format"]["duration"])
        width, height = int(video["width"]), int(video["height"])
    except OSError as exc:
        raise MediaError("PROCESSING_UNAVAILABLE") from exc
    except (subprocess.SubprocessError, ValueError, KeyError, StopIteration, json.JSONDecodeError) as exc:
        raise MediaError("VIDEO_UNREADABLE") from exc
    if duration < 5 or duration > 180 or width < 480 or height < 480:
        raise MediaError("VIDEO_OUT_OF_RANGE")
    return {"duration_seconds": duration, "width": width, "height": height, "codec": video.get("codec_name")}


def extract_review_frames(path: Path, output_dir: Path, duration: float, ffmpeg: str) -> list[str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    names = []
    for index in range(8):
        # Leave a margin at the end: some encoders report a duration beyond the last decodable frame.
        timestamp = (duration - 0.5) * (index + 0.5) / 8
        name = f"review_{index + 1:02d}.jpg"
        try:
            subprocess.run(
                [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-ss", str(timestamp), "-i", str(path), "-frames:v", "1", "-q:v", "3", "-y", str(output_dir / name)],
                capture_output=True,
                timeout=60,
                check=True,
            )
        except OSError as exc:
            raise MediaError("PROCESSING_UNAVAILABLE") from exc
        except subprocess.SubprocessError as exc:
            raise MediaError("FRAME_EXTRACTION_FAILED") from exc
        if not (output_dir / name).is_file():
            raise MediaError("FRAME_EXTRACTION_FAILED")
        names.append(name)
    return names


def create_browser_preview(path: Path, ffmpeg: str) -> bool:
    """Create an H.264 preview for browsers; keep the uploaded source intact."""
    output = path.parent / "preview.mp4"
    partial = path.parent / "preview.part.mp4"
    try:
        subprocess.run(
            [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-i", str(path),
             "-map", "0:v:0", "-an", "-vf", "scale=w='min(960,iw)':h=-2",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "28", "-pix_fmt", "yuv420p",
             "-movflags", "+faststart", "-y", str(partial)],
            capture_output=True, timeout=300, check=True,
        )
        if partial.stat().st_size == 0:
            return False
        partial.replace(output)
        return True
    except (OSError, subprocess.SubprocessError):
        return False
    finally:
        partial.unlink(missing_ok=True)
