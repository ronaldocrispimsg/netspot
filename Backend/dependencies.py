from datetime import datetime
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from jose import JWTError

from Backend.database import get_db
from Backend.models import User
from Backend.security import decode_token

security = HTTPBearer()

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security), db: Session = Depends(get_db)):
    try:
        payload = decode_token(credentials.credentials)
        username = payload.get("sub")

        user = db.query(User).filter(User.username == username).first()

        if not user:
            raise HTTPException(status_code=401, detail="Usuário não encontrado")

        if user.locked:
            if user.locked_until and user.locked_until <= datetime.now():
                user.locked = False
                user.locked_until = None
                user.attempts = 0
                db.commit()
            else:
                raise HTTPException(status_code=403, detail="Conta de usuário bloqueada")

        return user

    except JWTError:
        raise HTTPException(status_code=401, detail="Token inválido")
    
def get_current_admin(user: User = Depends(get_current_user)):
    is_admin = bool(getattr(user, "is_admin", False) or getattr(user, "username", "") == "admin")
    if not is_admin:
        raise HTTPException(status_code=403, detail="Acesso negado")
    return user
