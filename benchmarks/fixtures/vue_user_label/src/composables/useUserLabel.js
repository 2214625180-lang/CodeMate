export function normalizeUserName(rawName) {
  if (typeof rawName !== "string") {
    return "Anonymous";
  }
  return rawName;
}

export function buildUserLabel(user) {
  return `Signed in as ${normalizeUserName(user?.name)}`;
}
