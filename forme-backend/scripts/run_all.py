"""Supervise the local API, modeling workers, cloud bridge and SSH tunnel."""
from __future__ import annotations

import fcntl
import os
import secrets
import signal
import socket
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOGS = ROOT / "data" / "service-logs"
STOP = False


def stop(_signal: int, _frame: object) -> None:
    global STOP
    STOP = True


def environment() -> dict[str, str]:
    env = dict(os.environ)
    env["FORME_DATA_DIR"] = str(ROOT / "data")
    env["FORME_DEV_TOKEN"] = (ROOT / ".local-operator-token").read_text().strip()
    key_file = ROOT / ".customer-access-key"
    if not key_file.is_file():
        key_file.write_text(secrets.token_hex(24) + "\n")
        key_file.chmod(0o600)
    env["FORME_CUSTOMER_ACCESS_KEY"] = key_file.read_text().strip()
    env["FORME_CLOUD_CONFIG"] = str(ROOT / ".cloud-bridge.json")
    tool_dir = Path("/Volumes/extra/workspace1/colmap-metal/.pixi/envs/default/bin")
    for name in ("ffprobe", "ffmpeg"):
        path = tool_dir / name
        if path.is_file():
            env.setdefault("FORME_" + name.upper(), str(path))
    geometry_python = Path("/Volumes/extra/workspace1/apps/drawing-with-gaussians/.venv/bin/python")
    if geometry_python.is_file():
        env.setdefault("FORME_GEOMETRY_PYTHON", str(geometry_python))
    hunyuan_key = Path("/Users/emilia/Downloads/SecretKey.csv")
    if hunyuan_key.is_file():
        env["FORME_HUNYUAN_KEY_FILE"] = str(hunyuan_key)
    return env


def main() -> None:
    os.umask(0o077)
    LOGS.mkdir(parents=True, exist_ok=True)
    LOGS.chmod(0o700)
    with (LOGS / "supervisor.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("后台链路已经运行；打开 http://127.0.0.1:8001/operator/ 即可。", flush=True)
            return
        control_path = LOGS / "control.sock"
        control_path.unlink(missing_ok=True)
        control = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        control.bind(str(control_path))
        control_path.chmod(0o600)
        control.setblocking(False)
        signal.signal(signal.SIGINT, stop)
        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGHUP, stop)
        env = environment()
        python = str(ROOT / ".venv" / "bin" / "python")
        commands = {
            "api": [str(ROOT / ".venv" / "bin" / "uvicorn"), "forme_backend.api:create_app", "--factory", "--host", "127.0.0.1", "--port", "8001"],
            "media": [python, "-m", "forme_backend.worker"],
            "colmap": [python, "-m", "forme_backend.model_worker"],
            "scan": [python, "-m", "forme_backend.scan_worker"],
            "bridge": [python, "-m", "forme_backend.cloud_bridge"],
            "tunnel": ["/bin/zsh", str(ROOT / "start-tunnel.command")],
        }
        if "FORME_HUNYUAN_KEY_FILE" in env:
            commands["hunyuan"] = [python, "-m", "forme_backend.hunyuan_worker"]
        running: dict[str, tuple[subprocess.Popen[bytes], object, object]] = {}

        def launch(name: str) -> None:
            stdout = (LOGS / f"{name}.out.log").open("ab")
            stderr = (LOGS / f"{name}.err.log").open("ab")
            process = subprocess.Popen(commands[name], cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                                       stdout=stdout, stderr=stderr, start_new_session=True)
            running[name] = (process, stdout, stderr)
            print(f"{name} 已启动，PID {process.pid}", flush=True)

        try:
            print("Forme 后台链路启动中。操作面板：http://127.0.0.1:8001/operator/", flush=True)
            print(f"日志：{LOGS}；关闭请运行 stop-all.command 或按 Ctrl+C。", flush=True)
            for name in commands:
                launch(name)
            while not STOP:
                try:
                    if control.recv(128) == b"stop":
                        break
                except BlockingIOError:
                    pass
                for name, (process, stdout, stderr) in list(running.items()):
                    result = process.poll()
                    if result is not None:
                        stdout.close()
                        stderr.close()
                        print(f"{name} 退出（{result}），正在重启。", flush=True)
                        launch(name)
                time.sleep(2)
        finally:
            for process, _, _ in running.values():
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGTERM)
            for process, stdout, stderr in running.values():
                try:
                    process.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                stdout.close()
                stderr.close()
            control.close()
            control_path.unlink(missing_ok=True)
            print("Forme 后台链路已停止。", flush=True)


if __name__ == "__main__":
    main()
