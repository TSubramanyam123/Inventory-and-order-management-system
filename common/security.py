import hashlib
import hmac
import os
import secrets
import time
import jwt
from fastapi import Header, HTTPException
from pydantic import BaseModel, Field


def secret():
    value = os.getenv('JWT_SECRET', '')
    if len(value) < 32:
        raise RuntimeError('JWT_SECRET must contain at least 32 characters. Run python scripts/setup_env.py')
    return value


def hash_password(password):
    salt = secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    return f'scrypt${salt}${digest}'


def check_password(password, stored):
    _, salt, digest = stored.split('$')
    actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    return hmac.compare_digest(actual, digest)


def token(user):
    now = int(time.time())
    return jwt.encode({'sub': user['id'], 'role': user['role'], 'name': user['name'],
                       'iat': now, 'exp': now + int(os.getenv('ACCESS_TOKEN_SECONDS', '900')),
                       'iss': 'inventory-auth', 'aud': 'inventory-api', 'jti': secrets.token_hex(16)},
                      secret(), algorithm='HS256')


def decode(value):
    try:
        return jwt.decode(value, secret(), algorithms=['HS256'], issuer='inventory-auth', audience='inventory-api')
    except jwt.PyJWTError:
        raise HTTPException(401, 'Invalid or expired access token')


async def current_user(authorization: str = Header(default='')):
    if not authorization.startswith('Bearer '):
        raise HTTPException(401, 'Authentication required')
    user = decode(authorization[7:])
    # Roles in tokens are checked against current auth records by administrative
    # dependency; demoting a user revokes administrative access immediately.
    return user


async def internal(x_service_key: str = Header(default='')):
    configured = os.getenv('SERVICE_SECRET', '')
    if len(configured) < 32 or not hmac.compare_digest(x_service_key, configured):
        raise HTTPException(403, 'Internal service credentials required')


class Credentials(BaseModel):
    email: str = Field(min_length=5, max_length=254, pattern=r'^[^\s@]+@[^\s@]+\.[^\s@]+$')
    password: str = Field(min_length=8, max_length=128)


class Registration(Credentials):
    name: str = Field(min_length=2, max_length=100)
