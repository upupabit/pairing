"""AWS Signature Version 4 for one JSON POST (Amazon Bedrock with an IAM access key): the published algorithm,
https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_sigv-create-signed-request.html, with only the standard
library. Signs content-type, host and x-amz-date plus a hash of the exact body bytes sent."""

import hashlib
import hmac
from datetime import UTC, datetime
from urllib.parse import quote, urlsplit

_ALGORITHM = "AWS4-HMAC-SHA256"
_SIGNED_HEADERS = "content-type;host;x-amz-date"


def _hmac(key: bytes, text: str) -> bytes:
    return hmac.new(key, text.encode(), hashlib.sha256).digest()


class SigV4Signer:
    def __init__(self, access_key_id: str, secret_access_key: str, region: str, service: str = "bedrock") -> None:
        self._access_key_id = access_key_id
        self._secret = secret_access_key
        self._region = region
        self._service = service

    def signing_key(self, date: str) -> bytes:
        key = _hmac(f"AWS4{self._secret}".encode(), date)
        for part in (self._region, self._service, "aws4_request"):
            key = _hmac(key, part)
        return key

    def headers(self, url: str, body: bytes, now: datetime | None = None) -> dict[str, str]:
        """The headers for a POST of `body` (JSON) to `url`, which has no query string."""
        now = now or datetime.now(UTC)
        amz_date, date = now.strftime("%Y%m%dT%H%M%SZ"), now.strftime("%Y%m%d")
        parts = urlsplit(url)
        # Non-S3 services: each path segment is URI-encoded twice (a no-op for plain paths like /openai/v1/...).
        path = "/".join(quote(quote(seg, safe="-_.~"), safe="-_.~") for seg in parts.path.split("/")) or "/"
        canonical_headers = f"content-type:application/json\nhost:{parts.hostname}\nx-amz-date:{amz_date}\n"
        canonical = "\n".join(["POST", path, "", canonical_headers, _SIGNED_HEADERS, hashlib.sha256(body).hexdigest()])
        scope = f"{date}/{self._region}/{self._service}/aws4_request"
        to_sign = "\n".join([_ALGORITHM, amz_date, scope, hashlib.sha256(canonical.encode()).hexdigest()])
        signature = hmac.new(self.signing_key(date), to_sign.encode(), hashlib.sha256).hexdigest()
        return {
            "Content-Type": "application/json",
            "X-Amz-Date": amz_date,
            "Authorization": f"{_ALGORITHM} Credential={self._access_key_id}/{scope}, "
            f"SignedHeaders={_SIGNED_HEADERS}, Signature={signature}",
        }
