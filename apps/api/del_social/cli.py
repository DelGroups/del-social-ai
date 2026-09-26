"""Operator commands. Run on the server with the database owner's credentials:

    docker compose run --rm migrate python -m del_social.cli create-platform-admin --email you@example.com
    docker compose run --rm migrate python -m del_social.cli set-password --email you@example.com

The password is typed at a prompt, never passed as an argument (it would land in shell history).
"""
import argparse
import asyncio
import getpass
import os
import sys
import uuid

import asyncpg

from del_social.core.security import PasswordPolicyError, hash_password
from del_social.tenants.service import normalize_email


class CliError(Exception):
    pass


async def create_platform_admin(dsn: str, email: str, password: str) -> uuid.UUID:
    """Uses the owner connection: del_app is not allowed to set is_platform_admin."""
    try:
        email = normalize_email(email)
    except Exception:
        raise CliError("Invalid email address") from None
    try:
        password_hash = hash_password(password)
    except PasswordPolicyError as e:
        raise CliError(str(e)) from None

    conn = await asyncpg.connect(dsn)
    try:
        if await conn.fetchval("SELECT 1 FROM accounts WHERE email = $1", email):
            raise CliError(f"An account with email {email} already exists")
        return await conn.fetchval(
            "INSERT INTO accounts (email, password_hash, is_platform_admin)"
            " VALUES ($1, $2, true) RETURNING account_id",
            email,
            password_hash,
        )
    finally:
        await conn.close()


async def set_password(dsn: str, email: str, password: str) -> None:
    """Set an account's password and sign it out everywhere (operator recovery path)."""
    try:
        email = normalize_email(email)
    except Exception:
        raise CliError("Invalid email address") from None
    try:
        password_hash = hash_password(password)
    except PasswordPolicyError as e:
        raise CliError(str(e)) from None

    conn = await asyncpg.connect(dsn)
    try:
        async with conn.transaction():
            account_id = await conn.fetchval(
                "UPDATE accounts SET password_hash = $1, password_changed_at = now()"
                " WHERE email = $2 RETURNING account_id",
                password_hash,
                email,
            )
            if account_id is None:
                raise CliError(f"No account with email {email}")
            await conn.execute(
                "UPDATE auth_sessions SET revoked_at = now()"
                " WHERE account_id = $1 AND revoked_at IS NULL",
                account_id,
            )
    finally:
        await conn.close()


def _prompt_password() -> str:
    password = getpass.getpass("Password (min 10 characters): ")
    if password != getpass.getpass("Repeat password: "):
        raise CliError("Passwords do not match")
    return password


def _owner_dsn() -> str:
    url = os.environ.get("MIGRATION_DATABASE_URL")
    if not url:
        raise CliError("MIGRATION_DATABASE_URL is not set (run via the 'migrate' service)")
    return url.replace("postgresql+asyncpg://", "postgresql://", 1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="del_social.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    admin = sub.add_parser("create-platform-admin", help="Create the platform admin account")
    admin.add_argument("--email", required=True)
    reset = sub.add_parser("set-password", help="Set any account's password (signs it out everywhere)")
    reset.add_argument("--email", required=True)
    args = parser.parse_args(argv)

    try:
        if args.command == "create-platform-admin":
            account_id = asyncio.run(create_platform_admin(_owner_dsn(), args.email, _prompt_password()))
            print(f"Platform admin created: {account_id}")
        elif args.command == "set-password":
            asyncio.run(set_password(_owner_dsn(), args.email, _prompt_password()))
            print("Password set. All sessions of this account were signed out.")
    except CliError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
