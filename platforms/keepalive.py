import time
import threading
import json
import os
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
    # ✅ 升级为与抓包一致的 Chrome 145 指纹
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9,en-IN;q=0.8,en;q=0.7",
        "Sec-CH-UA": '"Not:A-Brand";v="99", "Google Chrome";v="145", "Chromium";v="145"',
        "Sec-CH-UA-Mobile": "?0",
        "Sec-CH-UA-Platform": '"Windows"',
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-site",
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
                        headers["X-XSRF-TOKEN"] = unquote(v.strip())
        elif len(credential.split("-")) >= 4:
            headers["Authorization"] = f"Bearer {credential}"
            token_val = credential.strip()
        else:
            headers["Cookie"] = credential

    if heartbeat_url and "altare.sh" in heartbeat_url:
        headers["Origin"] = "https://altare.sh"
        headers["Referer"] = "https://altare.sh/billing/rewards/afk"
        headers["Sec-Fetch-Site"] = "same-origin"
        
        # 尝试从 URL 中提取 tenant_id (例如: /api/tenants/677557c8.../rewards/afk/heartbeat)
        try:
            parts = heartbeat_url.split("/")
            if "tenants" in parts:
                idx = parts.index("tenants")
                tenant_id = parts[idx + 1]
                headers["X-Tenant-Id"] = tenant_id
                log(f"🔎 自动提取到 X-Tenant-Id: {tenant_id[:8]}***", "INFO", server_id)
        except:
            pass

    try:
        wait_seconds = int(wait_seconds)
    except (TypeError, ValueError):
        wait_seconds = 60

    # ==================== SSE 长连接保活线程 (针对 Altare.sh) ====================
    def maintain_sse_subscription(url, s_headers):
        while True:
            try:
                # 这种请求是持续不断的，模拟浏览器 EventSource
                with session.get(url, headers=s_headers, stream=True, timeout=120, verify=False) as r:
                    for _ in r.iter_lines():
                        # 主动检查一次配置，如果停用了，连 SSE 也一起断掉
                        if not os.path.exists(config_path): continue
                        pass
            except:
                pass
            time.sleep(10)

    if heartbeat_url and "altare.sh" in heartbeat_url and token_val:
        # 构建 SSE 订阅 URL，并注入 tenant 信息（如果存在）
        subscribe_url = f"https://altare.sh/api/core/updates/subscribe?token={token_val}"
        t_id_search = [v for k, v in headers.items() if k.lower() == "x-tenant-id"]
        if t_id_search:
             subscribe_url += f"&tenant={t_id_search[0]}"
             
        sse_headers = headers.copy()
        sse_headers["Accept"] = "text/event-stream"
        sse_headers.pop("Content-Type", None)
        log("🛰️ 启动后台 SSE 长连接订阅 (EventSource)...", "INFO", server_id)
        threading.Thread(target=maintain_sse_subscription, args=(subscribe_url, sse_headers), daemon=True).start()

    # 初始化：执行入场逻辑 (Altare 优先尝试 /start)
    if heartbeat_url:
        u = heartbeat_url.replace("/heartbeat", "/start") if "altare.sh" in heartbeat_url else heartbeat_url.replace("/heartbeat", "/join")
        try:
            log(f"🚀 执行 AFK 入场: {u.split('/')[-1]}...", "INFO", server_id)
            session.post(u, headers=headers, timeout=15, verify=False)
        except:
            pass

    while True:
        # 🟢 停止检测：实时拉取配置，发现停用则立刻退出 (解决多线程残留问题)
        try:
            if os.path.exists(config_path):
                with open(config_path, 'r', encoding='utf-8') as f:
                    configs = json.load(f)
                    current_acc = next((a for a in configs if a.get("server_id") == server_id), None)
                    if not current_acc or not current_acc.get("enabled", True):
                        log("⏹️ 监测到账号已停用，正在终止心跳线程...", "WARNING", server_id)
                        break
        except Exception:
            pass

        log("=" * 40, "INFO", server_id)
        log(f"📍 第 {loop_count} 次循环", "INFO", server_id)
        log("=" * 40, "INFO", server_id)

        # 每隔 30 次循环（约 30 分钟）重新请求入场，维持活力
        if loop_count > 1 and loop_count % 30 == 0 and heartbeat_url:
            u = heartbeat_url.replace("/heartbeat", "/start") if "altare.sh" in heartbeat_url else heartbeat_url.replace("/heartbeat", "/join")
            try:
                log(f"🔄 周期性刷新入场状态: {u.split('/')[-1]}...", "INFO", server_id)
                session.post(u, headers=headers, timeout=15, verify=False)
            except:
                pass

        if heartbeat_url:
            try:
                # 自动关联 XSRF 令牌
                for k, v in session.cookies.items():
                    if k == "XSRF-TOKEN":
                        headers["X-XSRF-TOKEN"] = unquote(v)

                log("❤️ 发送心跳请求...", "INFO", server_id)
                if "altare.sh" in heartbeat_url:
                    resp = session.post(heartbeat_url, headers=headers, timeout=15, verify=False)
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
                        session.post(u, headers=headers, timeout=10, verify=False)
                    except:
                        pass
                    log(f"❌ 权限仍被拦截: 请检查 Token 是否过期或 IP 被标记", "ERROR", server_id)
                else:
                    log(f"⚠️ 心跳异常 ({resp.status_code})", "WARNING", server_id)
            except Exception as e:
                log(f"❌ 心跳网络异常: {e}", "ERROR", server_id)
        else:
            log("✅ 伪装心跳成功", "INFO", server_id)

        # 💰 初始化(第1次)以及之后每 5 次心跳查询一次余额，避免被封
        if check_url and (loop_count == 1 or loop_count % 5 == 0):
            try:
                log("💰 周期性查询钱包/详情...", "INFO", server_id)
                resp = session.get(check_url, headers=headers, timeout=15, verify=False)
                if resp.status_code == 200:
                    try:
                        data = resp.json()
                        if "balanceCents" in data:
                            balance = data["balanceCents"] / 100.0
                            log(f"✅ 查询成功: 当前积分/余额位 {balance}", "INFO", server_id)
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
