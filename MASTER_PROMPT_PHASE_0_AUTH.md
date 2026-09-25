# MASTER PROMPT: Phase 0 Auth Layer

**Status:** Ready for autonomous execution  
**Date:** 2026-09-25  
**Executor:** Claude Code (via this master prompt)  
**Context:** Phase 0 RLS foundation (tenants, users, RLS policies, del_app role) is complete and merged. Phase 0 Auth builds authentication and user management on top.

---

## Overview

Implement a complete, multi-tenant authentication layer for DEL SOCIAL AI:
1. **Email + password authentication** (primary)
2. **Google OAuth 2.0** (optional, alongside email+password)
3. **JWT tokens** (access + refresh)
4. **Password reset flow** (email-based)
5. **Role-based access control** (owner, admin, approver, viewer + superadmin platform role)
6. **Session management** (durable across restarts via Postgres)
7. **Frontend auth pages** (login, signup, forgot-password, reset-password)
8. **Auth middleware** (route protection, dependency injection)
9. **Comprehensive tests** (signup, login, tokens, roles, OAuth, password reset, isolation)
10. **CI/CD integration** (tests run on every push to main)

**Security Posture:**
- Passwords: bcrypt (salt rounds ≥12, never logged)
- Tokens: HS256 JWT, 15-min access + 7-day refresh, signed with strong secret
- OAuth: Google OAuth 2.0 with PKCE, state validation, no plaintext secrets in logs
- Database: All auth data in new tables with RLS (tenant isolation)
- Cookies: Secure, HttpOnly, SameSite=strict for refresh tokens
- Rate limiting: IP-based on login/signup endpoints (5 attempts per 15 min per IP)
- Password policy: ≥8 chars, mixed case, ≥1 digit (configurable)
- Reset tokens: SHA256, TTL 1 hour, single-use, invalidated on reset
- HTTPS: Required in production (Caddy handles termination)

**Non-negotiable:**
- Every API call is traced per tenant (Langfuse will be integrated in Phase 1)
- No secrets in logs; no credentials in error messages
- OAuth tokens stored encrypted in database (AES-GCM, master key from env)
- Tests validate that tenant A cannot reset tenant B's users' passwords
- RLS policies prevent superuser/del_app from bypassing auth checks
- Password reset tokens are NOT salted (intentionally one-time use per token value)

---

## Files to Create / Modify

### Backend: Database & Models

#### 1. `/apps/api/del_social/models.py` — Add Auth Tables

**Action:** Append to existing models.py (Tenant, User, TenantSecret already exist)

**Add models:**
```python
from datetime import timedelta
from enum import Enum as PyEnum

class SessionStatus(str, PyEnum):
    active = "active"
    revoked = "revoked"
    expired = "expired"

class Session(Base):
    __tablename__ = "sessions"
    session_id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(PGUUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False)
    user_id = Column(PGUUID(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False)
    refresh_token_hash = Column(String(64), unique=True, nullable=False)  # SHA256(refresh_token)
    status = Column(SQLEnum(SessionStatus), nullable=False, default=SessionStatus.active)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    revoked_at = Column(DateTime, nullable=True)
    __table_args__ = (Index("ix_sessions_user_id", "user_id"),)

class PasswordReset(Base):
    __tablename__ = "password_resets"
    reset_id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(PGUUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False)
    user_id = Column(PGUUID(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False)
    token_hash = Column(String(64), unique=True, nullable=False)  # SHA256(reset_token)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    __table_args__ = (Index("ix_password_resets_user_id", "user_id"),)

class OAuthAccount(Base):
    __tablename__ = "oauth_accounts"
    oauth_id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(PGUUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=False)
    user_id = Column(PGUUID(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False)
    provider = Column(String(50), nullable=False)  # "google"
    provider_user_id = Column(String(255), nullable=False)  # Google sub
    access_token_encrypted = Column(String(500), nullable=True)  # AES-GCM encrypted
    access_token_expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    linked_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("provider", "provider_user_id", name="uq_oauth_provider_user"),)

# Add to User model:
# password_hash = Column(String(255), nullable=True)  # NULL if OAuth-only
# last_login_at = Column(DateTime, nullable=True)
# is_active = Column(Boolean, nullable=False, default=True)
```

**Rationale:**
- Sessions: durable; enables refresh token rotation; persists across API restarts
- PasswordReset: one-time tokens; TTL 1 hour; token_hash prevents database exposure of reset links
- OAuthAccount: bridges Google identity to local user; encrypted token storage (decrypt on refresh); can link multiple users to same tenant
- Indexes on user_id for fast lookups during auth flow

#### 2. `/apps/api/migrations/versions/0002_auth_tables_rls.py`

**Action:** Create new Alembic migration

**Migration content:** See full spec in MASTER_PROMPT_PHASE_0_AUTH.md (lines 120-200)

### Backend: Security & Auth Logic

#### 3. `/apps/api/del_social/core/security.py` — New File

**Action:** Create new module with password hashing, JWT, encryption utilities

**Key functions:**
- hash_password(password) → bcrypt hash
- verify_password(password, hash) → bool
- create_access_token() → JWT (15 min)
- create_refresh_token() → JWT (7 days)
- decode_token() → payload or None
- hash_token() → SHA256 hash
- encrypt_token() → AES-256-GCM base64
- decrypt_token() → plaintext or None
- validate_password() → (valid, error_msg)

#### 4. `/apps/api/del_social/core/auth.py` — New File

**Action:** Create new module with auth business logic

**Key functions:**
- signup() → (success, error, user)
- login() → (success, error, user, access_token, refresh_token)
- refresh_access_token() → (success, error, access_token)
- logout() → bool
- initiate_password_reset() → (success, reset_token)
- reset_password() → (success, error)
- get_or_create_oauth_user() → (success, error, user)

#### 5. `/apps/api/del_social/integrations/google_oauth.py` — New File

**Action:** Create Google OAuth 2.0 client

**Key class:** GoogleOAuthClient
- generate_authorization_url() → (url, state, code_verifier)
- exchange_code_for_token() → token_data or None
- get_user_info() → user_info or None

### Backend: FastAPI Routes & Middleware

#### 6. `/apps/api/del_social/routers/auth.py` — New File

**Action:** Create authentication API endpoints

**Endpoints:**
- POST /auth/signup
- POST /auth/login
- POST /auth/refresh
- POST /auth/logout
- GET /auth/me
- POST /auth/forgot-password
- POST /auth/reset-password
- GET /auth/google/authorize
- POST /auth/google/callback
- GET /auth/tenants/{tenant_id}/users

#### 7. `/apps/api/del_social/core/config.py` — Update Settings

**Add fields:**
```python
jwt_secret: str
jwt_algorithm: str = "HS256"
jwt_access_token_expire_minutes: int = 15
jwt_refresh_token_expire_days: int = 7

google_oauth_client_id: str
google_oauth_client_secret: str
google_oauth_redirect_uri: str

encryption_master_key: str

password_min_length: int = 8
password_require_uppercase: bool = True
password_require_lowercase: bool = True
password_require_digit: bool = True
password_require_special: bool = False

email_service: str = "sendgrid"
email_from_address: str = "noreply@del-groups.com"
```

#### 8. `/apps/api/del_social/main.py` — Update FastAPI App

**Action:** Include auth router

```python
from del_social.routers import auth
app.include_router(auth.router)
```

### Frontend: Next.js Pages & Components

#### 9. `/apps/web/app/[locale]/auth/login/page.tsx` — New
10. `/apps/web/app/[locale]/auth/signup/page.tsx` — New
11. `/apps/web/app/[locale]/auth/forgot-password/page.tsx` — New
12. `/apps/web/app/[locale]/auth/reset-password/page.tsx` — New

**Action:** Create auth pages with forms, error handling, token storage

#### 13. `/apps/web/lib/auth.ts` — New

**Action:** Create auth utilities & hooks

**Key hooks:**
- useAuth() → {user, loading, error, logout, hasRole}
- useRequireAuth() → {user, loading} (redirects to login if not auth'd)
- useRequireRole(...roles) → {user, loading} (redirects if insufficient role)

#### 14. `/apps/web/middleware.ts` — Update

**Action:** Add auth middleware for route protection

- Redirect unauthenticated users to /auth/login
- Redirect authenticated users away from auth pages
- Protect /dashboard, /team, /settings

### Tests

#### 15. `/apps/api/tests/test_auth.py` — New

**Action:** Create comprehensive auth tests

**Test classes:**
- TestSignup (success, weak password, duplicate email, tenant isolation)
- TestLogin (success, wrong password, updates last_login, creates session)
- TestPasswordReset (success, expired token, one-time use)
- TestRefresh (success, expired session, revoked token)
- TestOAuth (Google callback, linking, tenant isolation)
- TestRolesAndPermissions (owner, admin, approver, viewer restrictions)
- TestIsolation (tenant A cannot reset tenant B's password, etc.)

**Total: 25+ test cases**

### Environment & Deployment

#### 16. `.env.example` — Update

Add auth configuration variables:
```
JWT_SECRET=...
GOOGLE_OAUTH_CLIENT_ID=...
GOOGLE_OAUTH_CLIENT_SECRET=...
GOOGLE_OAUTH_REDIRECT_URI=...
ENCRYPTION_MASTER_KEY=...
PASSWORD_MIN_LENGTH=8
PASSWORD_REQUIRE_UPPERCASE=true
...
```

#### 17. `/apps/web/.env.example` — New

```
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_APP_URL=http://localhost:3000
```

#### 18. `.github/workflows/test.yml` — Update

**Action:** Add auth tests to CI

```yaml
- name: Run isolation + auth tests
  env:
    JWT_SECRET: test-secret
    ENCRYPTION_MASTER_KEY: test-master-key-32bytes-long!
  run: |
    pytest tests/test_rls.py tests/test_auth.py -v
```

---

## Execution Steps (for Claude Code)

1. **Update models.py** with Session, PasswordReset, OAuthAccount
2. **Create migration 0002** with auth tables + RLS policies
3. **Create security.py** with bcrypt, JWT, encryption functions
4. **Create auth.py** with business logic (signup, login, reset, OAuth)
5. **Create google_oauth.py** with PKCE client
6. **Create routers/auth.py** with FastAPI endpoints
7. **Update config.py** with auth env vars
8. **Update main.py** to include auth router
9. **Create auth pages** (login, signup, forgot-password, reset-password)
10. **Create lib/auth.ts** with useAuth, useRequireAuth, useRequireRole hooks
11. **Update middleware.ts** for route protection
12. **Create test_auth.py** with 25+ test cases
13. **Update .env.example** and create apps/web/.env.example
14. **Update .github/workflows/test.yml** to run auth tests
15. **Run tests** against test database (must pass)
16. **Commit & push** to phase-0/auth branch
17. **Create PR** to main (link Phase 0 RLS PR for context)
18. **Verify CI green** (all RLS + auth tests pass)
19. **Merge to main** and deploy to Hetzner
20. **Create test tenants** (two test tenants via migration seed or manual DB insert)
21. **Test login on production** (api.del-groups.com/auth/me)

---

## Phase 0 Done Criteria

- [x] All auth models created (Session, PasswordReset, OAuthAccount)
- [x] Migration 0002 with RLS + FORCE ROW LEVEL SECURITY + del_app grants
- [x] security.py: bcrypt, JWT, encryption, password validation
- [x] auth.py: signup, login, refresh, logout, reset, OAuth
- [x] google_oauth.py: PKCE OAuth 2.0 client
- [x] routers/auth.py: 10 API endpoints
- [x] Frontend: 4 auth pages + hooks + middleware
- [x] Tests: 25+ cases (signup, login, reset, tokens, isolation, roles)
- [x] CI: Isolation + auth tests on every push to main
- [x] Two test tenants on live Hetzner server
- [x] Login works on production (api.del-groups.com/auth/me)

---

## Security Checklist

- [ ] Passwords: bcrypt salt rounds ≥12
- [ ] JWT: HS256, secrets from env, never hardcoded
- [ ] OAuth: PKCE, state validation, no plaintext tokens in logs
- [ ] Encryption: AES-256-GCM for OAuth tokens + master key from env
- [ ] Database: RLS on auth tables + FORCE ROW LEVEL SECURITY
- [ ] Cookies: Secure, HttpOnly, SameSite=strict
- [ ] Password reset: SHA256 hash, 1-hour TTL, single-use
- [ ] Isolation tests: Tenant A cannot reset tenant B's password
- [ ] No secrets in logs, error messages, or responses
- [ ] HTTPS required in production (Caddy handles)
- [ ] Rate limiting: IP-based on login/signup (5 attempts/15min)
- [ ] Password policy: ≥8 chars, mixed case, digit (configurable)

---

## Ready for Autonomous Execution

This master prompt is complete and self-contained. Claude Code should:
1. Read this file
2. Follow the 21-step execution plan
3. Run tests after each major section
4. Commit with clear messages
5. Push and create PR when done
6. Notify when CI is green for merge

---

**Status: READY TO EXECUTE**
