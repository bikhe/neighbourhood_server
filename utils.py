import random
import string
from sqlalchemy.orm import Session
from models import Room

def generate_room_code(db: Session, length: int = 6) -> str:
    while True:
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))
        existing = db.query(Room).filter(Room.code == code).first()
        if not existing:
            return code