FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ app/
# Real feed responses: serve with FIXTURES_SOURCE=stub for offline demo renders.
COPY tests/fixtures/ tests/fixtures/
ENV PYTHONUNBUFFERED=1 TZ=Europe/London
EXPOSE 3459
# Liveness only (HTTP 200). A DATA CHECK is reported in the body, never as
# unhealthy, so deunhealth doesn't restart-loop a container over a feed change.
HEALTHCHECK --interval=5m --timeout=10s --start-period=30s \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:3459/healthz',timeout=8)"
CMD ["gunicorn", "-w", "1", "--threads", "4", "-b", "0.0.0.0:3459", "app.main:app"]
