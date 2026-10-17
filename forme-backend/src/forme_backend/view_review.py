"""Operator view selection. AI suggestions are evidence for review, never approval."""

from __future__ import annotations

import base64
import hashlib
import json
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

from .config import Settings
from .store import Store

SLOTS = ("front", "back", "left", "right", "top", "bolt")
LABELS = set(SLOTS) | {"unknown"}


def image_quality(ffmpeg: str, path: Path) -> dict[str, float]:
    """Small whole-frame sharpness/exposure hint; object visibility is still reviewed separately."""
    try:
        raw = subprocess.run([ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-i", str(path),
                              "-vf", "scale=64:64,format=gray", "-frames:v", "1", "-f", "rawvideo", "-"],
                             check=True, timeout=30, capture_output=True).stdout
    except (OSError, subprocess.SubprocessError):
        raw = b""
    if len(raw) != 4096:
        return {"sharpness": 0.0, "exposure": 0.0, "score": 0.0}
    sharpness = sum(abs(raw[i] - raw[i + 1]) + abs(raw[i] - raw[i + 64])
                    for i in range(63 * 63)) / (63 * 63 * 2)
    brightness = sum(raw) / len(raw)
    exposure = max(0.0, 1.0 - abs(brightness - 128) / 128)
    score = min(1.0, sharpness / 32) * 0.7 + exposure * 0.3
    return {"sharpness": round(sharpness, 2), "exposure": round(exposure, 2), "score": round(score, 3)}


def prepare(store: Store, settings: Settings, submission_id: str) -> None:
    submission = store.get_submission(submission_id)
    if submission is None:
        return
    folder = settings.data_dir / "submissions" / submission_id / "view_frames"
    folder.mkdir(parents=True, exist_ok=True)
    source = settings.data_dir / "uploads" / submission["upload_id"] / "source.video"
    duration = (submission["upload"]["metadata"] or {}).get("duration_seconds")
    try:
        if not source.is_file() or not duration:
            raise RuntimeError("缺少原视频或视频时长，请先完成质检。")
        for old in folder.glob("frame_*.jpg"):
            old.unlink()
        fps = min(2.0, 18.0 / duration)
        command = [settings.ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-i", str(source),
                   "-vf", f"fps={fps:.6f},scale=w='min(960,iw)':h=-2", "-frames:v", "18", "-q:v", "4",
                   "-y", str(folder / "frame_%03d.jpg")]
        subprocess.run(command, check=True, timeout=300, capture_output=True)
        frames = sorted(folder.glob("frame_*.jpg"))
        if len(frames) < 6:
            raise RuntimeError("可用帧不足 6 张，请检查视频。")
        data = {"source": "video", "model": None, "frames": [
            {"name": frame.name, "timestampSeconds": round((i + 0.5) / fps, 2),
             "sha256": hashlib.sha256(frame.read_bytes()).hexdigest(), "label": "unknown",
             "confidence": None, "quality": image_quality(settings.ffmpeg, frame), "reason": "待判断"}
            for i, frame in enumerate(frames)
        ], "selections": {}, "notes": ""}
        store.set_view_review(submission_id, "ready", data)
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        store.set_view_review(submission_id, "failed", {"error": str(exc)[:500]})


def _ask_vision(settings: Settings, image: Path, anchor: Path | None) -> dict:
    prompt = (
        "你在检查假肢外壳拍摄帧。只输出 JSON 对象："
        '{"label":"front|back|left|right|top|bolt|unknown","confidence":0.0,"reason":"一句话说明可见证据"}。'
        "top 必须是真实俯视且上口明显；bolt 必须看见螺栓或固定件。"
        "没有足够物理证据判断正背左右时选 unknown；不要依靠视频时间推测。"
        "鞋头在画面中朝左或朝右、相机旋转和拍摄者站位都不能单独证明假肢的左右侧。"
        "confidence 是主观参考，不是已校准概率。"
    )
    content = [{"type": "text", "text": prompt}]
    if anchor:
        prompt += "第一张图片是操作员确认的实物正面，第二张是待判断图片。"
        content[0]["text"] = prompt
        content.append({"type": "image_url", "image_url": {
            "url": "data:image/jpeg;base64," + base64.b64encode(anchor.read_bytes()).decode("ascii")}})
    content.append({"type": "image_url", "image_url": {
        "url": "data:image/jpeg;base64," + base64.b64encode(image.read_bytes()).decode("ascii")}})
    payload = {"model": settings.vision_model, "stream": False, "messages": [
        {"role": "user", "content": content}
    ]}
    request = urllib.request.Request(
        settings.vision_api_url,
        json.dumps(payload).encode("utf-8"),
        {"Content-Type": "application/json", "Authorization": f"Bearer {settings.vision_api_key}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            answer = json.loads(response.read(1024 * 1024))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"{settings.vision_provider_label} 返回 HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"无法连接 {settings.vision_provider_label}") from exc
    raw_content = answer["choices"][0]["message"]["content"].strip()
    if raw_content.startswith("```"):
        raw_content = raw_content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    parsed = json.loads(raw_content)
    label = str(parsed.get("label", "unknown")).lower()
    if label not in LABELS:
        label = "unknown"
    try:
        confidence = max(0.0, min(1.0, float(parsed.get("confidence", 0))))
    except (TypeError, ValueError):
        confidence = 0.0
    if confidence < 0.6:
        label = "unknown"
    return {"label": label, "confidence": confidence, "reason": str(parsed.get("reason", ""))[:200],
            "completionId": str(answer.get("id", ""))[:100],
            "totalTokens": answer.get("usage", {}).get("total_tokens")}


def classify(store: Store, settings: Settings, submission_id: str, front_anchor: str | None) -> None:
    review = store.get_view_review(submission_id)
    if review is None:
        return
    data = review["data"]
    folder = settings.data_dir / "submissions" / submission_id / "view_frames"
    names = {frame["name"] for frame in data.get("frames", [])}
    anchor = folder / front_anchor if front_anchor in names else None
    data["model"] = settings.vision_model
    data["provider"] = settings.vision_provider_label
    data["frontAnchor"] = front_anchor
    data.pop("error", None)
    for frame in data.get("frames", []):
        frame.update(label="unknown", confidence=None, reason="等待 API 判断")
    try:
        completed = 0
        errors = []
        for frame in data["frames"]:
            if frame["name"] == front_anchor:
                frame.update(label="front", confidence=1.0, reason="操作员标定的正面")
                continue
            try:
                frame.update(_ask_vision(settings, folder / frame["name"], anchor))
                if anchor is None and frame["label"] in {"front", "back", "left", "right"}:
                    frame["rawAiLabel"] = frame["label"]
                    frame["label"] = "unknown"
                    frame["reason"] = "缺少操作员确认的正面参照；" + frame["reason"]
                completed += 1
            except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
                message = str(exc)[:120]
                frame.update(label="unknown", confidence=None, reason=f"API 判断失败：{message}")
                errors.append({"frame": frame["name"], "message": message})
                break
        data["suggestions"] = {slot: [f["name"] for f in sorted(data["frames"],
            key=lambda item: (item["confidence"] or 0) * 0.8 + item.get("quality", {}).get("score", 0) * 0.2,
            reverse=True) if f["label"] == slot][:3] for slot in SLOTS}
        data["missing"] = [slot for slot in SLOTS if not data["suggestions"][slot]]
        data["apiErrors"] = errors
        store.set_view_review(submission_id, "failed" if errors and not completed else "partial" if errors else "classified", data)
    except Exception as exc:
        data["error"] = str(exc)[:500]
        store.set_view_review(submission_id, "failed", data)
