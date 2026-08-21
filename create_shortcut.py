import os
import sys

def create_desktop_shortcut():
    desktop = os.path.expandvars(r"%USERPROFILE%\Desktop")
    shortcut_path = os.path.join(desktop, "Clash Mi 智能守护.lnk")
    current_dir = os.path.dirname(os.path.abspath(__file__))
    target_path = os.path.join(current_dir, "启动桌面应用程序.bat")
    ico_path = os.path.join(current_dir, "app.ico")

    vbs_content = f'''
Set oWS = WScript.CreateObject("WScript.Shell")
sLinkFile = "{shortcut_path}"
Set oLink = oWS.CreateShortcut(sLinkFile)
oLink.TargetPath = "{target_path}"
oLink.WorkingDirectory = "{current_dir}"
oLink.Description = "Clash Mi Gemini 智能守护控制台"
oLink.IconLocation = "{ico_path},0"
oLink.Save
'''
    vbs_file = os.path.join(current_dir, "_temp_shortcut.vbs")
    with open(vbs_file, "w", encoding="gbk", errors="replace") as f:
        f.write(vbs_content)
    
    os.system(f'cscript //nologo "{vbs_file}"')
    if os.path.exists(vbs_file):
        os.remove(vbs_file)
    print(f"桌面快捷方式已成功更新专属图标: {shortcut_path}")

if __name__ == "__main__":
    create_desktop_shortcut()
