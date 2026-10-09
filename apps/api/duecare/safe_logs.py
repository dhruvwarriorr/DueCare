"""Keep OAuth query strings and private exception parameters out of default server logs."""

import logging


class SafeException(logging.Filter):
    def filter(self, record):
        if record.exc_info:
            kind = record.exc_info[0].__name__
            record.msg, record.args = "ASGI application error type=%s", (kind,)
            record.exc_info = record.exc_text = None
        return True


def configure():
    # Access URLs contain authorization codes and sender addresses. Application errors carry
    # a request ID instead; a public reverse proxy must also avoid logging these raw URLs.
    logging.getLogger("uvicorn.access").disabled = True
    logging.getLogger("uvicorn.error").addFilter(SafeException())
