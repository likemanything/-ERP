# ---------- 前端构建 ----------
FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---------- 后端运行 ----------
FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ERP_FRONTEND_DIST=/app/web \
    ERP_ENV=prod
WORKDIR /app
RUN pip install --no-cache-dir uv
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project && rm -rf /root/.cache
ENV PATH="/app/.venv/bin:$PATH"
COPY backend/ ./
COPY --from=web /web/dist /app/web
COPY deploy/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh && useradd -r -u 10001 erp && chown -R erp /app
USER erp
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/health')"
ENTRYPOINT ["/entrypoint.sh"]
CMD ["web"]
