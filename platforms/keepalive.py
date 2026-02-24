import time
import threading
import json
import os
import requests
import re
from urllib.parse import unquote


def process(session, account, log):
    """
    KeepAlive 演示模块 (长时在线版本)
    """
    server_id = account.get("server_id")
    loop_count = account.get("keepalive_loop_count", 1)
    wait_seconds = account.get("keepalive_wait_seconds", 60)
    heartbeat_url = account.get("keepalive_heartbeat_url", "").strip()
    check_url = account.get("keepalive_check_url", "").strip()
    
    # 配置路径，用于实时校验是否应该停止任务
    config_path = os.environ.get("CONFIG_FILE", "/app/data/config.json")

    # 解析凭证：智能识别 Token 和 Cookie
    credential = account.get("cookie", "").strip()
    # ✅ 1:1 像素级还原用户抓包中的 Chrome 142 指纹
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Sec-CH-UA": '"Chromium";v="142", "Google Chrome";v="142", "Not_A Brand";v="99"',
        "Sec-CH-UA-Mobile": "?0",
        "Sec-CH-UA-Platform": '"Windows"',
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "Connection": "keep-alive"
    }
    
    token_val = ""
    if credential:
        if credential.startswith("Bearer "):
            headers["Authorization"] = credential
            token_val = credential.split("Bearer ")[1].strip()
        elif "=" in credential:
            headers["Cookie"] = credential
            # 自动将 Cookie 注入 Session 以便后续提取 XSRF-TOKEN
            for item in credential.split(';'):
                if '=' in item:
                    k, v = item.strip().split('=', 1)
                    session.cookies.set(k.strip(), v.strip())
                    if k.strip() == "XSRF-TOKEN":
                        xsrf_token = unquote(v.strip())
                        headers["X-XSRF-TOKEN"] = xsrf_token
        elif len(credential.split("-")) >= 4:
            headers["Authorization"] = f"Bearer {credential}"
            token_val = credential.strip()
        else:
            headers["Cookie"] = credential

    # ✅ 强化 Tenant ID 探测与注入
    tenant_id = None
    if heartbeat_url and "altare.sh" in heartbeat_url:
        headers["Origin"] = "https://altare.sh"
        headers["Referer"] = "https://altare.sh/billing/rewards/afk"
        headers["Sec-Fetch-Site"] = "same-origin"
        
        # 尝试由 URL 探测 tenant_id
        match = re.search(r'tenants/([a-z0-9-]+)', heartbeat_url)
        if match:
            tenant_id = match.group(1)
            headers["X-Tenant-Id"] = tenant_id
            log(f"🔎 探测到 X-Tenant-Id: {tenant_id[:10]}***", "INFO", server_id)

    try:
        wait_seconds = int(wait_seconds)
    except (TypeError, ValueError):
        wait_seconds = 60

    # ==================== SSE 长连接保活线程 (同步 Tenant 信息) ====================
    def maintain_sse_subscription(url, s_headers, current_cookies):
        log("🛰️ 准备建立 SSE 长连接订阅 (EventSource)...", "INFO", server_id)
        while True:
            try:
                # 注入当前最新的 Cookies
                c_str = "; ".join([f"{k}={v}" for k, v in current_cookies.items()])
                s_headers["Cookie"] = c_str
                # 使用独立的请求以防止主 Session 被阻塞
                with requests.get(url, headers=s_headers, stream=True, timeout=120, verify=False) as r:
                    if r.status_code == 200:
                        log("✅ SSE 订阅成功：在线状态维持中...", "INFO", server_id)
                        for _ in r.iter_lines():
                            if not os.path.exists(config_path): break
                    else:
                        log(f"⚠️ SSE 订阅返回异常 ({r.status_code})", "WARNING", server_id)
            except:
                pass
            time.sleep(15)

    # 初始化逻辑：调整顺序 (先 Start 再 SSE)
    if heartbeat_url:
        u = heartbeat_url.replace("/heartbeat", "/start") if "altare.sh" in heartbeat_url else heartbeat_url.replace("/heartbeat", "/join")
        try:
            log(f"🚀 发送挂机开始请求: {u.split('/')[-1]}...", "INFO", server_id)
            # 🛑 核心修复：根据抓包，Body 必须绝对为空 (Content-Length: 0)
            resp = session.post(u, headers=headers, data=None, timeout=15, verify=False)
            if resp.status_code == 409:
                log("💡 提示 (409): 会话已激活。请确保已关闭所有 Altare.sh 浏览器标签，否则可能导致锁分。", "WARNING", server_id)
            else:
                try:
                    res_json = resp.json()
                    log(f"💡 请求结果 ({resp.status_code}): {json.dumps(res_json)[:100]}", "INFO", server_id)
                except:
                    log(f"💡 请求结果 ({resp.status_code}): {resp.text[:50]}", "INFO", server_id)
        except Exception as e:
            log(f"⚠️ 开始请求异常: {e}", "WARNING", server_id)

    # 启动 SSE (在 Start 之后启动，避免竞争)
    if heartbeat_url and "altare.sh" in heartbeat_url and token_val:
        subscribe_url = f"https://altare.sh/api/core/updates/subscribe?token={token_val}"
        if tenant_id:
            subscribe_url += f"&tenant={tenant_id}"
             
        sse_headers = headers.copy()
        sse_headers["Accept"] = "text/event-stream"
        sse_headers.pop("Content-Type", None)
        sse_headers["Cache-Control"] = "no-cache"
        # 传入 session.cookies 以便实时同步
        threading.Thread(target=maintain_sse_subscription, args=(subscribe_url, sse_headers, session.cookies), daemon=True).start()

    while True:
        # 🟢 停止检测
        try:
            if os.path.exists(config_path):
                with open(config_path, 'r', encoding='utf-8') as f:
                    configs = json.load(f)
                    current_acc = next((a for a in configs if a.get("server_id") == server_id), None)
                    if not current_acc or not current_acc.get("enabled", True):
                        log("⏹️ 监测到账号已停用，正在终止心跳线程...", "WARNING", server_id)
                        break
        except:
            pass

        log("=" * 40, "INFO", server_id)
        log(f"📍 第 {loop_count} 次循环", "INFO", server_id)
        log("=" * 40, "INFO", server_id)

        if loop_count > 1 and loop_count % 30 == 0 and heartbeat_url:
            u = heartbeat_url.replace("/heartbeat", "/start") if "altare.sh" in heartbeat_url else heartbeat_url.replace("/heartbeat", "/join")
            try:
                log(f"🔄 周期性刷新状态: {u.split('/')[-1]}...", "INFO", server_id)
                session.post(u, headers=headers, data=None, timeout=15, verify=False)
            except:
                pass

        if heartbeat_url:
            try:
                # 重新同步 XSRF
                for k, v in session.cookies.items():
                    if k == "XSRF-TOKEN":
                        headers["X-XSRF-TOKEN"] = unquote(v)

                log("❤️ 发送心跳请求...", "INFO", server_id)
                if "altare.sh" in heartbeat_url:
                    # ✅ 同样确保心跳包 Body 为空
                    resp = session.post(heartbeat_url, headers=headers, data=None, timeout=15, verify=False)
                else:
                    resp = session.get(heartbeat_url, headers=headers, timeout=15, verify=False)
                
                if resp.status_code == 200:
                    try:
                        resp_data = resp.json()
                        log(f"✅ 心跳成功 (200): {json.dumps(resp_data)[:100]}", "INFO", server_id)
                    except:
                        log(f"✅ 心跳成功 (200)", "INFO", server_id)
                elif resp.status_code in [401, 403]:
                    log(f"⚠️ 鉴权异常 ({resp.status_code})，尝试紧急重新入场...", "WARNING", server_id)
                    u = heartbeat_url.replace("/heartbeat", "/start") if "altare.sh" in heartbeat_url else heartbeat_url.replace("/heartbeat", "/join")
                    try:
                        session.post(u, headers=headers, data=None, timeout=10, verify=False)
                    except:
                        pass
                else:
                    log(f"⚠️ 心跳异常 ({resp.status_code}) {resp.text[:50]}", "WARNING", server_id)
            except Exception as e:
                log(f"❌ 心跳网络异常: {e}", "ERROR", server_id)
        else:
            log("✅ 伪装心跳成功", "INFO", server_id)

        # 💰 初始化以及之后每 5 次心跳查询一次
        if check_url and (loop_count == 1 or loop_count % 5 == 0):
            try:
                log("💰 周期性查询积分...", "INFO", server_id)
                resp = session.get(check_url, headers=headers, timeout=15, verify=False)
                if resp.status_code == 200:
                    try:
                        data = resp.json()
                        if "balanceCents" in data:
                            balance = data["balanceCents"] / 100.0
                            log(f"✅ 查询成功: 当前积分/余额 {balance}", "INFO", server_id)
                        else:
                            log(f"✅ 查询结果: {str(data)[:100]}", "INFO", server_id)
                    except:
                        log(f"✅ 查询成功 (200)", "INFO", server_id)
                elif resp.status_code in [401, 403]:
                    log(f"❌ 查询鉴权失败 ({resp.status_code})", "ERROR", server_id)
            except:
                pass

        log(f"⏳ 等待 {wait_seconds} 秒后继续...", "INFO", server_id)
        time.sleep(max(wait_seconds, 1))
        loop_count += 1

    return True, "心跳线程已安全终止", None
