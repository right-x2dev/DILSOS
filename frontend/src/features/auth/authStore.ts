import { create } from "zustand";
import { api, getToken, setToken } from "../../api/client";

export type User = { id: number; email: string; display_name: string; role: string; is_demo: boolean };
type LoginResponse = { access_token: string; user: User; environment: string };

type AuthState = {
  token: string | null;
  user: User | null;
  environment: string | null;
  login: (email: string, password: string) => Promise<void>;
  loadMe: () => Promise<void>;
  logout: () => void;
};

export const useAuth = create<AuthState>((set) => ({
  token: getToken(),
  user: null,
  environment: null,
  async login(email, password) {
    const r = await api<LoginResponse>("/auth/login", { body: { email, password } });
    setToken(r.access_token);
    set({ token: r.access_token, user: r.user, environment: r.environment });
  },
  async loadMe() {
    try {
      const u = await api<User>("/auth/me");
      set({ user: u });
    } catch {
      setToken(null);
      set({ token: null, user: null });
    }
  },
  logout() {
    setToken(null);
    set({ token: null, user: null });
  },
}));
