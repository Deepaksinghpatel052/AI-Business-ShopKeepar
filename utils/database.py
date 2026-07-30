from fastapi import Depends
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy import create_engine
import os
from typing import Annotated
from dotenv import load_dotenv

load_dotenv()

# ── Database ──────────────────────────────────────────────────────────────────
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./bizinsight.db")
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
