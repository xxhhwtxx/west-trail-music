FROM python:3.12-slim

WORKDIR /app

COPY requirements-docker.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py index.html default-cover.svg ./

EXPOSE 8000
CMD python -m uvicorn server:app --host 0.0.0.0 --port ${PORT:-8000}
