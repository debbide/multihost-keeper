import requests
import re
import time
import json
import urllib3
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# 禁用不安全请求警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def log(message, level="INFO"):
    timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{timestamp}] [{level}] {message}")

def renew_freexcraft(server_id, cookie):
    """
    FreeXCraft 自动化续期独立脚本
    :param server_id: 服务器 UUID (在仪表盘 URL 中)
    :param cookie: 浏览器中的完整 Cookie 字符串
    """
    dashboard_url = f"https://freexcraft.com/servers/{server_id}/dashboard"
    renew_url = f"https://freexcraft.com/servers/{server_id}/renew"
    
    session = requests.Session()
    
    # 设置重试策略
    retry_strategy = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    })

    # 设置 Cookie
    try:
        domain = "freexcraft.com"
        for item in cookie.strip().split(';'):
            if '=' in item:
                k, v = item.strip().split('=', 1)
                session.cookies.set(k, v, domain=domain)
    except Exception as e:
        log(f"Cookie 解析失败: {e}", "ERROR")
        return False

    try:
        log(f"正在访问仪表盘: {server_id}")
        # 获取 CSRF Token
        session.headers.update({
            'Accept': 'application/json, text/plain, */*',
            'Referer': dashboard_url,
            'X-Requested-With': 'XMLHttpRequest'
        })
        
        resp = session.get(dashboard_url, timeout=30, verify=False)
        if resp.status_code != 200:
            log(f"无法访问仪表盘 (状态码: {resp.status_code})", "ERROR")
            return False
            
        soup = BeautifulSoup(resp.text, 'html.parser')
        csrf_meta = soup.find('meta', {'name': 'csrf-token'})
        if not csrf_meta:
            log("未找到 CSRF Token，请检查 Cookie 是否有效", "ERROR")
            return False
            
        csrf_token = csrf_meta.get('content')
        session.headers.update({'X-CSRF-TOKEN': csrf_token})

        log("发送续期请求...")
        res = session.post(renew_url, timeout=30, verify=False)
        
        if res.status_code == 200:
            log("续期请求成功！", "SUCCESS")
            # 尝试提取时间（可选，找不到也不报错）
            try:
                time.sleep(1)
                check = session.get(dashboard_url, timeout=20, verify=False)
                # 寻找日期格式或时间格式
                m = re.search(r'(\d+\s*days?\s*\d+\s*hours?|\d+\s*days?|\d+\s*hours?)', check.text, re.I)
                if m:
                    log(f"当前剩余时间: {m.group(0)}", "SUCCESS")
            except:
                pass
            return True
        else:
            log(f"续期失败 (状态码: {res.status_code})", "ERROR")
            return False
            
    except Exception as e:
        log(f"运行异常: {e}", "ERROR")
        return False

if __name__ == "__main__":
    # --- 配置区域 ---
    # 你可以把这段信息填好，或者使用环境变量
    import os
    SERVER_ID = "4c1bbc0c-9859-44a9-b114-991fa5ca5c00"
    COOKIE = "_ga=GA1.1.1371832604.1770647459; FCCDCF=%5Bnull%2Cnull%2Cnull%2Cnull%2Cnull%2Cnull%2C%5B%5B32%2C%22%5B%5C%22f74b12f1-0f68-4566-b99b-4814752a10f6%5C%22%2C%5B1770647454%2C861000000%5D%5D%22%5D%5D%5D; FCNEC=%5B%5B%22AKsRol-nr1IuPvfGejU1iHW8YfMcn6iH4fytmiznO3bqIB9UEE6MWVB4B4OveDo7S-pdlPWENyziC1e4h0Q_cXkrNrp9oHCibl8mPPJUkXdjLVn86er4h91EBXztZ_J-6_8qs72i08FFhZsWSANPc0jPpkZNJpaRxQ%3D%3D%22%5D%5D; _ga_8KHW58GCFV=GS2.1.s1770802282$o3$g1$t1770804457$j53$l0$h225941840; XSRF-TOKEN=eyJpdiI6IlhyaVd5Mnh3RmVqaDdpTDdjUzlFbGc9PSIsInZhbHVlIjoiTHZKWjRNbUtTL3h5dGlDL1JDd1NEZ05OdXpIaXFKcWJSV3FIRXRnQzJOendTVC9nZjBrZXB1K255SzRqbEIvTkFYcFdWNGZnN1pacU9DYnpiQXA4UnNiRFp3RHJFVFNnSEdLOTc4V2hibUQ0TVRaU1dtdXNJRTNvc3BramRhTksiLCJtYWMiOiJjYjRiYjBlOTRiYzNlN2NhOTg3MDI0NjNmZmFiNjIwYmVlNjYyOGM1ODkzMDJhNThkNmRlY2I5OTk3YTFjODkzIiwidGFnIjoiIn0%3D; freexcraft_session=eyJpdiI6IkdqOG9JckhOSE1iQXViQnFDbWRqNXc9PSIsInZhbHVlIjoidWt2TXJpcEdQRjQ2SnJwTTgvb3A4blhhNE0vVFdWSy9OVWZtaFRMRncyOCtBR3R3K0k4aWU1QSsvdnhiaC9XSTZMUkF4b04xbDNSTmlDUHJyTWd5d0c0aWM3dmx6OGV2YTZndEFqSW5QNStsYlJyWGZDT1A3RmtWSEVkazBGZ2YiLCJtYWMiOiJjNWRmMDgyODFhNDYzNWY4MTZmMmY0N2U3ZjVkMGMyZDVjZDQ1MzFhZGRkZDJmZDAxZTk0YTE3ZGE0ZTU2MGMwIiwidGFnIjoiIn0%3D"
    # --- END ---

    renew_freexcraft(SERVER_ID, COOKIE)
