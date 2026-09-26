import re
from typing import Optional, Dict, Any
from ..base import IGuardValidator, GuardResult


class KeywordValidator(IGuardValidator):
    """Blocks requests for credentials or secrets.

    Uses word-boundary phrases so ordinary contract language such as
    "administrative fees" or "root cause" is not blocked.
    """

    FORBIDDEN_PATTERNS = {
        "password": r"\bpasswords?\b",
        "secret key": r"\bsecret keys?\b",
        "api key": r"\bapi[\s_-]?keys?\b",
        "admin credentials": r"\badmin(istrator)? (credentials|password|login)\b",
        "root access": r"\broot (access|password|credentials)\b",
        "database credentials": r"\bdatabase credentials\b",
    }

    def validate(self, input_text: str, context: Optional[Dict[str, Any]] = None) -> GuardResult:
        input_lower = input_text.lower()
        for label, pattern in self.FORBIDDEN_PATTERNS.items():
            if re.search(pattern, input_lower):
                return GuardResult(
                    is_safe=False,
                    violation_type="SENSITIVE_CONTENT",
                    message=f"Request contains forbidden keyword: '{label}'"
                )
        return GuardResult(is_safe=True)
