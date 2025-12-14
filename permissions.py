from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from models import Room, RoomMember, User, UserRole

def get_user_room_role(db: Session, user_id: int, room_id: int) -> UserRole | None:
    membership = db.query(RoomMember).filter(
        RoomMember.user_id == user_id,
        RoomMember.room_id == room_id
    ).first()
    
    if not membership:
        return None
    
    if membership.is_banned:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are banned from this room"
        )
    
    return membership.role

def check_room_access(db: Session, user_id: int, room_id: int):
    role = get_user_room_role(db, user_id, room_id)
    if role is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a member of this room"
        )
    return role

def check_admin_access(db: Session, user_id: int, room_id: int):
    role = check_room_access(db, user_id, room_id)
    if role not in [UserRole.OWNER, UserRole.ADMIN]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin rights required"
        )
    return role

def check_owner_access(db: Session, user_id: int, room_id: int):
    role = check_room_access(db, user_id, room_id)
    if role != UserRole.OWNER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Owner rights required"
        )
    return role