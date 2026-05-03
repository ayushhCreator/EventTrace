from __future__ import annotations

import base64
import hashlib
import hmac


def verify_twilio_signature(auth_token: str, signature: str, url: str, params: dict) -> bool:
    """Validate X-Twilio-Signature per Twilio's HMAC-SHA1 scheme."""
    s = url + "".join(f"{k}{v}" for k, v in sorted(params.items()))
    expected = base64.b64encode(hmac.new(auth_token.encode(), s.encode(), hashlib.sha1).digest()).decode()
    return hmac.compare_digest(expected, signature)

