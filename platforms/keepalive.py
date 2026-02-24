import time
from urllib.parse import unquote


def process(session, account, log):
    """
    KeepAlive 演示模块
    """
    server_id = account.get("server_id")
    loop_count = account.get("keepalive_loop_count", 1)
    wait_seconds = account.get("keepalive_wait_seconds", 60)
    heartbeat_url = account.get("keepalive_heartbeat_url", "").strip()
    check_url = account.get("keepalive_check_url", "").strip()
    
    # 解析凭证：智能识别 Token 和 Cookie
    credential = account.get("cookie", "").strip()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        "Sec-CH-UA": '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
        "Sec-CH-UA-Mobile": "?0",
        "Sec-CH-UA-Platform": '"Windows"',
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-site",
        "Connection": "keep-alive"
    }
    
    if credential:
        if credential.startswith("Bearer "):
            headers["Authorization"] = credential
        elif "=" in credential:
            headers["Cookie"] = credential
            # 自动将 Cookie 注入 Session 以便后续提取 XSRF-TOKEN
            for item in credential.split(';'):
                if '=' in item:
                    k, v = item.strip().split('=', 1)
                    session.cookies.set(k.strip(), v.strip())
        elif len(credential.split("-")) >= 4:
            headers["Authorization"] = f"Bearer {credential}"
        else:
            headers["Cookie"] = credential

    if heartbeat_url and "altare.sh" in heartbeat_url:
        headers["Origin"] = "https://altare.sh"
        headers["Referer"] = "https://altare.sh/billing/rewards/afk"

    try:
        wait_seconds = int(wait_seconds)
    except (TypeError, ValueError):
        wait_seconds = 60

    # 循环计数器，因为我们在单次调度内执行死循环挂机
    # loop_count = 1 # This line was removed as per instruction

    while True:
        log("=" * 40, "INFO", server_id)
        log(f"📍 第 {loop_count} 次循环", "INFO", server_id)
        log("=" * 40, "INFO", server_id)

        if heartbeat_url:
            try:
                # 自动关联 XSRF 令牌 (从刚才注入或上一轮返回的 Cookie 中提取)
                for k, v in session.cookies.items():
                    if k == "XSRF-TOKEN":
                        headers["X-XSRF-TOKEN"] = unquote(v)

                log("❤️ 发送心跳请求...", "INFO", server_id)
                # Altare.sh 强制要求使用 POST 才能拿积分
                if "altare.sh" in heartbeat_url:
                    resp = session.post(heartbeat_url, headers=headers, timeout=15, verify=False)
                else:
                    # 其他普通的挂机网址默认用 GET
                    resp = session.get(heartbeat_url, headers=headers, timeout=15, verify=False)
                
                if resp.status_code == 200:
                    log(f"✅ 心跳成功 (200)", "INFO", server_id)
                elif resp.status_code in [401, 403]:
                    log(f"❌ 权限被拦截 ({resp.status_code}): 请检查 Token 是否过期或 IP 被标记", "ERROR", server_id)
                else:
                    log(f"⚠️ 心跳异常 ({resp.status_code})", "WARNING", server_id)
            except Exception as e:
                log(f"❌ 心跳网络异常: {e}", "ERROR", server_id)
                # 心跳失败时不立刻退出，而是等待下一轮重试
        else:
            log("✅ 伪装心跳成功", "INFO", server_id)

        if check_url:
            try:
                log("💰 查询钱包/详情...", "INFO", server_id)
                resp = session.get(check_url, headers=headers, timeout=15, verify=False)
                if resp.status_code == 200:
                    try:
                        data = resp.json()
                        # 尝试专门针对 altare 等返回 balanceCents 的结构提取金额
                        if "balanceCents" in data:
                            balance = data["balanceCents"] / 100.0
                            log(f"✅ 查询成功: 当前积分/余额为 {balance}", "INFO", server_id)
                        else:
                            log(f"✅ 查询结果: {str(data)[:100]}", "INFO", server_id)
                    except:
                        log(f"✅ 查询成功 (200)", "INFO", server_id)
                elif resp.status_code in [401, 403]:
                    log(f"❌ 查询鉴权失败 ({resp.status_code})", "ERROR", server_id)
                else:
                    log(f"⚠️ 查询返回异常代码: {resp.status_code}", "WARNING", server_id)
            except Exception as e:
                log(f"❌ 查询执行异常: {e}", "WARNING", server_id)

        log(f"⏳ 等待 {wait_seconds} 秒后继续...", "INFO", server_id)
        time.sleep(max(wait_seconds, 1))
        loop_count += 1

    # 由于是无限挂机，下方理论上不可达，但在发生不可恢复异常时跳出
    return True, "心跳完成", None
