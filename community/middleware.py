CSP_REPORT_ONLY_POLICY = (
    "default-src 'self'; "
    "script-src 'self' https://challenges.cloudflare.com; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "font-src 'self'; "
    "frame-src https://challenges.cloudflare.com; "
    "connect-src 'self' https://challenges.cloudflare.com; "
    "base-uri 'self'; "
    "form-action 'self'"
)


class ContentSecurityPolicyReportOnlyMiddleware:
    """Adds Content-Security-Policy-Report-Only (not the enforcing header) so violations show up
    in the browser console without breaking anything — a first step before ever switching to the
    enforcing Content-Security-Policy header. 'unsafe-inline' in style-src is needed for the
    inline style="" attributes templates already use throughout; tightening that is a separate,
    larger change. Turnstile's own domain is allowed in script-src/frame-src/connect-src since the
    widget it renders (when TURNSTILE_SITE_KEY is set) needs all three."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.headers.setdefault('Content-Security-Policy-Report-Only', CSP_REPORT_ONLY_POLICY)
        return response
