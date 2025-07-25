from fastapi import FastAPI, HTTPException, Depends, Form
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy import Table, Column, Integer, String
from sqlalchemy.orm import Session
from passlib.context import CryptContext
import os

from database import metadata, engine, SessionLocal

app = FastAPI()

# 1. Serve your frontend from "/"
app.mount("/", StaticFiles(directory="frontend", html=True), name="static")


@app.get("/")
async def root():
    return FileResponse("frontend/index.html")

# 2. Define your users table (for SQLAlchemy)
users = Table(
    "users",
    metadata,
    Column("id", Integer, primary_key=True, index=True),
    Column("username", String, unique=True, index=True),
    Column("hashed_password", String),
    Column("score", Integer, default=0)
)
metadata.create_all(bind=engine)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.get("/api/hello")
async def hello():
    return {"message": "Hello, world!"}

@app.post("/api/register")
async def register(
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    user = db.execute(users.select().where(users.c.username == username)).fetchone()
    if user:
        raise HTTPException(status_code=400, detail="Username already exists")
    hashed_password = pwd_context.hash(password)
    db.execute(users.insert().values(username=username, hashed_password=hashed_password, score=0))
    db.commit()
    return {"message": "User registered"}

@app.post("/api/login")
async def login(
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    user = db.execute(users.select().where(users.c.username == username)).fetchone()
    if not user or not pwd_context.verify(password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    return {"message": "Login successful", "username": username}

# Only for local testing. Railway will use your "Start Command".
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8080)),
        reload=False
    )
