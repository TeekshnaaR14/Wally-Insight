from datetime import date
from decimal import Decimal
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from api.database import get_session
from api.models.app import AppConfig
from api.models.budgets import Budget
from api.models.recurring_transactions import RecurringTransaction
from api.models.transactions import Transaction
from api.routers.insights import router as insights_router
from api.routers.spending_history import get_today
from api.routers.transactions import router as transactions_router


class InsightsTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.addCleanup(self.engine.dispose)
        SQLModel.metadata.create_all(self.engine)
        self.today = date(2026, 11, 15)
        self.save(AppConfig(key="LOGIN_PAGE", value=False))
        app = FastAPI()
        app.include_router(insights_router)
        app.include_router(transactions_router)
        app.dependency_overrides[get_session] = self.session
        app.dependency_overrides[get_today] = lambda: self.today
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def session(self):
        with Session(self.engine) as session:
            yield session

    def save(self, *rows):
        with Session(self.engine) as session:
            session.add_all(rows)
            session.commit()

    def expense(self, category, amount, when, kind="expense"):
        return Transaction(
            category=category, amount=Decimal(amount), date=date.fromisoformat(when), type=kind
        )

    def insights(self):
        response = self.client.get("/insights")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers["cache-control"], "no-store")
        return response.json()

    def test_empty_then_new_transaction_is_reflected(self):
        self.assertEqual(self.insights(), {
            "top_categories": [],
            "biggest_change": None,
            "closest_budget": None,
            "monthly_subscription_cost": None,
        })
        response = self.client.post("/transactions", json={
            "name": "Groceries", "category": "Food", "amount": "18.25", "date": "2026-11-15",
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.insights()["top_categories"], [
            {"category": "Food", "amount": "18.25"},
        ])

    def test_spending_and_change_ignore_income_future_and_out_of_range_dates(self):
        self.save(
            self.expense("Food", "45", "2026-11-01"),
            self.expense("Food", "25", "2026-11-15"),
            self.expense("Food", "30", "2026-10-15"),
            self.expense("Food", "500", "2026-10-16"),
            self.expense("Rent", "200", "2026-11-09"),
            self.expense("Rent", "180", "2026-10-09"),
            self.expense("Travel", "20", "2026-11-06"),
            self.expense("Gifts", "10", "2026-11-06"),
            self.expense("Travel", "800", "2026-11-16"),
            self.expense("Salary", "1000", "2026-11-03", "income"),
        )
        result = self.insights()
        self.assertEqual(result["top_categories"], [
            {"category": "Rent", "amount": "200.00"},
            {"category": "Food", "amount": "70.00"},
            {"category": "Travel", "amount": "20.00"},
        ])
        self.assertEqual(result["biggest_change"], {
            "category": "Food", "current": "70.00", "previous": "30.00", "change": "40.00",
        })

    def test_change_compares_equal_days_when_previous_month_is_shorter(self):
        self.today = date(2026, 3, 31)
        self.save(
            self.expense("Food", "32", "2026-02-28"),
            self.expense("Food", "12", "2026-03-28"),
            self.expense("Food", "100", "2026-03-29"),
        )
        result = self.insights()
        self.assertEqual(result["top_categories"][0]["amount"], "112.00")
        self.assertEqual(result["biggest_change"], {
            "category": "Food", "current": "12.00", "previous": "32.00", "change": "-20.00",
        })

    def test_budget_uses_active_window_utilization_and_forecast(self):
        self.save(
            Budget(category="Food", limit=Decimal("100"), period="weekly",
                   start_date=date(2026, 11, 10)),
            Budget(category="Rent", limit=Decimal("300"), period="monthly",
                   start_date=date(2026, 11, 1)),
            self.expense("Food", "90", "2026-11-15"),
            self.expense("Food", "200", "2026-11-09"),
            self.expense("Food", "300", "2026-11-16"),
            self.expense("Rent", "260", "2026-11-01"),
        )
        self.assertEqual(self.insights()["closest_budget"], {
            "category": "Food", "period": "weekly", "spent": "90.00",
            "limit": "100.00", "forecast": "105.00",
        })

    def test_subscription_total_uses_payments_that_are_still_scheduled(self):
        self.save(
            RecurringTransaction(category="Media", amount=Decimal("36"), frequency="quarterly",
                                 startDate=date(2026, 10, 1), endDate=date(2027, 10, 1),
                                 isSubscription=True),
            RecurringTransaction(category="Media", amount=Decimal("8.50"), frequency="monthly",
                                 startDate=date(2026, 10, 1), endDate=date(2027, 10, 1),
                                 isSubscription=True),
            RecurringTransaction(category="Media", amount=Decimal("100"), frequency="monthly",
                                 startDate=date(2026, 9, 1), endDate=date(2026, 10, 1),
                                 isSubscription=True),
            RecurringTransaction(category="Rent", amount=Decimal("100"), frequency="monthly",
                                 startDate=date(2026, 10, 1), endDate=date(2027, 10, 1)),
        )
        self.assertEqual(self.insights()["monthly_subscription_cost"], "20.5")

    def test_insights_requires_login_when_enabled(self):
        self.save(AppConfig(key="SECRET_KEY", value="test-key"),
                  AppConfig(key="LOGIN_TOKEN", value=""))
        with Session(self.engine) as session:
            config = session.get(AppConfig, "LOGIN_PAGE")
            config.value = True
            session.add(config)
            session.commit()
        self.assertEqual(self.client.get("/insights").status_code, 401)
