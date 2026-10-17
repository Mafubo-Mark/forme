from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    dev_token: str
    ffprobe: str
    ffmpeg: str
    max_upload_bytes: int = 512 * 1024 * 1024
    colmap: str = "/Volumes/extra/workspace1/colmap-metal/build/src/colmap/exe/colmap"
    vision_model: str = "deepseek-flash"
    vision_api_key: str = ""
    vision_provider: str = "deepseek"
    customer_access_key: str = ""
    secure_customer_cookie: bool = False
    hunyuan_key_file: Path | None = None
    hunyuan_region: str = "ap-singapore"
    geometry_python: str = ""

    @property
    def vision_api_url(self) -> str:
        urls = {
            "deepseek": "https://api.deepseek.com/chat/completions",
            "tokenhub": "https://tokenhub-intl.tencentcloudmaas.com/v1/chat/completions",
        }
        return urls[self.vision_provider]

    @property
    def vision_provider_label(self) -> str:
        return {"deepseek": "DeepSeek", "tokenhub": "Tencent TokenHub"}[self.vision_provider]

    @classmethod
    def from_env(cls) -> "Settings":
        token = os.environ.get("FORME_DEV_TOKEN", "")
        if not token:
            raise RuntimeError("FORME_DEV_TOKEN is required until production authentication exists")
        provider = os.environ.get("FORME_VISION_PROVIDER", "deepseek").lower()
        if provider not in {"deepseek", "tokenhub"}:
            raise RuntimeError("FORME_VISION_PROVIDER must be deepseek or tokenhub")
        return cls(
            data_dir=Path(os.environ.get("FORME_DATA_DIR", "./data")).resolve(),
            dev_token=token,
            ffprobe=os.environ.get("FORME_FFPROBE", "ffprobe"),
            ffmpeg=os.environ.get("FORME_FFMPEG", "ffmpeg"),
            colmap=os.environ.get("FORME_COLMAP", "/Volumes/extra/workspace1/colmap-metal/build/src/colmap/exe/colmap"),
            vision_model=os.environ.get("FORME_VISION_MODEL", "deepseek-flash" if provider == "deepseek" else "deepseek/deepseek-flash"),
            vision_api_key=os.environ.get("FORME_DEEPSEEK_API_KEY" if provider == "deepseek" else "FORME_TOKENHUB_API_KEY", ""),
            vision_provider=provider,
            customer_access_key=os.environ.get("FORME_CUSTOMER_ACCESS_KEY", ""),
            secure_customer_cookie=os.environ.get("FORME_SECURE_CUSTOMER_COOKIE", "0") == "1",
            hunyuan_key_file=Path(os.environ["FORME_HUNYUAN_KEY_FILE"]).expanduser().resolve()
            if os.environ.get("FORME_HUNYUAN_KEY_FILE") else None,
            hunyuan_region=os.environ.get("FORME_HUNYUAN_REGION", "ap-singapore"),
            geometry_python=os.environ.get("FORME_GEOMETRY_PYTHON", ""),
        )
