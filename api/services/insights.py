from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from pydantic import BaseModel
from sqlmodel import Session, select

from ..models.recurring_transactions import RecurringTransaction
from .budget_progress import get_budget_progress
from .spending_history import expense_amounts_between, shift_month
from .subscriptions import subscription_summary


class CategorySpending(BaseModel):
    category: str
    amount: Decimal


class SpendingChange(BaseModel):
    category: str
    current: Decimal
    previous: Decimal
    change: Decimal


class BudgetRisk(BaseModel):
    category: str
    period: str
    spent: Decimal
    limit: Decimal
    forecast: Decimal | None


class Insights(BaseModel):
    top_categories: list[CategorySpending]
    biggest_change: SpendingChange | None
    closest_budget: BudgetRisk | None
    monthly_subscription_cost: Decimal | None


def get_insights(db: Session, today: date) -> Insights:
    current_start = today.replace(day=1)
    previous_start = shift_month(current_start, -1)
    previous_end = min(
        current_start - timedelta(days=1),
        previous_start + timedelta(days=today.day - 1),
    )
    current_end = current_start + (previous_end - previous_start)
    current = defaultdict(Decimal)
    comparable_current = defaultdict(Decimal)
    previous = defaultdict(Decimal)

    statement = expense_amounts_between(previous_start, today + timedelta(days=1))
    for category, amount, transaction_date in db.exec(statement):
        if transaction_date >= current_start:
            current[category] += amount
            if transaction_date <= current_end:
                comparable_current[category] += amount
        elif transaction_date <= previous_end:
            previous[category] += amount

    top_categories = sorted(current, key=lambda category: (-current[category], category))
    biggest_change = None
    if comparable_current and previous:
        changes = {
            category: comparable_current.get(category, Decimal(0)) - previous.get(category, Decimal(0))
            for category in comparable_current.keys() | previous.keys()
        }
        category = min(changes, key=lambda name: (-abs(changes[name]), name))
        if changes[category]:
            biggest_change = SpendingChange(
                category=category,
                current=comparable_current.get(category, Decimal(0)),
                previous=previous.get(category, Decimal(0)),
                change=changes[category],
            )

    budgets = get_budget_progress(db, today, through_today=True)
    closest_budget = max(
        (budget for budget in budgets if budget.spent > 0 and budget.start_date <= today),
        key=lambda budget: budget.spent / budget.limit,
        default=None,
    )
    recurring = db.exec(select(RecurringTransaction)).all()
    subscriptions = subscription_summary(recurring, today)

    return Insights(
        top_categories=[
            CategorySpending(category=category, amount=current[category])
            for category in top_categories[:3]
        ],
        biggest_change=biggest_change,
        closest_budget=BudgetRisk(
            category=closest_budget.category,
            period=closest_budget.period,
            spent=closest_budget.spent,
            limit=closest_budget.limit,
            forecast=closest_budget.projected_month_end,
        ) if closest_budget else None,
        monthly_subscription_cost=(
            Decimal(str(subscriptions["monthlyTotal"]))
            if subscriptions["subscriptions"] else None
        ),
    )
