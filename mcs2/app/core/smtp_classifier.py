"""
==========================================================
SMTP Error Classifier
Marketing Campaign System v2.5 Enterprise
==========================================================

Classifies SMTP responses into

• SUCCESS

• RETRY

• FAILED

• RATE_LIMIT

• INVALID_EMAIL

• INVALID_DOMAIN

• UNKNOWN

This allows the worker to intelligently retry only
temporary failures instead of permanently failing
every exception.
"""

from enum import Enum


class SMTPStatus(Enum):

    SUCCESS = "success"

    RETRY = "retry"

    FAILED = "failed"

    RATE_LIMIT = "rate_limit"

    INVALID_EMAIL = "invalid_email"

    INVALID_DOMAIN = "invalid_domain"

    SPAM_BLOCK = "spam_block"

    AUTHENTICATION = "authentication"

    CONNECTION = "connection"

    UNKNOWN = "unknown"


class SMTPClassifier:

    @staticmethod
    def classify(error) -> tuple:

        """
        Returns

        (
            SMTPStatus,
            category_string
        )
        """

        message = str(error).lower()

        # ---------------------------------
        # RATE LIMIT
        # ---------------------------------

        rate_limit_keywords = [

            "bounce limit",

            "too many",

            "rate limit",

            "throttled",

            "quota exceeded",

            "daily limit"

        ]

        if any(word in message for word in rate_limit_keywords):

            return (

                SMTPStatus.RATE_LIMIT,

                "rate_limit"

            )

        # ---------------------------------
        # TEMPORARY SMTP ERRORS
        # ---------------------------------

        retry_keywords = [
            "421", "450", "451", "452", "temporary", "try again",
            "timeout", "timed out", "connection reset", "connection closed",
            "mailbox busy"
        ]

        if any(word in message for word in retry_keywords):
            return (SMTPStatus.RETRY, "temporary_failure")

        # ---------------------------------
        # INVALID EMAIL
        # ---------------------------------

        invalid_email_keywords = [

            "550",

            "551",

            "553",

            "user unknown",

            "mailbox unavailable",

            "recipient rejected",

            "mailbox not found"

        ]

        if any(word in message for word in invalid_email_keywords):

            return (

                SMTPStatus.INVALID_EMAIL,

                "invalid_email"

            )

        # ---------------------------------
        # INVALID DOMAIN
        # ---------------------------------

        domain_keywords = [

            "domain not found",

            "dns",

            "host unknown",

            "no such domain"

        ]

        if any(word in message for word in domain_keywords):

            return (

                SMTPStatus.INVALID_DOMAIN,

                "invalid_domain"

            )

        # ---------------------------------
        # AUTH
        # ---------------------------------

        auth_keywords = [

            "authentication",

            "username",

            "password",

            "login failed",

            "535"

        ]

        if any(word in message for word in auth_keywords):

            return (

                SMTPStatus.AUTHENTICATION,

                "authentication"

            )

        # ---------------------------------
        # SPAM
        # ---------------------------------

        spam_keywords = [

            "spam",

            "blocked",

            "blacklist",

            "rejected",

            "policy"

        ]

        if any(word in message for word in spam_keywords):

            return (

                SMTPStatus.SPAM_BLOCK,

                "spam_policy"

            )

        # ---------------------------------
        # CONNECTION
        # ---------------------------------

        connection_keywords = [

            "connection refused",

            "network unreachable",

            "socket",

            "ssl",

            "tls"

        ]

        if any(word in message for word in connection_keywords):

            return (

                SMTPStatus.CONNECTION,

                "connection"

            )

        # ---------------------------------

        return (

            SMTPStatus.UNKNOWN,

            "unknown"

        )
