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
