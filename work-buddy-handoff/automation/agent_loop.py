"""One-command, bounded DeepSeek -> Blender -> render -> inspect -> revise loop.

Run from Terminal. If DEEPSEEK_API_KEY is absent, a hidden prompt asks for it:
    python3 projects/test4/deepseek-blender-trial/agent_loop.py
"""

import argparse
import base64
import getpass
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
HANDOFF = (HERE.parent / "evidence" / "original_video").is_dir()
ROOT = next((p for p in HERE.parents if (p / "apps/Blender.app/Contents/MacOS/Blender").exists()), list(HERE.parents)[-1])
TEST4 = HERE.parent
BLENDER = Path(os.environ.get("BLENDER_PATH", ROOT / "apps/Blender.app/Contents/MacOS/Blender"))
BASE_SCENE = (HERE.parent / "blender" / "base_scene.blend") if HANDOFF else (HERE / "base_scene.blend")
API_URL = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-flash"
FIELDS = {
    "clearance_mm": (5.0, 14.0),
    "wall_mm": (2.0, 5.0),
    "smooth_iterations": (5, 18),
    "upper_flare_mm": (-8.0, 12.0),
    "front_back_bias_mm": (-8.0, 8.0),
    "upper_raise_mm": (-5.0, 38.0),
    "rim_asymmetry_mm": (-18.0, 18.0),
}
RENDER_NAMES = ("front", "rear", "bolt_side", "three_quarter")
FRAMES = (HERE.parent / "evidence" / "key_frames") if HANDOFF else (TEST4 / "reconstruction/dense/images")
PHOTO_PATHS = (
    ("视频实拍：上口与侧面", FRAMES / "frame_00040.jpg"),
    ("视频实拍：螺栓和下段", FRAMES / "frame_00050.jpg"),
    ("视频实拍：上口俯视", FRAMES / "frame_00075.jpg"),
)

SYSTEM = """你是设计假肢外侧保护壳的 Blender 建模审查员。你需要逐轮查看四张渲染图、三张实拍图和网格检查指标，修改有范围限制的参数。回复必须是 JSON 对象，含 diagnosis、changes、accept、parameters。parameters 必须给出全部字段，不要给代码。

目标：保护壳包覆接受腔的主要外表面；后侧 +Y 保留贯通纵向开口；上口与接受腔异形上沿协调，不要盖住腔口；中段平顺，不能波浪起伏；右侧螺栓应通过真实挖空的避让口露出，不能把它当鼓包；底部停在接受腔区域，不要裹住鞋或小腿下部。优先修复明显视觉问题。当前实拍和 Hunyuan 参考模型都不是计量级真值。没有实测尺寸时，不得声称可打印试装或实际贴合。

参数含义：profile_mm 是从下到上的六个径向修正节点，正值向外扩、负值向内收。upper_flare_mm 只影响最上部向外扩。front_back_bias_mm 对上部前后倾向作平顺修正。upper_raise_mm 整体抬高上缘，rim_asymmetry_mm 增加平顺的不对称起伏。clearance_mm 是 Shrinkwrap 偏移，wall_mm 是壳厚，smooth_iterations 是表面平滑次数。几何引擎固定维护拓扑、C 形开口、螺栓挖空。

只根据实际可见证据给出修改。若指标显示非流形或高度显著异常，要指出失败，并给出保守参数。accept 仅表示视觉概念通过，不代表物理贴合验证通过。"""


def image_block(path):
    mime = "image/jpeg" if path.suffix.lower() == ".jpg" else "image/png"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}}


def validate_spec(raw):
    if not isinstance(raw, dict):
        raise ValueError("parameters 必须是对象")
    spec = {}
    for name, (lower, upper) in FIELDS.items():
        value = raw.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not lower <= value <= upper:
            raise ValueError(f"{name} 必须在 {lower}–{upper} 之间")
        spec[name] = int(value) if name == "smooth_iterations" else float(value)
    profile = raw.get("profile_mm")
    if not isinstance(profile, list) or len(profile) != 6:
        raise ValueError("profile_mm 必须有六个数值")
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not -8 <= v <= 8 for v in profile):
        raise ValueError("profile_mm 每个节点必须在 -8–8 mm")
    spec["profile_mm"] = [float(v) for v in profile]
    return spec


def run_blender(spec, folder):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "spec.json").write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    env = os.environ.copy()
    env.pop("DEEPSEEK_API_KEY", None)  # Blender never needs the credential.
    cmd = [str(BLENDER), "-b", str(BASE_SCENE), "--python", str(HERE / "build_iteration.py"),
           "--", str(folder / "spec.json"), str(folder)]
    with (folder / "blender.log").open("w", encoding="utf-8") as log:
        result = subprocess.run(cmd, cwd=str(ROOT), env=env, stdout=log, stderr=subprocess.STDOUT, timeout=180)
    if result.returncode != 0:
        raise RuntimeError(f"Blender 失败：请看 {folder / 'blender.log'}")
    return json.loads((folder / "metrics.json").read_text(encoding="utf-8"))


def ask_deepseek(key, iteration_folder, spec, metrics, prior_feedback):
    descriptions = "\n".join(f"{name}: {lo}–{hi}" for name, (lo, hi) in FIELDS.items())
    prompt = ("请检查本轮候选并返回完整 JSON。你必须查看全部图片，明确指出上口、中段、螺栓避让、后侧开口和底端的问题；"
              "若没有可见问题才设置 accept=true。请只改有理由修改的参数，调整要平顺，避免振荡。\n"
              f"允许范围：\n{descriptions}\nprofile_mm: 六个数，每个 -8–8。\n"
              f"当前参数：{json.dumps(spec, ensure_ascii=False)}\n"
              f"网格检查：{json.dumps(metrics, ensure_ascii=False)}\n"
              f"上一轮审查：{json.dumps(prior_feedback, ensure_ascii=False) if prior_feedback else '首轮'}\n"
              "JSON 格式：{\"diagnosis\":\"...\",\"changes\":\"...\",\"accept\":false,\"parameters\":{...}}")
    content = [{"type": "text", "text": prompt}]
    for label, path in PHOTO_PATHS:
        content.extend(({"type": "text", "text": label}, image_block(path)))
    for name in RENDER_NAMES:
        content.extend(({"type": "text", "text": f"当前 Blender 渲染：{name}"}, image_block(iteration_folder / (name + ".png"))))
    payload = {"model": MODEL, "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": content}],
               "thinking": {"type": "disabled"}, "response_format": {"type": "json_object"},
               "max_tokens": 1800, "stream": False}
    (iteration_folder / "request_text.json").write_text(json.dumps({"system": SYSTEM, "prompt": prompt}, ensure_ascii=False, indent=2), encoding="utf-8")
    request = urllib.request.Request(API_URL, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                                     headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"}, method="POST")
    with urllib.request.urlopen(request, timeout=240) as response:
        result = json.load(response)
    (iteration_folder / "response_raw.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    message = result.get("choices", [{}])[0].get("message", {}).get("content", "")
    if not isinstance(message, str) or not message.strip():
        raise ValueError("DeepSeek 返回空内容；原始响应已保存")
    feedback = json.loads(message)
    if not isinstance(feedback.get("diagnosis"), str) or not isinstance(feedback.get("changes"), str) or not isinstance(feedback.get("accept"), bool):
        raise ValueError("DeepSeek 审查 JSON 字段不完整")
    next_spec = validate_spec(feedback.get("parameters"))
    (iteration_folder / "feedback.json").write_text(json.dumps(feedback, ensure_ascii=False, indent=2), encoding="utf-8")
    (iteration_folder / "usage.json").write_text(json.dumps(result.get("usage", {}), ensure_ascii=False, indent=2), encoding="utf-8")
    return feedback, next_spec


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", type=int, default=3, help="Maximum DeepSeek review requests (1–5, default 3)")
    args = parser.parse_args()
    if not 1 <= args.rounds <= 5:
        parser.error("--rounds 必须在 1–5")
    key = os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        if not sys.stdin.isatty():
            print("非交互终端请设置 DEEPSEEK_API_KEY。", file=sys.stderr)
            return 2
        key = getpass.getpass("DeepSeek API Key（输入不回显，也不会保存）：").strip()
        if not key:
            print("未输入 API Key。", file=sys.stderr)
            return 2
    if not BLENDER.exists():
        print(f"Blender 不存在：{BLENDER}", file=sys.stderr)
        return 2
    out = HERE / "auto-loop"
    out.mkdir(exist_ok=True)
    seed = validate_spec(json.loads((HERE / "seed_spec.json").read_text(encoding="utf-8")))
    try:
        spec = seed
        prior = None
        summary = []
        for number in range(args.rounds):
            folder = out / f"iteration_{number:02d}"
            if number == 0 and (folder / "metrics.json").exists() and (folder / "spec.json").exists() and json.loads((folder / "spec.json").read_text()) == spec:
                metrics = json.loads((folder / "metrics.json").read_text())
            else:
                print(f"[{number + 1}/{args.rounds}] Blender 建模和渲染…", flush=True)
                metrics = run_blender(spec, folder)
            print(f"[{number + 1}/{args.rounds}] DeepSeek 看图审查…", flush=True)
            feedback, next_spec = ask_deepseek(key, folder, spec, metrics, prior)
            summary.append({"iteration": number, "metrics": metrics, "diagnosis": feedback["diagnosis"],
                            "changes": feedback["changes"], "accept": feedback["accept"], "parameters": spec})
            (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"诊断：{feedback['diagnosis']}\n修订：{feedback['changes']}", flush=True)
            if feedback["accept"] and metrics["watertight"] and 260 <= metrics["height_mm"] <= 390:
                print(f"视觉概念通过，停在 {folder}；物理贴合仍未验证。", flush=True)
                break
            if number == args.rounds - 1:
                if next_spec != spec:
                    final_folder = out / f"iteration_{number + 1:02d}"
                    print("已达审查轮数上限；生成最后一次修订供人工查看…", flush=True)
                    final_metrics = run_blender(next_spec, final_folder)
                    summary.append({"iteration": number + 1, "metrics": final_metrics,
                                    "diagnosis": "最终参数版本尚未送给 DeepSeek 再审查", "changes": "", "accept": False,
                                    "parameters": next_spec})
                    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
                    print(f"最后完成的网格和渲染在 {final_folder}；请查看 summary.json。", flush=True)
                else:
                    print(f"最后完成的网格和渲染在 {folder}；请查看 summary.json。", flush=True)
                break
            if next_spec == spec:
                print("模型没有改变参数，停止以免重复花费。", flush=True)
                break
            prior = feedback
            spec = next_spec
        return 0
    except (RuntimeError, ValueError, urllib.error.URLError, urllib.error.HTTPError, subprocess.TimeoutExpired) as exc:
        error = f"自动循环中止：{type(exc).__name__}: {exc}"
        (out / "error.txt").write_text(error, encoding="utf-8")
        print(error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
