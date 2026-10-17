"""Create a clearly labeled walkthrough of the historical Forme demo sample."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = Path('/Volumes/extra/workspace1/projects/test4')
OUT = Path(__file__).resolve().parent
TASK = ROOT / 'forme-backend/data/cover_tasks/fa5c0a40-fd4a-474f-80cf-3da92d7af3a8'
UPLOAD = ROOT / 'forme-backend/data/uploads/a3a6f7bc-3f35-4df7-994c-fc6ce85796aa'
FONT = '/System/Library/Fonts/STHeiti Medium.ttc'
title_font = ImageFont.truetype(FONT, 46)
body_font = ImageFont.truetype(FONT, 26)
small_font = ImageFont.truetype(FONT, 21)

slides = [
    ('01 / 拍摄输入', '含 200 mm 标定尺的真实环绕视频', '视频与人工确认的六视角均来自历史样本。', UPLOAD / 'review_frames/review_04.jpg'),
    ('02 / COLMAP 点云', '约 206 万个原始稠密点', '点云归档复用；今天重算标尺候选尺度 141.1745 mm / COLMAP 单位。', ROOT / 'analysis/isolated-orthographic.jpg'),
    ('03 / 混元 3D', '多视角生成的外观参考白模', '使用历史归档结果；白模不作为毫米贴合尺寸依据。', TASK / 'hunyuan_inputs/hunyuan_result/preview_00.png'),
    ('04 / 保护套设计', '祥云模板 · 低开口', '今天重新运行点云约束的局部微调，生成前后两片 STL。', TASK / 'workbuddy_hybrid_v2/review_front.png'),
    ('05 / 上口与侧面', '保留高翻边外露的设计意图', '上口净空、侧孔薄边和固定件位置仍需复核。', TASK / 'workbuddy_hybrid_v2/review_side.png'),
    ('06 / 数字试样', '毫米 3MF 已重新打包', '双片网格水密；约 315 mm 高。切片与实物适配尚未验收。', TASK / 'workbuddy_hybrid_v2/review_oblique.png'),
]

for index, (step, title, body, source) in enumerate(slides, 1):
    canvas = Image.new('RGB', (1280, 720), '#131d1c')
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle((52, 65, 520, 580), 24, fill='#e7eee9')
    draw.text((84, 110), step, font=small_font, fill='#2f7860')
    def wrap(value, font, width=400):
        lines, current = [], ''
        for char in value:
            if draw.textlength(current + char, font=font) > width and current:
                lines.append(current)
                current = char
            else:
                current += char
        return '\n'.join(lines + [current])
    draw.multiline_text((84, 184), wrap(title, title_font), font=title_font, fill='#152822', spacing=12)
    draw.multiline_text((84, 320), wrap(body, body_font), font=body_font, fill='#31473d', spacing=12)
    draw.text((84, 624), 'FORME  /  MAC WORKFLOW DEMO', font=small_font, fill='#a5bcb2')
    draw.text((700, 624), '历史样本复现 · 非成品验收', font=small_font, fill='#a5bcb2')
    original = Image.open(source).convert('RGB')
    visual = ImageOps.contain(original, (680, 560), Image.Resampling.LANCZOS)
    x = 550 + (680 - visual.width) // 2
    y = 50 + (560 - visual.height) // 2
    canvas.paste(visual, (x, y))
    canvas.save(OUT / f'slide_{index:02d}.png')
