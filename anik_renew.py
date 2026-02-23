import requests
import time
import os
import random
from datetime import datetime

# ==================== 配置区域 ====================

# 在这里填入你的 Cookie (PHPSESSID 等)
COOKIE = "PHPSESSID=holpoukooa2o8d63i5hanujhua; aiBotPromoDismissed=true"

# 要重启的服务器 ID 列表（数字 ID）
SERVER_IDS = [
    2860,
    # 如果有多个，可以继续添加，例如: 2861,
]

# 自动重启间隔 (秒)
# 默认 24 小时 (86400秒) 重启一次。
INTERVAL = 60 * 60 * 24

# ================================================

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def restart_server(server_id):
    """
    发送重启请求
    URL: https://anikbothosting.de/bot-action.php?action=restart&id={id}
    Method: GET
    """
    url = f"https://anikbothosting.de/bot-action.php"
    params = {
        "action": "restart",
        "id": server_id
    }
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36",
        "Cookie": COOKIE,
        "Referer": f"https://anikbothosting.de/bot-details.php?id={server_id}",
        "X-Requested-With": "XMLHttpRequest", # 关键头：表明是 AJAX 请求
        "Accept": "application/json",
    }
    
    try:
        log(f"正在发送重启指令: [ID: {server_id}]")
        # 必须使用 GET 请求，参数直接拼在 URL 里 (requests 会自动处理 params)
        resp = requests.get(url, params=params, headers=headers, timeout=30)
        
        if resp.status_code == 200:
            log(f"重启请求已发送 (Code: 200)")
            return True
        else:
            log(f"重启失败 (Code: {resp.status_code})")
            log(f"响应内容: {resp.text[:100]}...")
            return False
            
    except Exception as e:
        log(f"请求异常: {e}")
        return False

def main():
    log("AnikBotHosting 自动重启脚本已启动")
    log(f"目标服务器数: {len(SERVER_IDS)}")
    
    while True:
        for sid in SERVER_IDS:
            restart_server(sid)
            # 随机等待，避免并发过快
            time.sleep(random.randint(5, 10))
            
        log(f"本轮任务结束，等待 {INTERVAL} 秒后再次运行...")
        time.sleep(INTERVAL)

if __name__ == "__main__":
    main()
