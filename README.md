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
```

## Environment Variables

```env
DATABASE_URL=sqlite:///./bizinsight.db
SECRET_KEY=your-secret-key
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60
UPLOAD_DIR=./media/uploads
```

## Running with Docker

```bash
# 1. Make sure .env exists with real values (see env.example)
cp env.example .env

# 2. Build and start the app (also runs `alembic upgrade head` on startup)
docker compose up --build
```

The app will be available at http://localhost:8080.

Notes:
- `data/` (holds `bizinsight.db`), `faiss_store/`, `media/`, and `logs/` are
  bind-mounted into the container so data persists across rebuilds/restarts.
  `DATABASE_URL` is overridden in `docker-compose.yml` to point at
  `data/bizinsight.db` — a directory mount is used instead of mounting the
  sqlite file directly, since Docker silently turns a missing single-file
  bind mount into an empty directory, which breaks sqlite.
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

## Supported File Types

- PDF, DOC, DOCX
- CSV, XLS, XLSX
- PNG, JPEG
