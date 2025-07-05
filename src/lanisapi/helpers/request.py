"""This script includes the Request class to request data with exception handling."""

import httpx

from ..exceptions import LoginPageRedirectError, PageNotFoundError


def _check_response(response: httpx.Response) -> httpx.Response:
    if response.status_code == 404:
        msg = f"Lanis couldn't find the specified page: {response.url}"
        raise PageNotFoundError(msg)

    header_cookies = response.headers.get("set-cookie")
    if header_cookies and header_cookies == "i=0; secure":
        msg = f"Lanis returned the login page while trying to access {response.url}. Maybe the session is over."
        raise LoginPageRedirectError(msg)

    return response


class Request:

    def __init__(self):
        self.client: httpx.Client = httpx.Client(timeout=httpx.Timeout(30.0, connect=60.0))

    def post(self, *args: tuple, **kwargs: dict[str, any]) -> httpx.Response:
        """Return a response using the post function from httpx.Client."""
        response = self.client.post(*args, **kwargs)

        return _check_response(response)

    def get(self, *args: tuple, **kwargs: dict[str, any]) -> httpx.Response:
        """Return a response using the get function from httpx.Client."""
        response: httpx.Response = self.client.post(*args, **kwargs)

        return _check_response(response)

    def head(self, *args: tuple, **kwargs: dict[str, any]) -> httpx.Response:
        """Return a response using the head function from httpx.Client."""
        response: httpx.Response = self.client.head(*args, **kwargs)

        return _check_response(response)

    def request(self, *args: tuple, **kwargs: dict[str, any]) -> httpx.Response:
        """Return a response using the request function from httpx.Client."""
        response: httpx.Response = self.client.request(*args, **kwargs)

        return _check_response(response)

    def set_cookies(self, cookie: httpx.Cookies) -> None:
        """Set cookies."""
        self.client.cookies = cookie

    def get_cookies(self) -> httpx.Cookies:
        """Get cookies."""
        return self.client.cookies

    def set_headers(self, headers: httpx.Headers) -> None:
        """Set headers."""
        self.client.headers = headers

    def close(self) -> None:
        """Close the httpx client."""
        self.client.close()
