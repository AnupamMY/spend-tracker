import React, { useEffect, useState } from "react";
import toast, { Toaster } from "react-hot-toast";
import { api } from "./api/client.js";

const today = new Date().toISOString().slice(0, 10);
const currentMonth = today.slice(0, 7);

function money(value) {
  return Number(value || 0).toLocaleString("en-IN", { maximumFractionDigits: 2, minimumFractionDigits: 2 });
}

function rupees(value) {
  return `Rs. ${money(value)}`;
}

export function App() {
  const [token, setToken] = useState(() => localStorage.getItem("spendTrackerToken") || "");
  const [user, setUser] = useState(() => {
    const saved = localStorage.getItem("spendTrackerUser");
    return saved ? JSON.parse(saved) : null;
  });
  const [authMode, setAuthMode] = useState("login");
  const [authForm, setAuthForm] = useState({ email: "", password: "" });
  const [form, setForm] = useState({ amount: "", category: "", note: "", date: today });
  const [filters, setFilters] = useState({ category: "", start_date: "", end_date: "" });
  const [summaryMonth, setSummaryMonth] = useState(currentMonth);
  const [expenses, setExpenses] = useState([]);
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(false);

  async function loadData() {
    if (!token) return;
    setLoading(true);
    try {
      const [expenseData, summaryData] = await Promise.all([
        api.listExpenses(filters, token),
        api.getSummary(summaryMonth, token)
      ]);
      setExpenses(expenseData);
      setSummary(summaryData);
    } catch (error) {
      toast.error(error.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadData();
  }, [token]);

  async function submitAuth(event) {
    event.preventDefault();
    try {
      const data = authMode === "login" ? await api.login(authForm) : await api.signup(authForm);
      setToken(data.token);
      setUser(data.user);
      localStorage.setItem("spendTrackerToken", data.token);
      localStorage.setItem("spendTrackerUser", JSON.stringify(data.user));
      setAuthForm({ email: "", password: "" });
      toast.success(authMode === "login" ? "Logged in" : "Account created");
    } catch (error) {
      toast.error(error.message);
    }
  }

  function logout() {
    setToken("");
    setUser(null);
    setExpenses([]);
    setSummary(null);
    localStorage.removeItem("spendTrackerToken");
    localStorage.removeItem("spendTrackerUser");
  }

  async function addExpense(event) {
    event.preventDefault();
    try {
      await api.createExpense({ ...form, amount: Number(form.amount) }, token);
      setForm({ amount: "", category: "", note: "", date: today });
      toast.success("Expense added");
      await loadData();
    } catch (error) {
      toast.error(error.message);
    }
  }

  async function applyFilters(event) {
    event.preventDefault();
    await loadData();
  }

  async function refreshSummary(event) {
    event.preventDefault();
    await loadData();
  }

  return (
    <main>
      <Toaster position="top-right" />
      <header>
        <h1>Spend Tracker</h1>
        <p>Add expenses and review monthly spend.</p>
      </header>

      {!token ? (
        <form className="panel auth-card" onSubmit={submitAuth}>
          <div className="auth-tabs">
            <button type="button" className={authMode === "login" ? "active" : "secondary"} onClick={() => setAuthMode("login")}>
              Login
            </button>
            <button type="button" className={authMode === "signup" ? "active" : "secondary"} onClick={() => setAuthMode("signup")}>
              Sign up
            </button>
          </div>
          <label>
            Email
            <input type="email" value={authForm.email} onChange={(event) => setAuthForm({ ...authForm, email: event.target.value })} required />
          </label>
          <label>
            Password
            <input type="password" minLength="8" value={authForm.password} onChange={(event) => setAuthForm({ ...authForm, password: event.target.value })} required />
          </label>
          <button type="submit">{authMode === "login" ? "Login" : "Create account"}</button>
        </form>
      ) : (
        <section className="panel auth-panel">
          <span>
            Signed in as <strong>{user?.email}</strong>
          </span>
          <button type="button" className="secondary" onClick={logout}>
            Logout
          </button>
        </section>
      )}

      {loading && <p className="muted">Loading...</p>}

      {token && (
        <>
          <section className="grid">
            <form className="panel" onSubmit={addExpense}>
              <h2>Add Expense</h2>
              <label>
                Amount
                <input type="number" min="0.01" step="0.01" value={form.amount} onChange={(event) => setForm({ ...form, amount: event.target.value })} required />
              </label>
              <label>
                Category
                <input value={form.category} onChange={(event) => setForm({ ...form, category: event.target.value })} placeholder="Food" required />
              </label>
              <label>
                Note
                <input value={form.note} onChange={(event) => setForm({ ...form, note: event.target.value })} placeholder="Lunch with team" />
              </label>
              <label>
                Date
                <input type="date" value={form.date} onChange={(event) => setForm({ ...form, date: event.target.value })} required />
              </label>
              <button type="submit">Add expense</button>
            </form>

            <section className="panel">
              <form className="summary-controls" onSubmit={refreshSummary}>
                <h2>Summary</h2>
                <label>
                  Month
                  <input type="month" value={summaryMonth} onChange={(event) => setSummaryMonth(event.target.value)} />
                </label>
                <button type="submit">Refresh</button>
              </form>

              {summary && (
                <div className="summary">
                  <p className="total">{rupees(summary.totalSpend)}</p>
                  <p>
                    Previous month: {rupees(summary.previousMonthTotalSpend)}. Change: {rupees(summary.monthOverMonthChange.amount)}
                    {summary.monthOverMonthChange.percent != null ? ` (${summary.monthOverMonthChange.percent}%)` : ""}
                  </p>
                  <h3>By category</h3>
                  <ul>
                    {Object.entries(summary.spendByCategory).map(([category, total]) => (
                      <li key={category}>
                        <span>{category}</span>
                        <strong>{rupees(total)}</strong>
                      </li>
                    ))}
                  </ul>
                  {summary.insights.length > 0 ? (
                    <div className="insight-box">
                      <h3>Insights</h3>
                      <ul>
                        {summary.insights.map((insight) => (
                          <li key={`${insight.type}-${insight.category}`}>{insight.message}</li>
                        ))}
                      </ul>
                    </div>
                  ) : (
                    <p className="muted">No category increased by more than 20% versus previous month.</p>
                  )}
                </div>
              )}
            </section>
          </section>

          <section className="panel">
            <form className="filters" onSubmit={applyFilters}>
              <label>
                Category
                <input value={filters.category} onChange={(event) => setFilters({ ...filters, category: event.target.value })} placeholder="All" />
              </label>
              <label>
                Start date
                <input type="date" value={filters.start_date} onChange={(event) => setFilters({ ...filters, start_date: event.target.value })} />
              </label>
              <label>
                End date
                <input type="date" value={filters.end_date} onChange={(event) => setFilters({ ...filters, end_date: event.target.value })} />
              </label>
              <button type="submit">Apply filters</button>
            </form>

            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>Category</th>
                    <th>Note</th>
                    <th>Amount</th>
                  </tr>
                </thead>
                <tbody>
                  {expenses.map((expense) => (
                    <tr key={expense.id}>
                      <td>{expense.date}</td>
                      <td>{expense.category}</td>
                      <td>{expense.note || "-"}</td>
                      <td>{rupees(expense.amount)}</td>
                    </tr>
                  ))}
                  {expenses.length === 0 && (
                    <tr>
                      <td colSpan="4" className="empty-cell">
                        No expenses found.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </main>
  );
}
