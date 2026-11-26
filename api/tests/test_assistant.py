import json
import os
import unittest
from datetime import date
from decimal import Decimal
from unittest import mock

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine, func, select

from api.database import get_session
from api.models.app import AppConfig
from api.models.budget_alerts import BudgetAlert
from api.models.budgets import Budget
from api.models.currency import Currency
from api.models.recurring_transactions import RecurringTransaction
from api.models.transactions import Transaction
from api.routers.assistant import router as assistant_router
from api.routers.auth import check_login
from api.services import assistant
from api.services.assistant_context import build_context, render_context

test_engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

TODAY = date(2026, 11, 20)


def get_test_session():
    with Session(test_engine) as session:
        yield session


def skip_login():
    return True


test_app = FastAPI()
test_app.include_router(assistant_router)
test_app.dependency_overrides[get_session] = get_test_session
test_app.dependency_overrides[check_login] = skip_login

client = TestClient(test_app)


def expense(name, category, amount, on, type="expense"):
    return Transaction(name=name, category=category, amount=Decimal(str(amount)), type=type, date=on)


class AssistantTestCase(unittest.TestCase):
    def setUp(self):
        SQLModel.metadata.create_all(test_engine)
        self.db = Session(test_engine)
        self.requests = []
        assistant.http_transport = None
        # Defaults must not depend on the developer's own Ollama environment variables
        environment = mock.patch.dict(os.environ)
        environment.start()
        self.addCleanup(environment.stop)
        os.environ.pop("OLLAMA_URL", None)
        os.environ.pop("OLLAMA_MODEL", None)

    def tearDown(self):
        assistant.http_transport = None
        self.db.close()
        SQLModel.metadata.drop_all(test_engine)

    def add_demo_data(self):
        self.db.add_all([
            AppConfig(key="SELECTED_CURRENCY", value="EUR"),
            AppConfig(key="CURRENCY_POSITION", value="right"),
            Currency(name="EUR", symbol="€"),
            expense("Supermarket", "Food", 30, date(2026, 11, 2)),
            expense("Restaurant", "Food", 45.50, date(2026, 11, 10)),
            expense("Scheduled", "Food", 20, date(2026, 11, 25)),  # in the future, not spent yet
            expense("October shop", "Food", 100, date(2026, 10, 5)),
            expense("Rent", "Rent", 800, date(2026, 11, 1)),
            expense("Bus pass", "Transport", 25, date(2026, 11, 15)),
            expense("Salary", "Income", 2000, date(2026, 11, 1), type="income"),
            Budget(category="Food", limit=Decimal("100"), period="monthly", start_date=date(2026, 1, 1)),
            Budget(category="Transport", limit=Decimal("30"), period="monthly", start_date=date(2026, 1, 1)),
            Budget(category="Rent", limit=Decimal("750"), period="monthly", start_date=date(2026, 1, 1)),
            RecurringTransaction(
                name="Netflix", category="Entertainment", amount=Decimal("9.99"), type="expense",
                startDate=date(2026, 1, 5), endDate=date(2027, 1, 5), frequency="monthly", isSubscription=True,
            ),
            BudgetAlert(
                category="Rent", period="monthly", window_start=date(2026, 11, 1), window_end=date(2026, 11, 30),
                level="over_budget", threshold=100, spent=Decimal("800"), limit=Decimal("750"),
            ),
        ])
        self.db.commit()

    def mock_model(self, handler):
        def record(request):
            self.requests.append(request)
            return handler(request)
        assistant.http_transport = httpx.MockTransport(record)


class ContextBuilderTests(AssistantTestCase):
    def setUp(self):
        super().setUp()
        self.add_demo_data()
        self.context = build_context(self.db, TODAY)

    def test_category_totals_this_month_only_count_past_spending(self):
        month = self.context["this_month"]
        totals = {item["category"]: item["spent"] for item in month["by_category"]}

        self.assertEqual(totals, {"Rent": Decimal("800"), "Food": Decimal("75.50"), "Transport": Decimal("25")})
        self.assertEqual(month["total_spent"], Decimal("900.50"))
        self.assertEqual(month["total_income"], Decimal("2000"))

    def test_last_month_totals(self):
        totals = {item["category"]: item["spent"] for item in self.context["last_month"]["by_category"]}
        self.assertEqual(totals, {"Food": Decimal("100")})

    def test_budgets_sorted_from_closest_to_limit(self):
        budgets = self.context["budgets"]

        self.assertEqual([item["category"] for item in budgets], ["Rent", "Transport", "Food"])
        self.assertEqual(budgets[0]["percent_used"], Decimal("106.7"))
        self.assertEqual(budgets[0]["remaining"], Decimal("-50"))
        self.assertEqual(budgets[1]["percent_used"], Decimal("83.3"))
        self.assertEqual(budgets[2]["spent"], Decimal("75.50"))
        self.assertIsNotNone(budgets[2]["forecast"])

    def test_subscriptions_and_alerts_included(self):
        self.assertEqual(self.context["subscriptions"]["subscriptions"][0]["name"], "Netflix")
        self.assertEqual(self.context["subscriptions"]["monthlyTotal"], 9.99)
        self.assertEqual(self.context["budget_alerts"][0]["category"], "Rent")

    def test_biggest_expenses(self):
        names = [item["name"] for item in self.context["biggest_expenses_this_month"]]
        self.assertEqual(names, ["Rent", "Restaurant", "Supermarket", "Bus pass"])

    def test_rendered_text_has_exact_amounts_for_demo_questions(self):
        text = render_context(self.context)

        # "How much did I spend on food this month?"
        self.assertIn("THIS MONTH SO FAR (November 2026", text)
        self.assertIn("  - Food: 75.50€", text)
        # "Which budget is closest to its limit?"
        self.assertIn("BUDGETS (sorted from closest to its limit to furthest):\n- Rent", text)
        self.assertIn("106.7% used, over budget by 50.00€", text)
        self.assertIn("Netflix: 9.99€ monthly", text)
        self.assertIn("Total monthly cost of all subscriptions: 9.99€", text)

    def test_key_facts_answer_common_questions_directly(self):
        text = render_context(self.context)

        self.assertIn("- Total spent this month so far: 900.50€; last month: 100.00€", text)
        self.assertIn("- Category with the most spending this month: Rent (800.00€)", text)
        self.assertIn("- Budgets already over their limit: Rent (106.7% used, over by 50.00€)", text)
        self.assertIn(
            "- Budget closest to its limit (highest % used, not over yet): Transport (83.3% used, 5.00€ remaining)", text
        )
        # Key facts come before the detailed sections
        self.assertLess(text.index("KEY FACTS"), text.index("THIS MONTH SO FAR"))

    def test_key_facts_without_budgets(self):
        self.db.exec(Budget.__table__.delete())
        self.db.commit()
        text = render_context(build_context(self.db, TODAY))
        self.assertIn("- No budgets have been set.", text.split("THIS MONTH")[0])

    def test_building_context_never_writes(self):
        counts_before = [self.db.exec(select(func.count()).select_from(model)).one()
                         for model in (Transaction, Budget, BudgetAlert, AppConfig)]
        build_context(self.db, TODAY)
        counts_after = [self.db.exec(select(func.count()).select_from(model)).one()
                        for model in (Transaction, Budget, BudgetAlert, AppConfig)]

        self.assertEqual(counts_before, counts_after)
        self.assertFalse(self.db.new or self.db.dirty or self.db.deleted)


class EmptyContextTests(AssistantTestCase):
    def test_empty_data_says_so_instead_of_numbers(self):
        text = render_context(build_context(self.db, TODAY))
        self.assertIn("No spending recorded.", text)
        self.assertIn("No budgets have been set.", text)
        self.assertIn("No subscriptions.", text)

    def test_currency_on_the_left(self):
        self.db.add_all([
            AppConfig(key="SELECTED_CURRENCY", value="USD"),
            AppConfig(key="CURRENCY_POSITION", value="left"),
            Currency(name="USD", symbol="$"),
            expense("Lunch", "Food", 12.5, TODAY),
        ])
        self.db.commit()
        self.assertIn("  - Food: $12.50", render_context(build_context(self.db, TODAY)))


class PromptTests(unittest.TestCase):
    def test_messages_contain_rules_data_history_and_question(self):
        history = [{"role": "user", "content": "Hi"}, {"role": "assistant", "content": "Hello"}]
        messages = assistant.build_messages("How much on food?", "Food: 10€", history)

        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("Use ONLY the information in the WALLY DATA", messages[0]["content"])
        self.assertIn("Never guess or invent numbers", messages[0]["content"])
        self.assertIn("WALLY DATA:\nFood: 10€", messages[0]["content"])
        self.assertEqual(messages[1:3], history)
        self.assertEqual(messages[-1], {"role": "user", "content": "How much on food?"})


class AssistantEndpointTests(AssistantTestCase):
    def setUp(self):
        super().setUp()
        self.add_demo_data()

    def test_answer_from_local_ollama_with_user_data(self):
        def handler(request):
            return httpx.Response(200, json={"message": {"role": "assistant", "content": " You spent 75.50€ on Food. "}})
        self.mock_model(handler)

        response = client.post("/assistant", json={"question": "How much did I spend on food this month?"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            "answer": "You spent 75.50€ on Food.", "provider": "ollama", "model": "llama3.2:3b",
        })
        request = self.requests[0]
        body = json.loads(request.content)
        self.assertEqual(str(request.url), "http://localhost:11434/api/chat")
        self.assertEqual(body["model"], "llama3.2:3b")
        self.assertFalse(body["stream"])
        self.assertIn("WALLY DATA", body["messages"][0]["content"])
        self.assertIn("Food", body["messages"][0]["content"])
        self.assertEqual(body["messages"][-1]["content"], "How much did I spend on food this month?")

    def test_default_setup_never_calls_an_external_service(self):
        self.mock_model(lambda request: httpx.Response(200, json={"message": {"content": "OK"}}))
        client.post("/assistant", json={"question": "Which budget is closest to its limit?"})
        client.post("/assistant/test")

        self.assertTrue(self.requests)
        self.assertTrue(all(request.url.host == "localhost" for request in self.requests))

    def test_history_is_sent_for_follow_up_questions(self):
        self.mock_model(lambda request: httpx.Response(200, json={"message": {"content": "OK"}}))
        client.post("/assistant", json={
            "question": "And last month?",
            "history": [
                {"role": "user", "content": "How much on food this month?"},
                {"role": "assistant", "content": "75.50€"},
            ],
        })
        roles = [message["role"] for message in json.loads(self.requests[0].content)["messages"]]
        self.assertEqual(roles, ["system", "user", "assistant", "user"])

    def test_fallback_when_ollama_is_stopped(self):
        def handler(request):
            raise httpx.ConnectError("Connection refused")
        self.mock_model(handler)

        response = client.post("/assistant", json={"question": "How much did I spend?"})
        self.assertEqual(response.status_code, 503)
        self.assertIn("Ollama is not running", response.json()["detail"])

    def test_fallback_when_model_is_not_installed(self):
        self.mock_model(lambda request: httpx.Response(404, json={"error": "model 'llama3.2:3b' not found"}))
        response = client.post("/assistant", json={"question": "How much did I spend?"})
        self.assertEqual(response.status_code, 503)
        self.assertIn("is not installed", response.json()["detail"])

    def test_fallback_when_model_is_too_slow(self):
        def handler(request):
            raise httpx.ReadTimeout("timed out")
        self.mock_model(handler)
        response = client.post("/assistant", json={"question": "How much did I spend?"})
        self.assertEqual(response.status_code, 503)
        self.assertIn("took too long", response.json()["detail"])

    def test_rejects_empty_or_too_long_questions(self):
        self.assertEqual(client.post("/assistant", json={"question": "   "}).status_code, 422)
        self.assertEqual(client.post("/assistant", json={"question": "x" * 501}).status_code, 422)

    def test_connection_test_sends_no_user_data(self):
        self.mock_model(lambda request: httpx.Response(200, json={"message": {"content": "OK"}}))
        response = client.post("/assistant/test")

        self.assertEqual(response.status_code, 200)
        messages = json.loads(self.requests[0].content)["messages"]
        self.assertEqual(len(messages), 1)
        self.assertNotIn("Food", messages[0]["content"])


class AssistantSettingsTests(AssistantTestCase):
    def test_defaults_use_local_ollama(self):
        self.assertEqual(client.get("/assistant/settings").json(), {
            "provider": "ollama",
            "ollama_url": "http://localhost:11434",
            "ollama_model": "llama3.2:3b",
            "api_url": "",
            "api_model": "",
            "api_key_set": False,
        })

    def test_choose_another_ollama_model(self):
        response = client.put("/assistant/settings", json={"ollama_model": "llama3.1:8b", "ollama_url": "http://ollama:11434/"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["ollama_model"], "llama3.1:8b")
        self.assertEqual(response.json()["ollama_url"], "http://ollama:11434")

    def test_external_api_uses_key_and_never_returns_it(self):
        response = client.put("/assistant/settings", json={
            "provider": "api", "api_url": "https://api.example.com/v1", "api_model": "small-model", "api_key": "secret-key",
        })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["api_key_set"])
        self.assertNotIn("secret-key", response.text)
        self.assertNotIn("secret-key", client.get("/assistant/settings").text)

        self.mock_model(lambda request: httpx.Response(200, json={"choices": [{"message": {"content": "Answer"}}]}))
        response = client.post("/assistant", json={"question": "How much did I spend?"})

        self.assertEqual(response.json(), {"answer": "Answer", "provider": "api", "model": "small-model"})
        request = self.requests[0]
        self.assertEqual(str(request.url), "https://api.example.com/v1/chat/completions")
        self.assertEqual(request.headers["authorization"], "Bearer secret-key")
        self.assertEqual(json.loads(request.content)["model"], "small-model")

    def test_external_api_rejected_key(self):
        client.put("/assistant/settings", json={
            "provider": "api", "api_url": "https://api.example.com/v1", "api_model": "m", "api_key": "wrong",
        })
        self.mock_model(lambda request: httpx.Response(401, json={"error": {"message": "invalid key"}}))
        response = client.post("/assistant", json={"question": "Hi"})
        self.assertEqual(response.status_code, 503)
        self.assertIn("rejected the API key", response.json()["detail"])

    def test_api_key_can_be_removed(self):
        client.put("/assistant/settings", json={"api_key": "secret-key"})
        self.assertTrue(client.get("/assistant/settings").json()["api_key_set"])
        client.put("/assistant/settings", json={"api_key": ""})
        self.assertFalse(client.get("/assistant/settings").json()["api_key_set"])

    def test_external_api_needs_url_and_model(self):
        response = client.put("/assistant/settings", json={"provider": "api"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(client.get("/assistant/settings").json()["provider"], "ollama")

    def test_invalid_settings_are_rejected(self):
        self.assertEqual(client.put("/assistant/settings", json={"ollama_url": "ftp://x"}).status_code, 422)
        self.assertEqual(client.put("/assistant/settings", json={"ollama_model": "bad name!"}).status_code, 422)
        self.assertEqual(client.put("/assistant/settings", json={"provider": "other"}).status_code, 422)


class OllamaModelManagementTests(AssistantTestCase):
    def tearDown(self):
        if assistant._pull_thread:
            assistant._pull_thread.join(timeout=5)
        assistant._update_pull(running=False)
        super().tearDown()

    def test_lists_installed_and_recommended_models(self):
        self.mock_model(lambda request: httpx.Response(200, json={"models": [
            {"name": "llama3.2:3b", "size": 2019393189, "details": {"parameter_size": "3.2B"}},
        ]}))
        data = client.get("/assistant/ollama/models").json()

        self.assertTrue(data["reachable"])
        self.assertEqual(data["installed"], [{"name": "llama3.2:3b", "size_gb": 1.9, "parameter_size": "3.2B"}])
        recommended = {model["name"]: model for model in data["recommended"]}
        self.assertTrue(recommended["llama3.2:3b"]["installed"])
        self.assertFalse(recommended["llama3.2:1b"]["installed"])
        self.assertIn("fits", recommended["llama3.1:8b"])

    def test_models_when_ollama_is_stopped(self):
        def handler(request):
            raise httpx.ConnectError("refused")
        self.mock_model(handler)
        data = client.get("/assistant/ollama/models").json()

        self.assertFalse(data["reachable"])
        self.assertIn("not running", data["error"])
        self.assertEqual(len(data["recommended"]), len(assistant.RECOMMENDED_OLLAMA_MODELS))

    def test_download_model_reports_progress_and_success(self):
        lines = [
            {"status": "pulling manifest"},
            {"status": "downloading", "total": 100, "completed": 40},
            {"status": "success"},
        ]
        self.mock_model(lambda request: httpx.Response(200, content="\n".join(json.dumps(line) for line in lines).encode()))

        response = client.post("/assistant/ollama/pull", json={"model": "llama3.2:1b"})
        self.assertEqual(response.status_code, 202)
        assistant._pull_thread.join(timeout=5)

        status = client.get("/assistant/ollama/pull").json()
        self.assertEqual(status["model"], "llama3.2:1b")
        self.assertTrue(status["done"])
        self.assertIsNone(status["error"])
        self.assertEqual(json.loads(self.requests[0].content), {"model": "llama3.2:1b", "stream": True})

    def test_download_error_is_reported(self):
        self.mock_model(lambda request: httpx.Response(200, content=b'{"error": "pull model manifest: file does not exist"}'))
        client.post("/assistant/ollama/pull", json={"model": "no-such-model"})
        assistant._pull_thread.join(timeout=5)

        status = client.get("/assistant/ollama/pull").json()
        self.assertTrue(status["done"])
        self.assertIn("file does not exist", status["error"])

    def test_only_one_download_at_a_time(self):
        assistant._update_pull(running=True)
        response = client.post("/assistant/ollama/pull", json={"model": "llama3.2:1b"})
        self.assertEqual(response.status_code, 409)

    def test_invalid_model_name_is_rejected(self):
        self.assertEqual(client.post("/assistant/ollama/pull", json={"model": "rm -rf /"}).status_code, 422)


if __name__ == "__main__":
    unittest.main()
