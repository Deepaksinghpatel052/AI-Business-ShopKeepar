# AI-ShopKeeper

A FastAPI-based backend for managing shop owners with authentication and file upload functionality.

## Tech Stack

- Python 3.12
- FastAPI
- SQLAlchemy (ORM)
- SQLite (Database)
- Alembic (Migrations)
- JWT Authentication

## Project Structure
AI-ShopKeepar/
├── main.py
├── models/
│ ├── shop_owner.py
│ └── document.py
├── routers/
│ ├── auth.py
│ └── document.py
├── utils/
│ ├── auth.py
│ └── database.py
├── media/
│ └── uploads/
├── alembic/
├── .env
└── requirements.txt

## Setup

```bash
# 1. Virtual environment banao
python -m venv venv
venv\Scripts\activate

# 2. Dependencies install karo
pip install -r requirements.txt

# 3. .env file banao
cp .env.example .env
# .env me apni values daalo

# 4. Database migration chalao
alembic upgrade head

# 5. Server start karo
uvicorn main:app --reload

# 6. (Optional) Seed demo data - run in a separate terminal after the server is running
python -c "from services.scheduler import process_demo_documents; process_demo_documents()"
```

## Environment Variables

```env
DATABASE_URL=sqlite:///./bizinsight.db
SECRET_KEY=your-secret-key
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60
AWS_ACCESS_KEY_ID=your-iam-user-access-key
AWS_SECRET_ACCESS_KEY=your-iam-user-secret-key
AWS_REGION=ap-south-1
S3_BUCKET_NAME=your-private-s3-bucket
OPENAI_API_KEY=your-openai-key          # embeddings + optional OpenAI chat LLM
DEFAULT_LLM_PROVIDER=ollama             # ollama (local, default) | openai
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_CHAT_MODEL=phi3:mini
```

## LLM (local Ollama by default)

The chat LLM (intent detection, data extraction, answers, document verification) runs on
**local Ollama `phi3:mini`** by default. OpenAI can be switched on at runtime — no restart needed.

```bash
ollama pull phi3:mini      # one time
ollama serve               # usually already running as a background service
```

- `GET /llm/providers` — providers, installed Ollama models, and the active LLM
- `GET /llm/active` — current provider/model
- `PUT /llm/active` (admin) — e.g. `{"provider": "openai", "model": "gpt-4o-mini"}` or `{"provider": "ollama"}`

The choice is saved in the `llm_settings` table, so it survives restarts. Embeddings still use
OpenAI (`OPENAI_API_KEY`), because switching the embedding model would require re-indexing FAISS.
In Docker, the app reaches the host's Ollama at `host.docker.internal:11434` (already set in the compose files).

## Running with Docker

```bash
# 1. Make sure .env exists with real values (see env.example)
cp env.example .env

# 2. Build and start the app (also runs `alembic upgrade head` on startup)
docker compose up --build
```

The app will be available at http://localhost:8080.

### Docker Cheatsheet (production / Linux host)

```bash
# Build and start the app in the background (detached mode)
sudo docker compose up -d --build

# If a build seems stale (cached layers not picking up changes), rebuild from scratch and start
sudo docker compose build --no-cache && docker compose up -d

# Copy local media files into the running container's media volume
# (useful for seeding/restoring uploads that aren't tracked in git)
sudo docker compose cp media/. app:/app/media/

# List running (and stopped) containers to find the container ID/name
sudo docker ps -a

# Open an interactive shell inside a running container for debugging
sudo docker exec -it {CONTAINER ID} /bin/bash

# (Optional) Seed demo data - run after the container is up
docker compose exec app python -c "from services.scheduler import process_demo_documents; process_demo_documents()"
```

Notes:
- The database (`bizinsight.db`), `faiss_store/`, `media/`, and `logs/` live in
  Docker-managed named volumes (`app_data`, `app_faiss_store`, `app_media`,
  `app_logs`), not host folders. Docker creates and owns them automatically —
  nothing to `mkdir` or `chown` by hand, and it works the same on any host.
  `DATABASE_URL` is overridden in `docker-compose.yml` to point at
  `/app/data/bizinsight.db` inside the `app_data` volume.
- To back up the data: `docker run --rm -v ai-shopkeepar_app_data:/data -v "$PWD":/backup alpine tar czf /backup/data-backup.tar.gz -C /data .`
  (swap the volume name for `app_faiss_store`/`app_media` to back those up too;
  check the actual names with `docker volume ls`).
- `sentence-transformers`/`torch` are intentionally **not** installed in the image —
  the codebase always constructs `FaissVectorStore`/`EmbeddingPipeline` with
  `embedding_model="openai"`, so the local-model fallback path is currently dead
  code. Add them back to `requirements.txt` if you wire up a non-OpenAI embedding
  model later.
- To run the test suite inside the container: `docker compose exec app pytest`.

## API Endpoints

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | /auth/signup | No | Register new shop owner |
| POST | /auth/signin | No | Login and get JWT token |
| POST | /auth/token | No | Swagger UI login |
| GET | /auth/me | Yes | Get current user profile |
| POST | /documents/upload-file | Yes | Upload a file |
| GET | /documents/my-files | Yes | List all uploaded files |
| GET | /llm/providers | Yes | List LLM providers/models + active LLM |
| GET | /llm/active | Yes | Current active LLM |
| PUT | /llm/active | Admin | Switch LLM provider/model |

## Supported File Types

- PDF
- CSV (each row is indexed as `column: value` text, so answers can reference column names)
