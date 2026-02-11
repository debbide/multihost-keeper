from bs4 import BeautifulSoup
import re
import time

def process(session, account, log):
    """
    LemeHost 续期模块
    """
    server_id = account.get('server_id')
    base_url = "https://lemehost.com"
    free_plan_url = f"{base_url}/server/{server_id}/free-plan"
    
    try:
        log("访问页面中...", "INFO", server_id)
        resp = session.get(free_plan_url, timeout=30, verify=False)
        if resp.status_code != 200:
            return False, f"无法访问页面 (Code: {resp.status_code})", None

        soup = BeautifulSoup(resp.text, 'html.parser')
        csrf_meta = soup.find('meta', {'name': 'csrf-token'})
        if not csrf_meta:
            log("未找到 CSRF Token，Cookie 异常", "ERROR", server_id)
            return False, "未找到 CSRF Token，Cookie 可能已过期", None

        csrf_token = csrf_meta.get('content')

        post_headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'Referer': free_plan_url,
            'Origin': base_url
        }
        log("发送续期请求...", "INFO", server_id)
        session.post(free_plan_url, data={'_csrf-frontend': csrf_token}, headers=post_headers, timeout=30, verify=False)

        time.sleep(2)
        check_resp = session.get(free_plan_url, timeout=30, verify=False)
        time_matches = re.findall(r'(\d{2}:\d{2}:\d{2})', check_resp.text)

        if time_matches:
            remaining = time_matches[0]
            return True, f"续期成功，剩余时间 {remaining}", remaining
        else:
            return False, "未能获取剩余时间", None
    except Exception as e:
        log(f"模块运行异常: {e}", "ERROR", server_id)
        return False, f"异常: {e}", None
