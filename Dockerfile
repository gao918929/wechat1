FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend backend
COPY llm_wiki llm_wiki
COPY web web
COPY scripts scripts
RUN useradd --uid 10001 --create-home mealagent && mkdir -p /app/data && chown -R mealagent:mealagent /app
USER mealagent
EXPOSE 8000
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
