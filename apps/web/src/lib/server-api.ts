// Server-side calls to the API (Server Components only). Forwards the browser's cookies.
import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import type { Me } from "./types";

const API = process.env.API_INTERNAL_URL ?? "http://api:8000";

export async function apiGet<T>(path: string): Promise<{ status: number; data: T | null }> {
  const cookie = (await cookies()).toString();
  const res = await fetch(`${API}${path}`, { headers: { cookie }, cache: "no-store" });
  if (!res.ok) return { status: res.status, data: null };
  return { status: res.status, data: (await res.json()) as T };
}

/** The signed-in account, or null. */
export async function getMe(): Promise<Me | null> {
  const { data } = await apiGet<Me>("/auth/me");
  return data;
}

/** The signed-in account; redirects to the login page otherwise. */
export async function requireMe(next?: string): Promise<Me> {
  const me = await getMe();
  if (!me) redirect(next ? `/login?next=${encodeURIComponent(next)}` : "/login");
  return me;
}
