import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App } from "../app/App";
import { mockFetch, renderWithProviders } from "./utils";
import { useAuth } from "../features/auth/authStore";

const USER = { id: 1, email: "demo@dilsos.local", display_name: "Demo Planner", role: "planner", is_demo: true };

beforeEach(() => useAuth.setState({ token: null, user: null }));

test("unauthenticated users are redirected to login", () => {
  renderWithProviders(<App />, "/");
  expect(screen.getByRole("form", { name: "로그인" })).toBeInTheDocument();
});

test("login stores token, shows shell, demo banner and API health", async () => {
  mockFetch({
    "POST /auth/login": { access_token: "tok", user: USER, environment: "development" },
    "GET /health/ready": { status: "ready", task_backend: "db", database_dialect: "mysql", checks: [] },
    "GET /auth/me": USER,
  });
  renderWithProviders(<App />, "/login");
  await userEvent.type(screen.getByLabelText("비밀번호"), "demo1234");
  await userEvent.click(screen.getByRole("button", { name: "로그인" }));
  await waitFor(() => expect(screen.getByRole("navigation", { name: "주 메뉴" })).toBeInTheDocument());
  expect(localStorage.getItem("dilsos.token")).toBe("tok");
  expect(screen.getByRole("note")).toHaveTextContent("데모 모드");
  await waitFor(() => expect(screen.getByText(/API 정상/)).toBeInTheDocument());
});

test("failed login shows typed error", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(JSON.stringify({ error: { code: "invalid_credentials", message: "Invalid email or password", request_id: "r1" } }), {
      status: 401,
      headers: { "content-type": "application/json" },
    }),
  );
  renderWithProviders(<App />, "/login");
  await userEvent.type(screen.getByLabelText("비밀번호"), "x");
  await userEvent.click(screen.getByRole("button", { name: "로그인" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("invalid_credentials");
});
