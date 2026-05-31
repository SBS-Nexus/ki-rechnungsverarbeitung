"""
SBS Deutschland – Rate Limiter
Einfaches In-Memory Rate Limiting für API-Schutz.
"""

import time
from collections import defaultdict
from functools import wraps
from fastapi import Request, HTTPException


class RateLimiter:
    """In-Memory Rate Limiter"""
    
    def __init__(self):
        # {ip: [(timestamp, endpoint), ...]}
        self.requests = defaultdict(list)
        self.cleanup_interval = 60  # Sekunden
        self.last_cleanup = time.time()
    
    def _cleanup(self):
        """Alte Einträge entfernen"""
        now = time.time()
        if now - self.last_cleanup < self.cleanup_interval:
            return
        
        cutoff = now - 60  # Requests älter als 1 Minute löschen
        for ip in list(self.requests.keys()):
            self.requests[ip] = [
                (ts, ep) for ts, ep in self.requests[ip] 
                if ts > cutoff
            ]
            if not self.requests[ip]:
                del self.requests[ip]
        
        self.last_cleanup = now
    
    def is_allowed(self, ip: str, endpoint: str, limit: int = 60, window: int = 60) -> bool:
        """
        Prüft ob Request erlaubt ist.
        
        Args:
            ip: Client IP
            endpoint: API Endpoint
            limit: Max Requests pro Window
            window: Zeitfenster in Sekunden
        
        Returns:
            True wenn erlaubt, False wenn Limit erreicht
        """
        self._cleanup()
        
        now = time.time()
        cutoff = now - window
        
        # Requests im Zeitfenster zählen
        recent = [ts for ts, ep in self.requests[ip] if ts > cutoff]
        
        if len(recent) >= limit:
            return False
        
        # Request registrieren
        self.requests[ip].append((now, endpoint))
        return True
    
    def get_remaining(self, ip: str, limit: int = 60, window: int = 60) -> int:
        """Verbleibende Requests im Zeitfenster"""
        now = time.time()
        cutoff = now - window
        recent = [ts for ts, ep in self.requests[ip] if ts > cutoff]
        return max(0, limit - len(recent))


# Globale Instanz
limiter = RateLimiter()


# Rate Limits pro Endpoint-Typ
RATE_LIMITS = {
    "default": (60, 60),      # 60 Requests/Minute
    "upload": (10, 60),       # 10 Uploads/Minute
    "auth": (5, 900),         # 5 Login-Versuche / 15 Minuten (Brute-Force-Schutz)
    "export": (20, 60),       # 20 Exports/Minute
}


def get_client_ip(request: Request) -> str:
    """Holt echte Client-IP (auch hinter Proxy)"""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host or "unknown"


def check_rate_limit(request: Request, limit_type: str = "default"):
    """
    Prüft Rate Limit und wirft Exception wenn überschritten.
    
    Usage in Endpoint:
        check_rate_limit(request, "upload")
    """
    ip = get_client_ip(request)
    limit, window = RATE_LIMITS.get(limit_type, RATE_LIMITS["default"])
    
    if not limiter.is_allowed(ip, request.url.path, limit, window):
        remaining = limiter.get_remaining(ip, limit, window)
        raise HTTPException(
            status_code=429,
            detail={
                "error": "Too Many Requests",
                "message": f"Rate limit exceeded. Try again in {window} seconds.",
                "limit": limit,
                "remaining": remaining
            }
        )
