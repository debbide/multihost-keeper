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

# 复制应用文件
COPY main.py .
COPY app.py .
COPY templates/ templates/

# 创建日志和配置目录挂载点
VOLUME ["/app/config", "/app/logs"]

# 暴露 Web 端口
EXPOSE 5000

# 启动 Flask 应用 (会同时启动后台续期任务)
CMD ["python", "-u", "app.py"]
