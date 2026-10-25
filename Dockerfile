FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY assistant ./assistant
COPY data ./data
COPY eval/thresholds.json ./eval/thresholds.json
RUN useradd --create-home appuser
USER appuser
EXPOSE 8000
# optional: -e USE_LLM=true -e GROQ_API_KEY=... (supplied at run time, never baked into the image)
CMD ["uvicorn", "assistant.api:app", "--host", "0.0.0.0", "--port", "8000"]
