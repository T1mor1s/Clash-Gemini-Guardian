import os
import sys
import subprocess
import shutil

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

def build_standalone_exe():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    dist_dir = os.path.join(base_dir, "dist")
    exe_name = "Clash-Gemini-Guardian"

    print("[*] 开始使用 PyInstaller 编译为单文件绿色版 EXE...")

    cmd = [
        "pyinstaller",
        "--noconsole",
        "--onefile",
        "--icon=app.ico",
        "--add-data", "web;web",
        "--add-data", "app.ico;.",
        "--name", exe_name,
        "--clean",
        "gui_app.py"
    ]

    subprocess.run(cmd, cwd=base_dir, check=True)

    src_exe = os.path.join(dist_dir, f"{exe_name}.exe")
    target_exe = os.path.join(base_dir, f"{exe_name}.exe")
    if os.path.exists(src_exe):
        shutil.copy2(src_exe, target_exe)
        print(f"\n[OK] 独立单文件 EXE 已生成至根目录: {target_exe}")
        print("  -> 尺寸大小: ", os.path.getsize(target_exe) // (1024 * 1024), "MB")
        print("  -> 用户下载此单一 exe 文件即可双击直接运行，无需 Python 环境！")

if __name__ == "__main__":
    build_standalone_exe()
