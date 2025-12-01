#!/usr/bin/env python3
from flask import Flask, request, jsonify, session, render_template, redirect, url_for
import json
import os
import secrets
from functools import wraps
from main import (
    load_config, save_config, process_account, get_account_logs,
    start_background_task, get_all_states, update_account_state,
    DEFAULT_MIN_INTERVAL, DEFAULT_MAX_INTERVAL
)

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', secrets.token_hex(32))

AUTH_FILE = os.environ.get('AUTH_FILE', '/app/config/auth.json')

# ==================== 认证相关 ====================
def load_auth():
    """加载认证配置"""
    if not os.path.exists(AUTH_FILE):
        return {'username': 'admin', 'password': 'admin123'}
    try:
        with open(AUTH_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {'username': 'admin', 'password': 'admin123'}

def save_auth(auth_data):
    """保存认证配置"""
    try:
        auth_dir = os.path.dirname(AUTH_FILE)
        if auth_dir:
            os.makedirs(auth_dir, exist_ok=True)
        with open(AUTH_FILE, 'w', encoding='utf-8') as f:
            json.dump(auth_data, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False

def login_required(f):
    """登录验证装饰器"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            if request.is_json:
                return jsonify({'error': '未登录'}), 401
            return redirect(url_for('login_page'))
        return f(*args, **kwargs)
    return decorated_function

# ==================== 页面路由 ====================
@app.route('/')
def index_page():
    if not session.get('logged_in'):
        return redirect(url_for('login_page'))
    return render_template('index.html')

@app.route('/login')
def login_page():
    if session.get('logged_in'):
        return redirect(url_for('index_page'))
    return render_template('login.html')

# ==================== API 路由 ====================
@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.get_json()
    username = data.get('username', '')
    password = data.get('password', '')

    auth = load_auth()
    if username == auth['username'] and password == auth['password']:
        session['logged_in'] = True
        session.permanent = True
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': '用户名或密码错误'}), 401

@app.route('/api/logout', methods=['POST'])
def api_logout():
    session.clear()
    return jsonify({'success': True})

@app.route('/api/change-password', methods=['POST'])
@login_required
def change_password():
    """修改密码"""
    data = request.get_json()
    old_password = data.get('old_password', '').strip()
    new_password = data.get('new_password', '').strip()
    confirm_password = data.get('confirm_password', '').strip()

    if not old_password or not new_password or not confirm_password:
        return jsonify({'success': False, 'error': '所有字段都是必填的'}), 400

    if new_password != confirm_password:
        return jsonify({'success': False, 'error': '两次输入的新密码不一致'}), 400

    if len(new_password) < 6:
        return jsonify({'success': False, 'error': '新密码长度至少6位'}), 400

    auth = load_auth()
    if old_password != auth['password']:
        return jsonify({'success': False, 'error': '旧密码错误'}), 400

    auth['password'] = new_password
    if save_auth(auth):
        return jsonify({'success': True, 'message': '密码修改成功'})
    else:
        return jsonify({'success': False, 'error': '保存失败，请重试'}), 500

@app.route('/api/accounts', methods=['GET'])
@login_required
def get_accounts():
    accounts = load_config()
    states = get_all_states()

    result_accounts = []
    for acc in accounts:
        server_id = acc.get('server_id', '')
        state = states.get(server_id, {})
        result_acc = {
            'name': acc.get('name', ''),
            'server_id': server_id,
            'enabled': acc.get('enabled', True),
            'cookie': acc.get('cookie', ''),
            'min_interval': acc.get('min_interval', DEFAULT_MIN_INTERVAL),
            'max_interval': acc.get('max_interval', DEFAULT_MAX_INTERVAL),
            'next_run': state.get('next_run'),
            'last_run': state.get('last_run'),
            'start_time': state.get('start_time'),
            'last_result': state.get('last_result'),
            'remaining_time': state.get('remaining_time')
        }
        result_accounts.append(result_acc)
    return jsonify(result_accounts)

@app.route('/api/accounts', methods=['POST'])
@login_required
def add_account():
    data = request.get_json()
    name = data.get('name', '').strip()
    server_id = data.get('server_id', '').strip()
    cookie = data.get('cookie', '').strip()
    min_interval = data.get('min_interval', DEFAULT_MIN_INTERVAL)
    max_interval = data.get('max_interval', DEFAULT_MAX_INTERVAL)

    if not name or not server_id or not cookie:
        return jsonify({'error': '名称、Server ID 和 Cookie 都是必填的'}), 400

    try:
        min_interval = int(min_interval)
        max_interval = int(max_interval)
        if min_interval < 1 or max_interval < 1:
            return jsonify({'error': '时间间隔必须大于 0'}), 400
        if min_interval > max_interval:
            return jsonify({'error': '最小间隔不能大于最大间隔'}), 400
    except (TypeError, ValueError):
        return jsonify({'error': '时间间隔必须是数字'}), 400

    accounts = load_config()

    for acc in accounts:
        if acc.get('server_id') == server_id:
            return jsonify({'error': f'Server ID {server_id} 已存在'}), 400

    new_account = {
        'name': name,
        'server_id': server_id,
        'cookie': cookie,
        'enabled': True,
        'min_interval': min_interval,
        'max_interval': max_interval
    }
    accounts.append(new_account)

    try:
        save_config(accounts)
    except Exception as e:
        return jsonify({'error': f'保存失败: {str(e)}'}), 500

    return jsonify({'success': True})

@app.route('/api/accounts/<server_id>', methods=['PUT'])
@login_required
def update_account(server_id):
    data = request.get_json()
    accounts = load_config()

    for acc in accounts:
        if acc.get('server_id') == server_id:
            if 'name' in data:
                acc['name'] = data['name'].strip()
            if 'cookie' in data and data['cookie'].strip():
                acc['cookie'] = data['cookie'].strip()
            if 'enabled' in data:
                acc['enabled'] = data['enabled']
            if 'min_interval' in data:
                try:
                    acc['min_interval'] = int(data['min_interval'])
                except (TypeError, ValueError):
                    pass
            if 'max_interval' in data:
                try:
                    acc['max_interval'] = int(data['max_interval'])
                except (TypeError, ValueError):
                    pass
            # 支持修改 server_id
            if 'server_id' in data and data['server_id'].strip() and data['server_id'] != server_id:
                new_server_id = data['server_id'].strip()
                for other in accounts:
                    if other.get('server_id') == new_server_id:
                        return jsonify({'error': f'Server ID {new_server_id} 已存在'}), 400
                # 更新状态文件中的 ID
                try:
                    state_file = os.environ.get('STATE_FILE', '/app/logs/state.json')
                    if os.path.exists(state_file):
                        with open(state_file, 'r', encoding='utf-8') as f:
                            states = json.load(f)
                        if server_id in states:
                            states[new_server_id] = states.pop(server_id)
                            with open(state_file, 'w', encoding='utf-8') as f:
                                json.dump(states, f, indent=2, ensure_ascii=False)
                except Exception:
                    pass
                acc['server_id'] = new_server_id
            save_config(accounts)
            return jsonify({'success': True})

    return jsonify({'error': '账号不存在'}), 404

@app.route('/api/accounts/<server_id>', methods=['DELETE'])
@login_required
def delete_account(server_id):
    accounts = load_config()
    new_accounts = [acc for acc in accounts if acc.get('server_id') != server_id]

    if len(new_accounts) == len(accounts):
        return jsonify({'error': '账号不存在'}), 404

    save_config(new_accounts)
    return jsonify({'success': True})

@app.route('/api/accounts/<server_id>/renew', methods=['POST'])
@login_required
def renew_account(server_id):
    try:
        accounts = load_config()

        for acc in accounts:
            if acc.get('server_id') == server_id:
                try:
                    success, message, remaining = process_account(acc)
                except Exception as e:
                    return jsonify({
                        'success': False,
                        'message': f'续期异常: {str(e)}'
                    })
                from datetime import datetime
                update_account_state(
                    server_id,
                    last_run=datetime.now(),
                    last_result='success' if success else 'failed',
                    remaining_time=remaining,
                    start_time=datetime.now() if success else None
                )
                return jsonify({
                    'success': success,
                    'message': message,
                    'remaining_time': remaining
                })

        return jsonify({'error': '账号不存在'}), 404
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'服务器错误: {str(e)}'
        }), 500

@app.route('/api/accounts/<server_id>/logs', methods=['GET'])
@login_required
def get_logs(server_id):
    limit = request.args.get('limit', 5, type=int)
    logs = get_account_logs(server_id, limit)
    return jsonify(logs)

@app.route('/api/states', methods=['GET'])
@login_required
def get_states():
    """获取所有账号的运行状态"""
    return jsonify(get_all_states())

# ==================== 启动 ====================
if __name__ == '__main__':
    start_background_task()
    app.run(host='0.0.0.0', port=5000, debug=False)
