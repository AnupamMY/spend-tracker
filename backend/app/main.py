import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, field_validator

from .database import connect

JWT_SECRET = os.getenv("JWT_SECRET", "dev-jwt-secret-change-me")
JWT_EXPIRES_MINUTES = 60 * 24 * 7


class AuthInput(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        email = str(value or "").strip().lower()
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
            raise ValueError("A valid email is required.")
        return email

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        if len(value or "") < 8:
            raise ValueError("Password must be at least 8 characters.")
        return value


class ExpenseInput(BaseModel):
    amount: float
    category: str
    note: str = ""
    date: str

    model_config = ConfigDict(coerce_numbers_to_str=True)

    @field_validator("amount")
    @classmethod
    def validate_amount(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("Amount must be greater than zero.")
        return value

    @field_validator("category")
    @classmethod
    def validate_category(cls, value: str) -> str:
        category = str(value or "").strip()
        if not category:
            raise ValueError("Category is required.")
        if len(category) > 60:
            raise ValueError("Category must be 60 characters or fewer.")
        return category

    @field_validator("note")
    @classmethod
    def validate_note(cls, value: str) -> str:
        note = str(value or "").strip()
        if len(note) > 200:
            raise ValueError("Note must be 200 characters or fewer.")
        return note

    @field_validator("date")
    @classmethod
    def validate_expense_date(cls, value: str) -> str:
        if not is_valid_date(value):
            raise ValueError("Date must be a valid YYYY-MM-DD date.")
        return value


def create_app(db: sqlite3.Connection | None = None) -> FastAPI:
    app = FastAPI(title="Spend Tracker API")
    app.state.db = db or connect()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [error["msg"].replace("Value error, ", "", 1) for error in exc.errors()]
        return JSONResponse(status_code=400, content={"errors": errors})

    @app.exception_handler(HTTPException)
    async def http_exception_handler(_request: Request, exc: HTTPException) -> JSONResponse:
        if isinstance(exc.detail, dict):
            return JSONResponse(status_code=exc.status_code, content=exc.detail)
        return JSONResponse(status_code=exc.status_code, content={"errors": [str(exc.detail)]})

    def get_db() -> sqlite3.Connection:
        return app.state.db

    def current_user(
        authorization: str | None = Header(default=None),
        database: sqlite3.Connection = Depends(get_db),
    ) -> sqlite3.Row:
        if not authorization or not authorization.startswith("Bearer "):
            raise api_error(401, "Missing or invalid token.")
        payload = decode_token(authorization.removeprefix("Bearer ").strip())
        user = database.execute("SELECT id, email FROM users WHERE id = ?", (payload["sub"],)).fetchone()
        if user is None:
            raise api_error(401, "Missing or invalid token.")
        return user

    @app.get("/health")
    def health() -> dict[str, bool]:
        return {"ok": True}

    @app.post("/auth/signup", status_code=201)
    def signup(credentials: AuthInput, database: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
        try:
            cursor = database.execute(
                "INSERT INTO users (email, password_hash) VALUES (?, ?)",
                (credentials.email, hash_password(credentials.password)),
            )
            database.commit()
        except sqlite3.IntegrityError as error:
            if "UNIQUE" in str(error):
                raise api_error(409, "An account with that email already exists.") from error
            raise

        return auth_response(cursor.lastrowid, credentials.email)

    @app.post("/auth/login")
    def login(credentials: AuthInput, database: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
        user = database.execute(
            "SELECT id, email, password_hash FROM users WHERE email = ?",
            (credentials.email,),
        ).fetchone()
        if user is None or not verify_password(credentials.password, user["password_hash"]):
            raise api_error(401, "Invalid email or password.")
        return auth_response(user["id"], user["email"])

    @app.post("/expenses", status_code=201)
    def create_expense(
        expense: ExpenseInput,
        user: sqlite3.Row = Depends(current_user),
        database: sqlite3.Connection = Depends(get_db),
    ) -> dict[str, Any]:
        cursor = database.execute(
            """
            INSERT INTO expenses (user_id, amount, category, note, expense_date)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user["id"], expense.amount, expense.category, expense.note, expense.date),
        )
        database.commit()
        return map_expense(get_expense_by_id(database, cursor.lastrowid, user["id"]))

    @app.get("/expenses")
    def list_expenses(
        category: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = Query(100, ge=1, le=500),
        user: sqlite3.Row = Depends(current_user),
        database: sqlite3.Connection = Depends(get_db),
    ) -> list[dict[str, Any]]:
        errors = validate_filters(start_date, end_date)
        if errors:
            raise api_errors(400, errors)

        where: list[str] = ["user_id = ?"]
        params: list[Any] = [user["id"]]
        if category:
            where.append("LOWER(category) = LOWER(?)")
            params.append(category.strip())
        if start_date:
            where.append("expense_date >= ?")
            params.append(start_date)
        if end_date:
            where.append("expense_date <= ?")
            params.append(end_date)

        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        rows = database.execute(
            f"""
            SELECT id, amount, category, note, expense_date
            FROM expenses
            {where_sql}
            ORDER BY expense_date DESC, id DESC
            LIMIT ?
            """,
            [*params, limit],
        ).fetchall()
        return [map_expense(row) for row in rows]

    @app.get("/summary")
    def get_summary(
        month: str | None = None,
        user: sqlite3.Row = Depends(current_user),
        database: sqlite3.Connection = Depends(get_db),
    ) -> dict[str, Any]:
        selected_month = month or datetime.utcnow().strftime("%Y-%m")
        if not is_valid_month(selected_month):
            raise api_error(400, "Month must be a valid YYYY-MM value.")

        current_start = f"{selected_month}-01"
        current_end = month_end(selected_month)
        previous_month = previous_month_for(selected_month)
        previous_start = f"{previous_month}-01"
        previous_end = month_end(previous_month)

        total_spend = total_for_range(database, user["id"], current_start, current_end)
        previous_total = total_for_range(database, user["id"], previous_start, previous_end)
        spend_by_category = category_totals_for_range(database, user["id"], current_start, current_end)
        previous_by_category = category_totals_for_range(database, user["id"], previous_start, previous_end)

        insights = []
        for category, current_total in spend_by_category.items():
            previous_total_for_category = previous_by_category.get(category, 0)
            if previous_total_for_category > 0:
                change = percentage_change(current_total, previous_total_for_category)
                if change is not None and change > 20:
                    insights.append(
                        {
                            "type": "category_increase",
                            "category": category,
                            "message": f"{category} spend is up {change:.1f}% versus previous month.",
                            "changePercent": change,
                        }
                    )

        return {
            "month": selected_month,
            "totalSpend": total_spend,
            "spendByCategory": spend_by_category,
            "previousMonth": previous_month,
            "previousMonthTotalSpend": previous_total,
            "monthOverMonthChange": {
                "amount": round(total_spend - previous_total, 2),
                "percent": percentage_change(total_spend, previous_total),
            },
            "insights": insights,
        }

    frontend_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if frontend_dist.exists():
        assets_dir = frontend_dist / "assets"
        if assets_dir.exists():
            app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

        @app.get("/")
        def serve_frontend() -> FileResponse:
            return FileResponse(frontend_dist / "index.html")

    return app


def api_error(status_code: int, message: str) -> HTTPException:
    return api_errors(status_code, [message])


def api_errors(status_code: int, errors: list[str]) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"errors": errors})


def auth_response(user_id: int, email: str) -> dict[str, Any]:
    return {
        "token": create_token({"sub": user_id, "email": email}),
        "user": {"id": user_id, "email": email},
    }


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120000)
    return f"pbkdf2_sha256${salt}${digest.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, salt, digest = stored_hash.split("$", 2)
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120000).hex()
    return hmac.compare_digest(candidate, digest)


def create_token(payload: dict[str, Any]) -> str:
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=JWT_EXPIRES_MINUTES)
    token_payload = {**payload, "exp": int(expires_at.timestamp())}
    header = {"alg": "HS256", "typ": "JWT"}
    signing_input = f"{base64url_json(header)}.{base64url_json(token_payload)}"
    signature = sign(signing_input)
    return f"{signing_input}.{signature}"


def decode_token(token: str) -> dict[str, Any]:
    try:
        header_part, payload_part, signature = token.split(".")
    except ValueError as error:
        raise api_error(401, "Missing or invalid token.") from error

    signing_input = f"{header_part}.{payload_part}"
    if not hmac.compare_digest(sign(signing_input), signature):
        raise api_error(401, "Missing or invalid token.")

    try:
        payload = json.loads(base64url_decode(payload_part))
    except (ValueError, json.JSONDecodeError) as error:
        raise api_error(401, "Missing or invalid token.") from error

    if int(payload.get("exp", 0)) < int(datetime.now(timezone.utc).timestamp()):
        raise api_error(401, "Token has expired.")
    if "sub" not in payload:
        raise api_error(401, "Missing or invalid token.")
    return payload


def base64url_json(value: dict[str, Any]) -> str:
    raw = json.dumps(value, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def base64url_decode(value: str) -> str:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}").decode("utf-8")


def sign(value: str) -> str:
    signature = hmac.new(JWT_SECRET.encode("utf-8"), value.encode("utf-8"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")


def is_valid_date(value: str) -> bool:
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", str(value or "")):
        return False
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return False
    return parsed.isoformat() == value


def is_valid_month(value: str) -> bool:
    return bool(re.match(r"^\d{4}-\d{2}$", str(value or ""))) and is_valid_date(f"{value}-01")


def validate_filters(start_date: str | None, end_date: str | None) -> list[str]:
    errors = []
    if start_date and not is_valid_date(start_date):
        errors.append("start_date must be a valid YYYY-MM-DD date.")
    if end_date and not is_valid_date(end_date):
        errors.append("end_date must be a valid YYYY-MM-DD date.")
    if start_date and end_date and start_date > end_date:
        errors.append("start_date cannot be after end_date.")
    return errors


def month_end(month: str) -> str:
    year = int(month[:4])
    month_number = int(month[5:7])
    return date(year, month_number, monthrange(year, month_number)[1]).isoformat()


def previous_month_for(month: str) -> str:
    year = int(month[:4])
    month_number = int(month[5:7])
    if month_number == 1:
        return f"{year - 1}-12"
    return f"{year}-{month_number - 1:02d}"


def percentage_change(current: float, previous: float) -> float | None:
    if previous == 0:
        return None if current == 0 else 100.0
    return round(((current - previous) / previous) * 100, 2)


def total_for_range(database: sqlite3.Connection, user_id: int, start_date: str, end_date: str) -> float:
    row = database.execute(
        "SELECT COALESCE(SUM(amount), 0) AS total FROM expenses WHERE user_id = ? AND expense_date BETWEEN ? AND ?",
        (user_id, start_date, end_date),
    ).fetchone()
    return round(float(row["total"]), 2)


def category_totals_for_range(database: sqlite3.Connection, user_id: int, start_date: str, end_date: str) -> dict[str, float]:
    rows = database.execute(
        """
        SELECT category, SUM(amount) AS total
        FROM expenses
        WHERE user_id = ? AND expense_date BETWEEN ? AND ?
        GROUP BY category
        ORDER BY category
        """,
        (user_id, start_date, end_date),
    ).fetchall()
    return {row["category"]: round(float(row["total"]), 2) for row in rows}


def map_expense(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "amount": row["amount"],
        "category": row["category"],
        "note": row["note"],
        "date": row["expense_date"],
    }


def get_expense_by_id(database: sqlite3.Connection, expense_id: int, user_id: int) -> sqlite3.Row:
    return database.execute(
        "SELECT id, amount, category, note, expense_date FROM expenses WHERE id = ? AND user_id = ?",
        (expense_id, user_id),
    ).fetchone()
