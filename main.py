from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timedelta
from enum import Enum
import sqlite3
from contextlib import contextmanager

app = FastAPI()

# Database setup
DATABASE = "tasks.db"

@contextmanager
def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

def init_db():
    with get_db() as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS tasks
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                     title TEXT NOT NULL,
                     description TEXT,
                     status TEXT NOT NULL CHECK(status IN ('Pending', 'Completed')),
                     created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                     updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        conn.commit()

init_db()

# Data Models
class TaskStatus(str, Enum):
    PENDING = "Pending"
    COMPLETED = "Completed"

class TaskBase(BaseModel):
    title: str
    description: Optional[str] = None
    status: TaskStatus = TaskStatus.PENDING

class TaskCreate(TaskBase):
    pass

class Task(TaskBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True

class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[TaskStatus] = None

class WeeklyCompletion(BaseModel):
    year: int
    week_number: int
    total_tasks: int
    completed_tasks: int
    completion_percentage: float

# API Endpoints
@app.get("/")
def root():
    return {
        "message": "Task Management API is running",
        "endpoints": {
            "create_task": {"method": "POST", "path": "/tasks"},
            "list_tasks": {"method": "GET", "path": "/tasks"},
            "get_task": {"method": "GET", "path": "/tasks/{id}"},
            "update_task": {"method": "PUT", "path": "/tasks/{id}"},
            "delete_task": {"method": "DELETE", "path": "/tasks/{id}"},
            "weekly_analytics": {"method": "GET", "path": "/tasks/analytics/weekly-completion"}
        }
    }

@app.post("/tasks", response_model=Task, status_code=status.HTTP_201_CREATED)
def create_task(task: TaskCreate):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''INSERT INTO tasks (title, description, status)
                          VALUES (?, ?, ?)''',
                      (task.title, task.description, task.status.value))
        conn.commit()
        task_id = cursor.lastrowid
        
        cursor.execute('SELECT * FROM tasks WHERE id = ?', (task_id,))
        created_task = cursor.fetchone()
    
    return created_task

@app.get("/tasks", response_model=List[Task])
def read_tasks(status: Optional[TaskStatus] = None):
    with get_db() as conn:
        cursor = conn.cursor()
        
        if status:
            cursor.execute('SELECT * FROM tasks WHERE status = ?', (status.value,))
        else:
            cursor.execute('SELECT * FROM tasks')
        
        tasks = cursor.fetchall()
    
    return tasks

@app.get("/tasks/{task_id}", response_model=Task)
def read_task(task_id: int):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM tasks WHERE id = ?', (task_id,))
        task = cursor.fetchone()
    
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    return task

@app.put("/tasks/{task_id}", response_model=Task)
def update_task(task_id: int, task_update: TaskUpdate):
    with get_db() as conn:
        cursor = conn.cursor()
        
        # Get existing task
        cursor.execute('SELECT * FROM tasks WHERE id = ?', (task_id,))
        existing_task = cursor.fetchone()
        
        if not existing_task:
            raise HTTPException(status_code=404, detail="Task not found")
        
        # Prepare update values
        title = task_update.title if task_update.title else existing_task['title']
        description = task_update.description if task_update.description else existing_task['description']
        status = task_update.status.value if task_update.status else existing_task['status']
        
        # Update task
        cursor.execute('''UPDATE tasks 
                         SET title = ?, description = ?, status = ?, updated_at = CURRENT_TIMESTAMP
                         WHERE id = ?''',
                      (title, description, status, task_id))
        conn.commit()
        
        # Fetch updated task
        cursor.execute('SELECT * FROM tasks WHERE id = ?', (task_id,))
        updated_task = cursor.fetchone()
    
    return updated_task

@app.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(task_id: int):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('DELETE FROM tasks WHERE id = ?', (task_id,))
        conn.commit()
        
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Task not found")

@app.get("/tasks/analytics/weekly-completion", response_model=List[WeeklyCompletion])
def get_weekly_completion(weeks: int = 4):
    end_date = datetime.now()
    start_date = end_date - timedelta(weeks=weeks)
    
    with get_db() as conn:
        cursor = conn.cursor()
        
        # Get all tasks created in the period
        cursor.execute('''SELECT 
                            strftime('%Y', created_at) as year,
                            strftime('%W', created_at) as week_number,
                            COUNT(*) as total_tasks,
                            SUM(CASE WHEN status = 'Completed' THEN 1 ELSE 0 END) as completed_tasks
                         FROM tasks
                         WHERE created_at >= ?
                         GROUP BY year, week_number
                         ORDER BY year, week_number''',
                      (start_date.strftime('%Y-%m-%d'),))
        
        results = cursor.fetchall()
    
    analytics = []
    for row in results:
        total = row['total_tasks']
        completed = row['completed_tasks']
        percentage = (completed / total) * 100 if total > 0 else 0
        
        analytics.append(WeeklyCompletion(
            year=int(row['year']),
            week_number=int(row['week_number']),
            total_tasks=total,
            completed_tasks=completed,
            completion_percentage=round(percentage, 2)
        ))
    
    return analytics

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)