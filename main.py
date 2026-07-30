from fastapi import FastAPI
from routers import auth, document

app = FastAPI()

app.include_router(auth.router)
app.include_router(document.router)
@app.get("/")
async def read_root():
    return {"Hello": "World"}
