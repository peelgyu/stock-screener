"""StockInto 아이콘 세트 생성 (192/512/180/apple-touch)."""
from PIL import Image, ImageDraw, ImageFont
import os

OUT = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(OUT, exist_ok=True)


def make_icon(size: int, filename: str):
    # 배경: 보라→청록 그라디언트 (StockInto 브랜드 색)
    img = Image.new("RGB", (size, size), "#1a1a2e")
    draw = ImageDraw.Draw(img)

    # 그라디언트 효과 (수동)
    for y in range(size):
        r = int(123 + (0 - 123) * y / size)      # 7b → 00
        g = int(47 + (210 - 47) * y / size)      # 2f → d2
        b = int(247 + (255 - 247) * y / size)    # f7 → ff
        draw.line([(0, y), (size, y)], fill=(r, g, b))

    # 둥근 모서리 마스크 (Android adaptive icon 규격)
    radius = size // 8
    mask = Image.new("L", (size, size), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.rounded_rectangle((0, 0, size, size), radius=radius, fill=255)

    # 텍스트 "Si" 중앙에 그리기
    try:
        font = ImageFont.truetype("arialbd.ttf", size // 2)
    except Exception:
        try:
            font = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", size // 2)
        except Exception:
            font = ImageFont.load_default()

    text = "Si"
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    x = (size - tw) // 2 - bbox[0]
    y = (size - th) // 2 - bbox[1]

    # 텍스트 그림자
    draw.text((x + size // 80, y + size // 80), text, fill=(0, 0, 0, 100), font=font)
    # 본문 흰 글자
    draw.text((x, y), text, fill="white", font=font)

    # 마스크 적용
    final = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    final.paste(img, (0, 0), mask)

    path = os.path.join(OUT, filename)
    final.save(path, "PNG")
    print(f"Created: {path} ({size}x{size})")


if __name__ == "__main__":
    make_icon(192, "icon-192.png")
    make_icon(512, "icon-512.png")
    make_icon(180, "apple-touch-icon.png")
    make_icon(32, "favicon-32.png")
    print("All icons created.")
