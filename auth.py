"""NormaCheck - Module d'authentification.

JWT (HMAC-SHA256) + PBKDF2 password hashing.
Zero dependance externe (stdlib uniquement).
Compatible OVHcloud (persistant) et Vercel (in-memory).
"""

import base64
import hashlib
import hmac
import json
import os
import time
import uuid
from datetime import datetime
from typing import Optional

from fastapi import Request, HTTPException, Response

# --- Configuration ---
SECRET_KEY = os.getenv("NORMACHECK_SECRET_KEY", "normacheck-dev-key-CHANGEZ-EN-PRODUCTION")
TOKEN_EXPIRY_HOURS = int(os.getenv("NORMACHECK_TOKEN_EXPIRY", "24"))
PBKDF2_ITERATIONS = 150_000

# --- Environment ---
_IS_OVH = os.getenv("NORMACHECK_ENV") in ("production", "development", "staging")

# --- Stores ---
_users_store = None
_users: dict = {}
_dashboard_store = None
_dashboards: dict = {}

if _IS_OVH:
    try:
        from persistence import PersistentStore
        _users_store = PersistentStore("users", default={})
        _users = _users_store.load()
        _dashboard_store = PersistentStore("dashboards", default={})
        _dashboards = _dashboard_store.load()
    except ImportError:
        pass


# =========================================
# PASSWORD HASHING (PBKDF2-SHA256, stdlib)
# =========================================

def hash_password(password: str) -> str:
    salt = os.urandom(16).hex()
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), PBKDF2_ITERATIONS)
    return f"{salt}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    parts = stored.split("$", 1)
    if len(parts) != 2:
        return False
    salt = parts[0]
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), PBKDF2_ITERATIONS)
    return hmac.compare_digest(f"{salt}${dk.hex()}", stored)


# =========================================
# JWT (HMAC-SHA256, stdlib)
# =========================================

def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(s: str) -> bytes:
    s += "=" * (4 - len(s) % 4)
    return base64.urlsafe_b64decode(s)


def jwt_encode(payload: dict) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    h = _b64url_encode(json.dumps(header, separators=(",", ":")).encode())
    p = _b64url_encode(json.dumps(payload, separators=(",", ":"), default=str).encode())
    sig_input = f"{h}.{p}".encode()
    sig = hmac.new(SECRET_KEY.encode(), sig_input, hashlib.sha256).digest()
    return f"{h}.{p}.{_b64url_encode(sig)}"


def jwt_decode(token: str) -> Optional[dict]:
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        sig_input = f"{parts[0]}.{parts[1]}".encode()
        expected = hmac.new(SECRET_KEY.encode(), sig_input, hashlib.sha256).digest()
        actual = _b64url_decode(parts[2])
        if not hmac.compare_digest(expected, actual):
            return None
        payload = json.loads(_b64url_decode(parts[1]))
        if payload.get("exp") and payload["exp"] < time.time():
            return None
        return payload
    except Exception:
        return None


# =========================================
# USER CRUD
# =========================================

def create_user(email: str, password: str, nom: str, prenom: str,
                role: str = "collaborateur", tenant_id: str = None) -> dict:
    email = email.strip().lower()
    if email in _users:
        raise ValueError("Email deja utilise")
    if len(password) < 6:
        raise ValueError("Mot de passe trop court (min. 6 caracteres)")
    if not tenant_id:
        tenant_id = str(uuid.uuid4())[:8]
    user = {
        "id": str(uuid.uuid4())[:8],
        "email": email,
        "nom": nom,
        "prenom": prenom,
        "password_hash": hash_password(password),
        "role": role,
        "tenant_id": tenant_id,
        "created_at": datetime.now().isoformat(),
        "active": True,
    }
    _users[email] = user
    _save_users()
    return _safe_user(user)


def authenticate(email: str, password: str) -> Optional[dict]:
    email = email.strip().lower()
    user = _users.get(email)
    if not user or not verify_password(password, user["password_hash"]):
        return None
    if not user.get("active", True):
        return None
    return _safe_user(user)


def get_user(email: str) -> Optional[dict]:
    user = _users.get(email.strip().lower())
    if not user:
        return None
    return _safe_user(user)


def update_user_role(email: str, new_role: str) -> Optional[dict]:
    email = email.strip().lower()
    user = _users.get(email)
    if not user:
        return None
    user["role"] = new_role
    _save_users()
    return _safe_user(user)


def set_user_tenant(email: str, tenant_id: str) -> Optional[dict]:
    email = email.strip().lower()
    user = _users.get(email)
    if not user:
        return None
    user["tenant_id"] = tenant_id
    _save_users()
    return _safe_user(user)


def list_users_by_tenant(tenant_id: str) -> list:
    return [_safe_user(u) for u in _users.values() if u.get("tenant_id") == tenant_id]


def _safe_user(user: dict) -> dict:
    return {k: v for k, v in user.items() if k != "password_hash"}


def _save_users():
    if _users_store:
        _users_store.save(_users)


# =========================================
# TOKEN GENERATION
# =========================================

def generate_token(user: dict) -> str:
    return jwt_encode({
        "sub": user["email"],
        "role": user.get("role", "collaborateur"),
        "tenant_id": user.get("tenant_id", "default"),
        "nom": user.get("nom", ""),
        "prenom": user.get("prenom", ""),
        "exp": int(time.time()) + TOKEN_EXPIRY_HOURS * 3600,
        "iat": int(time.time()),
    })


def set_auth_cookie(response: Response, token: str):
    response.set_cookie(
        key="nc_token",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=TOKEN_EXPIRY_HOURS * 3600,
        secure=_IS_OVH,
    )


def clear_auth_cookie(response: Response):
    response.delete_cookie(key="nc_token")


# =========================================
# FASTAPI DEPENDENCIES
# =========================================

def get_current_user(request: Request) -> dict:
    """Extract and validate JWT from cookie or Authorization header."""
    token = request.cookies.get("nc_token")
    if not token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
    if not token:
        raise HTTPException(401, "Non authentifie")
    payload = jwt_decode(token)
    if not payload:
        raise HTTPException(401, "Session expiree ou invalide")
    email = payload.get("sub")
    user = _users.get(email)
    if not user:
        raise HTTPException(401, "Utilisateur inconnu")
    return _safe_user(user)


def get_optional_user(request: Request) -> Optional[dict]:
    """Like get_current_user but returns None instead of raising."""
    try:
        return get_current_user(request)
    except HTTPException:
        return None


def require_role(*allowed_roles):
    """Factory: returns a dependency that checks the user's role."""
    def checker(request: Request):
        user = get_current_user(request)
        if user["role"] not in allowed_roles:
            raise HTTPException(403, f"Role requis : {', '.join(allowed_roles)}")
        return user
    return checker


# =========================================
# DASHBOARD PERSISTENCE
# =========================================

def save_dashboard(email: str, data: dict):
    email = email.strip().lower()
    _dashboards[email] = {
        "data": data,
        "saved_at": datetime.now().isoformat(),
    }
    if _dashboard_store:
        _dashboard_store.save(_dashboards)


def load_dashboard(email: str) -> Optional[dict]:
    email = email.strip().lower()
    entry = _dashboards.get(email)
    if not entry:
        return None
    return entry
