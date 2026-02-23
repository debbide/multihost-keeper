import time


def process(session, account, log):
    """
    KeepAlive 演示模块
    """
    server_id = account.get("server_id")
    loop_count = account.get("keepalive_loop_count", 1)
    wait_seconds = account.get("keepalive_wait_seconds", 60)
    heartbeat_url = account.get("keepalive_heartbeat_url", "").strip()
    check_url = account.get("keepalive_check_url", "").strip()
    
    # 提取用户配在 Cookie 栏里的身份凭证（支持 Raw Cookie 或 Bearer Token）
    credential = account.get("cookie", "").strip()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
        "Accept": "*/*"
    }
    
    if credential:
        if credential.startswith("Bearer "):
            headers["Authorization"] = credential
        else:
            # 如果用户没加 Bearer 前缀但看起来像 UUID token
            if len(credential.split("-")) >= 4 and " " not in credential and "=" not in credential:
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
    loop_count = 1

    while True:
        log("=" * 40, "INFO", server_id)
        log(f"📍 第 {loop_count} 次循环", "INFO", server_id)
        log("=" * 40, "INFO", server_id)

        if heartbeat_url:
            try:
                log("❤️ 发送心跳请求...", "INFO", server_id)
                # Altare.sh 强制要求使用 POST 才能拿积分
                if "altare.sh" in heartbeat_url:
                    resp = session.post(heartbeat_url, headers=headers, timeout=15)
                else:
                    # 其他普通的挂机网址默认用 GET
                    resp = session.get(heartbeat_url, headers=headers, timeout=15)
                
                log(f"✅ 心跳成功 ({resp.status_code})", "INFO", server_id)
            except Exception as e:
                log(f"❌ 心跳失败: {e}", "ERROR", server_id)
                # 心跳失败时不立刻退出，而是等待下一轮重试
        else:
            log("✅ 伪装心跳成功", "INFO", server_id)

        if check_url:
            try:
                log("💰 查询钱包/详情...", "INFO", server_id)
                resp = session.get(check_url, headers=headers, timeout=15)
                try:
                    data = resp.json()
                    # 尝试专门针对 altare 等返回 balanceCents 的结构提取金额
                    if "balanceCents" in data:
                        balance = data["balanceCents"] / 100.0
                        log(f"✅ 查询成功: 当前积分/余额为 {balance}", "INFO", server_id)
                    else:
                        log(f"✅ 查询成功 ({resp.status_code}): {str(data)[:150]}", "INFO", server_id)
                except:
                    log(f"✅ 查询成功 ({resp.status_code})", "INFO", server_id)
            except Exception as e:
                log(f"❌ 查询失败: {e}", "WARNING", server_id)

        log(f"⏳ 等待 {wait_seconds} 秒后继续...", "INFO", server_id)
        time.sleep(max(wait_seconds, 1))
        loop_count += 1

    # 由于是无限挂机，下方理论上不可达，但在发生不可恢复异常时跳出
    return True, "心跳完成", None
