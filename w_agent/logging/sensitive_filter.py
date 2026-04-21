from pydantic import SecretStr
import re
from typing import Any

class SensitiveDataFilter:
    PATTERNS = [
        (re.compile(r'api[_-]?key["\']?\s*[:=]\s*["\']?([a-zA-Z0-9]+)'), r'api_key="***"'),
        (re.compile(r'Authorization: Bearer [a-zA-Z0-9\.\-_]+'), 'Authorization: Bearer ***'),
    ]
    
    @staticmethod
    def filter(value: Any) -> Any:
        if isinstance(value, SecretStr):
            return "********"
        if isinstance(value, str):
            for pattern, repl in SensitiveDataFilter.PATTERNS:
                value = pattern.sub(repl, value)
        return value

def add_sensitive_filter(logger, method_name, event_dict):
    for key, value in event_dict.items():
        event_dict[key] = SensitiveDataFilter.filter(value)
    return event_dict