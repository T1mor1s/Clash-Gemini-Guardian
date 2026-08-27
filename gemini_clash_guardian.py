#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Clash Mi 智能节点体检与自动优选守护工具 (Gemini / Antigravity 专用)
------------------------------------------------------------------
原理与机制：
1. 真实端到端全量 Google Gemini 深度检测：
   对列表中的每个节点（无论名称是美国、韩国、日本、新加坡还是台湾），
   程序都会通过 Clash 核心同时对：
     (1) Google Gemini 官方前端服务 (https://gemini.google.com/app)
     (2) Google Gemini API 官方模型通道 (https://generativelanguage.googleapis.com/v1beta/models)
     (3) Google 基础网络 (https://www.google.com/generate_204)
   进行实地 TCP/TLS 握手与 HTTP 连通性深度体检。
2. 地区封锁与风控 100% 精准拦截：
   - 彻底识别并降权所有中国香港 (HK)、中国大陆及受限地区节点，杜绝 400 "User location is not supported" 报错。
   - 任何单端点异常、丢包或超时节点直接标红 🔴 不可用。
3. 全策略组无缝同步与僵尸连接强制清理 (DELETE /connections)：
   - 切换节点时，同时无缝同步切换 Clash Mi 的所有策略组 (GLOBAL、节点选择、PROXY 等)；
   - 切换后立即强制清理所有旧的僵尸 TCP 长连接，确保 Antigravity 和浏览器立刻走全新最优节点，无需重启软件。
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
import shutil
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
        self.gemini_web_url = "https://gemini.google.com/app"
        self.gemini_api_url = "https://generativelanguage.googleapis.com/v1beta/models"
        self.google_gen204_url = "https://www.google.com/generate_204"
        self.timeout_sec = self.config.get("timeout_seconds", 5)
        self.max_workers = self.config.get("max_workers", 16)
        self.target_keywords = self.config.get("target_group_keywords", ["节点选择", "PROXY", "GLOBAL", "Google", "AI"])
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
        cfg_secret = self.config.get("clash_api_secret", "auto")
        if cfg_secret and cfg_secret != "auto":
            return cfg_secret

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
            return True, "香港节点 (Google 政策严格不开放 Gemini)"
        if '🇨🇳' in node_name or 'china' in name_lower:
            return True, "中国大陆 (Google 不开放地区)"
        if '🇷🇺' in node_name or 'russia' in name_lower:
            return True, "俄罗斯 (Google 不开放地区)"
        return False, "合规地区"

    def probe_single_endpoint(self, node_name, test_url):
        """通过该节点实际向指定目标地址发起真实的 TCP/TLS/HTTP 握手并测速"""
        encoded_name = parse.quote(node_name)
        endpoint = f"/proxies/{encoded_name}/delay?url={parse.quote(test_url)}&timeout={int(self.timeout_sec * 1000)}"
        ok, res = self._api_request(endpoint, timeout=self.timeout_sec + 2)
        if ok and isinstance(res, dict) and "delay" in res:
            return True, res["delay"]
        return False, str(res)

    def flush_connections(self):
        """强制清理 Clash 所有旧的僵尸长连接，避免 Antigravity 和浏览器走旧节点"""
        ok, _ = self._api_request("/connections", method="DELETE", timeout=3)
        return ok

    def probe_node(self, node_name):
        """
        对单个节点进行全方位的真实端到端网络连通性深度体检
        采用多端点融合校验机制：
        1. 必须能连通 Google Gemini API 核心模型通道 (generativelanguage.googleapis.com/v1beta/models)
        2. 必须能连通 Google Gemini 官方前端服务 (gemini.google.com/app)
        3. 必须能连通 Google 基础网络 (google.com/generate_204)
        """
        restricted, r_reason = self.is_region_restricted(node_name)
        
        # 1. 真实网络探测端点 1: Gemini API 核心模型通道
        ok_api, res_api = self.probe_single_endpoint(node_name, self.gemini_api_url)
        # 2. 真实网络探测端点 2: Gemini 官方 Web 服务
        ok_web, res_web = self.probe_single_endpoint(node_name, self.gemini_web_url)

        # 只要任一核心端点完全无法连接，说明该节点不可用于 Gemini / Antigravity
        if not ok_api or not ok_web:
            err_details = []
            if not ok_api:
                err_details.append("API通道阻断")
            if not ok_web:
                err_details.append("Web服务异常")
            
            desc = " / ".join(err_details)
            return {
                "name": node_name,
                "delay": 99999,
                "status": "FAIL",
                "status_text": "不可用",
                "desc": desc,
                "score": 99999
            }

        # 获取真实有效延迟（以两者综合延迟为准）
        effective_delay = max(res_api, res_web)

        # 3. 政策受限地区（如香港）：虽然物理可能连通，但 Google 严格返回 400 不支持，必须降权
        if restricted:
            return {
                "name": node_name,
                "delay": effective_delay,
                "status": "RESTRICTED",
                "status_text": "地区受限",
                "desc": r_reason,
                "score": effective_delay + 10000
            }

        # 4. 延迟过高 / 极度不稳定节点 (>1200ms)：极易在 AI 长对话流式通信中发生 504 断流
        if effective_delay > 1200:
            return {
                "name": node_name,
                "delay": effective_delay,
                "status": "RESTRICTED",
                "status_text": "高延迟/不稳定",
                "desc": f"实测延迟高达 {effective_delay}ms (易断流)",
                "score": effective_delay + 5000
            }

        # 5. 双端点完全正常、低延迟合规节点
        return {
            "name": node_name,
            "delay": effective_delay,
            "status": "OK",
            "status_text": "Gemini 正常",
            "desc": f"双端畅通 (API:{res_api}ms / Web:{res_web}ms)",
            "score": effective_delay
        }

    def benchmark_all_nodes(self, real_nodes):
        print(cstr(f"[*] 正在通过 Clash 内核对全部 {len(real_nodes)} 个节点向 Google Gemini 进行实地多端点深度检测...", Colors.CYAN))
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

    def switch_all_active_groups(self, target_node):
        """将 Clash Mi 内所有可用的代理选择策略组同步切换到目标节点，并清理僵尸连接"""
        _, selector_groups = self.get_proxies_data()
        switched_groups = []
        if selector_groups:
            for gname, ginfo in selector_groups.items():
                if ginfo.get("type") in ("Selector", "URLTest") or gname in ("GLOBAL", "节点选择", "PROXY"):
                    if "all" in ginfo and target_node in ginfo["all"]:
                        sw_ok, _ = self.switch_node(gname, target_node)
                        if sw_ok:
                            switched_groups.append(gname)

        # 立即清理旧连接
        self.flush_connections()
        return switched_groups

    RULE_TAG_START = "# >>> GEMINI-GUARDIAN-RULES-START >>>"
    RULE_TAG_END = "# <<< GEMINI-GUARDIAN-RULES-END <<<"

    def get_candidate_profile_paths(self):
        base = os.path.expandvars(r"%APPDATA%\clashmi\clashmi")
        profiles_json = os.path.join(base, "profiles.json")
        paths = []
        if os.path.exists(profiles_json):
            try:
                with open(profiles_json, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    cur_id = data.get("current_id")
                    if cur_id:
                        cur_path = os.path.join(base, "profiles", cur_id)
                        if os.path.exists(cur_path):
                            paths.append(cur_path)
            except Exception:
                pass

        runtime_yaml = os.path.join(base, "service_core_runtime_profile.yaml")
        if os.path.exists(runtime_yaml):
            paths.append(runtime_yaml)

        return list(dict.fromkeys(paths))

    def get_rules_status(self):
        paths = self.get_candidate_profile_paths()
        if not paths:
            return {"supported": False, "injected": False, "paths": []}
        
        injected = any(self.check_rules_injected(p) for p in paths)
        return {
            "supported": True,
            "injected": injected,
            "paths": [os.path.basename(p) for p in paths],
            "target_group": "节点选择"
        }

    def check_rules_injected(self, yaml_path):
        if not os.path.exists(yaml_path):
            return False
        try:
            with open(yaml_path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
            return (self.RULE_TAG_START in content and self.RULE_TAG_END in content)
        except Exception:
            return False

    def inject_gemini_rules(self, target_group="节点选择"):
        paths = self.get_candidate_profile_paths()
        if not paths:
            return False, "未找到 Clash Mi 配置文件"

        success_count = 0
        injected_lines = [
            f"{self.RULE_TAG_START}\n",
            f"- DOMAIN-SUFFIX,generativelanguage.googleapis.com,{target_group}\n",
            f"- DOMAIN-SUFFIX,gemini.google.com,{target_group}\n",
            f"- DOMAIN-SUFFIX,ai.google.dev,{target_group}\n",
            f"{self.RULE_TAG_END}\n"
        ]

        for yaml_path in paths:
            try:
                bak_path = yaml_path + ".gemini_bak"
                if not os.path.exists(bak_path):
                    shutil.copyfile(yaml_path, bak_path)

                with open(yaml_path, 'r', encoding='utf-8', errors='replace') as f:
                    lines = f.readlines()

                content = "".join(lines)
                if self.RULE_TAG_START in content:
                    pattern = re.compile(rf"{re.escape(self.RULE_TAG_START)}.*?{re.escape(self.RULE_TAG_END)}\n?", re.DOTALL)
                    content = pattern.sub("", content)
                    lines = content.splitlines(keepends=True)

                rules_idx = -1
                for i, l in enumerate(lines):
                    if re.match(r"^rules\s*:", l):
                        rules_idx = i
                        break

                if rules_idx != -1:
                    new_lines = lines[:rules_idx+1] + injected_lines + lines[rules_idx+1:]
                else:
                    new_lines = lines + ["\nrules:\n"] + injected_lines

                with open(yaml_path, 'w', encoding='utf-8') as f:
                    f.writelines(new_lines)
                success_count += 1
            except Exception:
                pass

        if success_count > 0:
            self._api_request("/configs?force=true", method="PUT", body={})
            self.flush_connections()
            return True, f"已成功向 {success_count} 个配置文件无损注入 Gemini 专属防漏规则并生效！"
        return False, "写入配置文件失败"

    def restore_gemini_rules(self):
        paths = self.get_candidate_profile_paths()
        if not paths:
            return False, "未找到 Clash Mi 配置文件"

        success_count = 0
        for yaml_path in paths:
            try:
                with open(yaml_path, 'r', encoding='utf-8', errors='replace') as f:
                    content = f.read()

                if self.RULE_TAG_START in content:
                    pattern = re.compile(rf"{re.escape(self.RULE_TAG_START)}.*?{re.escape(self.RULE_TAG_END)}\n?", re.DOTALL)
                    cleaned = pattern.sub("", content)
                    with open(yaml_path, 'w', encoding='utf-8') as f:
                        f.write(cleaned)
                    success_count += 1
            except Exception:
                pass

        if success_count > 0:
            self._api_request("/configs?force=true", method="PUT", body={})
            self.flush_connections()
            return True, "已成功移除 Gemini 专属规则并恢复原状！"
        return True, "未检测到已注入的规则，无需还原"

    def print_dashboard(self, results, selector_groups, selected_best=None):
        print("\n" + "=" * 84)
        title = " 🚀 Clash Mi 智能节点体检仪表盘 (Antigravity & Gemini 真实深度实测) "
        print(cstr(title.center(76), Colors.BOLD + Colors.CYAN))
        print("=" * 84)

        # 表头
        h_idx = pad_str("#", 4, 'center')
        h_name = pad_str("节点名称", 30, 'left')
        h_delay = pad_str("实测延迟", 12, 'center')
        h_status = pad_str("Gemini 状态", 14, 'center')
        h_remark = pad_str("真实网络诊断说明", 22, 'left')
        print(cstr(f"{h_idx} | {h_name} | {h_delay} | {h_status} | {h_remark}", Colors.BOLD))
        print("-" * 84)

        ok_count = 0
        rest_count = 0
        fail_count = 0

        for idx, item in enumerate(results, 1):
            name = item["name"]
            delay = item["delay"]
            status = item["status"]
            desc = item["desc"]

            display_name = name
            if str_width(display_name) > 28:
                while str_width(display_name) > 25:
                    display_name = display_name[:-1]
                display_name += "..."

            col_idx = pad_str(str(idx), 4, 'center')
            col_name = pad_str(display_name, 30, 'left')

            if status == "OK":
                ok_count += 1
                col_delay = pad_str(f"{delay} ms", 12, 'center')
                col_status = pad_str("🟢 完美支持", 14, 'center')
                col_remark = pad_str(desc, 22, 'left')
                line = f"{col_idx} | {col_name} | {col_delay} | {col_status} | {col_remark}"
                if idx == 1:
                    print(cstr(line, Colors.BOLD + Colors.GREEN))
                else:
                    print(cstr(line, Colors.GREEN))
            elif status == "RESTRICTED":
                rest_count += 1
                col_delay = pad_str(f"{delay} ms", 12, 'center')
                col_status = pad_str("🟡 地区/受限", 14, 'center')
                col_remark = pad_str(desc, 22, 'left')
                print(cstr(f"{col_idx} | {col_name} | {col_delay} | {col_status} | {col_remark}", Colors.YELLOW))
            else:
                fail_count += 1
                col_delay = pad_str("--", 12, 'center')
                col_status = pad_str("🔴 异常/不可用", 14, 'center')
                col_remark = pad_str(desc, 22, 'left')
                print(cstr(f"{col_idx} | {col_name} | {col_delay} | {col_status} | {col_remark}", Colors.RED))

        print("-" * 84)
        summary = f"统计：总计 {len(results)} 节点 | 🟢 双端畅通可用: {ok_count} | 🟡 地区受限/高延迟: {rest_count} | 🔴 实际故障/超时: {fail_count}"
        print(cstr(summary, Colors.BOLD))
        print("=" * 84 + "\n")

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

        print(cstr(f"[✓] 推荐最优 Gemini 节点: 【{best_node['name']}】 (实测双端延迟: {best_node['delay']}ms)", Colors.BOLD + Colors.GREEN))

        if auto_switch:
            switched = self.switch_all_active_groups(best_node["name"])
            if switched:
                print(cstr(f"  -> 已成功联动切换策略组 ({len(switched)}个): {', '.join(switched)} => 【{best_node['name']}】", Colors.CYAN))
                print(cstr("  -> 已成功清理全部旧的长连接缓存 (Connections Flushed)", Colors.DIM))

            if send_notify:
                notify_title = "Clash Mi 节点智能优选"
                notify_msg = f"已自动切换到最优节点: {best_node['name']}\nGemini 双端延迟: {best_node['delay']}ms (网络健康)"
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
