export interface SessionUser {
  id: string;
  name: string;
}

export function selectSessionUser(payload: { user?: SessionUser }): SessionUser | null {
  return payload.user ?? null;
}
