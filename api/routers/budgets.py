from fastapi import APIRouter, Depends, HTTPException
from typing import Annotated
from sqlmodel import Session, select
from sqlalchemy.exc import IntegrityError

from datetime import date

from ..services.budget_progress import BudgetWithProgress, get_budget_progress

from ..database import get_session
from ..models.budgets import Budget, BudgetCreate, BudgetPublic, BudgetUpdate
from ..models.budget_alerts import BudgetAlert
from ..models.categories import Category
from .auth import check_login


router = APIRouter(tags=["Budgets"], dependencies=[Depends(check_login)])


@router.get("/budgets", response_model=list[BudgetWithProgress])
def read_budgets(db: Annotated[Session, Depends(get_session)]):
    return get_budget_progress(db, date.today())


@router.post("/budgets", response_model=BudgetPublic)
def create_budget(
    budget: BudgetCreate,
    db: Annotated[Session, Depends(get_session)]
):
    # Budgets can only be created for existing transaction categories.
    if not db.get(Category, budget.category):
        raise HTTPException(status_code=400, detail="This category does not exist.")

    new_budget = Budget.model_validate(budget)
    db.add(new_budget)

    try:
        db.commit()
        db.refresh(new_budget)
        return new_budget
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail="A budget for this category already exists."
        )


@router.get("/budgets/{category_name}", response_model=BudgetPublic)
def read_budget(
    category_name: str,
    db: Annotated[Session, Depends(get_session)]
):
    budget = db.get(Budget, category_name)

    if not budget:
        raise HTTPException(status_code=404, detail="This budget does not exist.")

    return budget


@router.put("/budgets/{category_name}", response_model=BudgetPublic)
def update_budget(
    category_name: str,
    budget_update: BudgetUpdate,
    db: Annotated[Session, Depends(get_session)]
):
    budget = db.get(Budget, category_name)

    if not budget:
        raise HTTPException(status_code=404, detail="This budget does not exist.")

    budget_data = budget_update.model_dump(exclude_unset=True)
    budget.sqlmodel_update(budget_data)

    db.add(budget)
    db.commit()
    db.refresh(budget)

    return budget


@router.delete("/budgets/{category_name}")
def delete_budget(
    category_name: str,
    db: Annotated[Session, Depends(get_session)]
):
    budget = db.get(Budget, category_name)

    if not budget:
        raise HTTPException(status_code=404, detail="This budget does not exist.")

    # Remove the alerts of the deleted budget as well
    for alert in db.exec(select(BudgetAlert).where(BudgetAlert.category == category_name)).all():
        db.delete(alert)

    db.delete(budget)
    db.commit()

    return {"ok": True}
