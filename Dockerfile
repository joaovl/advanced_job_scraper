# Web app + careers crawler runtime (no Playwright — careers/providers are pure HTTP).
FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

COPY requirements-web.txt .
RUN pip install --no-cache-dir -r requirements-web.txt

COPY . .

EXPOSE 8000
# 2 sync workers is plenty for this read-mostly app; 120s timeout covers slow queries.
CMD ["gunicorn", "-w", "2", "-b", "0.0.0.0:8000", "--timeout", "120", "jobsdb.app:app"]
