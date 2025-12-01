#!/usr/bin/env python3
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup
import re
import time
import json
import os
import sys
import random
from datetime import datetime, timedelta
import threading
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==================== 配置 ====================
BASE_URL = "https://lemehost.com"
CONFIG_FILE = os.environ.get("CONFIG_FILE", "/app/config/config.json")
LOG_FILE = os.environ.get("LOG_FILE", "/app/logs/lemehost.log")
STATE_FILE = os.environ.get("STATE_FILE", "/app/logs/state.json")

DEFAULT_MIN_INTERVAL = 15
DEFAULT_MAX_INTERVAL = 25

account_states = {}
state_lock = threading.Lock()

# ==================== 配置加载 ====================
def load_config():
    """加载配置文件"""
    if not os.path.exists(CONFIG_FILE):
        return []
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return []

def save_config(accounts):
    """保存配置文件"""
    os.makedirs(os.path.dirname(CONFIG_FILE) or '.', exist_ok=True)
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(accounts, f, ensure_ascii=False, indent=2)

def load_state():
    """加载状态文件"""
    global account_states
    if not os.path.exists(STATE_FILE):
        return
    try:
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            for sid, state in data.items():
                if 'next_run' in state and state['next_run']:
                    state['next_run'] = datetime.fromisoformat(state['next_run'])
                if 'last_run' in state and state['last_run']:
                    state['last_run'] = datetime.fromisoformat(state['last_run'])
                if 'start_time' in state and state['start_time']:
                    state['start_time'] = datetime.fromisoformat(state['start_time'])
            account_states = data
    except Exception:
        pass

def save_state():
    """保存状态文件"""
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        data = {}
        with state_lock:
            for sid, state in account_states.items():
                data[sid] = {
                    'next_run': state.get('next_run').isoformat() if state.get('next_run') else None,
                    'last_run': state.get('last_run').isoformat() if state.get('last_run') else None,
                    'start_time': state.get('start_time').isoformat() if state.get('start_time') else None,
                    'last_result': state.get('last_result'),
                    'remaining_time': state.get('remaining_time')
                }
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

# ==================== 日志函数 ====================
def log(message, level="INFO", server_id=None):
    """同时输出到控制台和文件"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    if server_id:
        log_line = f"[{timestamp}] [{level}] [sid:{server_id}] {message}"
    else:
        log_line = f"[{timestamp}] [{level}] {message}"
    print(log_line)
    sys.stdout.flush()

    try:
        log_dir = os.path.dirname(LOG_FILE)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(log_line + '\n')
    except Exception:
        pass

def get_account_logs(server_id, limit=5):
    """获取指定账号的最近日志"""
    logs = []
    if not os.path.exists(LOG_FILE):
        return logs
    try:
        with open(LOG_FILE, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        pattern = f"[sid:{server_id}]"
        for line in reversed(lines):
            if pattern in line:
                logs.append(line.strip())
                if len(logs) >= limit:
                    break
        logs.reverse()
    except Exception:
        pass
    return logs

# ==================== 状态管理 ====================
def get_account_state(server_id):
    """获取账号状态"""
    with state_lock:
        return account_states.get(server_id, {}).copy()

def get_all_states():
    """获取所有账号状态"""
    with state_lock:
        result = {}
        for sid, state in account_states.items():
            result[sid] = {
                'next_run': state.get('next_run').isoformat() if state.get('next_run') else None,
                'last_run': state.get('last_run').isoformat() if state.get('last_run') else None,
                'start_time': state.get('start_time').isoformat() if state.get('start_time') else None,
                'last_result': state.get('last_result'),
                'remaining_time': state.get('remaining_time')
            }
        return result

def update_account_state(server_id, next_run=None, last_run=None, last_result=None, remaining_time=None, start_time=None):
    """更新账号状态"""
    with state_lock:
        if server_id not in account_states:
            account_states[server_id] = {}
        if next_run is not None:
            account_states[server_id]['next_run'] = next_run
        if last_run is not None:
            account_states[server_id]['last_run'] = last_run
        if last_result is not None:
            account_states[server_id]['last_result'] = last_result
        if remaining_time is not None:
            account_states[server_id]['remaining_time'] = remaining_time
        # start_time 只在首次成功时设置，之后不更新
        if start_time is not None and 'start_time' not in account_states[server_id]:
            account_states[server_id]['start_time'] = start_time
    save_state()

def schedule_next_run(account):
    """计算下次运行时间"""
    min_interval = account.get('min_interval', DEFAULT_MIN_INTERVAL)
    max_interval = account.get('max_interval', DEFAULT_MAX_INTERVAL)
    interval = random.randint(min_interval, max_interval)
    next_run = datetime.now() + timedelta(minutes=interval)
    return next_run, interval

# ==================== 单个账号处理 ====================
def process_account(account):
    """处理单个账号续期，返回 (success, message, remaining_time)"""
    name = account.get('name', '未命名')
    server_id = account.get('server_id')
    cookie = account.get('cookie')

    if not server_id or not cookie:
        return False, "缺少 server_id 或 cookie", None

    free_plan_url = f"{BASE_URL}/server/{server_id}/free-plan"

    log(f"开始处理账号: [{name}]", "INFO", server_id)

    session = requests.Session()

    retry_strategy = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    })

    try:
        for item in cookie.strip().split(';'):
            if '=' in item:
                k, v = item.strip().split('=', 1)
                session.cookies.set(k, v, domain='lemehost.com')
    except Exception as e:
        msg = f"Cookie 格式错误: {e}"
        log(msg, "ERROR", server_id)
        return False, msg, None

    try:
        resp = session.get(free_plan_url, timeout=30, verify=False)
        if resp.status_code != 200:
            msg = f"无法访问页面 (Code: {resp.status_code})"
            log(msg, "ERROR", server_id)
            return False, msg, None

        soup = BeautifulSoup(resp.text, 'html.parser')
        csrf_meta = soup.find('meta', {'name': 'csrf-token'})
        if not csrf_meta:
            msg = "未找到 CSRF Token，Cookie 可能已过期"
            log(msg, "ERROR", server_id)
            return False, msg, None

        csrf_token = csrf_meta.get('content')

        log("发送续期请求...", "INFO", server_id)
        post_headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'Referer': free_plan_url,
            'Origin': BASE_URL
        }
        session.post(free_plan_url, data={'_csrf-frontend': csrf_token}, headers=post_headers, timeout=30, verify=False)

        time.sleep(2)
        check_resp = session.get(free_plan_url, timeout=30, verify=False)
        time_matches = re.findall(r'(\d{2}:\d{2}:\d{2})', check_resp.text)

        if time_matches:
            remaining = time_matches[0]
            msg = f"续期成功，剩余时间 {remaining}"
            log(msg, "SUCCESS", server_id)
            return True, msg, remaining
        else:
            msg = "未能获取剩余时间，可能需要手动检查"
            log(msg, "WARNING", server_id)
            return False, msg, None

    except Exception as e:
        msg = f"异常: {e}"
        log(msg, "ERROR", server_id)
        return False, msg, None

# ==================== 后台定时任务 ====================
def account_worker(account):
    """单个账号的工作线程"""
    server_id = account.get('server_id')
    name = account.get('name', '未命名')

    success, msg, remaining = process_account(account)
    update_account_state(
        server_id,
        last_run=datetime.now(),
        last_result='success' if success else 'failed',
        remaining_time=remaining,
        start_time=datetime.now() if success else None
    )

    while True:
        accounts = load_config()
        current_acc = None
        for acc in accounts:
            if acc.get('server_id') == server_id:
                current_acc = acc
                break

        if not current_acc:
            log(f"账号 [{name}] 已被删除，停止任务", "INFO", server_id)
            break

        if not current_acc.get('enabled', True):
            time.sleep(60)
            continue

        next_run, interval = schedule_next_run(current_acc)
        update_account_state(server_id, next_run=next_run)
        log(f"下次运行: {next_run.strftime('%H:%M:%S')} (间隔 {interval} 分钟)", "INFO", server_id)

        while datetime.now() < next_run:
            time.sleep(10)
            accounts = load_config()
            still_exists = False
            for acc in accounts:
                if acc.get('server_id') == server_id:
                    still_exists = True
                    if not acc.get('enabled', True):
                        break
            if not still_exists:
                break

        accounts = load_config()
        current_acc = None
        for acc in accounts:
            if acc.get('server_id') == server_id:
                current_acc = acc
                break

        if not current_acc:
            break

        if not current_acc.get('enabled', True):
            continue

        success, msg, remaining = process_account(current_acc)
        update_account_state(
            server_id,
            last_run=datetime.now(),
            last_result='success' if success else 'failed',
            remaining_time=remaining,
            start_time=datetime.now() if success else None
        )

worker_threads = {}
worker_lock = threading.Lock()

def start_account_worker(account):
    """启动单个账号的工作线程"""
    server_id = account.get('server_id')
    with worker_lock:
        if server_id in worker_threads and worker_threads[server_id].is_alive():
            return False
        thread = threading.Thread(target=account_worker, args=(account,), daemon=True)
        thread.start()
        worker_threads[server_id] = thread
    return True

def background_task():
    """后台主任务：监控配置变化并管理工作线程"""
    log("="*40)
    log("LemeHost 自动续期服务启动")
    log("="*40)

    load_state()
    known_accounts = set()

    while True:
        accounts = load_config()
        current_ids = set()

        for acc in accounts:
            server_id = acc.get('server_id')
            if not server_id:
                continue
            current_ids.add(server_id)

            if server_id not in known_accounts:
                if acc.get('enabled', True):
                    log(f"发现新账号: [{acc.get('name', '未命名')}]", "INFO", server_id)
                    start_account_worker(acc)
                known_accounts.add(server_id)

        removed = known_accounts - current_ids
        for sid in removed:
            known_accounts.discard(sid)
            with state_lock:
                account_states.pop(sid, None)

        time.sleep(30)

def start_background_task():
    """启动后台任务线程"""
    thread = threading.Thread(target=background_task, daemon=True)
    thread.start()
    return thread

# ==================== 主入口 ====================
if __name__ == "__main__":
    background_task()
