from typing import List, Dict
from fastapi import FastAPI, HTTPException, Depends, Form, Body, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy import Table, Column, Integer, String, Text,  select, func, delete
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

#####NEW#########
# ---------- IQ question generators + reseed helpers ----------
def _mk_choices(correct: int) -> (list[str], int):
    """Return 4 unique choices (as strings) including the correct answer, plus the index of the correct one."""
    pool = {correct}
    for delta in [1, -1, 2, -2, 3, 4, 5]:
        pool.add(correct + delta)
        if len(pool) >= 6:
            break
    opts = list(pool)[:4]
    random.shuffle(opts)
    return [str(x) for x in opts], opts.index(correct)

def _arith_seq():
    a = random.randint(1, 20)
    d = random.randint(2, 9)
    seq = [a + i * d for i in range(4)]
    correct = a + 4 * d
    q = f"Find the next number: {seq[0]}, {seq[1]}, {seq[2]}, {seq[3]}, ?"
    choices, idx = _mk_choices(correct)
    return {"question": q, "choices": choices, "answer": idx}

def _geom_seq():
    a = random.randint(1, 5)
    r = random.choice([2, 3])
    seq = [a * (r ** i) for i in range(4)]
    correct = a * (r ** 4)
    q = f"Find the next number: {seq[0]}, {seq[1]}, {seq[2]}, {seq[3]}, ?"
    choices, idx = _mk_choices(correct)
    return {"question": q, "choices": choices, "answer": idx}

def _fib_like():
    x = random.randint(1, 5)
    y = random.randint(1, 5)
    seq = [x, y]
    for _ in range(2, 5):
        seq.append(seq[-1] + seq[-2])
    q = f"Find the next number: {seq[0]}, {seq[1]}, {seq[2]}, {seq[3]}, {seq[4]}, ?"
    correct = seq[-1] + seq[-2]
    choices, idx = _mk_choices(correct)
    return {"question": q, "choices": choices, "answer": idx}

def _odd_one_out():
    prop = random.choice(["even", "odd", "div3", "div5"])
    base = []
    while len(base) < 3:
        n = random.randint(10, 60)
        ok = (
            (prop == "even" and n % 2 == 0) or
            (prop == "odd" and n % 2 == 1) or
            (prop == "div3" and n % 3 == 0) or
            (prop == "div5" and n % 5 == 0)
        )
        if ok and n not in base:
            base.append(n)
    # outlier
    while True:
        m = random.randint(10, 60)
        ok = not (
            (prop == "even" and m % 2 == 0) or
            (prop == "odd" and m % 2 == 1) or
            (prop == "div3" and m % 3 == 0) or
            (prop == "div5" and m % 5 == 0)
        )
        if ok and m not in base:
            break
    items = base + [m]
    random.shuffle(items)
    q = f"Odd one out: {items[0]}, {items[1]}, {items[2]}, {items[3]}"
    correct_idx = items.index(m)
    return {"question": q, "choices": [str(x) for x in items], "answer": correct_idx}

GENS = [_arith_seq, _geom_seq, _fib_like, _odd_one_out]

def _make_iq_batch(n: int):
    batch = []
    for _ in range(n):
        q = random.choice(GENS)()
        batch.append(q)
    return batch
# --------------------------------------------------------------






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



# --- Bulk seed IQ questions (POST JSON) ---
from pydantic import BaseModel, Field
from typing import List

class SeedQuestion(BaseModel):
    question: str
    choices: List[str] = Field(min_items=4, max_items=4)
    answer: int  # 0..3

class SeedPayload(BaseModel):
    key: str
    questions: List[SeedQuestion]

@app.post("/api/admin/seed_bulk")
def seed_bulk(payload: SeedPayload, db: Session = Depends(get_db)):
    if payload.key != os.environ.get("ADMIN_KEY"):
        raise HTTPException(status_code=403, detail="Forbidden")

    # wipe existing
    db.execute(questions.delete())

    # insert new
    for q in payload.questions:
        db.execute(
            questions.insert().values(
                question=q.question,
                choices=json.dumps(q.choices),
                answer=q.answer
            )
        )
    db.commit()
    return {"ok": True, "total": len(payload.questions)}
##############################################################



# Only for local testing. Railway will use your "Start Command".
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8080)),
        reload=False
    )
