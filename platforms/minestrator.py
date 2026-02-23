import time
import subprocess
import json

def process(session, account, log):
    """
    Minestrator 续期模块 (底层使用 curl 绕过 TLS 风控)
    """
    server_id = account.get("server_id")
    api_key = account.get("minestrator_api_key")
    api_url = (
        account.get("minestrator_api_url")
        or f"https://mine.sttr.io/server/{server_id}/poweraction"
    )
    user_agent = (
        account.get("minestrator_user_agent")
        or "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    )
    wait_seconds = account.get("minestrator_wait_seconds", 30)

    if not server_id or not api_key:
        return False, "缺少 Server ID 或 API Key", None

    try:
        wait_seconds = int(wait_seconds)
    except (TypeError, ValueError):
        wait_seconds = 30

    # 从 session 中提取配置好的代理
    proxy = session.proxies.get("https") or session.proxies.get("http")
    token = account.get("minestrator_turnstile_token")

    def do_curl_request(action):
        payload = {"poweraction": action}
        if token:
            payload["turnstile_token"] = token
            
        cmd = [
            "curl", "-s", "-X", "PUT", api_url,
            "-H", f"Authorization: Bearer {api_key}",
            "-H", "Content-Type: application/json",
            "-H", "Origin: https://minestrator.com",
            "-H", f"User-Agent: {user_agent}",
            "-d", json.dumps(payload),
            "-w", "\n%{http_code}"
        ]
        
        if proxy:
            cmd.extend(["-x", proxy])
            
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if not result.stdout:
                return 0, ""
            
            # 提取正文和由于 -w 输出在末尾的状态码
            lines = result.stdout.strip().rsplit("\n", 1)
            if len(lines) == 2:
                body, code = lines
            else:
                body, code = "", lines[0]
                
            return int(code), body
        except Exception as e:
            return 0, str(e)

    try:
        log("发送 Kill 指令 (via curl)...", "INFO", server_id)
        kill_code, kill_body = do_curl_request("kill")
        log(f"Kill 返回: {kill_code} {kill_body[:100]}", "INFO", server_id)

        log(f"等待 {wait_seconds} 秒...", "INFO", server_id)
        time.sleep(max(wait_seconds, 1))

        log("发送 Start 指令 (via curl)...", "INFO", server_id)
        start_code, start_body = do_curl_request("start")
        if start_code != 200:
            log(f"Start 失败详情: {start_body}", "WARNING", server_id)
        log(f"Start 返回: {start_code} {start_body[:100]}", "INFO", server_id)

        if start_code in (200, 204):
            return True, "保活启动成功", None
        if start_code == 401:
            return False, "授权失效 (401)，请更新 API Key", None
        return False, f"启动异常，返回码: {start_code}", None
    except Exception as e:
        log(f"模块运行异常: {e}", "ERROR", server_id)
        return False, f"异常: {e}", None
