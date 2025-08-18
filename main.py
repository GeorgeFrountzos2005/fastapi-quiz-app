from typing import List, Dict
from fastapi import FastAPI, HTTPException, Depends, Form, Body
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy import Table, Column, Integer, String, Text,  func
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
# --- simple auto-seed so you can test immediately (remove later) ---
def seed_questions_if_empty():
    with SessionLocal() as db:
        cnt = db.execute(questions.count()).scalar()  # type: ignore
        if not cnt or cnt == 0:
            seed = [
                {"question": "What is 2 + 2?", "choices": ["3","4","5","6"], "answer": 1},
                {"question": "Capital of France?", "choices": ["Berlin","Madrid","Paris","Rome"], "answer": 2},
                {"question": "Which is a mammal?", "choices": ["Shark","Dolphin","Trout","Salmon"], "answer": 1},
                {"question": "H2O is…", "choices": ["Oxygen","Hydrogen","Water","Helium"], "answer": 2},
                {"question": "5 * 6 = ?", "choices": ["28","29","30","31"], "answer": 2},
                {"question": "Largest planet?", "choices": ["Earth","Mars","Jupiter","Venus"], "answer": 2},
                {"question": "Binary of 2?", "choices": ["10","11","01","00"], "answer": 0},
                {"question": "HTML stands for?", "choices": ["Hyperlinks and Text Markup Language","Home Tool Markup Language","HyperText Markup Language","Hyper Tool Multi Language"], "answer": 2},
                {"question": "FastAPI is a…", "choices": ["DB","Web framework","OS","Browser"], "answer": 1},
                {"question": "Year has how many months?", "choices": ["10","11","12","13"], "answer": 2}
            ]
            for q in seed:
                db.execute(
                    questions.insert().values(
                        question=q["question"],
                        choices=json.dumps(q["choices"]),
                        answer=q["answer"]
                    )
                )
            db.commit()

# call it at startup
seed_questions_if_empty()
# --- end auto-seed ---

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
    # pull all questions
    rows = db.execute(questions.select()).fetchall()
    if len(rows) < 50:
        raise HTTPException(status_code=400, detail="Not enough questions in DB yet")
    # build plain dicts and sample 50 unique
    all_qs = [
        {
            "id": r.id,
            "question": r.question,
            "choices": json.loads(r.choices)
            # NOTE: we do NOT include the answer here to keep it hidden
        }
        for r in rows
    ]
    selected = random.sample(all_qs, 50)
    return {"questions": selected}

@app.get("/api/questions")
def get_questions(db: Session = Depends(get_db)):
    # Grab ALL questions
    rows = db.execute(questions.select()).fetchall()

    # Convert them into Python dicts
    all_questions = []
    for row in rows:
        all_questions.append({
            "id": row.id,
            "question": row.question,
            "choices": json.loads(row.choices),  # turn JSON string back into list
            "answer": row.answer
        })

    # Pick 50 random ones
    selected = random.sample(all_questions, min(50, len(all_questions)))

    return {"questions": selected}

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
