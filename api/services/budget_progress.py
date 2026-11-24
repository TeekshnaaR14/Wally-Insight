from datetime import date
from decimal import Decimal

from sqlmodel import Session, select

from ..models.budgets import Budget, BudgetPublic
from ..models.transactions import Transaction
from .budget_forecast import forecast_month_end
from .budget_period import current_window, in_window


class BudgetWithProgress(BudgetPublic):
    window_start: date
    window_end: date
    spent: Decimal
    projected_month_end: Decimal | None = None

def get_budget_progress(
    db: Session, today: date, *, through_today: bool = False
) -> list[BudgetWithProgress]:
    budgets = db.exec(select(Budget).order_by(Budget.category)).all()
    statement = select(Transaction).where(Transaction.type == "expense")
    if through_today:
        statement = statement.where(Transaction.date <= today)
    transactions = db.exec(statement).all()
    result = []

    for budget in budgets:
        window_start, window_end = current_window(budget.period, budget.start_date, today)
        spent = sum(
            (transaction.amount for transaction in transactions
             if transaction.category == budget.category
             and in_window(transaction.date, window_start, window_end)),
            Decimal("0.00"),
        )
        projected = forecast_month_end(spent, window_start, window_end, today)

        result.append(BudgetWithProgress(
            category=budget.category,
            limit=budget.limit,
            period=budget.period,
            start_date=budget.start_date,
            window_start=window_start,
            window_end=window_end,
            spent=spent,
            projected_month_end=projected,
        ))
    return result
