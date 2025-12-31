FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 安装系统依赖（Playwright需要 + curl用于健康检查）
RUN apt-get update && apt-get install -y \
    curl \
    wget \
    gnupg \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    && rm -rf /var/lib/apt/lists/*

# 先复制依赖文件（利用Docker缓存层，依赖不变时不重新安装）
COPY requirements.txt .

# 安装Python依赖
RUN pip install --no-cache-dir -r requirements.txt

# 安装Playwright浏览器（放在依赖安装之后，利用缓存）
RUN playwright install chromium && \
    playwright install-deps chromium

# 复制应用代码（放在最后，代码变更时不影响依赖层缓存）
COPY . .

# 创建data目录结构（确保目录存在，即使挂载volume也能正常工作）
RUN mkdir -p /app/data/logs && \
    mkdir -p /app/data/m3u8_cache && \
    chmod -R 755 /app/data

# 暴露端口（内部端口8000）
EXPOSE 8000

# 健康检查（可选，也可以在docker-compose.yml中配置）
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python /app/healthcheck.py || exit 1

# 启动命令
CMD ["python", "api_server.py"]

