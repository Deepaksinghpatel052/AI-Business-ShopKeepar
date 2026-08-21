from fastapi import FastAPI
from routers import auth, document, query, demo

app = FastAPI()

app.include_router(auth.router)
app.include_router(document.router)
app.include_router(query.router)
app.include_router(demo.router)

@app.get("/")
async def read_root():
    return {"Hello": "World"}
