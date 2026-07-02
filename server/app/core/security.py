from passlib.context import CryptContext
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

_signer = URLSafeTimedSerializer(settings.SECRET_KEY, salt="session")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_session_token(user_id: str) -> str:
    return _signer.dumps({"uid": user_id})


def decode_session_token(token: str, max_age: int = settings.SESSION_MAX_AGE) -> str | None:
    try:
        data = _signer.loads(token, max_age=max_age)
        return data["uid"]
    except (BadSignature, SignatureExpired, KeyError):
        return None
