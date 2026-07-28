"""Authentication, session, and single-operator policy for the LAN console."""

import base64
from dataclasses import dataclass
import hashlib
import hmac
import math
import secrets
import threading
import time
from typing import Callable, Optional


class AuthenticationError(ValueError):
    pass


class ControlLeaseError(PermissionError):
    pass


class ManualControlError(PermissionError):
    pass


def hash_password(
    password: str,
    *,
    salt: Optional[bytes] = None,
    n: int = 2**14,
    r: int = 8,
    p: int = 1,
    dklen: int = 32,
) -> str:
    if not isinstance(password, str) or not password:
        raise ValueError("password must be a nonempty string")
    salt = secrets.token_bytes(16) if salt is None else bytes(salt)
    if len(salt) < 16:
        raise ValueError("salt must contain at least 16 bytes")
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=int(n),
        r=int(r),
        p=int(p),
        dklen=int(dklen),
    )
    encoded_salt = base64.urlsafe_b64encode(salt).decode("ascii")
    encoded_digest = base64.urlsafe_b64encode(digest).decode("ascii")
    return f"scrypt$n={int(n)},r={int(r)},p={int(p)}${encoded_salt}${encoded_digest}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, parameters, encoded_salt, encoded_digest = encoded.split("$")
        if algorithm != "scrypt":
            return False
        parsed = {}
        for item in parameters.split(","):
            name, value = item.split("=", 1)
            parsed[name] = int(value)
        if set(parsed) != {"n", "r", "p"}:
            return False
        salt = base64.urlsafe_b64decode(encoded_salt.encode("ascii"))
        expected = base64.urlsafe_b64decode(encoded_digest.encode("ascii"))
        candidate = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=parsed["n"],
            r=parsed["r"],
            p=parsed["p"],
            dklen=len(expected),
        )
    except (TypeError, ValueError, KeyError):
        return False
    return hmac.compare_digest(candidate, expected)


@dataclass(frozen=True)
class ConsolePolicyConfig:
    username: str
    password_hash: str
    session_idle_timeout_sec: float = 1800.0
    session_absolute_timeout_sec: float = 43200.0
    lease_timeout_sec: float = 2.0
    manual_timeout_sec: float = 0.2
    manual_max_linear: float = 0.6
    manual_max_angular: float = 1.4

    def __post_init__(self) -> None:
        if not self.username:
            raise ValueError("username must not be empty")
        if not self.password_hash.startswith("scrypt$"):
            raise ValueError("password_hash must use the supported scrypt format")
        for name in (
            "session_idle_timeout_sec",
            "session_absolute_timeout_sec",
            "lease_timeout_sec",
            "manual_timeout_sec",
            "manual_max_linear",
            "manual_max_angular",
        ):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value <= 0.0:
                raise ValueError(f"{name} must be finite and positive")
        if self.session_absolute_timeout_sec < self.session_idle_timeout_sec:
            raise ValueError(
                "session_absolute_timeout_sec must be at least the idle timeout"
            )


@dataclass(frozen=True)
class LoginResult:
    session_id: str
    csrf_token: str


@dataclass
class Session:
    session_id: str
    csrf_token: str
    username: str
    created_at: float
    last_seen_at: float


class ConsolePolicy:
    def __init__(
        self,
        *,
        config: ConsolePolicyConfig,
        clock: Callable[[], float] = time.monotonic,
        token_source: Callable[[], str] = lambda: secrets.token_urlsafe(32),
    ) -> None:
        self.config = config
        self._clock = clock
        self._token_source = token_source
        self._lock = threading.RLock()
        self._sessions: dict[str, Session] = {}
        self._issued_tokens: set[str] = set()
        self._lease_session_id: Optional[str] = None
        self._lease_heartbeat_at: Optional[float] = None
        self._manual_command = (0.0, 0.0, 0.0)
        self._manual_command_at: Optional[float] = None
        self._nav_active = False

    def login(self, username: str, password: str) -> LoginResult:
        username_ok = isinstance(username, str) and hmac.compare_digest(
            username.encode("utf-8"), self.config.username.encode("utf-8")
        )
        password_ok = isinstance(password, str) and verify_password(
            password, self.config.password_hash
        )
        if not (username_ok and password_ok):
            raise AuthenticationError("invalid credentials")

        with self._lock:
            now = self._clock()
            self._expire(now)
            session_id = self._new_token()
            csrf_token = self._new_token()
            self._sessions[session_id] = Session(
                session_id=session_id,
                csrf_token=csrf_token,
                username=self.config.username,
                created_at=now,
                last_seen_at=now,
            )
            return LoginResult(session_id=session_id, csrf_token=csrf_token)

    def authenticate(self, session_id: str, *, touch: bool = True) -> Session:
        with self._lock:
            now = self._clock()
            self._expire(now)
            session = self._sessions.get(session_id)
            if session is None:
                raise AuthenticationError("authentication required")
            if touch:
                session.last_seen_at = now
            return session

    def csrf_matches(self, session_id: str, candidate: str) -> bool:
        session = self.authenticate(session_id)
        return isinstance(candidate, str) and hmac.compare_digest(
            session.csrf_token.encode("utf-8"), candidate.encode("utf-8")
        )

    def logout(self, session_id: str) -> None:
        with self._lock:
            self._release_if_holder(session_id)
            self._sessions.pop(session_id, None)

    def disconnect(self, session_id: str) -> None:
        with self._lock:
            self._release_if_holder(session_id)

    def acquire_control(self, session_id: str) -> bool:
        with self._lock:
            self.authenticate(session_id)
            now = self._clock()
            self._expire(now)
            if (
                self._lease_session_id is not None
                and self._lease_session_id != session_id
            ):
                raise ControlLeaseError("control is held by another operator")
            self._lease_session_id = session_id
            self._lease_heartbeat_at = now
            return True

    def heartbeat(self, session_id: str) -> bool:
        with self._lock:
            self.authenticate(session_id)
            self._expire(self._clock())
            if self._lease_session_id != session_id:
                raise ControlLeaseError("control lease required")
            self._lease_heartbeat_at = self._clock()
            return True

    def release_control(self, session_id: str) -> None:
        with self._lock:
            self.authenticate(session_id)
            if self._lease_session_id == session_id:
                self._clear_lease()

    def set_nav_active(self, active: bool) -> None:
        with self._lock:
            self._nav_active = bool(active)
            if self._nav_active:
                self._clear_manual()

    def submit_manual(
        self, session_id: str, vx: float, vy: float, vyaw: float
    ) -> bool:
        with self._lock:
            self.authenticate(session_id)
            now = self._clock()
            self._expire(now)
            if self._lease_session_id != session_id:
                raise ControlLeaseError("control lease required")
            if self._nav_active:
                self._clear_manual()
                raise ManualControlError(
                    "manual control is locked; cancel navigation first"
                )
            values = (float(vx), float(vy), float(vyaw))
            if not all(math.isfinite(value) for value in values):
                self._clear_manual()
                raise ManualControlError("manual velocity must be finite")
            self._manual_command = (
                max(
                    -self.config.manual_max_linear,
                    min(self.config.manual_max_linear, values[0]),
                ),
                0.0,
                max(
                    -self.config.manual_max_angular,
                    min(self.config.manual_max_angular, values[2]),
                ),
            )
            self._manual_command_at = now
            self._lease_heartbeat_at = now
            return True

    def current_manual_command(self) -> tuple[float, float, float]:
        with self._lock:
            now = self._clock()
            self._expire(now)
            if (
                self._nav_active
                or self._lease_session_id is None
                or self._manual_command_at is None
                or now - self._manual_command_at > self.config.manual_timeout_sec
            ):
                self._clear_manual()
            return self._manual_command

    def authorize_arm(self, session_id: str) -> bool:
        with self._lock:
            self.authenticate(session_id)
            self._expire(self._clock())
            if self._lease_session_id != session_id:
                raise ControlLeaseError("control lease required")
            return True

    def authorize_disarm(self, session_id: str) -> bool:
        self.authenticate(session_id)
        return True

    def public_state(self) -> dict:
        with self._lock:
            self._expire(self._clock())
            return {
                "control_lease_held": self._lease_session_id is not None,
                "nav_active": self._nav_active,
                "manual_command_active": self._manual_command_at is not None,
            }

    def _new_token(self) -> str:
        for _ in range(1024):
            value = str(self._token_source())
            if len(value) >= 16 and value not in self._issued_tokens:
                self._issued_tokens.add(value)
                return value
        raise RuntimeError("token source did not produce a fresh opaque token")

    def _expire(self, now: float) -> None:
        expired = [
            session_id
            for session_id, session in self._sessions.items()
            if (
                now - session.last_seen_at > self.config.session_idle_timeout_sec
                or now - session.created_at
                > self.config.session_absolute_timeout_sec
            )
        ]
        for session_id in expired:
            self._release_if_holder(session_id)
            self._sessions.pop(session_id, None)
        if (
            self._lease_session_id is not None
            and self._lease_heartbeat_at is not None
            and now - self._lease_heartbeat_at > self.config.lease_timeout_sec
        ):
            self._clear_lease()

    def _release_if_holder(self, session_id: str) -> None:
        if self._lease_session_id == session_id:
            self._clear_lease()

    def _clear_lease(self) -> None:
        self._lease_session_id = None
        self._lease_heartbeat_at = None
        self._clear_manual()

    def _clear_manual(self) -> None:
        self._manual_command = (0.0, 0.0, 0.0)
        self._manual_command_at = None
