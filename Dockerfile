FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml .
COPY hyrule_web/ hyrule_web/

RUN pip install --no-cache-dir .

EXPOSE 8080

CMD ["uvicorn", "hyrule_web.app:app", "--host", "0.0.0.0", "--port", "8080"]
