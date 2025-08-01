from fastapi import FastAPI, HTTPException, Depends, Form, Body
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy import Table, Column, Integer, String
from sqlalchemy.orm import Session
from passlib.context import CryptContext
import os

from database import metadata, engine, SessionLocal

app = FastAPI()

# Mount static files at /static
app.mount("/static", StaticFiles(directory="frontend"), name="static")

# Serve your index.html for the root path
@app.get("/")
async def serve_index():
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

@app.post("/api/submit_score")
async def submit_score(
    username: str = Body(...),
    score: int = Body(...),
    db: Session = Depends(get_db)
):
    user = db.execute(users.select().where(users.c.username == username)).fetchone()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Only update if new score is higher
    if score > user.score:
        db.execute(users.update().where(users.c.username == username).values(score=score))
        db.commit()
        return {"message": "Score updated!"}
    return {"message": "Score not updated (lower or same as previous)"}

@app.get("/api/leaderboard")
async def leaderboard(db: Session = Depends(get_db)):
    result = db.execute(users.select().order_by(users.c.score.desc())).fetchall()
    return [{"username": r.username, "score": r.score} for r in result]

# Only for local testing. Railway will use your "Start Command".
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8080)),
        reload=False
    )
