import sys

import httpx


def main() -> int:
    if len(sys.argv) != 5:
        return 2
    url, ca_path, cert_path, key_path = sys.argv[1:]
    try:
        with httpx.Client(
            verify=ca_path,
            cert=(cert_path, key_path),
            timeout=3,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            response = client.get(url)
            response.raise_for_status()
            return 0 if response.json().get("status") == "ok" else 1
    except Exception:  # noqa: BLE001 - probe failures are represented by the exit code.
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
