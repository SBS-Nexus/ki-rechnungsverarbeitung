"""Read mail credentials at the request boundary; never supply a source fallback."""
import os


def resend_headers() -> dict[str, str]:
    """Build Resend headers or fail before an outbound request if unconfigured."""
    api_key = os.environ.get("RESEND_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("RESEND_API_KEY is not configured")
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
