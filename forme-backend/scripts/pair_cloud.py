#!/usr/bin/env python3
"""Receive one-time Forme bridge credentials over an authenticated SSH connection.

The server operator prepares ~/forme-bridge-bootstrap.json for the tunnel user.
No credential is printed or placed in shell arguments.
"""
import argparse
import json
import os
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
KEY = ROOT / "data/forme-cloud-tunnel-ed25519"
BOOTSTRAP = "forme-bridge-bootstrap.json"


def private_write(path: Path, contents: str):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as output:
        output.write(contents)
    os.chmod(path, 0o600)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", required=True)
    parser.add_argument("--user", default="forme_tunnel")
    parser.add_argument("--port", type=int, default=22)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", args.host):
        parser.error("Invalid SSH host")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.user):
        parser.error("Invalid SSH user")
    if not KEY.is_file():
        parser.error("Mac SSH key missing")
    target = f"{args.user}@{args.host}"
    base = ["ssh", "-i", str(KEY), "-p", str(args.port), "-o", "BatchMode=yes",
            "-o", "IdentitiesOnly=yes", "-o", "StrictHostKeyChecking=accept-new", target]
    received = subprocess.run(base + ["cat", BOOTSTRAP], check=True, capture_output=True, text=True)
    value = json.loads(received.stdout)
    if value.get("base_url") != "https://forme.agents-time.com":
        raise ValueError("Unexpected cloud URL")
    if not isinstance(value.get("worker_key"), str) or len(value["worker_key"]) < 32:
        raise ValueError("Cloud worker key missing or weak")
    if not isinstance(value.get("local_operator_token"), str) or len(value["local_operator_token"]) < 32:
        raise ValueError("Local operator token missing or weak")
    private_write(ROOT / ".cloud-bridge.json", json.dumps({
        "base_url": value["base_url"], "worker_key": value["worker_key"]
    }) + "\n")
    private_write(ROOT / ".local-operator-token", value["local_operator_token"] + "\n")
    subprocess.run(base + ["rm", "-f", BOOTSTRAP], check=True, capture_output=True, text=True)
    print("Pairing credentials saved locally with mode 600; server bootstrap deleted.")
    print("Tunnel target:", target, "port", args.port)


if __name__ == "__main__":
    main()
