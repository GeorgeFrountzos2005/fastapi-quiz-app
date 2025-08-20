from typing import List, Dict
from fastapi import FastAPI, HTTPException, Depends, Form, Body
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy import Table, Column, Integer, String, Text,  select, func
from sqlalchemy.orm import Session
from passlib.context import CryptContext
import os

from database import metadata, engine, SessionLocal

import json
import random
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

# NEW: Questions table
questions = Table(
    "questions",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("question", Text, nullable=False),
    Column("choices", String, nullable=False),  # Store as JSON string
    Column("answer", Integer, nullable=False)   # Index of correct choice
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

@app.get("/api/questions")
def get_questions(db: Session = Depends(get_db)):
    # Fetch all questions from DB
    rows = db.execute(questions.select()).fetchall()
    if not rows:
        raise HTTPException(status_code=400, detail="No questions in DB yet")

    # Return up to 50 random questions
    sample_size = min(50, len(rows))
    picked = random.sample(rows, sample_size)

    return {
        "questions": [
            {
                "id": r.id,
                "question": r.question,
                "choices": json.loads(r.choices),  # keep answers hidden
            }
            for r in picked
        ]
    }


@app.post("/api/grade")
def grade_quiz(
    payload: Dict = Body(...),
    db: Session = Depends(get_db)
):
    """
    payload = {
      "username": "alice",
      "answers": [{"id": 12, "choice": 2}, ...]  # choice is index in choices array
    }
    """
    username = payload.get("username")
    answers: List[Dict] = payload.get("answers", [])

    if not username:
        raise HTTPException(status_code=400, detail="Missing username")

    # fetch user
    user = db.execute(users.select().where(users.c.username == username)).fetchone()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # build map of submitted answers by question id
    submitted = {a["id"]: a["choice"] for a in answers if "id" in a and "choice" in a}

    # fetch all those questions from DB
    q_ids = list(submitted.keys())
    if not q_ids:
        return {"correct": 0, "total": 0, "saved": False}

    rows = db.execute(questions.select().where(questions.c.id.in_(q_ids))).fetchall()

    correct = 0
    total = len(rows)
    for r in rows:
        if submitted.get(r.id) == r.answer:
            correct += 1

    # update high score only if this attempt is higher
    if correct > (user.score or 0):
        db.execute(
            users.update()
            .where(users.c.username == username)
            .values(score=correct)
        )
        db.commit()
        saved = True
    else:
        saved = False

    return {"correct": correct, "total": total, "saved": saved}

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
