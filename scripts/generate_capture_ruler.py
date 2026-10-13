"""Create the downloadable A4 capture ruler with an exact 200 mm baseline."""
from pathlib import Path
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'dist/assets/downloads/forme-ruler-200mm-a4.pdf'
FONT = Path('/System/Library/Fonts/Supplemental/Arial Unicode.ttf')


def generate():
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    if not FONT.is_file():
        raise SystemExit('Set FONT to a Unicode TTF font supporting Traditional Chinese.')
    pdfmetrics.registerFont(TTFont('Guide', str(FONT)))
    c = canvas.Canvas(str(OUTPUT), pagesize=A4, pageCompression=1)
    c.setTitle('Forme 200 mm capture ruler - A4 actual size')
    c.setAuthor('Forme')
    c.setFillColorRGB(.10, .13, .12)
    c.setFont('Helvetica-Bold', 26)
    c.drawString(22*mm, 269*mm, 'forme.')
    c.setFont('Guide', 15)
    c.drawString(22*mm, 252*mm, '200 mm capture ruler / 拍攝標尺')
    lines = [
        ('1. Print A4 at 100% / Actual size. Disable Fit to page.', '以 A4、100% 原尺寸打印；關閉「縮放至頁面」。'),
        ('2. Check the 0-200 mm endpoints with a physical ruler.', '用實體尺核對 0 與 200 mm 兩端的距離。'),
        ('3. Cut out the strip along the dashed border.', '沿虛線剪下標尺。'),
        ('4. Fix it flat beside the prosthesis; keep it still.', '平直固定在義肢旁；拍攝期間保持不動。'),
        ('5. Show both endpoints clearly in several video views.', '在多個影片視角中清楚拍到兩端。'),
        ('Do not bend the strip or wrap it around the socket.', '不要彎折標尺，或把它環繞接收腔。'),
    ]
    y = 233*mm
    for en, zh in lines:
        c.setFont('Guide', 10)
        c.drawString(22*mm, y, en)
        c.drawString(22*mm, y-5*mm, zh)
        y -= 17*mm
    c.setFont('Guide', 9)
    c.drawString(22*mm, 111*mm, 'The strip is vertical so the full 200 mm fits on one A4 page.')
    c.drawString(22*mm, 106*mm, '標尺直向排列，完整 200 mm 可打印在一張 A4 紙上。')
    # Strip at the right; endpoints are exactly 200 mm apart on the page.
    left, bottom, width, height = 159*mm, 45*mm, 35*mm, 214*mm
    c.setStrokeColorRGB(.5, .5, .5)
    c.setDash(3, 3)
    c.rect(left, bottom, width, height)
    c.setDash()
    c.setStrokeColorRGB(0, 0, 0)
    c.setFillColorRGB(0, 0, 0)
    baseline_x, zero_y = 166*mm, 52*mm
    c.setLineWidth(.8)
    c.line(baseline_x, zero_y, baseline_x, zero_y+200*mm)
    for value in range(201):
        y = zero_y + value*mm
        length = 9 if value % 10 == 0 else 6 if value % 5 == 0 else 3
        c.setLineWidth(.65 if value % 10 == 0 else .3)
        c.line(baseline_x, y, baseline_x+length*mm, y)
        if value % 10 == 0:
            c.setFont('Helvetica-Bold' if value in (0, 200) else 'Helvetica', 9)
            c.drawString(baseline_x+11*mm, y-2.5, str(value))
    c.setFont('Helvetica', 8)
    c.drawString(166*mm, 255*mm, 'mm')
    c.setLineWidth(1)
    # A separate 50 mm check line helps reveal printer scaling.
    c.line(22*mm, 84*mm, 72*mm, 84*mm)
    for x in (22, 72): c.line(x*mm, 82*mm, x*mm, 86*mm)
    c.setFont('Guide', 9)
    c.drawString(22*mm, 76*mm, '50 mm print check / 打印尺寸核對')
    c.drawString(22*mm, 29*mm, 'Measure between tick endpoints, not the paper border.')
    c.drawString(22*mm, 24*mm, '量度刻度兩端之間的距離，請勿以紙邊作為測量點。')
    c.showPage()
    c.save()
    print(OUTPUT)


if __name__ == '__main__':
    generate()
