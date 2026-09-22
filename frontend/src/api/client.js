const API_URL =
  import.meta.env.VITE_API_URL ||
  (window.location.port === "5173" || window.location.port === "5174" ? "http://localhost:4000" : window.location.origin);

async function request(path, token, options = {}) {
  const authHeaders = token ? { Authorization: `Bearer ${token}` } : {};
  const response = await fetch(`${API_URL}${path}`, {
    headers: { "Content-Type": "application/json", ...authHeaders, ...(options.headers || {}) },
    ...options
  });

  const data = await response.json();
  if (!response.ok) {
    throw new Error((data.errors || ["Request failed."]).join(" "));
  }

  return data;
}

function toQuery(params) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== "") query.set(key, value);
  });
  return query.toString();
}

export const api = {
  signup: (credentials) =>
    request("/auth/signup", null, {
      method: "POST",
      body: JSON.stringify(credentials)
    }),
  login: (credentials) =>
    request("/auth/login", null, {
      method: "POST",
      body: JSON.stringify(credentials)
    }),
  createExpense: (expense, token) =>
    request("/expenses", token, {
      method: "POST",
      body: JSON.stringify(expense)
    }),
  listExpenses: (filters, token) => request(`/expenses?${toQuery(filters)}`, token),
  getSummary: (month, token) => request(`/summary?${toQuery({ month })}`, token)
};
