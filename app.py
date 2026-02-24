#!/usr/bin/env python3
from flask import Flask, request, jsonify, session, render_template, redirect, url_for
import json
import os
import secrets
from functools import wraps
import threading
import re
from datetime import datetime
from main import (
    load_config,
    save_config,
    process_account,
    get_account_logs,
    start_background_task,
    get_all_states,
    update_account_state,
    DEFAULT_MIN_INTERVAL,
    DEFAULT_MAX_INTERVAL,
)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))

DATA_DIR = os.environ.get("DATA_DIR", "/app/data")
AUTH_FILE = os.environ.get("AUTH_FILE", os.path.join(DATA_DIR, "auth.json"))
PROXY_NODES_FILE = os.environ.get(
    "PROXY_NODES_FILE", os.path.join(DATA_DIR, "proxy_nodes.json")
)
PROXY_RUNTIME_CONFIG_FILE = os.environ.get(
    "PROXY_RUNTIME_CONFIG_FILE", os.path.join(DATA_DIR, "singbox_config.json")
)
PROXY_BASE_PORT = 20000

proxy_process = None
proxy_lock = threading.Lock()
PROXY_LOG_FILE = os.environ.get("PROXY_LOG_FILE", os.path.join(DATA_DIR, "singbox.log"))


# ==================== 认证相关 ====================
def load_auth():
    """加载认证配置"""
    if not os.path.exists(AUTH_FILE):
        return {"username": "admin", "password": "admin123"}
    try:
        with open(AUTH_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"username": "admin", "password": "admin123"}


def save_auth(auth_data):
    """保存认证配置"""
    try:
        auth_dir = os.path.dirname(AUTH_FILE)
        if auth_dir:
            os.makedirs(auth_dir, exist_ok=True)
        with open(AUTH_FILE, "w", encoding="utf-8") as f:
            json.dump(auth_data, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def login_required(f):
    """登录验证装饰器"""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("logged_in"):
            if request.is_json:
                return jsonify({"error": "未登录"}), 401
            return redirect(url_for("login_page"))
        return f(*args, **kwargs)

    return decorated_function


# ==================== 代理配置 ====================
def load_proxy_config():
    if not os.path.exists(PROXY_NODES_FILE):
        return {"subscription_url": "", "nodes": []}
    try:
        with open(PROXY_NODES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if "nodes" not in data:
                data["nodes"] = []
            if "subscription_url" not in data:
                data["subscription_url"] = ""
            return data
    except Exception:
        return {"subscription_url": "", "nodes": []}


def save_proxy_config(data):
    try:
        os.makedirs(os.path.dirname(PROXY_NODES_FILE) or ".", exist_ok=True)
        with open(PROXY_NODES_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def run_proxy_cli(args, payload=None):
    import subprocess

    env = os.environ.copy()
    env["PROXY_CONFIG_DIR"] = os.path.dirname(PROXY_NODES_FILE) or "."
    cmd = ["node", os.path.join(os.path.dirname(__file__), "proxy", "bridge.js")] + args

    try:
        result = subprocess.run(
            cmd, input=payload, text=True, capture_output=True, env=env, timeout=60
        )
    except FileNotFoundError:
        return {"ok": False, "error": "Node.js 未安装或不可用"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

    if result.stdout:
        try:
            return json.loads(result.stdout)
        except Exception:
            return {"ok": False, "error": result.stdout.strip() or "代理模块返回异常"}
    if result.stderr:
        return {"ok": False, "error": result.stderr.strip()}
    return {"ok": False, "error": "代理模块无响应"}


def find_singbox_exec():
    bin_name = "sing-box.exe" if os.name == "nt" else "sing-box"
    project_root = os.path.dirname(__file__)
    possible_paths = [
        os.path.join(project_root, "bin", bin_name),
        os.path.join(project_root, bin_name),
        f"/usr/bin/{bin_name}",
        f"/usr/local/bin/{bin_name}",
        bin_name,
    ]
    for p in possible_paths:
        if os.path.exists(p):
            return p
    return bin_name


def build_proxy_runtime_config(nodes):
    result = run_proxy_cli(
        ["build-config"], payload=json.dumps(nodes, ensure_ascii=False)
    )
    if not result.get("ok"):
        return None, result.get("error", "生成配置失败")
    return result.get("config"), None


def stop_proxy_process():
    global proxy_process
    if proxy_process and proxy_process.poll() is None:
        try:
            proxy_process.terminate()
        except Exception:
            pass
    proxy_process = None


def apply_proxy_config(nodes=None):
    global proxy_process
    with proxy_lock:
        if nodes is None:
            config = load_proxy_config()
            nodes = config.get("nodes", [])

        if not nodes:
            stop_proxy_process()
            return True, None

        config_data, err = build_proxy_runtime_config(nodes)
        if err:
            return False, err

        try:
            os.makedirs(
                os.path.dirname(PROXY_RUNTIME_CONFIG_FILE) or ".", exist_ok=True
            )
            with open(PROXY_RUNTIME_CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(config_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            return False, f"写入代理配置失败: {e}"

        stop_proxy_process()
        try:
            import subprocess

            exec_path = find_singbox_exec()
            # 捕获日志到文件
            log_file = open(PROXY_LOG_FILE, "a", encoding="utf-8")
            log_file.write(f"\n--- Proxy Start at {datetime.now()} ---\n")
            log_file.flush()

            proxy_process = subprocess.Popen(
                [exec_path, "run", "-c", PROXY_RUNTIME_CONFIG_FILE],
                stdout=log_file,
                stderr=log_file,
            )
            print(f"[Proxy] sing-box started with pid {proxy_process.pid}")
        except Exception as e:
            return False, f"启动代理失败: {e}"

        return True, None


# ==================== 页面路由 ====================
@app.route("/")
def index_page():
    if not session.get("logged_in"):
        return redirect(url_for("login_page"))
    return render_template("index.html")


@app.route("/login")
def login_page():
    if session.get("logged_in"):
        return redirect(url_for("index_page"))
    return render_template("login.html")


# ==================== API 路由 ====================
@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json()
    username = data.get("username", "")
    password = data.get("password", "")

    auth = load_auth()
    if username == auth["username"] and password == auth["password"]:
        session["logged_in"] = True
        session.permanent = True
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "用户名或密码错误"}), 401


@app.route("/api/logout", methods=["POST"])
def api_logout():
    session.clear()
    return jsonify({"success": True})


@app.route("/api/change-password", methods=["POST"])
@login_required
def change_password():
    """修改密码"""
    data = request.get_json()
    old_password = data.get("old_password", "").strip()
    new_password = data.get("new_password", "").strip()
    confirm_password = data.get("confirm_password", "").strip()

    if not old_password or not new_password or not confirm_password:
        return jsonify({"success": False, "error": "所有字段都是必填的"}), 400

    if new_password != confirm_password:
        return jsonify({"success": False, "error": "两次输入的新密码不一致"}), 400

    if len(new_password) < 6:
        return jsonify({"success": False, "error": "新密码长度至少6位"}), 400

    auth = load_auth()
    if old_password != auth["password"]:
        return jsonify({"success": False, "error": "旧密码错误"}), 400

    auth["password"] = new_password
    if save_auth(auth):
        return jsonify({"success": True, "message": "密码修改成功"})
    else:
        return jsonify({"success": False, "error": "保存失败，请重试"}), 500


@app.route("/api/accounts", methods=["GET"])
@login_required
def get_accounts():
    accounts = load_config()
    states = get_all_states()

    result_accounts = []
    for acc in accounts:
        server_id = acc.get("server_id", "")
        platform = (acc.get("platform") or "").strip().lower()
        if not platform:
            platform = (
                "freexcraft"
                if re.match(r"^[0-9a-fA-F-]{36}$", str(server_id))
                else "lemehost"
            )
        state = states.get(server_id, {})
        result_acc = {
            "name": acc.get("name", ""),
            "server_id": server_id,
            "enabled": acc.get("enabled", True),
            "cookie": acc.get("cookie", ""),
            "platform": platform,
            "minestrator_api_key": "",
            "minestrator_api_url": acc.get("minestrator_api_url", ""),
            "minestrator_user_agent": acc.get("minestrator_user_agent", ""),
            "minestrator_wait_seconds": acc.get("minestrator_wait_seconds", 30),
            "keepalive_wait_seconds": acc.get("keepalive_wait_seconds", 60),
            "keepalive_start_interval": acc.get("keepalive_start_interval", 900),
            "keepalive_heartbeat_url": acc.get("keepalive_heartbeat_url", ""),
            "keepalive_check_url": acc.get("keepalive_check_url", ""),
            "proxy_node_id": acc.get("proxy_node_id", ""),
            "min_interval": acc.get("min_interval", DEFAULT_MIN_INTERVAL),
            "max_interval": acc.get("max_interval", DEFAULT_MAX_INTERVAL),
            "next_run": state.get("next_run"),
            "last_run": state.get("last_run"),
            "start_time": state.get("start_time"),
            "last_result": state.get("last_result"),
            "remaining_time": state.get("remaining_time"),
        }
        result_accounts.append(result_acc)
    return jsonify(result_accounts)


@app.route("/api/accounts", methods=["POST"])
@login_required
def add_account():
    data = request.get_json()
    name = data.get("name", "").strip()
    server_id = data.get("server_id", "").strip()
    cookie = data.get("cookie", "").strip()
    platform = (data.get("platform", "") or "").strip().lower()
    proxy_node_id = data.get("proxy_node_id", "").strip()
    min_interval = data.get("min_interval", DEFAULT_MIN_INTERVAL)
    max_interval = data.get("max_interval", DEFAULT_MAX_INTERVAL)

    minestrator_api_key = data.get("minestrator_api_key", "").strip()
    minestrator_api_url = data.get("minestrator_api_url", "").strip()
    minestrator_user_agent = data.get("minestrator_user_agent", "").strip()
    minestrator_wait_seconds = data.get("minestrator_wait_seconds", 30)

    keepalive_wait_seconds = data.get("keepalive_wait_seconds", 60)
    keepalive_start_interval = data.get("keepalive_start_interval", 900)
    keepalive_heartbeat_url = data.get("keepalive_heartbeat_url", "").strip()
    keepalive_check_url = data.get("keepalive_check_url", "").strip()

    if not name or not server_id:
        return jsonify({"error": "名称和 Server ID 是必填的"}), 400
    if platform == "minestrator":
        if not minestrator_api_key:
            return jsonify({"error": "Minestrator 需要 API Key"}), 400
    elif platform == "keepalive":
        pass
    else:
        if not cookie:
            return jsonify({"error": "名称、Server ID 和 Cookie 都是必填的"}), 400

    try:
        min_interval = int(min_interval)
        max_interval = int(max_interval)
        if min_interval < 1 or max_interval < 1:
            return jsonify({"error": "时间间隔必须大于 0"}), 400
        if min_interval > max_interval:
            return jsonify({"error": "最小间隔不能大于最大间隔"}), 400
    except (TypeError, ValueError):
        return jsonify({"error": "时间间隔必须是数字"}), 400

    accounts = load_config()

    for acc in accounts:
        if acc.get("server_id") == server_id:
            return jsonify({"error": f"Server ID {server_id} 已存在"}), 400

    new_account = {
        "name": name,
        "server_id": server_id,
        "cookie": cookie,
        "platform": platform or None,
        "minestrator_api_key": minestrator_api_key,
        "minestrator_api_url": minestrator_api_url,
        "minestrator_user_agent": minestrator_user_agent,
        "minestrator_wait_seconds": minestrator_wait_seconds,
        "keepalive_wait_seconds": keepalive_wait_seconds,
        "keepalive_start_interval": keepalive_start_interval,
        "keepalive_heartbeat_url": keepalive_heartbeat_url,
        "keepalive_check_url": keepalive_check_url,
        "enabled": True,
        "proxy_node_id": proxy_node_id,
        "min_interval": min_interval,
        "max_interval": max_interval,
    }
    accounts.append(new_account)

    try:
        save_config(accounts)
    except Exception as e:
        return jsonify({"error": f"保存失败: {str(e)}"}), 500

    return jsonify({"success": True})


@app.route("/api/accounts/<server_id>", methods=["PUT"])
@login_required
def update_account(server_id):
    data = request.get_json()
    accounts = load_config()

    for acc in accounts:
        if acc.get("server_id") == server_id:
            if "name" in data:
                acc["name"] = data["name"].strip()
            if "cookie" in data and data["cookie"].strip():
                acc["cookie"] = data["cookie"].strip()
            if "platform" in data:
                acc["platform"] = (data["platform"] or "").strip().lower()
            if "minestrator_api_key" in data and data["minestrator_api_key"].strip():
                acc["minestrator_api_key"] = data["minestrator_api_key"].strip()
            if "minestrator_api_url" in data:
                acc["minestrator_api_url"] = data["minestrator_api_url"].strip()
            if "minestrator_user_agent" in data:
                acc["minestrator_user_agent"] = data["minestrator_user_agent"].strip()
            if "minestrator_wait_seconds" in data:
                try:
                    acc["minestrator_wait_seconds"] = int(
                        data["minestrator_wait_seconds"]
                    )
                except (TypeError, ValueError):
                    pass
            if "keepalive_wait_seconds" in data:
                try:
                    acc["keepalive_wait_seconds"] = int(data["keepalive_wait_seconds"])
                except (TypeError, ValueError):
                    pass
            if "keepalive_start_interval" in data:
                try:
                    acc["keepalive_start_interval"] = int(
                        data["keepalive_start_interval"]
                    )
                except (TypeError, ValueError):
                    pass
            if "keepalive_heartbeat_url" in data:
                acc["keepalive_heartbeat_url"] = data["keepalive_heartbeat_url"].strip()
            if "keepalive_check_url" in data:
                acc["keepalive_check_url"] = data["keepalive_check_url"].strip()
            if "enabled" in data:
                acc["enabled"] = data["enabled"]
            if "proxy_node_id" in data:
                acc["proxy_node_id"] = data["proxy_node_id"].strip()
            if "min_interval" in data:
                try:
                    acc["min_interval"] = int(data["min_interval"])
                except (TypeError, ValueError):
                    pass
            if "max_interval" in data:
                try:
                    acc["max_interval"] = int(data["max_interval"])
                except (TypeError, ValueError):
                    pass
            # 支持修改 server_id
            if (
                "server_id" in data
                and data["server_id"].strip()
                and data["server_id"] != server_id
            ):
                new_server_id = data["server_id"].strip()
                for other in accounts:
                    if other.get("server_id") == new_server_id:
                        return jsonify(
                            {"error": f"Server ID {new_server_id} 已存在"}
                        ), 400
                # 更新状态文件中的 ID
                try:
                    state_file = os.environ.get("STATE_FILE", "/app/logs/state.json")
                    if os.path.exists(state_file):
                        with open(state_file, "r", encoding="utf-8") as f:
                            states = json.load(f)
                        if server_id in states:
                            states[new_server_id] = states.pop(server_id)
                            with open(state_file, "w", encoding="utf-8") as f:
                                json.dump(states, f, indent=2, ensure_ascii=False)
                except Exception:
                    pass
                acc["server_id"] = new_server_id
            save_config(accounts)
            return jsonify({"success": True})

    return jsonify({"error": "账号不存在"}), 404


@app.route("/api/accounts/<server_id>", methods=["DELETE"])
@login_required
def delete_account(server_id):
    accounts = load_config()
    new_accounts = [acc for acc in accounts if acc.get("server_id") != server_id]

    if len(new_accounts) == len(accounts):
        return jsonify({"error": "账号不存在"}), 404

    save_config(new_accounts)
    return jsonify({"success": True})


@app.route("/api/accounts/<server_id>/renew", methods=["POST"])
@login_required
def renew_account(server_id):
    try:
        data = request.get_json(silent=True) or {}
        token = data.get("minestrator_turnstile_token", "").strip()
        accounts = load_config()

        for acc in accounts:
            if acc.get("server_id") == server_id:
                try:
                    if token:
                        temp_acc = dict(acc)
                        temp_acc["minestrator_turnstile_token"] = token
                        success, message, remaining = process_account(temp_acc)
                    else:
                        success, message, remaining = process_account(acc)
                except Exception as e:
                    return jsonify({"success": False, "message": f"续期异常: {str(e)}"})
                from datetime import datetime

                update_account_state(
                    server_id,
                    last_run=datetime.now(),
                    last_result="success" if success else "failed",
                    remaining_time=remaining,
                    start_time=datetime.now() if success else None,
                )
                return jsonify(
                    {
                        "success": success,
                        "message": message,
                        "remaining_time": remaining,
                    }
                )

        return jsonify({"error": "账号不存在"}), 404
    except Exception as e:
        return jsonify({"success": False, "message": f"服务器错误: {str(e)}"}), 500


@app.route("/api/accounts/<server_id>/logs", methods=["GET"])
@login_required
def get_logs(server_id):
    limit = request.args.get("limit", 5, type=int)
    logs = get_account_logs(server_id, limit)
    return jsonify(logs)


@app.route("/api/states", methods=["GET"])
@login_required
def get_states():
    """获取所有账号的运行状态"""
    return jsonify(get_all_states())


# ==================== 代理 API ====================
@app.route("/api/proxy/config", methods=["GET"])
@login_required
def get_proxy_config():
    return jsonify(load_proxy_config())


@app.route("/api/proxy/link", methods=["POST"])
@login_required
def add_proxy_link():
    data = request.get_json() or {}
    link = data.get("link", "").strip()
    if not link:
        return jsonify({"success": False, "error": "代理链接不能为空"}), 400

    result = run_proxy_cli(["parse", link])
    if not result.get("ok"):
        return jsonify(
            {"success": False, "error": result.get("error", "解析失败")}
        ), 400

    config = load_proxy_config()
    node = result.get("node")
    if not node:
        return jsonify({"success": False, "error": "解析失败"}), 400

    config["nodes"] = config.get("nodes", []) + [node]
    if not save_proxy_config(config):
        return jsonify({"success": False, "error": "保存失败"}), 500

    return jsonify({"success": True, "node": node})


@app.route("/api/proxy/subscription", methods=["POST"])
@login_required
def sync_proxy_subscription():
    data = request.get_json() or {}
    url = data.get("url", "").strip()
    mode = data.get("mode", "replace")
    if not url:
        return jsonify({"success": False, "error": "订阅链接不能为空"}), 400

    result = run_proxy_cli(["sync", url])
    if not result.get("ok"):
        return jsonify(
            {"success": False, "error": result.get("error", "同步失败")}
        ), 400

    nodes = result.get("nodes", [])
    config = load_proxy_config()
    if mode == "append":
        config["nodes"] = config.get("nodes", []) + nodes
    else:
        config["nodes"] = nodes
    config["subscription_url"] = url

    if not save_proxy_config(config):
        return jsonify({"success": False, "error": "保存失败"}), 500

    return jsonify({"success": True, "nodes": nodes})


@app.route("/api/proxy/nodes/<node_id>", methods=["DELETE"])
@login_required
def delete_proxy_node(node_id):
    config = load_proxy_config()
    nodes = config.get("nodes", [])
    new_nodes = [n for n in nodes if n.get("id") != node_id]
    if len(new_nodes) == len(nodes):
        return jsonify({"success": False, "error": "节点不存在"}), 404
    config["nodes"] = new_nodes
    if not save_proxy_config(config):
        return jsonify({"success": False, "error": "保存失败"}), 500

    return jsonify({"success": True})


@app.route("/api/proxy/test", methods=["POST"])
@login_required
def test_proxy_node():
    data = request.get_json() or {}
    node_id = data.get("node_id", "").strip()
    if not node_id:
        return jsonify({"success": False, "error": "节点 ID 不能为空"}), 400

    config = load_proxy_config()
    node = next((n for n in config.get("nodes", []) if n.get("id") == node_id), None)
    if not node:
        return jsonify({"success": False, "error": "节点不存在"}), 404

    result = run_proxy_cli(["test"], payload=json.dumps(node, ensure_ascii=False))
    if not result.get("ok"):
        return jsonify(
            {"success": False, "error": result.get("error", "测试失败")}
        ), 400
    return jsonify({"success": True, "latency_ms": result.get("latency_ms")})


@app.route("/api/proxy/apply", methods=["POST"])
@login_required
def apply_proxy_runtime():
    config = load_proxy_config()
    ok, err = apply_proxy_config(config.get("nodes", []))
    if not ok:
        return jsonify({"success": False, "error": err}), 500
    return jsonify({"success": True})


# ==================== 启动 ====================
if __name__ == "__main__":
    import logging

    # ✅ 静音 Flask/Werkzeug 的默认 HTTP 访问日志，让控制台清爽
    log_werk = logging.getLogger("werkzeug")
    log_werk.setLevel(logging.ERROR)

    apply_proxy_config()
    start_background_task()
    app.run(host="0.0.0.0", port=5000, debug=False)
