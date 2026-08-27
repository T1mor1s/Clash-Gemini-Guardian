#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Clash Mi 智能节点体检与自动优选控制台 (Desktop App + System Tray)
---------------------------------------------------------------
特性：
1. 单实例互斥保护：多次点击快捷方式仅会唤起已有界面，绝不会重复启动或在托盘产生多个图标。
2. 现代化可视化 Web 独立窗口客户端 (带专属 Fluent 3D 图标)。
3. 后台 HTTP API 微服务与 Google Gemini 深度测速引擎。
4. Windows 任务栏系统托盘常驻与右键菜单（支持安全退出与托盘图标自动清理）。
5. 支持 PyInstaller 一键编译为独立单文件 EXE。
"""

import os
import sys
import io
import json
import time
import atexit
import signal
import ctypes
import threading
import subprocess
import webbrowser
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib import parse

from gemini_clash_guardian import ClashMiGuardian, show_windows_toast

def safe_reconfigure_io():
    try:
        if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        if sys.stderr and hasattr(sys.stderr, 'reconfigure'):
            sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

safe_reconfigure_io()

PORT = 18989

# 路径兼容：支持 Python 源码运行与 PyInstaller 单文件 EXE 模式
if getattr(sys, 'frozen', False):
    BASE_DIR = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
    RUNTIME_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    RUNTIME_DIR = BASE_DIR

WEB_DIR = os.path.join(BASE_DIR, "web")
USER_DATA_DIR = os.path.join(RUNTIME_DIR, "web_cache")
ICO_PATH = os.path.join(BASE_DIR, "app.ico")
CONFIG_PATH = os.path.join(RUNTIME_DIR, "config.json")
MUTEX_NAME = "Global\\ClashMiGeminiGuardian_SingleInstance_Mutex_v1"

global_tray_instance = None

def cleanup_tray_icon():
    global global_tray_instance
    if global_tray_instance and hasattr(global_tray_instance, 'hwnd'):
        try:
            import win32gui
            nid = (global_tray_instance.hwnd, global_tray_instance.notify_id)
            win32gui.Shell_NotifyIcon(win32gui.NIM_DELETE, nid)
        except Exception:
            pass

atexit.register(cleanup_tray_icon)

class AppState:
    def __init__(self):
        self.guardian = ClashMiGuardian(CONFIG_PATH)
        self.guardian_enabled = True
        self.cached_nodes = []
        self.active_node = None
        self.active_group = "节点选择"
        self.active_delay = 0
        self.active_status = "OK"
        self.log_queue = []
        self.lock = threading.Lock()
        self.guardian_thread = None
        self.is_running = True

    def add_log(self, msg, level="info"):
        with self.lock:
            self.log_queue.append({"msg": msg, "level": level, "time": time.time()})
            if len(self.log_queue) > 100:
                self.log_queue.pop(0)

    def pop_logs(self):
        with self.lock:
            logs = list(self.log_queue)
            self.log_queue.clear()
            return logs

state = AppState()

class GuardianAPIHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=WEB_DIR, **kwargs)

    def log_message(self, format, *args):
        pass

    def send_json(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = parse.urlparse(self.path)
        path = parsed.path

        if path == "/api/status":
            ok, ver = state.guardian.test_connection()
            ok_conf, conf = state.guardian._api_request("/configs")
            clash_mode = (conf.get("mode", "rule") if ok_conf and isinstance(conf, dict) else "rule").lower()
            _, selector_groups = state.guardian.get_proxies_data()
            
            active_node = None
            active_group = "GLOBAL" if clash_mode == "global" else "节点选择"

            if selector_groups:
                if clash_mode == "global" and "GLOBAL" in selector_groups:
                    active_node = selector_groups["GLOBAL"].get("now")
                    active_group = "GLOBAL"
                elif "节点选择" in selector_groups:
                    active_node = selector_groups["节点选择"].get("now")
                    active_group = "节点选择"
                else:
                    for kw in state.guardian.target_keywords:
                        for gname, ginfo in selector_groups.items():
                            if kw in gname:
                                active_node = ginfo.get("now")
                                active_group = gname
                                break
                        if active_node:
                            break

            state.active_node = active_node or state.active_node
            state.active_group = active_group
            state.clash_mode = clash_mode

            self.send_json({
                "clash_online": ok,
                "clash_version": ver,
                "clash_mode": state.clash_mode,
                "active_node": state.active_node,
                "active_group": state.active_group,
                "active_delay": state.active_delay,
                "active_status": state.active_status,
                "guardian_running": state.guardian_enabled,
                "logs": state.pop_logs()
            })
            return

        elif path == "/api/nodes":
            if not state.cached_nodes:
                real_nodes, _ = state.guardian.get_proxies_data()
                if real_nodes:
                    state.cached_nodes = [{"name": n, "delay": 99999, "status": "UNKNOWN", "desc": "等待体检"} for n in real_nodes]

            self.send_json({
                "ok": True,
                "nodes": state.cached_nodes,
                "active_node": state.active_node
            })
            return

        elif path == "/api/rules/status":
            r_status = state.guardian.get_rules_status()
            self.send_json(r_status)
            return

        super().do_GET()

    def do_POST(self):
        parsed = parse.urlparse(self.path)
        path = parsed.path
        length = int(self.headers.get('Content-Length', 0))
        body_data = {}
        if length > 0:
            try:
                body_data = json.loads(self.rfile.read(length).decode('utf-8'))
            except Exception:
                pass

        if path == "/api/benchmark":
            real_nodes, selector_groups = state.guardian.get_proxies_data()
            if not real_nodes:
                self.send_json({"ok": False, "msg": "未发现代理节点"})
                return

            state.add_log(f"开始对 {len(real_nodes)} 个节点进行全量 Gemini 深度体检...", "info")
            results = state.guardian.benchmark_all_nodes(real_nodes)
            state.cached_nodes = results

            best_node = None
            for item in results:
                if item["status"] == "OK":
                    best_node = item
                    break

            if best_node:
                state.active_node = best_node["name"]
                state.active_delay = best_node["delay"]
                state.active_status = "OK"
                
                switched = state.guardian.switch_all_active_groups(best_node["name"])
                show_windows_toast("Clash Mi 智能优选", f"已切换至最优节点: {best_node['name']} ({best_node['delay']}ms)")
                state.add_log(f"体检完成，已全量同步切换策略组至: {best_node['name']} ({best_node['delay']}ms)，并已清理旧长连接", "success")
            else:
                state.add_log("警告: 全量体检未发现完全支持 Gemini 的节点！", "warn")

            self.send_json({
                "ok": True,
                "nodes": state.cached_nodes,
                "best_node": best_node
            })
            return

        elif path == "/api/switch":
            target_name = body_data.get("name")
            if not target_name:
                self.send_json({"ok": False, "msg": "缺少节点名称"})
                return

            switched_groups = state.guardian.switch_all_active_groups(target_name)
            if switched_groups:
                state.active_node = target_name
                probe_res = state.guardian.probe_node(target_name)
                state.active_delay = probe_res["delay"]
                state.active_status = probe_res["status"]
                state.add_log(f"已全量同步切换策略组至: {target_name} ({probe_res['desc']})，并刷新长连接", "success")
                show_windows_toast("Clash Mi 节点切换", f"已切换至: {target_name}")
                self.send_json({"ok": True, "switched_groups": switched_groups})
            else:
                self.send_json({"ok": False, "msg": "未找到可切换的策略组"})
            return

        elif path == "/api/guardian/toggle":
            enabled = body_data.get("enabled", True)
            state.guardian_enabled = enabled
            state.add_log(f"后台自动守护已{'开启' if enabled else '暂停'}", "info")
            self.send_json({"ok": True, "guardian_running": state.guardian_enabled})
            return

        elif path == "/api/rules/inject":
            target_group = body_data.get("target_group", "节点选择")
            ok, msg = state.guardian.inject_gemini_rules(target_group=target_group)
            if ok:
                state.add_log(f"已成功向 Clash 注入 Gemini 专属防漏规则 (锁死策略组: {target_group})", "success")
                show_windows_toast("Clash 规则自动化", "已成功注入 Gemini 专属防漏分流规则！")
            else:
                state.add_log(f"注入规则失败: {msg}", "error")
            self.send_json({"ok": ok, "msg": msg, "rules_status": state.guardian.get_rules_status()})
            return

        elif path == "/api/rules/restore":
            ok, msg = state.guardian.restore_gemini_rules()
            if ok:
                state.add_log("已成功从 Clash 移除 Gemini 专属规则并恢复原状", "info")
                show_windows_toast("Clash 规则自动化", "已恢复原配置规则")
            else:
                state.add_log(f"恢复规则失败: {msg}", "error")
            self.send_json({"ok": ok, "msg": msg, "rules_status": state.guardian.get_rules_status()})
            return

        self.send_json({"ok": False, "msg": "未知的 API 端点"}, code=404)

def run_guardian_background():
    """后台守护监控线程"""
    interval = state.guardian.config.get("daemon_interval_seconds", 180)
    time.sleep(3)

    while state.is_running:
        try:
            if state.guardian_enabled:
                _, selector_groups = state.guardian.get_proxies_data()
                active_node = None
                if selector_groups:
                    for kw in state.guardian.target_keywords:
                        for gname, ginfo in selector_groups.items():
                            if kw in gname:
                                active_node = ginfo.get("now")
                                break
                        if active_node:
                            break
                    if not active_node and "GLOBAL" in selector_groups:
                        active_node = selector_groups["GLOBAL"].get("now")

                if active_node:
                    state.active_node = active_node
                    probe_res = state.guardian.probe_node(active_node)
                    state.active_delay = probe_res["delay"]
                    state.active_status = probe_res["status"]

                    if probe_res["status"] == "OK" and probe_res["delay"] < 800:
                        state.add_log(f"心跳正常: 当前节点 [{active_node}] Gemini 延迟 {probe_res['delay']}ms", "info")
                    else:
                        state.add_log(f"⚠️ 警告: 当前节点 [{active_node}] 状态恶化 ({probe_res['desc']})，触发自动优选...", "warn")
                        best = state.guardian.run_optimization(auto_switch=True, send_notify=True)
                        if best:
                            state.active_node = best["name"]
                            state.active_delay = best["delay"]
                            state.active_status = best["status"]
                            state.add_log(f"已自动恢复并切换到节点: {best['name']} ({best['delay']}ms)", "success")
        except Exception as e:
            state.add_log(f"守护循环异常: {e}", "error")

        for _ in range(interval):
            if not state.is_running:
                break
            time.sleep(1)

def open_ui_window():
    """以独立桌面 App 窗口或默认浏览器打开界面"""
    url = f"http://127.0.0.1:{PORT}"
    os.makedirs(USER_DATA_DIR, exist_ok=True)

    edge_paths = [
        os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"
    ]
    chrome_paths = [
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe")
    ]

    for p in edge_paths + chrome_paths:
        if os.path.exists(p):
            try:
                cmd = f'"{p}" --app={url} --user-data-dir="{USER_DATA_DIR}" --window-size=1180,820 --window-position=200,100'
                subprocess.Popen(cmd, shell=True)
                return
            except Exception:
                pass

    webbrowser.open(url)

def run_system_tray():
    global global_tray_instance
    try:
        import win32gui
        import win32con

        class SysTray:
            def __init__(self):
                self.msg_taskbar_created = win32gui.RegisterWindowMessage("TaskbarCreated")
                win32gui.InitCommonControls()
                self.hinst = win32gui.GetModuleHandle(None)
                
                wnd_class = win32gui.WNDCLASS()
                wnd_class.hInstance = self.hinst
                wnd_class.lpszClassName = "ClashMiGuardianTray"
                wnd_class.lpfnWndProc = self.wnd_proc
                self.class_atom = win32gui.RegisterClass(wnd_class)
                
                self.hwnd = win32gui.CreateWindow(
                    self.class_atom, "ClashMiGuardian", 0, 0, 0, 0, 0, 0, 0, self.hinst, None
                )
                self.notify_id = 1001

                if os.path.exists(ICO_PATH):
                    try:
                        self.hicon = win32gui.LoadImage(
                            0, ICO_PATH, win32con.IMAGE_ICON, 0, 0,
                            win32con.LR_LOADFROMFILE | win32con.LR_DEFAULTSIZE
                        )
                    except Exception:
                        self.hicon = win32gui.LoadIcon(0, win32con.IDI_APPLICATION)
                else:
                    self.hicon = win32gui.LoadIcon(0, win32con.IDI_APPLICATION)
                
                nid = (self.hwnd, self.notify_id, win32gui.NIF_ICON | win32gui.NIF_MESSAGE | win32gui.NIF_TIP,
                       win32con.WM_USER + 20, self.hicon, "Clash Mi Gemini 智能守护")
                win32gui.Shell_NotifyIcon(win32gui.NIM_ADD, nid)

            def wnd_proc(self, hwnd, msg, wparam, lparam):
                if msg == win32con.WM_USER + 20:
                    if lparam == win32con.WM_LBUTTONUP or lparam == win32con.WM_LBUTTONDBLCLK:
                        open_ui_window()
                    elif lparam == win32con.WM_RBUTTONUP:
                        self.show_menu()
                elif msg == self.msg_taskbar_created:
                    nid = (self.hwnd, self.notify_id, win32gui.NIF_ICON | win32gui.NIF_MESSAGE | win32gui.NIF_TIP,
                           win32con.WM_USER + 20, self.hicon, "Clash Mi Gemini 智能守护")
                    win32gui.Shell_NotifyIcon(win32gui.NIM_ADD, nid)
                elif msg == win32con.WM_DESTROY:
                    nid = (self.hwnd, self.notify_id)
                    win32gui.Shell_NotifyIcon(win32gui.NIM_DELETE, nid)
                    win32gui.PostQuitMessage(0)
                return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

            def show_menu(self):
                menu = win32gui.CreatePopupMenu()
                win32gui.AppendMenu(menu, win32con.MF_STRING, 101, "🖥️ 打开控制面板")
                win32gui.AppendMenu(menu, win32con.MF_STRING, 102, "🚀 一键体检与最优切换")
                daemon_status_text = "🛡️ 暂停自动守护" if state.guardian_enabled else "🛡️ 开启自动守护"
                win32gui.AppendMenu(menu, win32con.MF_STRING, 103, daemon_status_text)
                win32gui.AppendMenu(menu, win32con.MF_SEPARATOR, 0, "")
                win32gui.AppendMenu(menu, win32con.MF_STRING, 104, "❌ 退出程序")

                pos = win32gui.GetCursorPos()
                win32gui.SetForegroundWindow(self.hwnd)
                cmd = win32gui.TrackPopupMenu(
                    menu, win32con.TPM_LEFTALIGN | win32con.TPM_RETURNCMD,
                    pos[0], pos[1], 0, self.hwnd, None
                )
                win32gui.PostMessage(self.hwnd, win32con.WM_NULL, 0, 0)

                if cmd == 101:
                    open_ui_window()
                elif cmd == 102:
                    threading.Thread(target=lambda: state.guardian.run_optimization(auto_switch=True, send_notify=True), daemon=True).start()
                elif cmd == 103:
                    state.guardian_enabled = not state.guardian_enabled
                    state.add_log(f"托盘切换：后台自动守护已{'开启' if state.guardian_enabled else '暂停'}", "info")
                    show_windows_toast("Clash Mi 守护状态变更", f"后台自动守护已{'开启' if state.guardian_enabled else '暂停'}")
                elif cmd == 104:
                    state.is_running = False
                    cleanup_tray_icon()
                    try:
                        win32gui.DestroyWindow(self.hwnd)
                    except Exception:
                        pass
                    os._exit(0)

        tray = SysTray()
        global_tray_instance = tray
        win32gui.PumpMessages()
    except Exception as e:
        print(f"[!] 托盘启动异常，降级为常规后台模式: {e}")
        while state.is_running:
            time.sleep(1)

def main():
    kernel32 = ctypes.windll.kernel32
    mutex = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    last_error = kernel32.GetLastError()
    
    if last_error == 183:
        open_ui_window()
        sys.exit(0)

    print(f"[*] 正在启动 Clash Mi 智能守护 Web 桌面客户端 (http://127.0.0.1:{PORT})...")
    
    server = HTTPServer(('127.0.0.1', PORT), GuardianAPIHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    guardian_t = threading.Thread(target=run_guardian_background, daemon=True)
    guardian_t.start()

    time.sleep(0.5)
    open_ui_window()

    run_system_tray()

if __name__ == "__main__":
    main()
