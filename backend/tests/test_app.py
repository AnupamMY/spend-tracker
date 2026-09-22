from fastapi.testclient import TestClient

from app.database import connect
from app.main import create_app


def make_client() -> TestClient:
    return TestClient(create_app(connect(":memory:")))


def auth_headers(client: TestClient, email: str = "user@example.com") -> dict[str, str]:
    response = client.post("/auth/signup", json={"email": email, "password": "password123"})
    assert response.status_code == 201
    return {"Authorization": f"Bearer {response.json()['token']}"}


def add_expense(client: TestClient, headers: dict[str, str], amount: float, category: str, date: str, note: str = ""):
    return client.post(
        "/expenses",
        json={"amount": amount, "category": category, "note": note, "date": date},
        headers=headers,
    )


def test_signup_login_and_create_expense():
    client = make_client()
    headers = auth_headers(client)

    created = add_expense(client, headers, 42.5, "Food", "2026-09-10", "Lunch")

    assert created.status_code == 201
    assert created.json()["category"] == "Food"

    login = client.post("/auth/login", json={"email": "user@example.com", "password": "password123"})
    assert login.status_code == 200
    assert login.json()["token"]


def test_rejects_invalid_login():
    client = make_client()
    auth_headers(client)

    response = client.post("/auth/login", json={"email": "user@example.com", "password": "wrongpass"})

    assert response.status_code == 401
    assert response.json()["errors"] == ["Invalid email or password."]


def test_creates_and_lists_expenses_for_current_user_only():
    client = make_client()
    first_user = auth_headers(client, "first@example.com")
    second_user = auth_headers(client, "second@example.com")

    created = add_expense(client, first_user, 42.5, "Food", "2026-09-10", "Lunch")
    add_expense(client, second_user, 99, "Travel", "2026-09-11", "Taxi")

    response = client.get("/expenses", headers=first_user)

    assert response.status_code == 200
    assert response.json() == [created.json()]


def test_rejects_invalid_expense_input():
    client = make_client()
    headers = auth_headers(client)

    response = client.post(
        "/expenses",
        json={"amount": -1, "category": "", "note": "x" * 201, "date": "not-a-date"},
        headers=headers,
    )

    assert response.status_code == 400
    errors = " ".join(response.json()["errors"])
    assert "Amount must be greater than zero" in errors
    assert "Category is required" in errors
    assert "Note must be 200 characters or fewer" in errors
    assert "Date must be a valid YYYY-MM-DD date" in errors


def test_filters_expenses_by_category_and_date_range():
    client = make_client()
    headers = auth_headers(client)
    add_expense(client, headers, 20, "Food", "2026-09-01")
    add_expense(client, headers, 30, "Food", "2026-09-15")
    add_expense(client, headers, 50, "Travel", "2026-09-20")
    add_expense(client, headers, 99, "Food", "2026-10-01")

    response = client.get("/expenses?category=food&start_date=2026-09-10&end_date=2026-09-30", headers=headers)

    assert response.status_code == 200
    assert [item["amount"] for item in response.json()] == [30]


def test_rejects_invalid_date_range_filter():
    client = make_client()
    headers = auth_headers(client)

    response = client.get("/expenses?start_date=2026-10-01&end_date=2026-09-01", headers=headers)

    assert response.status_code == 400
    assert "start_date cannot be after end_date." in response.json()["errors"]


def test_summary_returns_totals_by_category_and_month_over_month_change():
    client = make_client()
    headers = auth_headers(client)
    add_expense(client, headers, 100, "Food", "2026-08-04")
    add_expense(client, headers, 120, "Food", "2026-09-02")
    add_expense(client, headers, 80, "Travel", "2026-09-12")

    response = client.get("/summary?month=2026-09", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["totalSpend"] == 200
    assert body["spendByCategory"] == {"Food": 120, "Travel": 80}
    assert body["previousMonthTotalSpend"] == 100
    assert body["monthOverMonthChange"] == {"amount": 100, "percent": 100}


def test_summary_flags_category_spend_increase_over_twenty_percent():
    client = make_client()
    headers = auth_headers(client)
    add_expense(client, headers, 100, "Software", "2026-08-01")
    add_expense(client, headers, 121, "Software", "2026-09-01")

    response = client.get("/summary?month=2026-09", headers=headers)

    assert response.status_code == 200
    assert response.json()["insights"][0]["category"] == "Software"
    assert response.json()["insights"][0]["changePercent"] == 21


def test_rejects_requests_without_token():
    client = make_client()

    response = client.get("/expenses")

    assert response.status_code == 401
    assert response.json()["errors"] == ["Missing or invalid token."]
