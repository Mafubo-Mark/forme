"""Submit and collect one Hunyuan 3D Pro candidate from a reviewed input package.

Uses Tencent Cloud international TC3 authentication. Secrets stay in the CSV;
request bodies (which contain photos) are never written to disk.
"""
from __future__ import annotations

import argparse
import base64
import csv
import fcntl
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HOST = "hunyuan.intl.tencentcloudapi.com"
SERVICE = "hunyuan"
VERSION = "2023-09-01"


def credentials(path: Path) -> tuple[str, str]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) != 1 or not rows[0].get("SecretId") or not rows[0].get("SecretKey"):
        raise ValueError("Expected one SecretId/SecretKey row")
    return rows[0]["SecretId"], rows[0]["SecretKey"]


def sign(secret_id: str, secret_key: str, action: str, payload: bytes, region: str, timestamp: int) -> dict[str, str]:
    date = datetime.fromtimestamp(timestamp, timezone.utc).strftime("%Y-%m-%d")
    content_type = "application/json; charset=utf-8"
    canonical = ("POST\n/\n\n" + f"content-type:{content_type}\nhost:{HOST}\n\n"
                 + "content-type;host\n" + hashlib.sha256(payload).hexdigest())
    scope = f"{date}/{SERVICE}/tc3_request"
    to_sign = ("TC3-HMAC-SHA256\n" + str(timestamp) + "\n" + scope + "\n"
               + hashlib.sha256(canonical.encode()).hexdigest())
    key = ("TC3" + secret_key).encode()
    for value in (date, SERVICE, "tc3_request"):
        key = hmac.new(key, value.encode(), hashlib.sha256).digest()
    signature = hmac.new(key, to_sign.encode(), hashlib.sha256).hexdigest()
    return {
        "Authorization": (f"TC3-HMAC-SHA256 Credential={secret_id}/{scope}, "
                          f"SignedHeaders=content-type;host, Signature={signature}"),
        "Content-Type": content_type,
        "Host": HOST,
        "X-TC-Action": action,
        "X-TC-Version": VERSION,
        "X-TC-Region": region,
        "X-TC-Timestamp": str(timestamp),
    }


def call(action: str, body: dict, key_file: Path, region: str) -> dict:
    secret_id, secret_key = credentials(key_file)
    payload = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode()
    request = urllib.request.Request(
        f"https://{HOST}/", data=payload, method="POST",
        headers=sign(secret_id, secret_key, action, payload, region, int(time.time())),
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        # Do not log request headers, the photo payload, or credentials.
        raise RuntimeError(f"Tencent API HTTP {exc.code}: {exc.read(2048).decode(errors='replace')}") from exc
    data = result.get("Response", {})
    if "Error" in data:
        error = data["Error"]
        raise RuntimeError(f"Tencent API {error.get('Code')}: {error.get('Message')}")
    return data


def build_input(manifest_path: Path) -> tuple[dict, dict]:
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("status") != "prepared_not_submitted":
        raise ValueError("Input package has not passed local preparation")
    entries = {item["slot"]: item for item in manifest["images"]}
    required = ("front", "left", "right", "back")
    if any(slot not in entries for slot in required):
        raise ValueError("Four required views are missing")
    encoded = {}
    for slot in required:
        path = Path(entries[slot]["path"])
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != entries[slot]["sha256"]:
            raise ValueError(f"View hash changed: {slot}")
        if not raw.startswith(b"\xff\xd8\xff") or len(raw) > 6_000_000:
            raise ValueError(f"View must be a JPEG under 6 MB: {slot}")
        encoded[slot] = base64.b64encode(raw).decode("ascii")
    body = {
        "Model": "3.1", "GenerateType": "Geometry", "ImageBase64": encoded["front"],
        "MultiViewImages": [
            {"ViewType": slot, "ViewImageBase64": encoded[slot]}
            for slot in ("left", "right", "back")
        ],
    }
    return manifest, body


def write_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def submit(manifest_path: Path, key_file: Path, region: str) -> dict:
    manifest, body = build_input(manifest_path)
    record_path = manifest_path.parent / "hunyuan_job.json"
    attempt_path = manifest_path.parent / "hunyuan_submission_attempt.json"
    with (manifest_path.parent / "hunyuan_submit.lock").open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if record_path.exists():
            raise ValueError("A Hunyuan job record already exists; query it before any resubmission")
        if attempt_path.exists():
            raise ValueError("A prior submission attempt has uncertain outcome; reconcile it before retrying")
        credentials(key_file)
        write_json(attempt_path, {"status": "outcome_uncertain_until_job_id_recorded",
                                  "submissionId": manifest["submissionId"],
                                  "sourceVideoSha256": manifest["sourceVideoSha256"],
                                  "submittedAt": datetime.now(timezone.utc).isoformat()})
        response = call("SubmitHunyuanTo3DProJob", body, key_file, region)
        if not response.get("JobId"):
            raise RuntimeError("Tencent did not return JobId")
        record = {
            "submissionId": manifest["submissionId"], "sourceVideoSha256": manifest["sourceVideoSha256"],
            "provider": "tencent_hunyuan_3d_pro_international", "model": "3.1",
            "generateType": "Geometry", "region": region, "jobId": response["JobId"],
            "requestId": response.get("RequestId"), "status": "submitted",
            "submittedViews": ["front", "left", "right", "back"],
            "reviewOnlyViews": ["top", "bolt"],
            "submittedAt": datetime.now(timezone.utc).isoformat(),
        }
        write_json(record_path, record)
        write_json(attempt_path, {"status": "job_id_recorded", "jobId": record["jobId"],
                                  "submissionId": manifest["submissionId"],
                                  "sourceVideoSha256": manifest["sourceVideoSha256"],
                                  "submittedAt": record["submittedAt"]})
        return record


def poll(record_path: Path, key_file: Path) -> dict:
    record = json.loads(record_path.read_text())
    response = call("QueryHunyuanTo3DProJob", {"JobId": record["jobId"]}, key_file, record["region"])
    status = response.get("Status", "unknown")
    record["status"] = status
    record["lastQueryAt"] = datetime.now(timezone.utc).isoformat()
    record["lastRequestId"] = response.get("RequestId")
    if status == "FAIL":
        record["errorCode"] = response.get("ErrorCode")
        record["errorMessage"] = response.get("ErrorMessage")
    if status == "DONE":
        record["resultFiles"] = response.get("ResultFile3Ds", [])
    write_json(record_path, record)
    return record


def archive(record_path: Path) -> dict:
    record = json.loads(record_path.read_text())
    if record.get("status") != "DONE" or not record.get("resultFiles"):
        raise ValueError("Hunyuan result is not ready")
    output = (record_path.parent / "hunyuan_result").resolve()
    output.mkdir(exist_ok=True)
    artifacts = []
    for index, item in enumerate(record["resultFiles"]):
        url = item.get("Url")
        parsed = urllib.parse.urlparse(url or "")
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("Result URL is not HTTPS")
        source_name = Path(urllib.parse.unquote(parsed.path)).name
        extension = Path(source_name).suffix.lower()
        if extension not in {".zip", ".obj", ".glb", ".gltf", ".stl", ".fbx", ".png", ".jpg", ".jpeg"}:
            extension = ".bin"
        target = output / f"result_{index:02d}{extension}"
        if target.exists():
            digest = hashlib.sha256(target.read_bytes()).hexdigest()
            artifacts.append({"type": item.get("Type"), "path": str(target), "bytes": target.stat().st_size, "sha256": digest})
            continue
        temporary = target.with_suffix(target.suffix + ".tmp")
        digest = hashlib.sha256()
        total = 0
        with urllib.request.urlopen(url, timeout=90) as response, temporary.open("wb") as stream:
            while chunk := response.read(1024 * 1024):
                total += len(chunk)
                if total > 512 * 1024 * 1024:
                    raise ValueError("Result exceeds 512 MB cap")
                digest.update(chunk)
                stream.write(chunk)
        temporary.replace(target)
        artifacts.append({"type": item.get("Type"), "path": str(target), "bytes": total, "sha256": digest.hexdigest()})
    previews = []
    for index, item in enumerate(record["resultFiles"]):
        url = item.get("PreviewImageUrl")
        if not url:
            continue
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("Preview URL is not HTTPS")
        target = output / f"preview_{index:02d}.png"
        if not target.exists():
            with urllib.request.urlopen(url, timeout=45) as response:
                content = response.read(20 * 1024 * 1024 + 1)
            if len(content) > 20 * 1024 * 1024:
                raise ValueError("Preview exceeds 20 MB cap")
            target.write_bytes(content)
        previews.append({"path": str(target), "bytes": target.stat().st_size,
                         "sha256": hashlib.sha256(target.read_bytes()).hexdigest()})
    record["artifacts"] = artifacts
    record["previews"] = previews
    record["archivedAt"] = datetime.now(timezone.utc).isoformat()
    write_json(record_path, record)
    return record


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("check", "submit", "poll", "archive"))
    parser.add_argument("path", type=Path, help="Input manifest for check/submit; job record for poll")
    parser.add_argument("--key-file", type=Path,
                        default=Path(os.environ["FORME_HUNYUAN_KEY_FILE"]) if os.environ.get("FORME_HUNYUAN_KEY_FILE") else None)
    parser.add_argument("--region", default=os.environ.get("FORME_HUNYUAN_REGION", "ap-singapore"))
    args = parser.parse_args()
    if args.action in {"submit", "poll"} and args.key_file is None:
        parser.error("Set FORME_HUNYUAN_KEY_FILE or pass --key-file")
    if args.action == "check":
        manifest, body = build_input(args.path)
        print(json.dumps({"submissionId": manifest["submissionId"], "model": body["Model"],
                          "generateType": body["GenerateType"], "views": ["front", "left", "right", "back"],
                          "region": args.region, "credentialAvailable": args.key_file.is_file()}))
    elif args.action == "submit":
        print(json.dumps(submit(args.path, args.key_file, args.region), ensure_ascii=False))
    elif args.action == "poll":
        result = poll(args.path, args.key_file)
        print(json.dumps({k: v for k, v in result.items() if k != "resultFiles"}, ensure_ascii=False))
    else:
        result = archive(args.path)
        print(json.dumps({"jobId": result["jobId"], "status": result["status"],
                          "artifacts": result["artifacts"], "previews": result["previews"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
