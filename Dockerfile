FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PRO_ONE_MODE=production PORT=8000
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt && useradd --create-home --uid 10001 proone
COPY app ./app
COPY data ./data
COPY schemas ./schemas
USER proone
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8000')+'/health',timeout=3)"
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port \"${PORT:-8000}\" --no-access-log"]
