FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py index.html default-cover.svg ./

ENV PORT=8000
CMD python -c "import os; from server import app; import uvicorn; uvicorn.run(app, host='0.0.0.0', port=int(os.environ.get('PORT',8000)))"
