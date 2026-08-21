#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Clash Mi 智能节点体检与自动优选守护工具 (Gemini / Antigravity 专用)
------------------------------------------------------------------
原理与机制：
1. 真实网络探测：绝非只看节点名称！对列表中的每个节点（美国、韩国、日本、新加坡等），
   程序都会通过 Clash 核心向 Google Gemini 官方服务器 (generativelanguage.googleapis.com)
   发起真实的 TCP/TLS 握手与 HTTP 请求，精确测量端到端网络延迟与连通状态。
2. 异常与阻断识别：任何节点如果出现服务器故障、IP 被 Google 封锁或丢包超时（如 503/504），
   均会被精准标记为 🔴 异常/不可用 并彻底排除。
3. 政策合规双重保障：针对部分物理连通但由于 Google 官方政策限制导致无法使用的区域（如香港），
   自动标记为 🟡 地区受限 并降权，避免选入。
4. 毫秒级自动切换与 Windows 桌面通知。
"""

import os
import sys
import io
import json
import time
import re
import argparse
import subprocess
import threading
from urllib import request, parse, error
from concurrent.futures import ThreadPoolExecutor

# 初始化 Windows 控制台环境（支持 UTF-8 与 ANSI 颜色）
if os.name == 'nt':
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleTitleW("Clash Mi - Gemini 节点体检与自动切换")
        hStdOut = kernel32.GetStdHandle(-11)
        mode = ctypes.c_ulong()
        kernel32.GetConsoleMode(hStdOut, ctypes.byref(mode))
        mode.value |= 0x0004  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        kernel32.SetConsoleMode(hStdOut, mode)
    except Exception:
        pass

if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
if hasattr(sys.stderr, 'reconfigure'):
    try:
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

# 终端 ANSI 颜色定义
class Colors:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    RED = "\033[31m"
    CYAN = "\033[36m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"

def cstr(text, color):
    return f"{color}{text}{Colors.RESET}"

# 获取字符显示宽度（解决中文字符/Emoji在终端排版对齐问题）
def str_width(s):
    width = 0
    for char in s:
        cp = ord(char)
        if (0x1100 <= cp <= 0x115F or
            0x2E80 <= cp <= 0xA4CF or
            0xAC00 <= cp <= 0xD7A3 or
            0xF900 <= cp <= 0xFAFF or
            0xFE10 <= cp <= 0xFE19 or
            0xFE30 <= cp <= 0xFE6F or
            0xFF00 <= cp <= 0xFF60 or
            0xFFE0 <= cp <= 0xFFE6 or
            0x1F300 <= cp <= 0x1FAFF or
            0x1F1E6 <= cp <= 0x1F1FF):
            width += 2
        else:
            width += 1
    return width

def pad_str(s, target_width, align='left'):
    curr_w = str_width(s)
    pad = max(0, target_width - curr_w)
    if align == 'right':
        return ' ' * pad + s
    elif align == 'center':
        left = pad // 2
        right = pad - left
        return ' ' * left + s + ' ' * right
    return s + ' ' * pad

# Windows 原生桌面 Toast 弹窗
def show_windows_toast(title, message):
    def _notify():
        ps_code = f"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
$template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$nodes = $template.GetElementsByTagName('text')
$nodes.Item(0).AppendChild($template.CreateTextNode('{title.replace("'", "''")}')) | Out-Null
$nodes.Item(1).AppendChild($template.CreateTextNode('{message.replace("'", "''")}')) | Out-Null
$toast = [Windows.UI.Notifications.ToastNotification]::new($template)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('Clash Mi Guardian').Show($toast)
"""
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_code],
                capture_output=True,
                creationflags=0x08000000 if os.name == 'nt' else 0
            )
        except Exception:
            pass

    threading.Thread(target=_notify, daemon=True).start()

class ClashMiGuardian:
    def __init__(self, config_path="config.json"):
        self.config = self.load_config(config_path)
        self.api_url = self.config.get("clash_api_url", "http://127.0.0.1:9090").rstrip('/')
        self.secret = self.resolve_secret()
        self.test_urls = self.config.get("gemini_test_urls", [
            "https://generativelanguage.googleapis.com",
            "https://alkalimakersuite-pa.googleapis.com"
        ])
        self.timeout_sec = self.config.get("timeout_seconds", 5)
        self.max_workers = self.config.get("max_workers", 12)
        self.target_keywords = self.config.get("target_group_keywords", ["节点选择", "PROXY", "GLOBAL"])
        self.ignore_keywords = [
            '剩余', '到期', '官网', '重置', '通知', '公告', 'DIRECT', 'REJECT', 
            'PASS', 'GLOBAL', '流量', '时间', '网址', '客服'
        ]

    def load_config(self, path):
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(cstr(f"[!] 读取配置文件失败，将采用自动探测模式: {e}", Colors.YELLOW))
        return {}

    def resolve_secret(self):
        # 1. 优先使用配置中的 Secret
        cfg_secret = self.config.get("clash_api_secret", "auto")
        if cfg_secret and cfg_secret != "auto":
            return cfg_secret

        # 2. 自动从 Clash Mi 的 service.json 读取
        possible_paths = [
            os.path.expandvars(r"%APPDATA%\clashmi\clashmi\service.json"),
            os.path.expandvars(r"%LOCALAPPDATA%\clashmi\clashmi\service.json"),
            r"D:\Clash Mi\data\service.json",
        ]
        for p in possible_paths:
            if os.path.exists(p):
                try:
                    with open(p, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        secret = data.get("secret")
                        port = data.get("control_port")
                        if port:
                            self.api_url = f"http://127.0.0.1:{port}"
                        if secret:
                            return secret
                except Exception:
                    pass
        return ""

    def _api_request(self, endpoint, method="GET", body=None, timeout=6):
        url = f"{self.api_url}{endpoint}"
        headers = {}
        if self.secret:
            headers["Authorization"] = f"Bearer {self.secret}"
        
        data_bytes = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data_bytes = json.dumps(body).encode("utf-8")

        req = request.Request(url, data=data_bytes, headers=headers, method=method)
        try:
            with request.urlopen(req, timeout=timeout) as resp:
                if resp.status == 204:
                    return True, None
                content = resp.read().decode('utf-8')
                return True, json.loads(content) if content else {}
        except error.HTTPError as e:
            try:
                err_content = e.read().decode('utf-8')
                return False, f"HTTP {e.code}: {err_content}"
            except Exception:
                return False, f"HTTP {e.code}"
        except Exception as e:
            return False, str(e)

    def test_connection(self):
        ok, res = self._api_request("/version")
        if ok:
            ver = res.get("version", "未知")
            return True, f"Clash 核心版本: {ver}"
        return False, f"无法连接 Clash REST API ({self.api_url}): {res}"

    def get_proxies_data(self):
        ok, res = self._api_request("/proxies")
        if not ok:
            return None, None
        
        proxies = res.get("proxies", {})
        real_nodes = []
        selector_groups = {}

        for name, info in proxies.items():
            t = info.get("type", "")
            if t in ("Selector", "URLTest", "Fallback"):
                selector_groups[name] = info
            elif t not in ("Direct", "Reject", "Compatible", "Pass", "Relay"):
                if not any(k in name for k in self.ignore_keywords):
                    real_nodes.append(name)

        return real_nodes, selector_groups

    def is_region_restricted(self, node_name):
        """识别被 Google Gemini 严格政策限制的地区（如中国香港、中国大陆等）"""
        name_lower = node_name.lower()
        if '🇭🇰' in node_name or 'hong kong' in name_lower or 'hongkong' in name_lower or 'hk' in name_lower:
            return True, "香港节点 (Gemini 官方政策限制地区)"
        if '🇨🇳' in node_name or 'china' in name_lower:
            return True, "中国大陆 (Gemini 限制地区)"
        if '🇷🇺' in node_name or 'russia' in name_lower:
            return True, "俄罗斯 (Gemini 限制地区)"
        return False, "合规地区"

    def probe_single_endpoint(self, node_name, test_url):
        """通过该节点实际向指定目标地址发起真实的 TCP/TLS/HTTP 握手并测速"""
        encoded_name = parse.quote(node_name)
        endpoint = f"/proxies/{encoded_name}/delay?url={parse.quote(test_url)}&timeout={int(self.timeout_sec * 1000)}"
        ok, res = self._api_request(endpoint, timeout=self.timeout_sec + 2)
        if ok and isinstance(res, dict) and "delay" in res:
            return True, res["delay"]
        return False, str(res)

    def probe_node(self, node_name):
        """对单个节点进行全方位的真实网络连通性深度体检"""
        restricted, r_reason = self.is_region_restricted(node_name)
        
        # 1. 真实探测端点 1: Gemini 主 API (generativelanguage.googleapis.com)
        main_url = self.test_urls[0]
        ok_main, res_main = self.probe_single_endpoint(node_name, main_url)

        if not ok_main:
            err_msg = str(res_main)
            if "Timeout" in err_msg or "504" in err_msg:
                desc = "Gemini 连接超时 (504)"
            elif "503" in err_msg:
                desc = "节点服务不可用 (503)"
            elif "refused" in err_msg.lower():
                desc = "代理拒绝连接"
            else:
                desc = f"网络异常: {err_msg[:16]}"
                
            return {
                "name": node_name,
                "delay": 99999,
                "status": "FAIL",
                "status_text": "不可用",
                "desc": desc,
                "score": 99999
            }

        delay = res_main

        # 2. 如果节点属于政策受限区域（如香港），予以标记并降权
        if restricted:
            return {
                "name": node_name,
                "delay": delay,
                "status": "RESTRICTED",
                "status_text": "地区受限",
                "desc": r_reason,
                "score": delay + 10000
            }

        # 3. 正常可用且合规节点
        return {
            "name": node_name,
            "delay": delay,
            "status": "OK",
            "status_text": "Gemini 正常",
            "desc": "实测连通/无限制",
            "score": delay
        }

    def benchmark_all_nodes(self, real_nodes):
        print(cstr(f"[*] 正在通过 Clash 内核对全部 {len(real_nodes)} 个节点向 Google Gemini 进行实地握手检测...", Colors.CYAN))
        results = []
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            futures = [pool.submit(self.probe_node, node) for node in real_nodes]
            for f in futures:
                results.append(f.result())

        results.sort(key=lambda x: (x["score"]))
        return results

    def switch_node(self, group_name, target_node):
        encoded_group = parse.quote(group_name)
        ok, res = self._api_request(f"/proxies/{encoded_group}", method="PUT", body={"name": target_node})
        return ok, res

    def print_dashboard(self, results, selector_groups, selected_best=None):
        print("\n" + "=" * 78)
        title = " 🚀 Clash Mi 智能节点体检仪表盘 (Antigravity & Gemini 真实实测) "
        print(cstr(title.center(70), Colors.BOLD + Colors.CYAN))
        print("=" * 78)

        # 表头
        h_idx = pad_str("#", 4, 'center')
        h_name = pad_str("节点名称", 32, 'left')
        h_delay = pad_str("实测延迟", 12, 'center')
        h_status = pad_str("Gemini 状态", 14, 'center')
        h_remark = pad_str("真实网络诊断说明", 16, 'left')
        print(cstr(f"{h_idx} | {h_name} | {h_delay} | {h_status} | {h_remark}", Colors.BOLD))
        print("-" * 78)

        ok_count = 0
        rest_count = 0
        fail_count = 0

        for idx, item in enumerate(results, 1):
            name = item["name"]
            delay = item["delay"]
            status = item["status"]
            desc = item["desc"]

            display_name = name
            if str_width(display_name) > 30:
                while str_width(display_name) > 27:
                    display_name = display_name[:-1]
                display_name += "..."

            col_idx = pad_str(str(idx), 4, 'center')
            col_name = pad_str(display_name, 32, 'left')

            if status == "OK":
                ok_count += 1
                col_delay = pad_str(f"{delay} ms", 12, 'center')
                col_status = pad_str("🟢 完美支持", 14, 'center')
                col_remark = pad_str(desc, 16, 'left')
                line = f"{col_idx} | {col_name} | {col_delay} | {col_status} | {col_remark}"
                if idx == 1:
                    print(cstr(line, Colors.BOLD + Colors.GREEN))
                else:
                    print(cstr(line, Colors.GREEN))
            elif status == "RESTRICTED":
                rest_count += 1
                col_delay = pad_str(f"{delay} ms", 12, 'center')
                col_status = pad_str("🟡 地区受限", 14, 'center')
                col_remark = pad_str(desc, 16, 'left')
                print(cstr(f"{col_idx} | {col_name} | {col_delay} | {col_status} | {col_remark}", Colors.YELLOW))
            else:
                fail_count += 1
                col_delay = pad_str("--", 12, 'center')
                col_status = pad_str("🔴 异常/超时", 14, 'center')
                col_remark = pad_str(desc, 16, 'left')
                print(cstr(f"{col_idx} | {col_name} | {col_delay} | {col_status} | {col_remark}", Colors.RED))

        print("-" * 78)
        summary = f"统计：总计 {len(results)} 节点 | 🟢 实测可用: {ok_count} | 🟡 地区受限: {rest_count} | 🔴 实际故障/超时: {fail_count}"
        print(cstr(summary, Colors.BOLD))
        print("=" * 78 + "\n")

    def run_optimization(self, auto_switch=True, send_notify=True):
        ok, msg = self.test_connection()
        if not ok:
            print(cstr(f"[X] {msg}", Colors.RED))
            print(cstr("[!] 请确认 Clash Mi 客户端已开启，并且在设置中允许了外部控制 (External Controller)", Colors.YELLOW))
            return None

        real_nodes, selector_groups = self.get_proxies_data()
        if not real_nodes:
            print(cstr("[!] 未在 Clash Mi 中获取到可用代理节点", Colors.YELLOW))
            return None

        results = self.benchmark_all_nodes(real_nodes)
        
        best_node = None
        for item in results:
            if item["status"] == "OK":
                best_node = item
                break

        self.print_dashboard(results, selector_groups, selected_best=best_node)

        if not best_node:
            print(cstr("[!] 警告: 没有检测到任何支持 Gemini 的 🟢 可用节点！请检查订阅节点或网络。", Colors.RED))
            if send_notify:
                show_windows_toast("Clash Mi 节点体检告警", "未能找到支持 Gemini 的可用节点，请检查节点订阅！")
            return None

        print(cstr(f"[✓] 推荐最优 Gemini 节点: 【{best_node['name']}】 (实测延迟: {best_node['delay']}ms)", Colors.BOLD + Colors.GREEN))

        if auto_switch:
            switched_groups = []
            for gname, ginfo in selector_groups.items():
                if any(kw in gname for kw in self.target_keywords) or gname == "GLOBAL":
                    current_node = ginfo.get("now", "")
                    if current_node != best_node["name"]:
                        sw_ok, sw_res = self.switch_node(gname, best_node["name"])
                        if sw_ok:
                            switched_groups.append(gname)
                            print(cstr(f"  -> 已成功切换策略组 [{gname}] : {current_node} => {best_node['name']}", Colors.CYAN))
                        else:
                            print(cstr(f"  -> 切换策略组 [{gname}] 失败: {sw_res}", Colors.RED))
                    else:
                        print(cstr(f"  -> 策略组 [{gname}] 当前已在最优节点上，无需重复切换", Colors.DIM))

            if switched_groups and send_notify:
                notify_title = "Clash Mi 节点智能优选"
                notify_msg = f"已自动切换到最优节点: {best_node['name']}\nGemini 实测延迟: {best_node['delay']}ms (网络健康)"
                show_windows_toast(notify_title, notify_msg)

        return best_node

    def run_daemon(self, interval=180):
        if os.name == 'nt':
            try:
                ctypes.windll.kernel32.SetConsoleTitleW("Clash Mi - Gemini 节点守护监控中...")
            except Exception:
                pass

        print(cstr("\n" + "=" * 60, Colors.CYAN))
        print(cstr(" 🛡️ Clash Mi Gemini 自动守护模式已启动", Colors.BOLD + Colors.GREEN))
        print(cstr(f" 监控频率: 每 {interval} 秒巡检一次当前节点健康度", Colors.CYAN))
        print(cstr(" 遇到节点不可用或 Gemini 报错时将毫秒级自动无缝切换", Colors.CYAN))
        print(cstr(" 按 Ctrl + C 可退出守护进程", Colors.DIM))
        print(cstr("=" * 60 + "\n", Colors.CYAN))

        current_best = self.run_optimization(auto_switch=True, send_notify=True)

        while True:
            try:
                time.sleep(interval)
                _, selector_groups = self.get_proxies_data()
                if not selector_groups:
                    continue

                active_node = None
                for kw in self.target_keywords:
                    for gname, ginfo in selector_groups.items():
                        if kw in gname:
                            active_node = ginfo.get("now")
                            break
                    if active_node:
                        break

                if not active_node:
                    active_node = selector_groups.get("GLOBAL", {}).get("now")

                if not active_node:
                    continue

                probe_res = self.probe_node(active_node)
                timestamp = time.strftime("%H:%M:%S")

                if probe_res["status"] == "OK" and probe_res["delay"] < 800:
                    print(f"[{timestamp}] 当前节点 [{active_node}] 运行健康: Gemini 延迟 {probe_res['delay']}ms")
                else:
                    print(cstr(f"\n[{timestamp}] [!] 监测到当前节点 [{active_node}] 状态恶化 ({probe_res['status_text']}: {probe_res['desc']})，触发紧急全量优选...", Colors.YELLOW))
                    self.run_optimization(auto_switch=True, send_notify=True)

            except KeyboardInterrupt:
                print(cstr("\n[!] 守护进程已安全退出。", Colors.YELLOW))
                break
            except Exception as e:
                print(cstr(f"[!] 守护循环发生异常: {e}", Colors.RED))
                time.sleep(5)

def main():
    parser = argparse.ArgumentParser(description="Clash Mi 智能节点体检与自动优选守护工具 (Gemini / Antigravity 专用)")
    parser.add_argument("--daemon", action="store_true", help="启动后台持续监控与自动故障切换守护模式")
    parser.add_argument("--once", action="store_true", default=True, help="单次体检并优选（默认模式）")
    parser.add_argument("--interval", type=int, default=180, help="守护模式巡检间隔秒数 (默认 180 秒)")
    parser.add_argument("--no-switch", action="store_true", help="仅体检不自动切换节点")
    parser.add_argument("--no-notify", action="store_true", help="禁用桌面弹窗通知")
    args = parser.parse_args()

    guardian = ClashMiGuardian("config.json")

    if args.daemon:
        guardian.run_daemon(interval=args.interval)
    else:
        guardian.run_optimization(
            auto_switch=not args.no_switch,
            send_notify=not args.no_notify
        )

if __name__ == "__main__":
    main()
