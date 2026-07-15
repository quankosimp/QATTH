from __future__ import annotations

import http.client
import ipaddress
import re
import socket
import ssl
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from app.core.errors import AppError


MAX_RESPONSE_BYTES = 1024 * 1024


@dataclass(frozen=True)
class VerifiedPage:
    final_url: str
    http_status: int
    outcome: str
    title: str | None
    description: str | None
    content_hash_input: str


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, origin_host: str, pinned_ip: str, port: int, timeout: float) -> None:
        super().__init__(origin_host, port=port, timeout=timeout)
        self._pinned_ip = pinned_ip

    def connect(self) -> None:
        self.sock = socket.create_connection((self._pinned_ip, self.port), self.timeout)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, origin_host: str, pinned_ip: str, port: int, timeout: float) -> None:
        super().__init__(origin_host, port=port, timeout=timeout, context=ssl.create_default_context())
        self._pinned_ip = pinned_ip

    def connect(self) -> None:
        raw_socket = socket.create_connection((self._pinned_ip, self.port), self.timeout)
        self.sock = self._context.wrap_socket(raw_socket, server_hostname=self.host)


class SafeJobFetcher:
    expired_phrases = (
        "job is no longer available",
        "job has expired",
        "position has been filled",
        "no longer accepting applications",
        "tin tuyển dụng đã hết hạn",
        "việc làm đã hết hạn",
        "không còn nhận hồ sơ",
        "vị trí đã được tuyển",
    )
    stopwords = {
        "and", "the", "for", "with", "inc", "ltd", "llc", "company",
        "cong", "ty", "tnhh", "co", "phan", "va", "cho", "tai",
    }

    def fetch(
        self,
        url: str,
        *,
        expected_title: str | None = None,
        expected_company: str | None = None,
    ) -> VerifiedPage:
        current = url
        for _ in range(4):
            parsed, pinned_ip = self._resolve_public_url(current)
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            connection_type = _PinnedHTTPSConnection if parsed.scheme == "https" else _PinnedHTTPConnection
            connection = connection_type(parsed.hostname or "", pinned_ip, port, 12)
            path = parsed.path or "/"
            if parsed.query:
                path += "?" + parsed.query
            host_header = parsed.hostname or ""
            if parsed.port and parsed.port not in {80, 443}:
                host_header += ":" + str(parsed.port)
            try:
                connection.request(
                    "GET",
                    path,
                    headers={
                        "Host": host_header,
                        "User-Agent": "QATTH-JobVerifier/1.0",
                        "Accept": "text/html,application/xhtml+xml",
                        "Accept-Encoding": "identity",
                        "Connection": "close",
                    },
                )
                response = connection.getresponse()
                body = response.read(MAX_RESPONSE_BYTES + 1)
            except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
                raise AppError(
                    502,
                    "JOB_SOURCE_FETCH_FAILED",
                    "Job source could not be fetched",
                    retryable=True,
                ) from exc
            finally:
                connection.close()
            if len(body) > MAX_RESPONSE_BYTES:
                raise AppError(422, "JOB_SOURCE_TOO_LARGE", "Job source response exceeds 1 MiB")
            if response.status in {301, 302, 303, 307, 308}:
                location = response.getheader("Location")
                if not location:
                    raise AppError(422, "JOB_SOURCE_REDIRECT_INVALID", "Job source redirect has no target")
                current = urljoin(current, location)
                continue
            content_type = (response.getheader("Content-Type") or "").lower()
            title = None
            description = None
            if "html" in content_type and body:
                soup = BeautifulSoup(body, "html.parser")
                for node in soup(["script", "style", "noscript", "iframe", "object", "embed"]):
                    node.decompose()
                title = soup.title.get_text(" ", strip=True)[:500] if soup.title else None
                description = " ".join(soup.get_text(" ", strip=True).split())[:20000] or None
            outcome = self._classify(
                response.status,
                content_type,
                title,
                description,
                expected_title,
                expected_company,
            )
            return VerifiedPage(
                final_url=current,
                http_status=response.status,
                outcome=outcome,
                title=title,
                description=description,
                content_hash_input=body.decode("utf-8", "replace"),
            )
        raise AppError(422, "JOB_SOURCE_REDIRECT_INVALID", "Job source has too many redirects")

    @staticmethod
    def _resolve_public_url(url: str):
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise AppError(422, "JOB_SOURCE_URL_INVALID", "Job source URL is invalid")
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        if port not in {80, 443}:
            raise AppError(422, "JOB_SOURCE_PORT_BLOCKED", "Job source port is not allowed")
        try:
            resolved = socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise AppError(422, "JOB_SOURCE_DNS_FAILED", "Job source hostname could not be resolved") from exc
        addresses = sorted({item[4][0] for item in resolved})
        if not addresses:
            raise AppError(422, "JOB_SOURCE_DNS_FAILED", "Job source hostname has no address")
        for address in addresses:
            ip = ipaddress.ip_address(address)
            if not ip.is_global or ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                raise AppError(422, "JOB_SOURCE_URL_BLOCKED", "Job source resolves to a non-public address")
        return parsed, addresses[0]

    @classmethod
    def _classify(
        cls,
        status: int,
        content_type: str,
        title: str | None,
        description: str | None,
        expected_title: str | None,
        expected_company: str | None,
    ) -> str:
        if status != 200:
            return "unavailable"
        if "html" not in content_type:
            return "content_type_unsupported"
        page_text = " ".join(value for value in (title, description) if value).casefold()
        if any(phrase in page_text for phrase in cls.expired_phrases):
            return "expired"
        if not page_text:
            return "content_empty"
        if expected_title and not cls._matches(page_text, expected_title, minimum_ratio=0.5):
            return "title_mismatch"
        if expected_company and not cls._matches(page_text, expected_company, minimum_ratio=0.34):
            return "company_mismatch"
        return "verified"

    @classmethod
    def _matches(cls, page_text: str, expected: str, minimum_ratio: float) -> bool:
        expected_tokens = {
            token
            for token in re.findall(r"[\w+#.]+", expected.casefold())
            if len(token) > 1 and token not in cls.stopwords
        }
        if not expected_tokens:
            return True
        page_tokens = set(re.findall(r"[\w+#.]+", page_text))
        return len(expected_tokens & page_tokens) / len(expected_tokens) >= minimum_ratio
