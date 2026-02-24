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
    start_interval_seconds = account.get("keepalive_start_interval", 900)
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
        "Priority": "u=1, i",
        "Connection": "keep-alive",
    }

    token_val = ""
    if credential:
        if credential.startswith("Bearer "):
            headers["Authorization"] = credential
            token_val = credential.split("Bearer ")[1].strip()
        elif "=" in credential:
            headers["Cookie"] = credential
            # 自动将 Cookie 注入 Session 以便后续提取 XSRF-TOKEN
            for item in credential.split(";"):
                if "=" in item:
                    k, v = item.strip().split("=", 1)
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

        # 尝试由 URL 探测 tenant_id
        import re

        match = re.search(r"tenants/([a-z0-9-]+)", heartbeat_url)
        if match:
            tenant_id = match.group(1)
            headers["X-Tenant-Id"] = tenant_id

    try:
        wait_seconds = int(wait_seconds)
    except (TypeError, ValueError):
        wait_seconds = 60

    def is_account_active():
        if not os.path.exists(config_path):
            return False
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                configs = json.load(f)
            current_acc = next(
                (a for a in configs if a.get("server_id") == server_id), None
            )
            return bool(current_acc and current_acc.get("enabled", True))
        except Exception:
            return True

    # ==================== SSE 长连接保活线程 (同步 Tenant 信息) ====================
    def maintain_sse_subscription(url, s_headers, current_cookies):
        log("🛰️ 准备建立 SSE 长连接订阅 (EventSource)...", "INFO", server_id)
        backoff_seconds = 5
        while True:
            if not is_account_active():
                log("⏹️ 账号已停用，SSE 订阅线程退出", "WARNING", server_id)
                break
            try:
                # 注入当前最新的 Cookies
                c_str = "; ".join([f"{k}={v}" for k, v in current_cookies.items()])
                s_headers["Cookie"] = c_str
                # 同步最新的 XSRF
                for k, v in current_cookies.items():
                    if k == "XSRF-TOKEN":
                        s_headers["X-XSRF-TOKEN"] = unquote(v)

                with requests.get(
                    url, headers=s_headers, stream=True, timeout=120, verify=False
                ) as r:
                    if r.status_code == 200:
                        log("✅ SSE 订阅成功：在线状态维持中...", "INFO", server_id)
                        backoff_seconds = 5

                        # 【核心修复：对齐真正的 attach 路径】
                        if tenant_id and "altare.sh" in heartbeat_url:
                            try:
                                # 🛑 重要：根据 F12 抓包，attach 属于核心网关中的 updates 模块
                                a_url = f"https://altare.sh/api/core/updates/attach?tenantId={tenant_id}"
                                log(
                                    f"🔗 计分链路绑定: updates/attach (ID: {tenant_id[:8]}...)",
                                    "INFO",
                                    server_id,
                                )

                                # 将 tenant_id 补全到请求头
                                s_headers["X-Tenant-Id"] = tenant_id
                                a_resp = requests.post(
                                    a_url,
                                    headers=s_headers,
                                    data=None,
                                    timeout=10,
                                    verify=False,
                                )

                                if a_resp.status_code in [200, 201, 204]:
                                    log(
                                        f"🔗 会话绑定成功 ({a_resp.status_code})：计分已激活。",
                                        "INFO",
                                        server_id,
                                    )
                                else:
                                    log(
                                        f"⚠️ 绑定结果异常 ({a_resp.status_code})",
                                        "WARNING",
                                        server_id,
                                    )
                            except Exception as e:
                                log(f"❌ attach 错误: {e}", "ERROR", server_id)

                        for _ in r.iter_lines():
                            if not is_account_active():
                                break
                    else:
                        log(
                            f"⚠️ SSE 订阅返回异常 ({r.status_code})",
                            "WARNING",
                            server_id,
                        )
            except:
                pass
            time.sleep(backoff_seconds)
            backoff_seconds = min(backoff_seconds * 2, 120)

    # 1. 发送激活请求 (如果 409 则说明已经激活，正常)
    last_start_ts = None
    if heartbeat_url:
        u = (
            heartbeat_url.replace("/heartbeat", "/start")
            if "altare.sh" in heartbeat_url
            else heartbeat_url.replace("/heartbeat", "/join")
        )
        try:
            log(f"🚀 发送状态激活请求: {u.split('/')[-1]}...", "INFO", server_id)
            # Body 必须为空 (Content-Length: 0)
            resp = session.post(u, headers=headers, data=None, timeout=15, verify=False)
            if resp.status_code == 409:
                log(
                    "✨ 状态确认：服务器显示该账号已处于 AFK 计分状态 (409)",
                    "INFO",
                    server_id,
                )
            else:
                log(f"💡 激活完成 ({resp.status_code})", "INFO", server_id)
            last_start_ts = time.time()
        except Exception as e:
            log(f"⚠️ 激活异常: {e}", "WARNING", server_id)

    # 2. 启动异步 SSE 线程 (必须使用 args 且不能带括号，否则会阻塞主线程)
    if heartbeat_url and "altare.sh" in heartbeat_url and token_val:
        sub_url = f"https://altare.sh/api/core/updates/subscribe?token={token_val}"
        if tenant_id:
            sub_url += f"&tenant={tenant_id}"

        sse_h = headers.copy()
        sse_h["Accept"] = "text/event-stream"
        sse_h.pop("Content-Type", None)
        sse_h["Cache-Control"] = "no-cache"
        # ✅ 正确启动
        threading.Thread(
            target=maintain_sse_subscription,
            args=(sub_url, sse_h, session.cookies),
            daemon=True,
        ).start()

    # 3. 主循环心跳
    while True:
        # 🟢 停止检测
        if not is_account_active():
            log("⏹️ 监测到账号已停用，正在终止心跳线程...", "WARNING", server_id)
            break

        log("=" * 40, "INFO", server_id)
        log(f"📍 第 {loop_count} 次循环", "INFO", server_id)
        log("=" * 40, "INFO", server_id)

        # 定时刷新 /start，避免会话过期
        if heartbeat_url and start_interval_seconds:
            try:
                interval = int(start_interval_seconds)
            except (TypeError, ValueError):
                interval = 900
            if interval > 0:
                now_ts = time.time()
                if not last_start_ts or now_ts - last_start_ts >= interval:
                    u = (
                        heartbeat_url.replace("/heartbeat", "/start")
                        if "altare.sh" in heartbeat_url
                        else heartbeat_url.replace("/heartbeat", "/join")
                    )
                    try:
                        session.post(
                            u, headers=headers, data=None, timeout=15, verify=False
                        )
                        last_start_ts = now_ts
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
                    # 必须使用 data=None 实现 Content-Length: 0
                    resp = session.post(
                        heartbeat_url,
                        headers=headers,
                        data=None,
                        timeout=15,
                        verify=False,
                    )
                else:
                    resp = session.get(
                        heartbeat_url, headers=headers, timeout=15, verify=False
                    )

                if resp.status_code == 200:
                    log(f"✅ 心跳成功 (200)", "INFO", server_id)
                elif resp.status_code in [401, 403]:
                    log(
                        f"⚠️ 鉴权失效 ({resp.status_code})，尝试重连...",
                        "WARNING",
                        server_id,
                    )
                    u = (
                        heartbeat_url.replace("/heartbeat", "/start")
                        if "altare.sh" in heartbeat_url
                        else heartbeat_url.replace("/heartbeat", "/join")
                    )
                    try:
                        session.post(
                            u, headers=headers, data=None, timeout=10, verify=False
                        )
                    except:
                        pass
                else:
                    log(f"⚠️ 心跳异常 ({resp.status_code})", "WARNING", server_id)
            except Exception as e:
                log(f"❌ 网络异常: {e}", "ERROR", server_id)
        else:
            log("✅ 模拟心跳成功", "INFO", server_id)

        # 💰 关键项：积分余额显回 (每 5 次查一次)
        if check_url and (loop_count == 1 or loop_count % 5 == 0):
            try:
                log("💰 正在同步积分余额...", "INFO", server_id)
                resp = session.get(check_url, headers=headers, timeout=15, verify=False)
                if resp.status_code == 200:
                    try:
                        data = resp.json()
                        if "balanceCents" in data:
                            balance = data["balanceCents"] / 100.0
                            log(
                                f"✅ 查询成功: 当前积分/余额 【 {balance} 】",
                                "INFO",
                                server_id,
                            )
                        else:
                            log(f"✅ 查询结果: {str(data)[:100]}", "INFO", server_id)
                    except:
                        log(f"✅ 查询成功 (200)", "INFO", server_id)
                elif resp.status_code in [401, 403]:
                    log(f"❌ 查分鉴权失败 ({resp.status_code})", "ERROR", server_id)
            except:
                pass

        log(f"⏳ 等待 {wait_seconds} 秒后继续...", "INFO", server_id)
        time.sleep(max(wait_seconds, 1))
        loop_count += 1

    return True, "心跳线程已安全终止", None
