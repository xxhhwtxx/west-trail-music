FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py index.html default-cover.svg ./

# Railway 用 PORT 环境变量
CMD ["sh", "-c", "python server.py"]
