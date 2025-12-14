import asyncio
from fastapi import FastAPI, Depends, HTTPException, status, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime, timedelta
from database import get_db, engine, Base
from models import User, Task, ShoppingItem, CleaningSchedule, Message, Room, RoomMember, UserRole
from auth import (
    get_password_hash, 
    verify_password, 
    create_access_token, 
    get_current_user,
    ACCESS_TOKEN_EXPIRE_MINUTES
)
from permissions import check_room_access, check_admin_access, check_owner_access
from utils import generate_room_code

Base.metadata.create_all(bind=engine)

tags_metadata = [
    {"name": "auth", "description": "Аутентификация и регистрация"},
    {"name": "rooms", "description": "Управление комнатами"},
    {"name": "users", "description": "Пользователи"},
    {"name": "tasks", "description": "Задачи"},
    {"name": "shopping", "description": "Покупки"},
    {"name": "cleaning", "description": "График уборки"},
    {"name": "messages", "description": "Чат"},
]

app = FastAPI(
    title="Neighbourhood App API",
    description="Backend API для приложения совместного проживания",
    version="2.0.0",
    openapi_tags=tags_metadata,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Pydantic Models
class UserRegister(BaseModel):
    username: str
    password: str
    first_name: str
    last_name: str
    middle_name: Optional[str] = None
    birth_date: str
    contact: str

class UserLogin(BaseModel):
    username: str
    password: str

class UserResponse(BaseModel):
    id: int
    username: str
    first_name: str
    last_name: str
    middle_name: Optional[str] = None
    birth_date: str
    contact: str
    created_at: datetime
    class Config:
        from_attributes = True

class RoomCreate(BaseModel):
    name: str

class RoomJoin(BaseModel):
    code: str

class RoomResponse(BaseModel):
    id: int
    name: str
    code: str
    created_by: int
    created_at: datetime
    member_count: int

class RoomMemberResponse(BaseModel):
    id: int
    user: UserResponse
    role: str
    is_banned: bool
    joined_at: datetime
    class Config:
        from_attributes = True

class TaskCreate(BaseModel):
    title: str
    description: Optional[str] = None
    assignee_id: int

class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    assignee_id: Optional[int] = None
    completed: Optional[bool] = None

class TaskResponse(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    assignee_id: int
    assignee: UserResponse
    completed: bool
    created_at: datetime
    updated_at: datetime
    class Config:
        from_attributes = True

class ShoppingItemCreate(BaseModel):
    name: str
    quantity: Optional[str] = None

class ShoppingItemUpdate(BaseModel):
    name: Optional[str] = None
    quantity: Optional[str] = None
    purchased: Optional[bool] = None

class ShoppingItemResponse(BaseModel):
    id: int
    name: str
    quantity: Optional[str] = None
    purchased: bool
    created_by: int
    created_at: datetime
    class Config:
        from_attributes = True

class CleaningScheduleCreate(BaseModel):
    user_id: int
    day_of_week: int
    area: str

class CleaningScheduleUpdate(BaseModel):
    user_id: Optional[int] = None
    day_of_week: Optional[int] = None
    area: Optional[str] = None

class CleaningScheduleResponse(BaseModel):
    id: int
    user_id: int
    day_of_week: int
    area: str
    created_at: datetime
    updated_at: datetime
    class Config:
        from_attributes = True

class MessageCreate(BaseModel):
    content: str

class MessageResponse(BaseModel):
    id: int
    sender_id: int
    sender: UserResponse
    content: str
    created_at: datetime
    class Config:
        from_attributes = True

class Token(BaseModel):
    access_token: str
    token_type: str
    user: UserResponse

# Auth Endpoints
@app.post("/api/register", response_model=Token, tags=["auth"])
def register(user_data: UserRegister, db: Session = Depends(get_db)):
    existing_user = db.query(User).filter(User.username == user_data.username).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Username already registered")
    
    hashed_password = get_password_hash(user_data.password)
    db_user = User(
        username=user_data.username,
        hashed_password=hashed_password,
        first_name=user_data.first_name,
        last_name=user_data.last_name,
        middle_name=user_data.middle_name,
        birth_date=user_data.birth_date,
        contact=user_data.contact
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    
    access_token = create_access_token(
        data={"sub": db_user.username},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": db_user
    }

@app.post("/api/login", response_model=Token, tags=["auth"])
def login(user_data: UserLogin, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == user_data.username).first()
    if not user or not verify_password(user_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password"
        )
    
    access_token = create_access_token(
        data={"sub": user.username},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": user
    }

@app.get("/api/me", response_model=UserResponse, tags=["auth"])
def get_me(current_user: User = Depends(get_current_user)):
    return current_user

# Room Endpoints
@app.post("/api/rooms", response_model=RoomResponse, tags=["rooms"], status_code=201)
def create_room(
    room_data: RoomCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    code = generate_room_code(db)
    room = Room(name=room_data.name, code=code, created_by=current_user.id)
    db.add(room)
    db.commit()
    db.refresh(room)
    
    membership = RoomMember(room_id=room.id, user_id=current_user.id, role=UserRole.OWNER)
    db.add(membership)
    db.commit()
    
    return {
        "id": room.id,
        "name": room.name,
        "code": room.code,
        "created_by": room.created_by,
        "created_at": room.created_at,
        "member_count": 1
    }

@app.get("/api/rooms", response_model=List[RoomResponse], tags=["rooms"])
def get_my_rooms(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    memberships = db.query(RoomMember).filter(
        RoomMember.user_id == current_user.id,
        RoomMember.is_banned == False
    ).all()
    
    rooms = []
    for membership in memberships:
        room = membership.room
        member_count = db.query(RoomMember).filter(
            RoomMember.room_id == room.id,
            RoomMember.is_banned == False
        ).count()
        
        rooms.append({
            "id": room.id,
            "name": room.name,
            "code": room.code,
            "created_by": room.created_by,
            "created_at": room.created_at,
            "member_count": member_count
        })
    
    return rooms

@app.post("/api/rooms/join", response_model=RoomResponse, tags=["rooms"])
def join_room(join_data: RoomJoin, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    room = db.query(Room).filter(Room.code == join_data.code.upper()).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    
    existing = db.query(RoomMember).filter(
        RoomMember.room_id == room.id,
        RoomMember.user_id == current_user.id
    ).first()
    
    if existing:
        if existing.is_banned:
            raise HTTPException(status_code=403, detail="You are banned from this room")
        raise HTTPException(status_code=400, detail="Already a member")
    
    membership = RoomMember(room_id=room.id, user_id=current_user.id, role=UserRole.MEMBER)
    db.add(membership)
    db.commit()
    
    member_count = db.query(RoomMember).filter(
        RoomMember.room_id == room.id,
        RoomMember.is_banned == False
    ).count()
    
    return {
        "id": room.id,
        "name": room.name,
        "code": room.code,
        "created_by": room.created_by,
        "created_at": room.created_at,
        "member_count": member_count
    }

@app.delete("/api/rooms/{room_id}", tags=["rooms"])
def delete_room(room_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    check_owner_access(db, current_user.id, room_id)
    room = db.query(Room).filter(Room.id == room_id).first()
    db.delete(room)
    db.commit()
    return {"message": "Room deleted"}

@app.post("/api/rooms/{room_id}/leave", tags=["rooms"])
def leave_room(room_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    membership = db.query(RoomMember).filter(
        RoomMember.room_id == room_id,
        RoomMember.user_id == current_user.id
    ).first()
    
    if not membership:
        raise HTTPException(status_code=404, detail="Not a member")
    
    if membership.role == UserRole.OWNER:
        raise HTTPException(status_code=400, detail="Owner cannot leave the room. Delete it instead.")
    
    db.delete(membership)
    db.commit()
    return {"message": "Left the room"}

@app.get("/api/rooms/{room_id}/members", response_model=List[RoomMemberResponse], tags=["rooms"])
def get_room_members(room_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    check_room_access(db, current_user.id, room_id)
    members = db.query(RoomMember).filter(RoomMember.room_id == room_id).all()
    
    result = []
    for member in members:
        result.append({
            "id": member.id,
            "user": member.user,
            "role": member.role.value,
            "is_banned": member.is_banned,
            "joined_at": member.joined_at
        })
    
    return result

@app.post("/api/rooms/{room_id}/ban/{user_id}", tags=["rooms"])
def ban_user(room_id: int, user_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    check_owner_access(db, current_user.id, room_id)
    
    membership = db.query(RoomMember).filter(
        RoomMember.room_id == room_id,
        RoomMember.user_id == user_id
    ).first()
    
    if not membership:
        raise HTTPException(status_code=404, detail="User not found in room")
    
    if membership.role == UserRole.OWNER:
        raise HTTPException(status_code=400, detail="Cannot ban owner")
    
    membership.is_banned = True
    db.commit()
    return {"message": "User banned"}

@app.post("/api/rooms/{room_id}/unban/{user_id}", tags=["rooms"])
def unban_user(room_id: int, user_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    check_owner_access(db, current_user.id, room_id)
    
    membership = db.query(RoomMember).filter(
        RoomMember.room_id == room_id,
        RoomMember.user_id == user_id
    ).first()
    
    if not membership:
        raise HTTPException(status_code=404, detail="User not found in room")
    
    membership.is_banned = False
    db.commit()
    return {"message": "User unbanned"}

@app.delete("/api/rooms/{room_id}/kick/{user_id}", tags=["rooms"])
def kick_user(room_id: int, user_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    check_owner_access(db, current_user.id, room_id)
    
    membership = db.query(RoomMember).filter(
        RoomMember.room_id == room_id,
        RoomMember.user_id == user_id
    ).first()
    
    if not membership:
        raise HTTPException(status_code=404, detail="User not found in room")
    
    if membership.role == UserRole.OWNER:
        raise HTTPException(status_code=400, detail="Cannot kick owner")
    
    db.delete(membership)
    db.commit()
    return {"message": "User kicked"}

# Users Endpoints
@app.get("/api/rooms/{room_id}/users", response_model=List[UserResponse], tags=["users"])
def get_room_users(room_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    check_room_access(db, current_user.id, room_id)
    
    members = db.query(RoomMember).filter(
        RoomMember.room_id == room_id,
        RoomMember.is_banned == False
    ).all()
    
    return [member.user for member in members]

# Tasks Endpoints
@app.get("/api/rooms/{room_id}/tasks", response_model=List[TaskResponse], tags=["tasks"])
def get_tasks(room_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    check_room_access(db, current_user.id, room_id)
    return db.query(Task).filter(Task.room_id == room_id).all()

@app.post("/api/rooms/{room_id}/tasks", response_model=TaskResponse, tags=["tasks"], status_code=201)
def create_task(room_id: int, task_data: TaskCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    check_room_access(db, current_user.id, room_id)
    task = Task(**task_data.dict(), room_id=room_id)
    db.add(task)
    db.commit()
    db.refresh(task)
    return task

@app.put("/api/rooms/{room_id}/tasks/{task_id}", response_model=TaskResponse, tags=["tasks"])
def update_task(room_id: int, task_id: int, task_data: TaskUpdate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    role = check_room_access(db, current_user.id, room_id)
    task = db.query(Task).filter(Task.id == task_id, Task.room_id == room_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    if role == UserRole.MEMBER and task.assignee_id != current_user.id:
        raise HTTPException(status_code=403, detail="Can only edit your own tasks")
    
    for key, value in task_data.dict(exclude_unset=True).items():
        setattr(task, key, value)
    
    db.commit()
    db.refresh(task)
    return task

@app.delete("/api/rooms/{room_id}/tasks/{task_id}", tags=["tasks"])
def delete_task(room_id: int, task_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    role = check_room_access(db, current_user.id, room_id)
    task = db.query(Task).filter(Task.id == task_id, Task.room_id == room_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    if role == UserRole.MEMBER and task.assignee_id != current_user.id:
        raise HTTPException(status_code=403, detail="Can only delete your own tasks")
    
    db.delete(task)
    db.commit()
    return {"message": "Task deleted"}

# Shopping Endpoints
@app.get("/api/rooms/{room_id}/shopping", response_model=List[ShoppingItemResponse], tags=["shopping"])
def get_shopping_items(room_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    check_room_access(db, current_user.id, room_id)
    return db.query(ShoppingItem).filter(ShoppingItem.room_id == room_id).all()

@app.post("/api/rooms/{room_id}/shopping", response_model=ShoppingItemResponse, tags=["shopping"], status_code=201)
def create_shopping_item(room_id: int, item_data: ShoppingItemCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    check_room_access(db, current_user.id, room_id)
    item = ShoppingItem(**item_data.dict(), room_id=room_id, created_by=current_user.id)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item

@app.put("/api/rooms/{room_id}/shopping/{item_id}", response_model=ShoppingItemResponse, tags=["shopping"])
def update_shopping_item(room_id: int, item_id: int, item_data: ShoppingItemUpdate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    check_room_access(db, current_user.id, room_id)
    item = db.query(ShoppingItem).filter(ShoppingItem.id == item_id, ShoppingItem.room_id == room_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    
    for key, value in item_data.dict(exclude_unset=True).items():
        setattr(item, key, value)
    
    db.commit()
    db.refresh(item)
    return item

@app.delete("/api/rooms/{room_id}/shopping/{item_id}", tags=["shopping"])
def delete_shopping_item(room_id: int, item_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    check_room_access(db, current_user.id, room_id)
    item = db.query(ShoppingItem).filter(ShoppingItem.id == item_id, ShoppingItem.room_id == room_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    
    db.delete(item)
    db.commit()
    return {"message": "Item deleted"}

# Cleaning Endpoints
@app.get("/api/rooms/{room_id}/cleaning", response_model=List[CleaningScheduleResponse], tags=["cleaning"])
def get_cleaning_schedule(room_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    check_room_access(db, current_user.id, room_id)
    return db.query(CleaningSchedule).filter(CleaningSchedule.room_id == room_id).all()

@app.post("/api/rooms/{room_id}/cleaning", response_model=CleaningScheduleResponse, tags=["cleaning"], status_code=201)
def create_cleaning_schedule(room_id: int, schedule_data: CleaningScheduleCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    check_room_access(db, current_user.id, room_id)
    schedule = CleaningSchedule(**schedule_data.dict(), room_id=room_id)
    db.add(schedule)
    db.commit()
    db.refresh(schedule)
    return schedule

@app.put("/api/rooms/{room_id}/cleaning/{schedule_id}", response_model=CleaningScheduleResponse, tags=["cleaning"])
def update_cleaning_schedule(room_id: int, schedule_id: int, schedule_data: CleaningScheduleUpdate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    check_room_access(db, current_user.id, room_id)
    schedule = db.query(CleaningSchedule).filter(
        CleaningSchedule.id == schedule_id,
        CleaningSchedule.room_id == room_id
    ).first()
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    
    for key, value in schedule_data.dict(exclude_unset=True).items():
        setattr(schedule, key, value)
    
    db.commit()
    db.refresh(schedule)
    return schedule

@app.delete("/api/rooms/{room_id}/cleaning/{schedule_id}", tags=["cleaning"])
def delete_cleaning_schedule(room_id: int, schedule_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    check_room_access(db, current_user.id, room_id)
    schedule = db.query(CleaningSchedule).filter(
        CleaningSchedule.id == schedule_id,
        CleaningSchedule.room_id == room_id
    ).first()
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    
    db.delete(schedule)
    db.commit()
    return {"message": "Schedule deleted"}

# Messages Endpoints
@app.get("/api/rooms/{room_id}/messages", response_model=List[MessageResponse], tags=["messages"])
def get_messages(room_id: int, limit: int = 100, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    check_room_access(db, current_user.id, room_id)
    messages = db.query(Message).filter(
        Message.room_id == room_id
    ).order_by(Message.created_at.desc()).limit(limit).all()
    return messages[::-1]

@app.post("/api/rooms/{room_id}/messages", response_model=MessageResponse, tags=["messages"], status_code=201)
def create_message(room_id: int, message_data: MessageCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    check_room_access(db, current_user.id, room_id)
    message = Message(room_id=room_id, sender_id=current_user.id, content=message_data.content)
    db.add(message)
    db.commit()
    db.refresh(message)
    return message

@app.get("/api/rooms/{room_id}/messages/poll", response_model=List[MessageResponse], tags=["messages"])
async def poll_messages(
    room_id: int,
    last_message_id: int = Query(0, description="ID последнего полученного сообщения"),
    timeout: int = Query(25, description="Таймаут ожидания в секундах"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    check_room_access(db, current_user.id, room_id)
    timeout = min(timeout, 30)
    start_time = asyncio.get_event_loop().time()
    
    while True:
        query = db.query(Message).filter(Message.room_id == room_id)
        if last_message_id > 0:
            query = query.filter(Message.id > last_message_id)
        
        new_messages = query.order_by(Message.created_at.asc()).all()
        
        if new_messages:
            return new_messages
        
        elapsed = asyncio.get_event_loop().time() - start_time
        if elapsed >= timeout:
            return []
        
        await asyncio.sleep(0.5)
        db.expire_all()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)