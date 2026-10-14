import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "./authStore";
import { Button, ErrorState, Field, inputCls } from "../../components/ui";

export function LoginPage() {
  const login = useAuth((s) => s.login);
  const nav = useNavigate();
  const [email, setEmail] = useState("demo@dilsos.local");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(email, password);
      nav("/");
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-tower-900 p-4">
      <form onSubmit={submit} className="w-full max-w-sm rounded-xl bg-white p-6 shadow-xl" aria-label="로그인">
        <h1 className="text-2xl font-bold text-tower-900">DILSOS</h1>
        <p className="mb-4 text-sm text-ink-600">Dynamic Integrated Logistics Scheduling &amp; Optimization</p>
        <div className="mb-4 rounded-md bg-amber-50 p-2.5 text-xs text-amber-900">
          개발용 데모 계정: <b>demo@dilsos.local</b> / <b>demo1234</b> (seed 명령으로 생성). 운영 환경에서는 데모 로그인이 비활성화됩니다.
        </div>
        <div className="space-y-3">
          <Field label="이메일">
            <input className={inputCls} value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="username" required />
          </Field>
          <Field label="비밀번호">
            <input
              className={inputCls}
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              required
            />
          </Field>
          {error ? <ErrorState error={error} /> : null}
          <Button type="submit" disabled={busy} className="w-full justify-center">
            {busy ? "로그인 중…" : "로그인"}
          </Button>
        </div>
      </form>
    </div>
  );
}
