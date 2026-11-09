"""
生成屏幕使用时间图标（.ico 多尺寸 16/32/48/256）
靛蓝色圆角背景 + 白色时钟柱状图 + Marvis角标
"""
import os
import math
from pathlib import Path
from PIL import Image, ImageDraw

PROJECT_DIR = Path(__file__).parent
MARVIS_BASE = Path(r"D:\Program Files\Tencent\Marvis")

def find_marvis_logo():
    candidates = []
    for root, dirs, files in os.walk(str(MARVIS_BASE)):
        for f in files:
            if f.lower().endswith(('.png', '.ico', '.jpg', '.jpeg')):
                name_lower = f.lower()
                if 'avatar' in name_lower and 'marvis' in name_lower:
                    candidates.append(os.path.join(root, f))
    return candidates[0] if candidates else None

def generate_icon_image(size):
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    bg_color = (75, 72, 234, 255)
    radius = max(2, size // 6)

    draw.rounded_rectangle(
        [(1, 1), (size-2, size-2)],
        radius=radius,
        fill=bg_color
    )

    cx, cy = size * 0.4, size * 0.42
    clock_r = size * 0.22
    line_w = max(1, size // 80)

    draw.ellipse(
        [cx - clock_r, cy - clock_r, cx + clock_r, cy + clock_r],
        outline='white', width=line_w
    )

    angle_h = -60 * math.pi / 180
    h_len = clock_r * 0.5
    end_x = cx + h_len * math.sin(angle_h)
    end_y = cy - h_len * math.cos(angle_h)
    draw.line([cx, cy, end_x, end_y], fill='white', width=line_w + 1)

    angle_m = 60 * math.pi / 180
    m_len = clock_r * 0.7
    end_x2 = cx + m_len * math.sin(angle_m)
    end_y2 = cy - m_len * math.cos(angle_m)
    draw.line([cx, cy, end_x2, end_y2], fill='white', width=line_w)

    dot_r = max(1, size // 50)
    draw.ellipse([cx-dot_r, cy-dot_r, cx+dot_r, cy+dot_r], fill='white')

    bar_x = int(size * 0.62)
    bar_bottom = int(size * 0.78)
    bar_width = max(1, size // 28)
    bar_gap = max(1, size // 40)
    bars_data = [
        (bar_x, bar_bottom - int(size * 0.18), bar_bottom),
        (bar_x + bar_width + bar_gap, bar_bottom - int(size * 0.28), bar_bottom),
        (bar_x + 2 * (bar_width + bar_gap), bar_bottom - int(size * 0.22), bar_bottom),
    ]
    for bx, by1, by2 in bars_data:
        draw.rectangle([bx, by1, bx + bar_width, by2], fill='white')

    # Marvis角标
    logo_path = find_marvis_logo()
    if logo_path:
        try:
            logo = Image.open(logo_path).convert('RGBA')
            badge_size = max(4, int(size * 0.28))

            badge_bg = Image.new('RGBA', (badge_size + 4, badge_size + 4), (0, 0, 0, 0))
            badge_draw = ImageDraw.Draw(badge_bg)
            badge_draw.ellipse([0, 0, badge_size + 3, badge_size + 3], fill='white')

            logo_resized = logo.resize((badge_size-2, badge_size-2), Image.LANCZOS)
            badge_bg.paste(logo_resized, (3, 3), logo_resized)

            pos_x = size - badge_size - 5 - (4 if size >= 48 else 1)
            pos_y = size - badge_size - 5 - (4 if size >= 48 else 1)
            img.paste(badge_bg, (pos_x, pos_y), badge_bg)
        except Exception as e:
            print(f"  角标加载失败: {e}")

    return img

def main():
    sizes = [16, 32, 48, 256]
    images = []

    for s in sizes:
        print(f"生成 {s}x{s} 图标...")
        img = generate_icon_image(s)
        images.append(img)

    output_path = PROJECT_DIR / "icon.ico"

    images[0].save(
        str(output_path),
        format='ICO',
        sizes=[(sz, sz) for sz in sizes],
        append_images=images[1:]
    )

    verify = Image.open(str(output_path))
    print(f"图标已生成: {output_path}")
    print(f"尺寸: {verify.info.get('sizes', 'unknown')}")
    print(f"文件大小: {output_path.stat().st_size} bytes")

if __name__ == '__main__':
    main()
