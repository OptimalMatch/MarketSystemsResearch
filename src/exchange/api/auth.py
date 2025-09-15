"""
Authentication module for Exchange API
Provides API key validation and JWT token generation
"""

import os
try:
    import jwt
except ImportError:
    # Use PyJWT if jwt not available
    import jwt as jwt
import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Optional, Dict, Tuple
from fastapi import HTTPException, Security, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials, APIKeyHeader
import asyncpg
from passlib.context import CryptContext

# Configuration
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "exchange-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Security schemes
bearer_scheme = HTTPBearer(auto_error=False)
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

# Database connection pool
db_pool: Optional[asyncpg.Pool] = None


async def init_db_pool():
    """Initialize database connection pool"""
    global db_pool
    if not db_pool:
        db_pool = await asyncpg.create_pool(
            host=os.getenv("POSTGRES_HOST", "postgres"),
            port=int(os.getenv("POSTGRES_PORT", 5432)),
            database=os.getenv("POSTGRES_DB", "exchange_db"),
            user=os.getenv("POSTGRES_USER", "exchange_user"),
            password=os.getenv("POSTGRES_PASSWORD", "exchange_pass"),
            min_size=10,
            max_size=20
        )
    return db_pool


async def close_db_pool():
    """Close database connection pool"""
    global db_pool
    if db_pool:
        await db_pool.close()
        db_pool = None


def hash_api_secret(secret: str) -> str:
    """Hash API secret for storage"""
    return pwd_context.hash(secret)


def verify_api_secret(plain_secret: str, hashed_secret: str) -> bool:
    """Verify API secret against hash"""
    return pwd_context.verify(plain_secret, hashed_secret)


def generate_api_credentials() -> Tuple[str, str]:
    """Generate new API key and secret"""
    api_key = f"exch_{secrets.token_urlsafe(32)}"
    api_secret = secrets.token_urlsafe(48)
    return api_key, api_secret


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create JWT access token"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def decode_access_token(token: str) -> Dict:
    """Decode and validate JWT token"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")


async def validate_api_key(api_key: str) -> Optional[Dict]:
    """Validate API key against database"""
    if not api_key:
        return None

    # For testing, accept test keys
    if api_key.startswith("test-"):
        return {
            "user_id": "test-user",
            "username": "testuser",
            "permissions": ["trade", "read"]
        }

    pool = await init_db_pool()
    if not pool:
        # Fallback for testing without database
        return None

    try:
        async with pool.acquire() as conn:
            query = """
                SELECT id, username, email, kyc_status, is_active
                FROM exchange.users
                WHERE api_key = $1 AND is_active = true
            """
            row = await conn.fetchrow(query, api_key)

            if row:
                return {
                    "user_id": str(row["id"]),
                    "username": row["username"],
                    "email": row["email"],
                    "kyc_status": row["kyc_status"],
                    "permissions": ["trade", "read"] if row["kyc_status"] == "verified" else ["read"]
                }
    except Exception as e:
        print(f"Database error during API key validation: {e}")

    return None


async def get_current_user(
    api_key: Optional[str] = Depends(api_key_header),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme)
) -> str:
    """Get current authenticated user from API key or JWT token"""

    # First try API key
    if api_key:
        user_data = await validate_api_key(api_key)
        if user_data:
            return user_data["user_id"]

    # Then try JWT token
    if credentials:
        try:
            payload = decode_access_token(credentials.credentials)
            return payload.get("user_id")
        except:
            pass

    # For testing/development, allow unauthenticated access with warning
    if os.getenv("ENVIRONMENT", "development") == "development":
        return "anonymous-dev-user"

    raise HTTPException(
        status_code=401,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_user_full(
    api_key: Optional[str] = Depends(api_key_header),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme)
) -> Dict:
    """Get full user data for authenticated user"""

    # First try API key
    if api_key:
        user_data = await validate_api_key(api_key)
        if user_data:
            return user_data

    # Then try JWT token
    if credentials:
        try:
            payload = decode_access_token(credentials.credentials)
            # Fetch full user data from database
            pool = await init_db_pool()
            if pool:
                async with pool.acquire() as conn:
                    query = """
                        SELECT id, username, email, kyc_status, is_active
                        FROM exchange.users
                        WHERE id = $1::uuid
                    """
                    row = await conn.fetchrow(query, payload.get("user_id"))
                    if row:
                        return {
                            "user_id": str(row["id"]),
                            "username": row["username"],
                            "email": row["email"],
                            "kyc_status": row["kyc_status"],
                            "permissions": ["trade", "read"] if row["kyc_status"] == "verified" else ["read"]
                        }
        except:
            pass

    # For testing/development
    if os.getenv("ENVIRONMENT", "development") == "development":
        return {
            "user_id": "anonymous-dev-user",
            "username": "anonymous",
            "permissions": ["trade", "read"]
        }

    raise HTTPException(status_code=401, detail="Not authenticated")


def require_permission(permission: str):
    """Decorator to require specific permission"""
    async def permission_checker(user_data: Dict = Depends(get_current_user_full)) -> Dict:
        if permission not in user_data.get("permissions", []):
            raise HTTPException(
                status_code=403,
                detail=f"Permission '{permission}' required"
            )
        return user_data
    return permission_checker


# Rate limiting helpers
class RateLimiter:
    """Simple in-memory rate limiter"""

    def __init__(self, requests_per_minute: int = 60):
        self.requests_per_minute = requests_per_minute
        self.requests = {}

    def check_rate_limit(self, user_id: str) -> bool:
        """Check if user has exceeded rate limit"""
        now = datetime.utcnow()
        minute_ago = now - timedelta(minutes=1)

        # Clean old requests
        if user_id in self.requests:
            self.requests[user_id] = [
                req_time for req_time in self.requests[user_id]
                if req_time > minute_ago
            ]
        else:
            self.requests[user_id] = []

        # Check limit
        if len(self.requests[user_id]) >= self.requests_per_minute:
            return False

        # Add current request
        self.requests[user_id].append(now)
        return True


# Global rate limiter instance
rate_limiter = RateLimiter(requests_per_minute=100)


async def check_rate_limit(user_id: str = Depends(get_current_user)):
    """Check rate limit for current user"""
    if not rate_limiter.check_rate_limit(user_id):
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded. Please slow down your requests."
        )
    return user_id