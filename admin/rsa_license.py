#!/usr/bin/env python3
"""Operator CLI for the auto-rsa license Worker.

Wraps the Worker's /admin endpoints so the operator never hand-crafts
curl. Reads two env vars (keep them in your password manager, not the
shell history):

    RSA_LICENSE_SERVER_URL   https://rsa-license.<subdomain>.workers.dev
    RSA_LICENSE_ADMIN_SECRET the ADMIN_SECRET you set as a Worker secret

Examples:
    python admin/rsa_license.py issue --tier advanced --for "Alice"
    python admin/rsa_license.py list
    python admin/rsa_license.py revoke <license_id>
    python admin/rsa_license.py kill on  --message "Fixing a fill bug — update coming"
    python admin/rsa_license.py kill on  --min-version 0.8.0
    python admin/rsa_license.py kill off
    python admin/rsa_license.py rebind <license_id> <new_hardware_id>

`kill on` is the emergency stop: every friend's app refuses to place
orders on its next pre-trade check. `kill off` clears it. Pair `kill`
with `revoke` when you need a hard, grace-proof stop for one license.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import requests

_TIMEOUT = 15


def _cfg() -> tuple[str, str]:
    url = (os.getenv("RSA_LICENSE_SERVER_URL") or "").rstrip("/")
    secret = os.getenv("RSA_LICENSE_ADMIN_SECRET") or ""
    if not url or not secret:
        sys.exit(
            "Set RSA_LICENSE_SERVER_URL and RSA_LICENSE_ADMIN_SECRET "
            "in the environment first.",
        )
    return url, secret


def _post(path: str, body: dict) -> dict:
    url, secret = _cfg()
    resp = requests.post(
        f"{url}{path}", json=body,
        headers={"authorization": f"Bearer {secret}"}, timeout=_TIMEOUT,
    )
    return _out(resp)


def _get(path: str) -> dict:
    url, secret = _cfg()
    resp = requests.get(
        f"{url}{path}",
        headers={"authorization": f"Bearer {secret}"}, timeout=_TIMEOUT,
    )
    return _out(resp)


def _out(resp: requests.Response) -> dict:
    try:
        data = resp.json()
    except ValueError:
        sys.exit(f"HTTP {resp.status_code}: {resp.text[:200]}")
    if resp.status_code != 200:
        sys.exit(f"HTTP {resp.status_code}: {json.dumps(data)}")
    return data


def cmd_issue(args: argparse.Namespace) -> None:
    body = {"tier": args.tier, "notes": args.for_whom}
    if args.expires:
        body["expires_at"] = args.expires
    data = _post("/admin/issue", body)
    print(f"Issued: {data['license_key']}")
    print(f"  license_id : {data['license_id']}")
    print(f"  tier       : {data['tier']}")
    print(f"  expires_at : {data['expires_at']}")
    print("\nSend the license_key to the friend (Signal/email). They paste it")
    print("into the app's License section to activate.")


def cmd_revoke(args: argparse.Namespace) -> None:
    data = _post("/admin/revoke", {"license_id": args.license_id})
    print(f"Revoked {data['license_id']}. Next refresh returns 410; the cached")
    print("token still works through the 7-day grace window.")


def cmd_kill(args: argparse.Namespace) -> None:
    if args.state == "on":
        body: dict = {"active": True}
        if args.message:
            body["message"] = args.message
        if args.min_version:
            body["min_app_version"] = args.min_version
        data = _post("/admin/kill", body)
        scope = (
            f"builds <= {data['min_app_version']}"
            if data.get("min_app_version") else "ALL builds"
        )
        print(f"KILL SWITCH ON ({scope}).")
        print(f"  message: {data['message']}")
        print("Every friend's app blocks order placement on its next check.")
    else:
        data = _post("/admin/kill", {"active": False})
        print("Kill switch OFF. Trading resumes on the next check.")


def cmd_rebind(args: argparse.Namespace) -> None:
    data = _post(
        "/admin/rebind",
        {"license_id": args.license_id, "hardware_id": args.hardware_id},
    )
    print(f"Rebound {data['license_id']} -> {data['hardware_id']}")


def cmd_list(_args: argparse.Namespace) -> None:
    data = _get("/admin/list")
    rows = data.get("licenses", [])
    if not rows:
        print("No licenses issued yet.")
        return
    print(f"{'LICENSE_ID':38}  {'TIER':9}  {'HW':4}  {'STATUS':8}  EXPIRES        NOTES")
    for r in rows:
        print(
            f"{r.get('license_id', ''):38}  "
            f"{r.get('tier', ''):9}  "
            f"{'yes' if r.get('hardware_id') else 'no':4}  "
            f"{r.get('status', ''):8}  "
            f"{str(r.get('expires_at', ''))[:10]:13}  "
            f"{r.get('notes', '')}",
        )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="rsa_license", description="auto-rsa license operator CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("issue", help="issue a new license key")
    pi.add_argument(
        "--tier", required=True,
        choices=["basic", "advanced", "operator", "friend_lite", "friend_main"],
    )
    pi.add_argument("--for", dest="for_whom", default="", help="note: who it's for")
    pi.add_argument("--expires", default="", help="ISO expiry (default: 1 year out)")
    pi.set_defaults(func=cmd_issue)

    pr = sub.add_parser("revoke", help="revoke a license by id")
    pr.add_argument("license_id")
    pr.set_defaults(func=cmd_revoke)

    pk = sub.add_parser("kill", help="global kill switch on/off")
    pk.add_argument("state", choices=["on", "off"])
    pk.add_argument("--message", default="", help="what friends see")
    pk.add_argument("--min-version", dest="min_version", default="",
                    help="only kill builds at or below this version")
    pk.set_defaults(func=cmd_kill)

    pb = sub.add_parser("rebind", help="bind a license to a new hardware id")
    pb.add_argument("license_id")
    pb.add_argument("hardware_id")
    pb.set_defaults(func=cmd_rebind)

    pl = sub.add_parser("list", help="list all licenses")
    pl.set_defaults(func=cmd_list)
    return p


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
