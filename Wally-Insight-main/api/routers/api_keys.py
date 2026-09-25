import secrets
import bcrypt
from fastapi import APIRouter, Depends, HTTPException
from typing import Annotated
from sqlmodel import Session, select, func

from ..database import get_session
from ..models.api_keys import ApiKeys, ApiKeyPublic
from .auth import check_login

MAX_API_KEYS = 3

router = APIRouter(tags=["API Keys"], dependencies=[Depends(check_login)])

@router.get("/api-keys", response_model=list[ApiKeyPublic])
def list_api_keys(
    db: Annotated[Session, Depends(get_session)],
):
    return db.exec(select(ApiKeys)).all()

@router.post("/api-keys")
def create_api_key(
    db: Annotated[Session, Depends(get_session)],
):
    # Enforce max API keys limit
    count = db.exec(select(func.count()).select_from(ApiKeys)).one()
    if count >= MAX_API_KEYS:
        raise HTTPException(status_code=400, detail=f"Maximum of {MAX_API_KEYS} API keys allowed")

    # Generate a random API key
    raw_key = secrets.token_hex(32)

    # Hash the key for storage
    key_hash = bcrypt.hashpw(raw_key.encode('utf-8'), bcrypt.gensalt()).decode()

    # Create the record
    api_key = ApiKeys(key_hash=key_hash)
    db.add(api_key)
    db.commit()
    db.refresh(api_key)

    # Return the plaintext key only once
    return {
        "id": api_key.id,
        "key": raw_key,
        "created_at": api_key.created_at,
    }

@router.delete("/api-keys/{api_key_id}")
def delete_api_key(
    api_key_id: str,
    db: Annotated[Session, Depends(get_session)],
):
    api_key = db.get(ApiKeys, api_key_id)
    if not api_key:
        raise HTTPException(status_code=404, detail="API key not found")
    db.delete(api_key)
    db.commit()
    return {"message": "API key deleted"}
