# 使用轻量级 Python 基础镜像
FROM python:3.9-slim

# 设置工作目录
WORKDIR /app

# 设置时区为上海 (可选，方便看日志)
ENV TZ=Asia/Shanghai
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# 复制依赖并安装
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 安装 Node.js 依赖（代理模块）
RUN env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY -u no_proxy -u NO_PROXY \
    apt-get update && apt-get install -y nodejs npm && rm -rf /var/lib/apt/lists/*

# 安装 sing-box
ARG SING_BOX_VERSION=1.10.2
RUN apt-get update && apt-get install -y curl unzip ca-certificates && rm -rf /var/lib/apt/lists/* \
    && (curl -fL --retry 3 --retry-delay 2 \
        "https://ghfast.top/https://github.com/SagerNet/sing-box/releases/download/v${SING_BOX_VERSION}/sing-box-${SING_BOX_VERSION}-linux-amd64.tar.gz" \
        -o /tmp/sing-box.tar.gz \
        || curl -fL --retry 3 --retry-delay 2 \
        "https://github.com/SagerNet/sing-box/releases/download/v${SING_BOX_VERSION}/sing-box-${SING_BOX_VERSION}-linux-amd64.tar.gz" \
        -o /tmp/sing-box.tar.gz) \
    && tar -xzf /tmp/sing-box.tar.gz -C /tmp \
    && mv "/tmp/sing-box-${SING_BOX_VERSION}-linux-amd64/sing-box" /usr/local/bin/sing-box \
    && chmod +x /usr/local/bin/sing-box \
    && rm -rf /tmp/sing-box*
COPY package.json .
RUN npm install --omit=dev

# 复制应用文件
COPY main.py .
COPY app.py .
COPY platforms/ platforms/
COPY proxy/ proxy/
COPY templates/ templates/
COPY anik_renew.py .
COPY leme_power.py .
COPY freexcraft_renew.py .

# 创建日志和配置目录挂载点
VOLUME ["/app/config", "/app/logs"]

# 暴露 Web 端口
EXPOSE 5000

# 启动 Flask 应用 (会同时启动后台续期任务)
CMD ["python", "-u", "app.py"]
