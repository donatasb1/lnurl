
import jwt
import asyncio
from datetime import timedelta, datetime
from fastapi.security import HTTPBasic, HTTPBasicCredentials, OAuth2AuthorizationCodeBearer
from fastapi import Depends, Header
from typing import Annotated
from .base import TokenData
from .lnurl import encode
import secrets
import binascii
import os

SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = os.getenv("ALGORITHM")


def random_k1():
    random_bytes = secrets.token_bytes(32)  # Generates 32 random bytes
    random_hex = binascii.hexlify(random_bytes).decode()  # Convert bytes to a hexadecimal string
    return random_hex

# Decode access token
def decode_access_token(authorization: str = Header(None)):
    if authorization is None:
        return None
    try:
        token = authorization.split()[1]
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        token_data = TokenData(userid=payload.get("sub"), token=token)
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None
    return token_data

class RateLimiter:
    """
    Limit requests to 1 per interval seconds
    """
    def __init__(self, interval: int):
        self.interval = interval
        self.request_cache: dict[str, float] = {}

    async def register(self, key: str) -> bool:
        # return is_limited
        current_time = datetime.utcnow().timestamp()
        async with asyncio.Lock():
            last_access_time = self.request_cache.get(key, 0)
            if current_time - last_access_time < self.interval:
                self.request_cache[key] = current_time
                return True
            else:
                self.request_cache[key] = current_time
                return False

    async def cleanup(self):
        while True:
            asyncio.sleep(180)
            current_time = datetime.utcnow().timestamp()
            to_rem = []
            for key, last_accessed_time in self.request_cache.items():
                if (last_accessed_time + self.interval) < current_time:
                    to_rem.append(key)
            for k in to_rem:
                self.request_cache.pop(k)

