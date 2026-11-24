from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from sqlmodel import Session

from ..database import get_session
from ..services.insights import Insights, get_insights
from .auth import check_login
from .spending_history import get_today


router = APIRouter(tags=["Insights"], dependencies=[Depends(check_login)])


@router.get("/insights", response_model=Insights)
def read_insights(
    response: Response,
    db: Annotated[Session, Depends(get_session)],
    today: Annotated[date, Depends(get_today)],
):
    response.headers["Cache-Control"] = "no-store"
    return get_insights(db, today)
