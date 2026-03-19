import re

# Compiled regexes for heuristic pre-filter
TRACEBACK_START = re.compile(r"^Traceback \(most recent call last\):")
FILE_LINE_PATTERN = re.compile(r'^\s*File ".+", line \d+')
ERROR_LINE = re.compile(r"^\w*(Error|Exception|Fault):")
FATAL_KEYWORDS = re.compile(r"^(CRITICAL|FATAL|PANIC)[\s:]", re.IGNORECASE)

STDERR_ERROR_KEYWORDS = [
    "Traceback",
    "Error:",
    "Exception:",
    "Fatal:",
    "CRITICAL:",
    "SyntaxError",
    "IndentationError",
    "ModuleNotFoundError",
    "ImportError",
    "AttributeError",
    "NameError",
    "OSError",
    "PermissionError",
]

IGNORE_PATTERNS = [
    re.compile(r"DeprecationWarning"),
    re.compile(r"PendingDeprecationWarning"),
    re.compile(r"ResourceWarning"),
    re.compile(r"UserWarning"),
    re.compile(r"InsecureRequestWarning"),
    re.compile(r"Watching for file changes"),
    re.compile(r"Performing system checks"),
]

# Seconds of no new stderr before a burst is considered "settled"
SETTLE_TIMEOUT = 2.0

# Max lines to keep in the rolling buffer
MAX_BUFFER_LINES = 100

# Lines to grab when a process dies
DEATH_CONTEXT_LINES = 80
