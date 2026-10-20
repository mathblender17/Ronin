# Stage 1: build the React frontend.
FROM node:22-alpine AS web
WORKDIR /app
RUN corepack enable && corepack prepare pnpm@11.25.0 --activate
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY index.html vite.config.ts tsconfig.json tailwind.config.js postcss.config.js ./
COPY src ./src
RUN pnpm build

# Stage 2: FastAPI serves the API and the built frontend from one container.
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    RONIN_READ_ONLY=1 \
    RONIN_DATABASE_URL=sqlite:////app/showcase/ronin.db
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend ./backend
COPY showcase ./showcase
COPY --from=web /app/dist ./dist
EXPOSE 10000
# Render provides PORT; default to 10000 elsewhere.
CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-10000}"]
