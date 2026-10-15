# The MeChess app in a container: `docker compose up`, then open the address it prints (it contains the access key of the run).
# Stage 1 builds the frontend; stage 2 is the server with Stockfish and the C++ engine. Nothing here needs torch: the app does not import it.
FROM node:22-slim AS web
WORKDIR /w
COPY frontend/package.json frontend/package-lock.json frontend/
RUN cd frontend && npm ci
COPY frontend frontend
RUN cd frontend && npm run build

FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends stockfish g++ make && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
# only what the app needs (the full pins also hold the research dependencies)
RUN pip install --no-cache-dir "chess==1.11.2" "PyYAML==6.0.3" "requests==2.34.2" "numpy==2.5.3" "zstandard==0.25.0" \
    "fastapi==0.143.1" "uvicorn==0.54.0" "websockets==17.2" "SQLAlchemy==2.1.4" "alembic==1.20.0" "httpx==0.28.1"
COPY chessme chessme
COPY engine engine
COPY configs configs
COPY pyproject.toml README.md LICENSE ./
RUN make -C engine
COPY --from=web /w/frontend/dist chessme/app/static
ENV PATH="/usr/games:${PATH}" CHESSME_ROOT=/app
VOLUME /data
EXPOSE 8765
# 0.0.0.0 inside the container only: the compose file publishes the port to 127.0.0.1 on your computer
CMD ["python", "-m", "chessme", "app", "--host", "0.0.0.0", "--no-browser", "--data-dir", "/data", "--research-dir", "/data/research", "--legacy-coach-dir", "/data/coach", "--bot-dir", "/data/bot"]
