import logging
import time

from utils.logger import setup_logging

setup_logging()

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from routers import auth, document, query, demo, membership

logger = logging.getLogger(__name__)

app = FastAPI()

app.include_router(auth.router)
app.include_router(document.router)
app.include_router(query.router)
app.include_router(demo.router)
app.include_router(membership.router)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Har request ka method/path/status/duration log karo — ek jagah se poore app ka traffic track karne ke liye."""
    start = time.monotonic()
    response = await call_next(request)
    duration_ms = round((time.monotonic() - start) * 1000, 2)

    logger.info(
        f"{request.client.host if request.client else '-'} \"{request.method} {request.url.path}\" "
        f"{response.status_code} {duration_ms}ms"
    )
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """
    Koi bhi unhandled exception (jo kisi endpoint ke apne try/except me catch nahi hui) yahan
    poori traceback ke saath log ho jaati hai — production me kuch bhi fail ho, isi ek log
    file me dhoond sakte hain.
    """
    logger.exception(f"Unhandled error on {request.method} {request.url.path}")
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.get("/")
async def read_root():
    return {"Hello": "World"}
