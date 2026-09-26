"""Sign-in, sign-out, password change, invitation and reset links (ADR 002)."""
import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import func, insert, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from del_social.core.auth import InvalidCredentials, RateLimited, authenticate
from del_social.core.db import set_account, set_tenant
from del_social.core.deps import CurrentAccount, check_origin, current_account, get_db, get_rate_limiter
from del_social.core.rate_limit import (
    LOGIN_EMAIL_LIMIT,
    LOGIN_WINDOW_SECONDS,
    RateLimiter,
    login_email_key,
)
from del_social.core.security import PasswordPolicyError, hash_password, hash_token, verify_password
from del_social.core.sessions import (
    SESSION_ABSOLUTE,
    SESSION_COOKIE,
    create_session,
    resolve_session,
    revoke_other_sessions,
    revoke_session,
)
from del_social.models import Account, Invitation, MemberRole, Membership, PasswordReset

router = APIRouter(prefix="/auth", tags=["auth"])

LINK_FAILURE_LIMIT = 30  # bad invitation/reset tokens per IP per window
UNPROCESSABLE = 422  # Starlette renamed the constant between versions


# --- schemas ---


class LoginIn(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=1024)


class MembershipOut(BaseModel):
    tenant_id: uuid.UUID
    tenant_name: str
    role: MemberRole


class MeOut(BaseModel):
    account_id: uuid.UUID
    email: str
    is_platform_admin: bool
    memberships: list[MembershipOut]


class PasswordChangeIn(BaseModel):
    current_password: str = Field(max_length=1024)
    new_password: str = Field(max_length=1024)


class InvitationInfo(BaseModel):
    tenant_name: str
    email: str
    role: MemberRole
    status: Literal["pending", "expired", "accepted", "revoked"]


class AcceptIn(BaseModel):
    password: str | None = Field(default=None, max_length=1024)


class ResetIn(BaseModel):
    new_password: str = Field(max_length=1024)


class ResetInfo(BaseModel):
    email: str


# --- helpers ---


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=int(SESSION_ABSOLUTE.total_seconds()),
        secure=True,
        httponly=True,
        samesite="lax",
        path="/",
    )


def _new_password_hash(password: str) -> str:
    try:
        return hash_password(password)
    except PasswordPolicyError as e:
        raise HTTPException(UNPROCESSABLE, str(e)) from None


async def _me(db: AsyncSession, account_id: uuid.UUID) -> MeOut:
    """Requires the account context (set_account) to be set."""
    account = (
        await db.execute(
            select(Account.account_id, Account.email, Account.is_platform_admin).where(
                Account.account_id == account_id
            )
        )
    ).one()
    rows = (await db.execute(text("SELECT tenant_id, tenant_name, role FROM auth_my_memberships()"))).all()
    return MeOut(
        account_id=account.account_id,
        email=account.email,
        is_platform_admin=account.is_platform_admin,
        memberships=[MembershipOut(tenant_id=r.tenant_id, tenant_name=r.tenant_name, role=r.role) for r in rows],
    )


async def _guard_link_lookup(limiter: RateLimiter, request: Request) -> str:
    key = f"rl:link:ip:{_client_ip(request)}"
    if await limiter.is_blocked(key, LINK_FAILURE_LIMIT):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many attempts. Try again later.")
    return key


def _invitation_status(row) -> str:
    if row.revoked_at is not None:
        return "revoked"
    if row.accepted_at is not None:
        return "accepted"
    if row.expires_at <= datetime.now(UTC):
        return "expired"
    return "pending"


async def _find_invitation(db: AsyncSession, limiter: RateLimiter, request: Request, token: str):
    key = await _guard_link_lookup(limiter, request)
    row = (
        await db.execute(text("SELECT * FROM auth_invitation_by_token(:h)"), {"h": hash_token(token)})
    ).first()
    if row is None:
        await limiter.record(key, LOGIN_WINDOW_SECONDS)
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invitation not found")
    return row


# --- sign-in / sign-out ---


@router.post("/login", response_model=MeOut, dependencies=[Depends(check_origin)])
async def login(
    body: LoginIn,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    limiter: RateLimiter = Depends(get_rate_limiter),
) -> MeOut:
    ip = _client_ip(request)
    try:
        account_id = await authenticate(db, limiter, body.email, body.password, ip)
    except InvalidCredentials:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password") from None
    except RateLimited:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, "Too many attempts. Try again later."
        ) from None
    token = await create_session(db, account_id, request.headers.get("user-agent"), ip)
    _set_session_cookie(response, token)
    return await _me(db, account_id)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    response: Response,
    _: CurrentAccount = Depends(current_account),
    db: AsyncSession = Depends(get_db),
) -> None:
    await revoke_session(db, request.cookies[SESSION_COOKIE])
    response.delete_cookie(SESSION_COOKIE, path="/", secure=True, httponly=True, samesite="lax")


@router.get("/me", response_model=MeOut)
async def me(
    account: CurrentAccount = Depends(current_account), db: AsyncSession = Depends(get_db)
) -> MeOut:
    return await _me(db, account.account_id)


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    body: PasswordChangeIn,
    request: Request,
    account: CurrentAccount = Depends(current_account),
    db: AsyncSession = Depends(get_db),
    limiter: RateLimiter = Depends(get_rate_limiter),
) -> None:
    key = login_email_key(account.email)
    if await limiter.is_blocked(key, LOGIN_EMAIL_LIMIT):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many attempts. Try again later.")
    current_hash = await db.scalar(
        select(Account.password_hash).where(Account.account_id == account.account_id)
    )
    if not verify_password(body.current_password, current_hash):
        await limiter.record(key, LOGIN_WINDOW_SECONDS)
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Current password is incorrect")
    await db.execute(
        update(Account)
        .where(Account.account_id == account.account_id)
        .values(password_hash=_new_password_hash(body.new_password), password_changed_at=func.now())
    )
    # Anyone else signed in as this account is signed out
    await revoke_other_sessions(db, keep_token=request.cookies[SESSION_COOKIE])


# --- invitation links (no sign-in required to view) ---


@router.get("/invitations/{token}", response_model=InvitationInfo)
async def get_invitation(
    token: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    limiter: RateLimiter = Depends(get_rate_limiter),
) -> InvitationInfo:
    row = await _find_invitation(db, limiter, request, token)
    return InvitationInfo(
        tenant_name=row.tenant_name, email=row.email, role=row.role, status=_invitation_status(row)
    )


@router.post(
    "/invitations/{token}/accept", response_model=MeOut, dependencies=[Depends(check_origin)]
)
async def accept_invitation(
    token: str,
    body: AcceptIn,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    limiter: RateLimiter = Depends(get_rate_limiter),
) -> MeOut:
    invitation = await _find_invitation(db, limiter, request, token)
    invitation_status = _invitation_status(invitation)
    if invitation_status != "pending":
        raise HTTPException(status.HTTP_410_GONE, f"This invitation is {invitation_status}")

    session_token = request.cookies.get(SESSION_COOKIE)
    account_id = await resolve_session(db, session_token) if session_token else None
    new_session: str | None = None

    if account_id is not None:
        # Signed in: the invitation must be for this exact account
        email = await db.scalar(select(Account.email).where(Account.account_id == account_id))
        if email != invitation.email:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "This invitation is for a different email address"
            )
    else:
        existing = (
            await db.execute(text("SELECT account_id FROM auth_login_lookup(:e)"), {"e": invitation.email})
        ).first()
        if existing is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "An account with this email already exists. Sign in, then open the link again.",
            )
        if not body.password:
            raise HTTPException(UNPROCESSABLE, "Choose a password")
        password_hash = _new_password_hash(body.password)
        account_id = uuid.uuid4()
        await set_account(db, account_id)
        # Exactly the columns del_app may insert (migration 0003)
        await db.execute(
            insert(Account).values(
                account_id=account_id, email=invitation.email, password_hash=password_hash
            )
        )
        new_session = await create_session(
            db, account_id, request.headers.get("user-agent"), _client_ip(request)
        )

    await set_tenant(db, invitation.tenant_id)
    if await db.scalar(select(Membership.membership_id).where(Membership.account_id == account_id)):
        raise HTTPException(status.HTTP_409_CONFLICT, "You are already a member of this tenant")
    db.add(Membership(tenant_id=invitation.tenant_id, account_id=account_id, role=invitation.role))
    claimed = await db.execute(
        update(Invitation)
        .where(
            Invitation.invitation_id == invitation.invitation_id,
            Invitation.accepted_at.is_(None),
            Invitation.revoked_at.is_(None),
        )
        .values(accepted_at=func.now(), accepted_by=account_id)
    )
    if claimed.rowcount != 1:  # lost a race with another accept or a revoke
        raise HTTPException(status.HTTP_410_GONE, "This invitation is no longer valid")

    if new_session:
        _set_session_cookie(response, new_session)
    return await _me(db, account_id)


# --- password reset links (issued by a platform admin) ---


@router.get("/password-resets/{token}", response_model=ResetInfo)
async def get_password_reset(
    token: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    limiter: RateLimiter = Depends(get_rate_limiter),
) -> ResetInfo:
    """Which account a valid link is for, so the page can show it and password managers
    save the new password under the right email. Holding the link already grants the reset."""
    key = await _guard_link_lookup(limiter, request)
    account_id = await db.scalar(
        text("SELECT auth_password_reset_by_token(:h)"), {"h": hash_token(token)}
    )
    if account_id is None:
        await limiter.record(key, LOGIN_WINDOW_SECONDS)
        raise HTTPException(status.HTTP_410_GONE, "This link is invalid or has expired")
    await set_account(db, account_id)
    email = await db.scalar(select(Account.email).where(Account.account_id == account_id))
    return ResetInfo(email=email)


@router.post(
    "/password-resets/{token}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(check_origin)],
)
async def use_password_reset(
    token: str,
    body: ResetIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    limiter: RateLimiter = Depends(get_rate_limiter),
) -> None:
    key = await _guard_link_lookup(limiter, request)
    token_hash = hash_token(token)
    account_id = await db.scalar(text("SELECT auth_password_reset_by_token(:h)"), {"h": token_hash})
    if account_id is None:
        await limiter.record(key, LOGIN_WINDOW_SECONDS)
        raise HTTPException(status.HTTP_410_GONE, "This link is invalid or has expired")
    password_hash = _new_password_hash(body.new_password)

    await set_account(db, account_id)
    used = await db.execute(
        update(PasswordReset)
        .where(PasswordReset.token_hash == token_hash, PasswordReset.used_at.is_(None))
        .values(used_at=func.now())
    )
    if used.rowcount != 1:
        raise HTTPException(status.HTTP_410_GONE, "This link is invalid or has expired")
    await db.execute(
        update(Account)
        .where(Account.account_id == account_id)
        .values(password_hash=password_hash, password_changed_at=func.now())
    )
    await revoke_other_sessions(db)  # sign out everywhere
    email = await db.scalar(select(Account.email).where(Account.account_id == account_id))
    await limiter.reset(login_email_key(email))
