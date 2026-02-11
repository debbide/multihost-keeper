import requests
from bs4 import BeautifulSoup
import re
import time

def process(session, account, log):
    """
    FreeXCraft 续期模块
    """
    server_id = account.get('server_id')
    dashboard_url = f"https://freexcraft.com/servers/{server_id}/dashboard"
    renew_url = f"https://freexcraft.com/servers/{server_id}/renew"
    
    try:
        # 1. 提取 CSRF
        log(f"访问仪表盘中...", "INFO", server_id)
        resp = session.get(dashboard_url, timeout=30, verify=False)
        
        if resp.status_code != 200:
             return False, f"无法访问仪表盘 (Code: {resp.status_code})", None
             
        soup = BeautifulSoup(resp.text, 'html.parser')
        csrf_meta = soup.find('meta', {'name': 'csrf-token'})
        if not csrf_meta:
            log("未找到 CSRF Token，Cookie 可能已过期", "ERROR", server_id)
            return False, "未找到 CSRF Token", None
            
        csrf_token = csrf_meta.get('content')
        
        # 准备续期请求头
        session.headers.update({
            'Accept': 'application/json, text/plain, */*',
            'Referer': dashboard_url,
            'Origin': 'https://freexcraft.com',
            'X-Requested-With': 'XMLHttpRequest',
            'X-CSRF-TOKEN': csrf_token
        })

        # 2. 续期
        log("发送续期请求...", "INFO", server_id)
        res = session.post(renew_url, timeout=30, verify=False)
        
        success = False
        if res.status_code == 200:
            try:
                data = res.json()
                if data.get('success'): success = True
            except:
                if "success" in res.text.lower(): success = True
        
        if success:
            time.sleep(1)
            # 抓取剩余时间 (重置 Header 以访问 API)
            session.headers.pop('X-Requested-With', None)
            check_resp = session.get(dashboard_url, timeout=30, verify=False)
            time_info = None
            time_matches = re.findall(r'(\d+\s*days?\s*\d+\s*hours?|\d+\s*days?|\d+\s*hours?)', check_resp.text, re.IGNORECASE)
            if time_matches:
                time_info = time_matches[0]
            
            return True, f"续期成功，剩余时间 {time_info}" if time_info else "续期成功", time_info
        else:
            return False, f"续期失败 (Code: {res.status_code})", None
            
    except Exception as e:
        log(f"模块运行异常: {e}", "ERROR", server_id)
        return False, f"异常: {e}", None
