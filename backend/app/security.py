"""Security headers for public hosting. Set LIVINGDOC_CSP=0 to turn the Content-Security-Policy off (e.g. a separately hosted frontend)."""
import os

CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; "
       "img-src 'self' data:; connect-src 'self'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'")


async def headers(request, call_next):
    resp = await call_next(request)
    p = request.url.path
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")          # private links carry a token in the URL
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Permissions-Policy", "camera=(), geolocation=(), payment=(), microphone=(self)")
    if os.environ.get("LIVINGDOC_CSP", "1") == "1" and not p.startswith(("/docs", "/redoc")):
        resp.headers.setdefault("Content-Security-Policy", CSP)
    if request.headers.get("x-forwarded-proto", request.url.scheme) == "https":
        resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
    return resp
