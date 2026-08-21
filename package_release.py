import os
import zipfile

def make_release_zip():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    zip_name = "Clash-Gemini-Guardian-v1.0.0.zip"
    zip_path = os.path.join(base_dir, zip_name)

    include_files = [
        "app.ico",
        "app_icon.png",
        "config.json",
        "create_shortcut.py",
        "gemini_clash_guardian.py",
        "gui_app.py",
        "LICENSE",
        "README.md",
        "requirements.txt",
        "启动桌面应用程序.bat",
        "创建桌面快捷方式.bat",
        "一键测试并优选节点.bat",
        "启动后台自动守护.bat"
    ]

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # 添加主文件
        for f in include_files:
            fp = os.path.join(base_dir, f)
            if os.path.exists(fp):
                zf.write(fp, arcname=os.path.join("ClashMi智能守护", f))

        # 添加 web 目录
        web_dir = os.path.join(base_dir, "web")
        if os.path.exists(web_dir):
            for root, dirs, files in os.walk(web_dir):
                for file in files:
                    full_path = os.path.join(root, file)
                    rel_path = os.path.relpath(full_path, base_dir)
                    zf.write(full_path, arcname=os.path.join("ClashMi智能守护", rel_path))

    print(f"开源发布包已成功打包: {zip_path}")

if __name__ == "__main__":
    make_release_zip()
