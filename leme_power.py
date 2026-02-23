import requests
import json
import time
import sys
import hashlib
import os

# 检查依赖
try:
    import websocket
except ImportError:
    print("提示: 缺少 'websocket-client' 库。")
    print("请执行: pip install websocket-client")
    sys.exit(1)

# ==================== 配置区域 ====================

# 1. 填入你的 LemeHost Cookie (直接从抓包里复制整段内容)
COOKIE = "_ga=GA1.1.1159764315.1764569210; source=2a774c69574a831f9f19ad75d4bba505d382a66cc44cc48099155b5b2e413184a%3A2%3A%7Bi%3A0%3Bs%3A6%3A%22source%22%3Bi%3A1%3Ba%3A5%3A%7Bs%3A10%3A%22created_at%22%3Bi%3A1766489806%3Bs%3A5%3A%22agent%22%3Bs%3A111%3A%22Mozilla%2F5.0%20%28Windows%20NT%2010.0%3B%20Win64%3B%20x64%29%20AppleWebKit%2F537.36%20%28KHTML%2C%20like%20Gecko%29%20Chrome%2F143.0.0.0%20Safari%2F537.36%22%3Bs%3A8%3A%22referrer%22%3BN%3Bs%3A7%3A%22country%22%3Bs%3A2%3A%22SG%22%3Bs%3A2%3A%22ip%22%3Bs%3A35%3A%222603%3Ac02b%3A300%3A3800%3A0%3Ab48a%3Aeaf5%3A5921%22%3B%7D%7D; _identity-frontend=c98b305d9949d30e2fa7037c26aa854411b4d18961dcff560abd01f9589fd864a%3A2%3A%7Bi%3A0%3Bs%3A18%3A%22_identity-frontend%22%3Bi%3A1%3Bs%3A49%3A%22%5B3392%2C%22XWu1EZBA2vW7OeoEnD9aIy-UOEsseWkF%22%2C2592000%5D%22%3B%7D; _csrf-frontend=cde8dd9b96ce525b04bff1093889ad33c25b50a826469b918a1f09089d53cd8da%3A2%3A%7Bi%3A0%3Bs%3A14%3A%22_csrf-frontend%22%3Bi%3A1%3Bs%3A32%3A%22T9YEjW0tV5d8jalaJRuH8VRhnvMKGGHA%22%3B%7D; advanced-frontend=26fel1l2ork8vplobnqldmca6s; _ga_NKPT7KSJVC=GS2.1.s1771157492$o15$g1$t1771158285$j6$l0$h0; _ga_P7XCNLWSKN=GS2.1.s1771157493$o11$g1$t1771158285$j7$l0$h0"

# 2. 填入你抓包获取的 x-csrf-token 那个长字符串
CSRF_TOKEN = "iafsHRxZQGxga7OvI4De-bukq6nOY0q1fJcI1aJ3l4zdnrVYdg5wGDZe15dJ4bKY8fbe4fY1GN0S4UWe5TDfzQ=="

# 3. 填入你的服务器 ID
SERVER_ID = "10018288"

# ================================================

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}")

def get_ws_authorization(session, server_id):
    """ 获取 WebSocket Token 和 Socket 路径 """
    url = "https://lemehost.com/server/token"
    rid = hashlib.md5(os.urandom(32)).hexdigest()
    
    params = {
        "id": server_id,
        "request_id": rid,
        "version": "3",
        "force": "true",
        "ws_token_counter": "1",
        "v": "4",
        "reason": "reason: token expiring args: undefined"
    }
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": f"https://lemehost.com/server/view?id={server_id}",
        "X-Requested-With": "XMLHttpRequest",
        "X-CSRF-TOKEN": CSRF_TOKEN.strip()
    }
    
    try:
        # 在这里执行 GET 请求获取 token 和 socket 地址
        resp = session.get(url, params=params, headers=headers, timeout=20, verify=False)
        if resp.status_code == 200:
            data = resp.json()
            return data.get("token"), data.get("socket")
        else:
            log(f"✘ 获取授权失败 (状态码: {resp.status_code})")
            if "Please wait" in resp.text:
                log("! 检测到防火墙拦截 (Please wait页面)，请确认在你的机器上运行脚本。")
            return None, None
    except Exception as e:
        log(f"✘ 请求异常: {e}")
        return None, None

def on_message(ws, message):
    data = json.loads(message)
    event = data.get("event")
    
    if event == "auth success":
        log("✔ WebSocket 鉴权成功！")
        log("🚀 正在发送开机信号 (power start)...")
        ws.send(json.dumps({"event": "power signal", "args": ["start"]}))
        log("✅ 信号已发送，请刷新网页查看服务器状态。")
        time.sleep(1) # 给服务器留点处理时间
        ws.close()
    elif event == "status":
        log(f"服务器状态更新: {data.get('args')[0]}")
    elif event == "jwt error":
        log("✘ JWT 令牌错误，鉴权失败。")
        ws.close()

def on_error(ws, error):
    log(f"WebSocket 错误: {error}")

def on_close(ws, ccode, cmsg):
    log("WebSocket 连接已关闭。")

def on_open(ws, token):
    log("WebSocket 已连接，正在验证身份...")
    ws.send(json.dumps({"event": "auth", "args": [token]}))

def main():
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    log(f"LemeHost 自动开机工具启动 [服务器ID: {SERVER_ID}]")
    
    # 创建会话并清洗 Cookie
    session = requests.Session()
    session.headers.update({"Cookie": COOKIE.replace('\n', '').strip()})
    
    # 获取授权信息
    token, socket_url = get_ws_authorization(session, SERVER_ID)
    
    if token and socket_url:
        log(f"成功获取授权 Token! [长度: {len(token)}]")
        
        # 建立 WebSocket 连接并发起开机信号
        ws = websocket.WebSocketApp(
            socket_url,
            on_open=lambda ws: on_open(ws, token),
            on_message=on_message,
            on_error=on_error,
            on_close=on_close
        )
        ws.run_forever()
    else:
        log("✘ 无法完成开机操作。")

if __name__ == "__main__":
    main()
