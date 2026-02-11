import requests
from bs4 import BeautifulSoup
import re
import time
import logging

def process(session, account):
    """
    FreeXCraft 续期模块
    """
    server_id = account.get('server_id')
    name = account.get('name')
    dashboard_url = f"https://freexcraft.com/servers/{server_id}/dashboard"
    renew_url = f"https://freexcraft.com/servers/{server_id}/renew"
    
    try:
        # SPA 适配请求头
        session.headers.update({
            'Accept': 'application/json, text/plain, */*',
            'Referer': dashboard_url,
            'X-Requested-With': 'XMLHttpRequest'
        })
        
        # 1. 提取 CSRF
        resp = session.get(dashboard_url, timeout=30, verify=False)
        if resp.status_code != 200:
             return False, f"无法访问仪表盘 (Code: {resp.status_code})", None
             
        soup = BeautifulSoup(resp.text, 'html.parser')
        csrf_meta = soup.find('meta', {'name': 'csrf-token'})
        if not csrf_meta:
            return False, "未找到 CSRF Token", None
            
        csrf_token = csrf_meta.get('content')
        session.headers.update({'X-CSRF-TOKEN': csrf_token})

        # 2. 续期
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
            # 抓取剩余时间
            check_resp = session.get(dashboard_url, timeout=30, verify=False)
            time_info = None
            time_matches = re.findall(r'(\d+\s*days?\s*\d+\s*hours?|\d+\s*days?|\d+\s*hours?)', check_resp.text, re.IGNORECASE)
            if time_matches:
                time_info = time_matches[0]
            
            return True, f"续期成功" + (f"，剩余 {time_info}" if time_info else ""), time_info
        else:
            return False, f"续期失败 (Code: {res.status_code})", None
            
    except Exception as e:
        return False, f"FreeXCraft 模块异常: {e}", None
