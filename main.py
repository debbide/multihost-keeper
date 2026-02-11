#!/usr/bin/env python3
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import re
import time
import json
import os
import sys
import random
from datetime import datetime, timedelta
import threading
import urllib3
import importlib
import io

# 强制设置输出编码为 UTF-8
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==================== 配置 ====================
CONFIG_FILE = os.environ.get("CONFIG_FILE", "/app/config/config.json")
LOG_FILE = os.environ.get("LOG_FILE", "/app/logs/lemehost.log")
STATE_FILE = os.environ.get("STATE_FILE", "/app/logs/state.json")

DEFAULT_MIN_INTERVAL = 15
DEFAULT_MAX_INTERVAL = 25

account_states = {}
state_lock = threading.Lock()

# ==================== 动态模块加载 ====================
def get_platform_module(server_id):
    """
    根据 server_id 识别并加载对应的平台模块
    """
    if re.match(r'^[0-9a-fA-F-]{36}$', str(server_id)):
        pkg = "platforms.freexcraft"
        domain = "freexcraft.com"
    else:
        pkg = "platforms.lemehost"
        domain = "lemehost.com"
    
    try:
        module = importlib.import_module(pkg)
        return module, domain
    except Exception as e:
        print(f"加载模块 {pkg} 失败: {e}")
        return None, None

# ==================== 配置加载 ====================
def load_config():
    if not os.path.exists(CONFIG_FILE): return []
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception: return []

def save_config(accounts):
    os.makedirs(os.path.dirname(CONFIG_FILE) or '.', exist_ok=True)
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(accounts, f, ensure_ascii=False, indent=2)

def load_state():
    global account_states
    if not os.path.exists(STATE_FILE): return
    try:
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            for sid, state in data.items():
                for k in ['next_run', 'last_run', 'start_time']:
                    if state.get(k): state[k] = datetime.fromisoformat(state[k])
            account_states = data
    except Exception: pass

def save_state():
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
    except Exception: pass

def log(message, level="INFO", server_id=None):
    """
    自愈式日志格式：适配用户审美 [HH:MM:SS] 消息
    文件的末尾附加 [sid:xxx] 用于 Web 端过滤
    """
    now = datetime.now()
    time_str = now.strftime('%H:%M:%S')
    
    # 纯净显示格式 (用于 print 和用户阅读)
    display_line = f"{time_str} {message}"
    
    # 持久化格式 (包含 sid 以供后端过滤)
    log_line = display_line
    if server_id:
        log_line += f" [sid:{server_id}]"
    
    print(display_line)
    sys.stdout.flush()
    try:
        log_dir = os.path.dirname(LOG_FILE)
        if log_dir: os.makedirs(log_dir, exist_ok=True)
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(log_line + '\n')
    except Exception: pass

def get_account_logs(server_id, limit=5):
    logs = []
    if not os.path.exists(LOG_FILE): return logs
    try:
        with open(LOG_FILE, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        pattern = f"[sid:{server_id}]"
        for line in reversed(lines):
            if pattern in line:
                # 返回时不带 sid 后缀，保持界面整洁
                clean_line = line.replace(pattern, "").strip()
                logs.append(clean_line)
                if len(logs) >= limit: break
        logs.reverse()
    except Exception: pass
    return logs

def get_all_states():
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

def update_account_state(server_id, **kwargs):
    with state_lock:
        if server_id not in account_states: account_states[server_id] = {}
        for k, v in kwargs.items():
            if v is not None:
                if k == 'start_time' and 'start_time' in account_states[server_id]: continue
                account_states[server_id][k] = v
    save_state()

def schedule_next_run(account):
    interval = random.randint(account.get('min_interval', DEFAULT_MIN_INTERVAL), 
                              account.get('max_interval', DEFAULT_MAX_INTERVAL))
    return datetime.now() + timedelta(minutes=interval), interval

# ==================== 核心处理逻辑 ====================
def process_account(account):
    name = account.get('name', '未命名')
    server_id = account.get('server_id')
    cookie = account.get('cookie')
    if not server_id or not cookie: return False, "缺少 ID 或 Cookie", None

    module, domain = get_platform_module(server_id)
    if not module: return False, "平台模块加载失败", None

    log(f"开始处理账号: [{name}]", "INFO", server_id)

    session = requests.Session()
    adapter = HTTPAdapter(max_retries=Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504]))
    session.mount("https://", adapter)
    session.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'})

    try:
        for item in cookie.strip().split(';'):
            if '=' in item:
                k, v = item.strip().split('=', 1)
                session.cookies.set(k, v, domain=domain)
    except Exception as e:
        return False, f"Cookie 解析失败: {e}", None

    try:
        # 将 log 函数注入模块
        return module.process(session, account, log)
    except Exception as e:
        return False, f"调用模块出错: {e}", None

# ==================== 定时任务逻辑 ====================
def account_worker(account):
    server_id = account.get('server_id')
    def run():
        success, msg, remaining = process_account(account)
        update_account_state(server_id, last_run=datetime.now(), 
                             last_result='success' if success else 'failed',
                             remaining_time=remaining, start_time=datetime.now() if success else None)
        return success

    run()
    while True:
        acc = next((a for a in load_config() if a.get('server_id') == server_id), None)
        if not acc: break
        if not acc.get('enabled', True):
            time.sleep(60); continue

        next_run, interval = schedule_next_run(acc)
        update_account_state(server_id, next_run=next_run)
        log(f"下次运行: {next_run.strftime('%H:%M:%S')} (间隔 {interval} 分钟)", "INFO", server_id)

        while datetime.now() < next_run:
            time.sleep(10)
            if not next((a for a in load_config() if a.get('server_id') == server_id), None): return

        run()

worker_threads = {}
worker_lock = threading.Lock()

def start_account_worker(account):
    sid = account.get('server_id')
    with worker_lock:
        if sid in worker_threads and worker_threads[sid].is_alive(): return False
        t = threading.Thread(target=account_worker, args=(account,), daemon=True)
        t.start()
        worker_threads[sid] = t
    return True

def background_task():
    log("="*30)
    log("模块化续期服务已启动")
    log("="*30)
    load_state()
    known = set()
    while True:
        accounts = load_config()
        current = {acc.get('server_id') for acc in accounts if acc.get('server_id')}
        for acc in accounts:
            sid = acc.get('server_id')
            if sid and sid not in known:
                if acc.get('enabled', True): start_account_worker(acc)
                known.add(sid)
        for sid in (known - current):
            known.discard(sid)
            with state_lock: account_states.pop(sid, None)
        time.sleep(30)

def start_background_task():
    t = threading.Thread(target=background_task, daemon=True)
    t.start()
    return t

if __name__ == "__main__":
    background_task()
