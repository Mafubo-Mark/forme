"""Request one visual Blender redesign from DeepSeek; do not execute its code."""

import base64
import json
import mimetypes
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path


HERE = Path(__file__).resolve().parent
TEST4 = HERE.parent
MODEL = "deepseek-flash"
API_URL = "https://api.deepseek.com/chat/completions"

IMAGES = [
    ("原视频：开放上口与侧面，frame_00040", TEST4 / "reconstruction/dense/images/frame_00040.jpg"),
    ("原视频：白色下段和螺栓，frame_00050", TEST4 / "reconstruction/dense/images/frame_00050.jpg"),
    ("原视频：上口俯视，frame_00075", TEST4 / "reconstruction/dense/images/frame_00075.jpg"),
    ("原视频：上口另一角度，frame_00082", TEST4 / "reconstruction/dense/images/frame_00082.jpg"),
    ("原有 Blender 保护壳：正面", TEST4 / "blender-cover-redesign/front.png"),
    ("原有 Blender 保护壳：背面", TEST4 / "blender-cover-redesign/rear.png"),
    ("原有 Blender 保护壳：螺栓侧", TEST4 / "blender-cover-redesign/bolt-side.png"),
    ("原有 Blender 保护壳：斜视", TEST4 / "blender-cover-redesign/three-quarter.png"),
]

SYSTEM = """你是一位熟悉 Blender Python 的工业设计建模师。请输出合法 JSON 对象，字段必须是
"diagnosis"（简短中文）、"design_plan"（简短中文）、"blender_python"（可执行 Python 字符串）。
设计目标是异形假肢外侧保护壳，不是圆柱体，也不是原扫描网格的直接偏移。
以原视频照片为外形证据；现有保护壳渲染图只用来识别失败之处。
不要宣称可试装或毫米级精度。不要用文件系统读写、网络调用、subprocess、os、sys、eval、exec。
Python 代码仅使用 bpy、math、mathutils、numpy，运行时已载入给定 .blend，必须保留原始参考模型。
只在场景内建立新对象，名字以 'DS Trial' 开头；不要保存或导出文件，外部运行器负责保存和渲染。
"""

USER = """请针对照片重新设计一个平顺的全长 C 形保护壳。已载入 Blender 5.2 场景，单位 mm，
存在对象 '01 Reference prosthesis | 120 mm top scale'、'02 COVER | editable Blender modifiers'，
还有旧版壳和切割器。原参考模型与旧版壳的 z 轴已经直立，鞋尖方向大约是 -Y，
原模型螺栓一侧为 +X。当前版上口只是造型推断，固定方式和间隙未验证。

本轮只设计主体及上口，不加字母或装饰孔。主体应遵循异形接受腔轮廓但保持视觉平顺；
上口应接近照片中的高低起伏，不要用统一水平圆环；背侧留安装开口；螺栓只做独立开放避让，
不能当作主体表面的鼓包。与参考模型的间隙先做保守概念版，绝不称为已验证贴合。
请在 Blender Python 中建立可编辑的低面数控制网格及适当修改器。
优先读取场景中参考物和旧壳的包围盒、顶点范围，而不要凭空假设绝对位置。
若照片不足以确认某局部结构，请在 diagnosis 中指出，不得捏造尺寸。

返回 JSON，示例格式：
{"diagnosis":"...","design_plan":"...","blender_python":"import bpy\\n..."}
"""


def image_block(path: Path) -> dict:
    mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{data}", "detail": "high"}}


def main() -> int:
    key = os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        error = "DEEPSEEK_API_KEY 不在当前终端环境中；请在设置它的同一终端运行本脚本。"
        (HERE / "run_error.txt").write_text(error, encoding="utf-8")
        print(error, file=sys.stderr)
        return 2
    for _, path in IMAGES:
        if not path.is_file():
            error = f"缺少输入图片：{path}"
            (HERE / "run_error.txt").write_text(error, encoding="utf-8")
            print(error, file=sys.stderr)
            return 2
    content = [{"type": "text", "text": USER}]
    for label, path in IMAGES:
        content.append({"type": "text", "text": label})
        content.append(image_block(path))
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": content},
        ],
        "thinking": {"type": "disabled"},
        "response_format": {"type": "json_object"},
        "max_tokens": 12000,
        "stream": False,
    }
    request = urllib.request.Request(
        API_URL,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        method="POST",
    )
    print(f"向 {MODEL} 提交 {len(IMAGES)} 张图片；API Key 不会写入输出文件。", flush=True)
    try:
        with urllib.request.urlopen(request, timeout=240) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        error = f"DeepSeek HTTP {exc.code}: {exc.read(2000).decode('utf-8', 'replace')}"
        (HERE / "run_error.txt").write_text(error, encoding="utf-8")
        print(error, file=sys.stderr)
        return 1
    except urllib.error.URLError as exc:
        error = f"网络请求失败：{exc.reason}"
        (HERE / "run_error.txt").write_text(error, encoding="utf-8")
        print(error, file=sys.stderr)
        return 1
    (HERE / "deepseek_raw.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        message = result["choices"][0]["message"]["content"]
        candidate = json.loads(message)
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        finish = result.get("choices", [{}])[0].get("finish_reason")
        error = f"DeepSeek 已回复，但响应 JSON 解析失败：{type(exc).__name__}: {exc}; finish_reason={finish}; usage={result.get('usage', {})}"
        (HERE / "run_error.txt").write_text(error, encoding="utf-8")
        print(error, file=sys.stderr)
        return 1
    if not isinstance(candidate.get("blender_python"), str):
        raise ValueError("响应缺少 blender_python 字符串")
    (HERE / "deepseek_response.json").write_text(json.dumps(candidate, ensure_ascii=False, indent=2), encoding="utf-8")
    (HERE / "candidate_blender.py").write_text(candidate["blender_python"], encoding="utf-8")
    (HERE / "usage.json").write_text(json.dumps(result.get("usage", {}), ensure_ascii=False, indent=2), encoding="utf-8")
    print("已保存 deepseek_response.json、candidate_blender.py、usage.json；候选代码尚未执行。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
