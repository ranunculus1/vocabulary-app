FROM python:3.11-slim

WORKDIR /app

# 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用
COPY . .

# 暴露端口
EXPOSE 7860

# 启动命令
CMD ["python", "app.py", "--port", "7860", "--host", "0.0.0.0"]
