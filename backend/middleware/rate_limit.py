import time
from collections import defaultdict
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint


class RateLimitMiddleware(BaseHTTPMiddleware):
    """In-memory sliding window rate limiting middleware.

    Enforces a general global limit and tighter limits for resource-heavy paths
    (U-Net ML inference, Ollama LLM queries, and PDF reports).
    """

    def __init__(
        self,
        app,
        global_limit: int = 100,
        global_window: int = 60,
        heavy_limit: int = 15,
        heavy_window: int = 60,
    ) -> None:
        super().__init__(app)
        self.global_limit = global_limit
        self.global_window = global_window
        self.heavy_limit = heavy_limit
        self.heavy_window = heavy_window
        # Dictionary mapping IP -> {"global": [timestamps], "heavy": [timestamps]}
        self.history = defaultdict(lambda: {"global": [], "heavy": []})
        self.last_pruned = time.time()

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        now = time.time()

        # Prune older IP records once every hour
        if now - self.last_pruned > 3600:
            self._prune_history(now)

        # Resolve client IP
        client_ip = request.client.host if request.client else "unknown"
        path = request.url.path

        # Bypass rate limiting for local loopback (testing/dev convenience)
        # unless explicitly enforced via header (for unit testing)
        enforce = request.headers.get("x-enforce-rate-limit") == "true"
        if not enforce and client_ip in ("127.0.0.1", "::1", "localhost"):
            return await call_next(request)

        # Identify heavy paths
        is_heavy = path.startswith(("/api/analyze", "/api/chat", "/api/narration", "/api/report"))

        # Filter out timestamps older than the sliding window
        self.history[client_ip]["global"] = [
            t for t in self.history[client_ip]["global"] if now - t < self.global_window
        ]
        self.history[client_ip]["heavy"] = [
            t for t in self.history[client_ip]["heavy"] if now - t < self.heavy_window
        ]

        # Enforce global rate limit
        if len(self.history[client_ip]["global"]) >= self.global_limit:
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests. Please try again later."},
            )

        # Enforce heavy endpoints limit
        if is_heavy and len(self.history[client_ip]["heavy"]) >= self.heavy_limit:
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Rate limit exceeded for resource-intensive operations. Please try again in a minute."
                },
            )

        # Record current request timestamps
        self.history[client_ip]["global"].append(now)
        if is_heavy:
            self.history[client_ip]["heavy"].append(now)

        return await call_next(request)

    def _prune_history(self, now: float) -> None:
        """Housekeep historical requests dictionary to prevent memory leaks."""
        inactive_ips = []
        for ip, record in self.history.items():
            record["global"] = [t for t in record["global"] if now - t < self.global_window]
            record["heavy"] = [t for t in record["heavy"] if now - t < self.heavy_window]
            if not record["global"] and not record["heavy"]:
                inactive_ips.append(ip)

        for ip in inactive_ips:
            self.history.pop(ip, None)
        self.last_pruned = now
