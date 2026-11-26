"""Read-only summary of the user's data that is given to the AI assistant.

The assistant model never touches the database. It only receives the text
built here, and everything in this module only reads (select) from the database.
"""
import calendar
from datetime import date
from decimal import Decimal

from dateutil.relativedelta import relativedelta
from sqlmodel import Session, select

from ..models.app import AppConfig
from ..models.budget_alerts import BudgetAlert, OVER_BUDGET
from ..models.budgets import Budget
from ..models.currency import Currency
from ..models.recurring_transactions import RecurringTransaction
from ..models.transactions import Transaction
from .budget_forecast import forecast_month_end
from .budget_period import current_window, in_window
from .subscriptions import subscription_summary

ZERO = Decimal("0.00")
TOP_EXPENSES = 5


def _config(db: Session, key: str, default: str) -> str:
    config = db.get(AppConfig, key)
    return str(config.value) if config and config.value not in (None, "") else default


def _currency(db: Session) -> dict:
    name = _config(db, "SELECTED_CURRENCY", "EUR")
    currency = db.get(Currency, name)
    return {
        "name": name,
        "symbol": currency.symbol if currency else name,
        "position": _config(db, "CURRENCY_POSITION", "right"),
    }


def _period_summary(transactions, start: date, end: date, label: str) -> dict:
    spent_by_category: dict[str, Decimal] = {}
    total_spent = ZERO
    total_income = ZERO
    count = 0

    for transaction in transactions:
        if not in_window(transaction.date, start, end):
            continue
        count += 1
        if transaction.type == "income":
            total_income += transaction.amount
        else:
            total_spent += transaction.amount
            spent_by_category[transaction.category] = (
                spent_by_category.get(transaction.category, ZERO) + transaction.amount
            )

    by_category = sorted(
        ({"category": category, "spent": amount} for category, amount in spent_by_category.items()),
        key=lambda item: (-item["spent"], item["category"]),
    )
    return {
        "label": label,
        "start": start,
        "end": end,
        "total_spent": total_spent,
        "total_income": total_income,
        "transaction_count": count,
        "by_category": by_category,
    }


def _budgets(db: Session, transactions, today: date) -> list[dict]:
    result = []
    for budget in db.exec(select(Budget)).all():
        window_start, window_end = current_window(budget.period, budget.start_date, today)
        spent = sum(
            (transaction.amount for transaction in transactions
             if transaction.category == budget.category
             and transaction.type == "expense"
             and in_window(transaction.date, window_start, window_end)),
            ZERO,
        )
        percent_used = (spent * 100 / budget.limit).quantize(Decimal("0.1"))
        result.append({
            "category": budget.category,
            "period": budget.period,
            "limit": budget.limit,
            "spent": spent,
            "remaining": budget.limit - spent,
            "percent_used": percent_used,
            "window_start": window_start,
            "window_end": window_end,
            "forecast": forecast_month_end(spent, window_start, window_end, today),
        })

    # Closest to (or furthest over) its limit first
    return sorted(result, key=lambda item: (-item["percent_used"], item["category"]))


def build_context(db: Session, today: date | None = None) -> dict:
    """Collect category totals, budget status, forecasts, subscriptions and alerts.

    Only transactions dated today or earlier count as spent, because recurring
    transactions are stored in advance for future dates.
    """
    today = today or date.today()

    month_start = today.replace(day=1)
    month_end = today.replace(day=calendar.monthrange(today.year, today.month)[1])
    last_month_start = month_start - relativedelta(months=1)
    last_month_end = month_start - relativedelta(days=1)
    year_start = date(today.year, 1, 1)

    transactions = db.exec(
        select(Transaction).where(
            Transaction.date >= min(last_month_start, year_start),
            Transaction.date <= today,
        )
    ).all()

    this_month = _period_summary(transactions, month_start, today, today.strftime("%B %Y"))
    this_month["end_of_month"] = month_end

    expenses_this_month = sorted(
        (t for t in transactions if t.type == "expense" and in_window(t.date, month_start, today)),
        key=lambda t: (-t.amount, t.date),
    )

    budget_alerts = db.exec(
        select(BudgetAlert).where(BudgetAlert.dismissed == False)  # noqa: E712
    ).all()

    return {
        "today": today,
        "currency": _currency(db),
        "this_month": this_month,
        "last_month": _period_summary(
            transactions, last_month_start, last_month_end, last_month_start.strftime("%B %Y")
        ),
        "this_year": _period_summary(transactions, year_start, today, str(today.year)),
        "biggest_expenses_this_month": [
            {"name": t.name or t.category, "category": t.category, "amount": t.amount, "date": t.date}
            for t in expenses_this_month[:TOP_EXPENSES]
        ],
        "budgets": _budgets(db, transactions, today),
        "subscriptions": subscription_summary(db.exec(select(RecurringTransaction)).all(), today),
        "budget_alerts": [
            {
                "category": alert.category,
                "type": "over budget" if alert.level == OVER_BUDGET else f"{alert.threshold}% warning",
                "spent": alert.spent,
                "limit": alert.limit,
            }
            for alert in budget_alerts
        ],
    }


def format_money(amount, currency: dict) -> str:
    value = f"{Decimal(str(amount)):,.2f}"
    return f"{currency['symbol']}{value}" if currency["position"] == "left" else f"{value}{currency['symbol']}"


def key_facts(context: dict, money) -> list[str]:
    """Answers to the most common questions, worked out here so the model does not have to compare numbers."""
    month = context["this_month"]
    lines = [
        "KEY FACTS:",
        f"- Total spent this month so far: {money(month['total_spent'])}; "
        f"last month: {money(context['last_month']['total_spent'])}",
    ]
    if month["by_category"]:
        top = month["by_category"][0]
        lines.append(f"- Category with the most spending this month: {top['category']} ({money(top['spent'])})")

    budgets = context["budgets"]
    over = [item for item in budgets if item["remaining"] < 0]
    under = [item for item in budgets if item["remaining"] >= 0]
    if not budgets:
        lines.append("- No budgets have been set.")
    if over:
        lines.append("- Budgets already over their limit: " + ", ".join(
            f"{item['category']} ({item['percent_used']}% used, over by {money(-item['remaining'])})" for item in over
        ))
    elif budgets:
        lines.append("- No budget is over its limit.")
    if under:
        closest = under[0]
        lines.append(
            f"- Budget closest to its limit (highest % used, not over yet): {closest['category']} "
            f"({closest['percent_used']}% used, {money(closest['remaining'])} remaining)"
        )
    return lines


def render_context(context: dict) -> str:
    """Turn the summary into plain text that small local models read reliably."""
    currency = context["currency"]

    def money(amount):
        return format_money(amount, currency)

    def period(summary, title):
        lines = [
            f"{title} ({summary['label']}, {summary['start']} to {summary['end']}):",
            f"- Total spent: {money(summary['total_spent'])}",
            f"- Total income: {money(summary['total_income'])}",
            f"- Number of transactions: {summary['transaction_count']}",
        ]
        if summary["by_category"]:
            lines.append("- Spent per category:")
            lines += [f"  - {item['category']}: {money(item['spent'])}" for item in summary["by_category"]]
        else:
            lines.append("- No spending recorded.")
        return lines

    lines = [
        f"Today is {context['today']}. Currency: {currency['name']} ({currency['symbol']}).",
        "",
        *key_facts(context, money),
        "",
        *period(context["this_month"], "THIS MONTH SO FAR"),
        "",
        *period(context["last_month"], "LAST MONTH"),
        "",
        *period(context["this_year"], "THIS YEAR SO FAR"),
        "",
        "BIGGEST EXPENSES THIS MONTH:",
    ]
    if context["biggest_expenses_this_month"]:
        lines += [
            f"- {item['name']} ({item['category']}): {money(item['amount'])} on {item['date']}"
            for item in context["biggest_expenses_this_month"]
        ]
    else:
        lines.append("- None.")

    lines += ["", "BUDGETS (sorted from closest to its limit to furthest):"]
    if context["budgets"]:
        for item in context["budgets"]:
            status = (
                f"over budget by {money(-item['remaining'])}" if item["remaining"] < 0
                else f"{money(item['remaining'])} remaining"
            )
            forecast = (
                f"forecast for the end of the period: {money(item['forecast'])}"
                if item["forecast"] is not None else "forecast: not enough data yet"
            )
            lines.append(
                f"- {item['category']} ({item['period']}, {item['window_start']} to {item['window_end']}): "
                f"spent {money(item['spent'])} of {money(item['limit'])} limit, "
                f"{item['percent_used']}% used, {status}, {forecast}"
            )
    else:
        lines.append("- No budgets have been set.")

    subscriptions = context["subscriptions"]
    lines += ["", "SUBSCRIPTIONS:"]
    if subscriptions["subscriptions"]:
        lines += [
            f"- {item['name']}: {money(item['amount'])} {item['frequency']}, "
            f"next charge {item['nextExpectedCharge']}, monthly equivalent {money(item['monthlyEquivalent'])}"
            for item in subscriptions["subscriptions"]
        ]
        lines.append(f"- Total monthly cost of all subscriptions: {money(subscriptions['monthlyTotal'])}")
    else:
        lines.append("- No subscriptions.")

    lines += ["", "ACTIVE BUDGET ALERTS:"]
    if context["budget_alerts"]:
        lines += [
            f"- {item['category']}: {item['type']} (spent {money(item['spent'])} of {money(item['limit'])})"
            for item in context["budget_alerts"]
        ]
    else:
        lines.append("- None.")

    return "\n".join(lines)
