#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成 Clash Mi Gemini 智能守护专属 Fluent 3D 风格高清应用图标与 ICO 文件
"""

import os
import math
from PIL import Image, ImageDraw, ImageFilter

def create_fluent_icon(size=512):
    # 创建高分辨率画布 (带透明通道)
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 1. 基础圆角矩形背景 (Squircle)
    margin = int(size * 0.06)
    bg_box = [margin, margin, size - margin, size - margin]
    radius = int(size * 0.22)

    # 创建深空靛蓝到午夜黑的渐变底座
    bg_mask = Image.new("L", (size, size), 0)
    bg_draw = ImageDraw.Draw(bg_mask)
    bg_draw.rounded_rectangle(bg_box, radius=radius, fill=255)

    base_gradient = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    for y in range(size):
        ratio = y / size
        # 从深靛蓝 (15, 23, 42) 到 午夜蓝紫 (30, 27, 75)
        r = int(15 + ratio * 20)
        g = int(23 + ratio * 18)
        b = int(55 + ratio * 60)
        for x in range(size):
            base_gradient.putpixel((x, y), (r, g, b, 255))

    # 应用底座圆角蒙版
    base_bg = Image.composite(base_gradient, Image.new("RGBA", (size, size), (0,0,0,0)), bg_mask)

    # 2. 底座边缘微光 (Cyan Glow border)
    border_img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    b_draw = ImageDraw.Draw(border_img)
    b_draw.rounded_rectangle(bg_box, radius=radius, outline=(59, 130, 246, 120), width=int(size * 0.015))
    base_bg = Image.alpha_composite(base_bg, border_img)

    # 3. 绘制中心科技感守护盾牌 (Translucent Glowing Shield)
    shield_img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    s_draw = ImageDraw.Draw(shield_img)
    
    cx, cy = size // 2, int(size * 0.52)
    sw = int(size * 0.28)  # 半宽
    sh_top = cy - int(size * 0.26)
    sh_mid = cy + int(size * 0.05)
    sh_bot = cy + int(size * 0.28)

    shield_points = [
        (cx - sw, sh_top),
        (cx + sw, sh_top),
        (cx + sw, sh_mid),
        (cx, sh_bot),
        (cx - sw, sh_mid)
    ]

    # 盾牌主体半透明渐变 (Electric Cyan to Deep Blue)
    s_draw.polygon(shield_points, fill=(6, 182, 212, 140))
    
    # 盾牌发光轮廓
    s_draw.line(shield_points + [shield_points[0]], fill=(52, 211, 153, 230), width=int(size * 0.025))

    # 4. 盾心 Gemini 璀璨四芒星 AI 核心 (Glowing 4-pointed Star)
    star_img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    st_draw = ImageDraw.Draw(star_img)

    star_cx, star_cy = cx, cy - int(size * 0.02)
    star_r_outer = int(size * 0.16)
    star_r_inner = int(size * 0.035)

    star_pts = []
    for i in range(8):
        angle = i * math.pi / 4
        r = star_r_outer if i % 2 == 0 else star_r_inner
        px = star_cx + r * math.cos(angle)
        py = star_cy + r * math.sin(angle)
        star_pts.append((px, py))

    # 绘制纯白与高亮极光青四芒星
    st_draw.polygon(star_pts, fill=(255, 255, 255, 255))

    # 添加星芒发光光晕 (Glow Filter)
    star_glow = star_img.filter(ImageFilter.GaussianBlur(radius=int(size * 0.03)))
    
    # 5. 绘制网络轨道与环绕光点 (Network Orbits & Energy Nodes)
    orbit_img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    o_draw = ImageDraw.Draw(orbit_img)

    # 绘制两个发光卫星节点
    node1_pos = (cx - int(size * 0.18), cy - int(size * 0.16))
    node2_pos = (cx + int(size * 0.18), cy - int(size * 0.16))
    node3_pos = (cx, cy + int(size * 0.20))

    for nx, ny in [node1_pos, node2_pos, node3_pos]:
        o_draw.ellipse([nx-6, ny-6, nx+6, ny+6], fill=(52, 211, 153, 255))
        # 连线到核心
        o_draw.line([(nx, ny), (star_cx, star_cy)], fill=(59, 130, 246, 160), width=3)

    # 6. 图层复合 (Compositing)
    final_img = Image.alpha_composite(base_bg, shield_img)
    final_img = Image.alpha_composite(final_img, orbit_img)
    final_img = Image.alpha_composite(final_img, star_glow)
    final_img = Image.alpha_composite(final_img, star_img)

    return final_img

def main():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    web_dir = os.path.join(current_dir, "web")
    os.makedirs(web_dir, exist_ok=True)

    print("[*] 正在渲染 Fluent 3D 专属应用图标...")
    master_icon = create_fluent_icon(size=512)

    # 1. 保存高清原图
    png_path = os.path.join(current_dir, "app_icon.png")
    master_icon.save(png_path, format="PNG")
    print(f"  -> 已生成高清 PNG 图标: {png_path}")

    # 2. 保存 Web 端图标
    web_png_path = os.path.join(web_dir, "icon.png")
    web_icon = master_icon.resize((256, 256), Image.Resampling.LANCZOS)
    web_icon.save(web_png_path, format="PNG")
    print(f"  -> 已生成 Web 图标: {web_png_path}")

    # 3. 保存 Windows 多尺寸 ICO 图标 (16, 32, 48, 64, 128, 256)
    ico_path = os.path.join(current_dir, "app.ico")
    web_favicon_path = os.path.join(web_dir, "favicon.ico")

    sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    master_icon.save(ico_path, format="ICO", sizes=sizes)
    master_icon.save(web_favicon_path, format="ICO", sizes=sizes)
    print(f"  -> 已生成 Windows 标准多尺寸 ICO 图标: {ico_path}")
    print(f"  -> 已生成 Web Favicon: {web_favicon_path}")

    print("\n[✓] 全套图标文件生成完成！")

if __name__ == "__main__":
    main()
