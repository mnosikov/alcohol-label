FROM node:22-bookworm AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
WORKDIR /app
RUN apt-get update \
  && apt-get install -y --no-install-recommends tesseract-ocr curl \
  && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml ./
COPY backend/__init__.py ./backend/__init__.py
COPY backend/app ./backend/app
COPY backend/migrations ./backend/migrations
RUN pip install --no-cache-dir "."
COPY --from=frontend-build /app/frontend/dist ./frontend/dist
RUN mkdir -p /data/uploads
EXPOSE 8000
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
