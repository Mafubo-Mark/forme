"""Ask DeepSeek to repair the first candidate; save code for review only."""

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

from request_first_pass import API_URL, HERE, MODEL, TEST4, image_block


SYSTEM = """你是一位资深 Blender Python 建模程序员。请返回合法 JSON 对象，包含
"diagnosis"、"design_plan"、"blender_python" 三个字符串字段。只给可以在 Blender 5.2
执行的完整 Python 脚本。不要执行外部程序、网络、文件读写；不要删除参考模型。
代码只能使用 bpy、math、mathutils、numpy。新建对象必须以 'DS Trial' 命名。
输出是概念设计，不得声称毫米级贴合或可试装。"""

FEEDBACK = """首轮候选经过静态审查，未运行。必须修正以下问题：
1. 第 127 行 `bfaces = [] for i in range(...)` 是 Python 语法错误；修订代码必须可通过 ast.parse。
2. theta 只覆盖 π±gap 的约 28–40°，这只是窄片。真实 C 壳须覆盖约 300° 以上，
   背侧 +Y 留连续纵向开口；以 +Y 为中心设置缺口，角度应从 π/2+gap 到 5π/2−gap。
3. 不可用全局中心 + X/Y 极值做每层对称椭圆。应从参考 mesh 的每个高度带估计局部中心和
   多角度径向轮廓，剔除明显硬件突出点后做适度平顺，并让中心随高度变化。
4. 所谓螺栓避让必须从壳体实际减去材料；独立展示一个圆片不算避让。
   场景里已有概念切割器 `Bolt relief | 42 wide x 52 tall`，可以用它的拷贝作 Boolean DIFFERENCE，
   但不得宣称其尺寸通过实测。
5. 上口的高度曲线必须参考视频照片中的异形边缘，不能只在最高一圈凭空叠一个正弦双峰。
6. 现有 .blend 对象名为 `01 Reference prosthesis | 120 mm top scale`、
   `00 COVER | cleaned final design`、`02 Editable design cage | hidden | enable to change modifiers`。
   首轮中的 `02 COVER | editable Blender modifiers` 根本不存在。
7. 只创建新对象；不要覆盖原场景内容，不加文字、装饰孔或假固定件。

请先说明修订后的几何思路，再给完整 Blender Python。JSON 示例：
{"diagnosis":"...","design_plan":"...","blender_python":"import bpy\\n..."}
"""

IMAGES = [
    ("原视频侧面及上口", TEST4 / "reconstruction/dense/images/frame_00040.jpg"),
    ("原视频螺栓与下段", TEST4 / "reconstruction/dense/images/frame_00050.jpg"),
    ("原视频上口俯视", TEST4 / "reconstruction/dense/images/frame_00075.jpg"),
    ("旧 Blender 壳正面", TEST4 / "blender-cover-redesign/front.png"),
    ("旧 Blender 壳螺栓侧", TEST4 / "blender-cover-redesign/bolt-side.png"),
]


def main() -> int:
    key = os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        (HERE / "revision_error.txt").write_text("DEEPSEEK_API_KEY 不在当前终端环境中", encoding="utf-8")
        print("DEEPSEEK_API_KEY 不在当前终端环境中", file=sys.stderr)
        return 2
    first = (HERE / "candidate_blender.py").read_text(encoding="utf-8")
    content = [{"type": "text", "text": FEEDBACK + "\n\n首轮候选代码：\n" + first}]
    for label, path in IMAGES:
        content.extend([{"type": "text", "text": label}, image_block(path)])
    payload = {
        "model": MODEL,
        "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": content}],
        "thinking": {"type": "disabled"},
        "response_format": {"type": "json_object"},
        "max_tokens": 12000,
        "stream": False,
    }
    req = urllib.request.Request(API_URL, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=240) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        error = f"DeepSeek HTTP {exc.code}: {exc.read(2000).decode('utf-8', 'replace')}"
        (HERE / "revision_error.txt").write_text(error, encoding="utf-8")
        print(error, file=sys.stderr)
        return 1
    except urllib.error.URLError as exc:
        error = f"网络请求失败：{exc.reason}"
        (HERE / "revision_error.txt").write_text(error, encoding="utf-8")
        print(error, file=sys.stderr)
        return 1
    (HERE / "deepseek_revision_raw.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        candidate = json.loads(result["choices"][0]["message"]["content"])
        code = candidate["blender_python"]
        if not isinstance(code, str): raise TypeError("blender_python 不是字符串")
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        error = f"DeepSeek 修订响应无法解析：{type(exc).__name__}: {exc}"
        (HERE / "revision_error.txt").write_text(error, encoding="utf-8")
        print(error, file=sys.stderr)
        return 1
    (HERE / "deepseek_revision.json").write_text(json.dumps(candidate, ensure_ascii=False, indent=2), encoding="utf-8")
    (HERE / "candidate_blender_v2.py").write_text(code, encoding="utf-8")
    (HERE / "revision_usage.json").write_text(json.dumps(result.get("usage", {}), ensure_ascii=False, indent=2), encoding="utf-8")
    print("修订候选已保存；代码尚未执行。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
