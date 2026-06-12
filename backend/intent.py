import re
from dataclasses import dataclass, field

CONFIDENCE_THRESHOLD = 0.40

TODAYS_PRIORITIES = "TODAYS_PRIORITIES"
OVERDUE_CUSTOMERS = "OVERDUE_CUSTOMERS"
HIGH_RISK_LOANS = "HIGH_RISK_LOANS"
COLLATERAL_RISK = "COLLATERAL_RISK"
CUSTOMER_SUMMARY = "CUSTOMER_SUMMARY"
CUSTOMER_ACCOUNTS = "CUSTOMER_ACCOUNTS"
CUSTOMER_LOANS = "CUSTOMER_LOANS"
DUE_SOON = "DUE_SOON"
DUE_TODAY = "DUE_TODAY"
DUE_TOMORROW = "DUE_TOMORROW"
DUE_THIS_WEEK = "DUE_THIS_WEEK"
MISSED_PAYMENTS = "MISSED_PAYMENTS"
CUSTOMER_COUNT = "CUSTOMER_COUNT"
LOAN_COUNT = "LOAN_COUNT"
ACCOUNT_COUNT = "ACCOUNT_COUNT"
TOTAL_OVERDUE = "TOTAL_OVERDUE"
PORTFOLIO_BALANCE = "PORTFOLIO_BALANCE"
CUSTOMER_SEARCH = "CUSTOMER_SEARCH"
PORTFOLIO_SUMMARY = "PORTFOLIO_SUMMARY"
UNKNOWN = "UNKNOWN"

CLARIFYING_MESSAGE = (
    "I can help with portfolio analytics, customer search, accounts, loans, payments, "
    "collateral, or daily priorities. Which would you like to see?"
)

OPERATIONAL_INTENTS = frozenset({
    TODAYS_PRIORITIES,
    OVERDUE_CUSTOMERS,
    HIGH_RISK_LOANS,
    COLLATERAL_RISK,
    CUSTOMER_SUMMARY,
    CUSTOMER_ACCOUNTS,
    CUSTOMER_LOANS,
    DUE_SOON,
    DUE_TODAY,
    DUE_TOMORROW,
    DUE_THIS_WEEK,
    MISSED_PAYMENTS,
    CUSTOMER_COUNT,
    LOAN_COUNT,
    ACCOUNT_COUNT,
    TOTAL_OVERDUE,
    PORTFOLIO_BALANCE,
    CUSTOMER_SEARCH,
    PORTFOLIO_SUMMARY,
})

AMBIGUOUS_PHRASES = (
    "show me details",
    "tell me more",
    "help me",
    "help",
    "what can you do",
    "what do you do",
    "i need help",
    "more info",
    "more information",
    "continue",
    "go on",
)

TODAYS_PRIORITIES_PHRASES = (
    "who should i call today",
    "who should i call first today",
    "what should i focus on today",
    "what should i focus on this morning",
    "what requires attention today",
    "what requires attention this morning",
    "what needs my attention",
    "what needs my attention today",
    "give me today's priorities",
    "give me todays priorities",
    "give me my morning briefing",
    "what should i do today",
    "what do you think i should do today",
    "what should i focus on",
    "what needs attention",
    "who should i call first",
    "what should i work on first",
    "what should i work on first today",
    "what is most important today",
    "what's most important today",
    "what should i prioritize",
    "what should i prioritize today",
    "who needs attention first this morning",
    "who needs attention first today",
    "what should i be doing right now",
    "give me an operations summary",
    "give me today's operations summary",
    "give me today's portfolio summary",
    "give me todays portfolio summary",
    "which customers need attention",
    "which accounts need immediate attention",
    "what should i focus on before lunch",
    "what should i take care of today",
    "what should i take care of before the end of the day",
    "what should i do first today",
    "today's priorities",
    "today priorities",
    "what should i call today",
    "morning follow-up list",
    "morning follow up list",
    "where should i start today",
    "where should i spend my time first",
    "if i only make one call today, who should it be",
    "give me a one-minute executive summary of today's operations",
    "what is the most important thing i should know right now",
    "which customer needs attention before things get worse",
    "what's the biggest issue in the portfolio today",
    "what is the biggest issue in the portfolio today",
    "give me a manager's summary of today's workload",
    "give me a managers summary of today's workload",
    "what is the highest priority account today",
    "if i were the branch manager, what would i do first",
)

TODAYS_PRIORITIES_EXECUTIVE_PHRASES = (
    "what should i do today",
    "what do you think i should do today",
    "what should i focus on today",
    "what should i focus on",
    "what needs attention",
    "what needs my attention",
    "what should i work on first",
    "what is most important today",
    "what should i prioritize",
    "give me today's priorities",
    "who should i call today",
    "who needs attention first this morning",
    "what should i be doing right now",
    "give me an operations summary",
    "give me today's portfolio summary",
)

TODAYS_PRIORITIES_SYNONYMS = (
    "priority",
    "priorities",
    "prioritize",
    "urgent",
    "important",
    "focus",
    "attention",
    "needs my attention",
    "morning briefing",
    "executive summary",
    "operations summary",
    "manager summary",
    "manager's summary",
    "first call",
    "highest priority",
    "most important",
    "where should i start",
    "what should i do first",
    "workload",
    "briefing",
    "one call",
    "branch manager",
    "spend my time",
    "end of the day",
    "right now",
    "before things get worse",
    "biggest issue",
    "operations today",
)

TODAYS_PRIORITIES_CONTEXT = (
    "today",
    "this morning",
    "morning",
    "now",
    "first",
    "before",
    "end of the day",
    "right now",
    "workload",
    "operations",
    "portfolio",
    "briefing",
    "call",
)

TODAYS_PRIORITIES_PATTERNS = (
    re.compile(r"who should i call(?:\s+first)?(?:\s+today)?", re.IGNORECASE),
    re.compile(
        r"(?:what|who)\s+should\s+i\s+(?:call|focus(?:\s+on)?|do|work on|take care of|priorit(?:y|ize)|be doing)(?:\s+first)?(?:\s+today|\s+this morning|\s+right now)?",
        re.IGNORECASE,
    ),
    re.compile(
        r"what do you think i should do(?:\s+today|\s+this morning|\s+right now)?",
        re.IGNORECASE,
    ),
    re.compile(
        r"what needs?(?:\s+my)?\s+attention(?:\s+today|\s+first|\s+this morning)?",
        re.IGNORECASE,
    ),
    re.compile(
        r"who needs?(?:\s+my)?\s+attention(?:\s+first)?(?:\s+this morning|\s+today)?",
        re.IGNORECASE,
    ),
    re.compile(
        r"what(?:'s| is)\s+(?:the\s+)?most important(?:\s+thing)?(?:\s+today|\s+right now)?",
        re.IGNORECASE,
    ),
    re.compile(r"what requires attention(?:\s+today|\s+this morning)?", re.IGNORECASE),
    re.compile(
        r"give me (?:my |an? )?(?:priorities|morning briefing|manager'?s summary|operations summary)",
        re.IGNORECASE,
    ),
    re.compile(
        r"give me today'?s (?:priorities|portfolio summary|operations summary)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:what|where)\s+should\s+i\s+(?:focus|start|begin|work|spend my time)(?:\s+on)?(?:\s+before|\s+today|\s+first)?",
        re.IGNORECASE,
    ),
    re.compile(
        r"which (?:customers?|accounts?|customer)\s+need(?:s)?(?:\s+immediate|\s+attention|\s+before)?",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:today(?:'s)?|this\s+morning(?:'s)?|morning)\s+"
        r"(?:priorit(?:y|ies)|briefing|follow[- ]?up|workload|plan|agenda|operations|portfolio summary)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:priorit(?:y|ies)|briefing|executive summary|manager'?s summary|follow[- ]?up|operations summary)"
        r".*(?:today|this morning|morning|operations|workload|portfolio|right now)",
        re.IGNORECASE,
    ),
    re.compile(r"if i (?:only make one call|were the branch manager)", re.IGNORECASE),
    re.compile(r"one[- ]minute executive summary", re.IGNORECASE),
    re.compile(r"most important thing.*(?:know|right now)", re.IGNORECASE),
    re.compile(r"biggest issue.*portfolio.*today", re.IGNORECASE),
    re.compile(r"highest priority account.*today", re.IGNORECASE),
    re.compile(r"take care of before the end of the day", re.IGNORECASE),
    re.compile(r"^what needs attention\??$", re.IGNORECASE),
    re.compile(r"^what should i focus on\??$", re.IGNORECASE),
    re.compile(r"^who should i call first\??$", re.IGNORECASE),
)

OVERDUE_SYNONYMS = (
    "overdue",
    "past due",
    "late",
    "behind on payment",
    "behind on payments",
    "who owes",
    "owes us",
    "delinquent",
    "late payment",
    "late customers",
)

HIGH_RISK_SYNONYMS = (
    "high risk",
    "high-risk",
    "high ltv",
    "riskiest",
    "risky loan",
    "highest risk loan",
    "ltv",
    "loan to value",
)

COLLATERAL_SYNONYMS = (
    "collateral",
    "forfeiture",
    "pledged assets",
    "assets at risk",
    "nearing forfeiture",
    "collateral risk",
)

CUSTOMER_SUMMARY_SYNONYMS = (
    "customer summary",
    "customer overview",
    "customer details",
    "summarize customer",
    "tell me about",
    "prepare me for a call",
    "profile",
)

CUSTOMER_ACCOUNTS_SYNONYMS = (
    "account balance",
    "account balances",
    "checking",
    "savings",
    "how much money",
    "balance",
    "deposit",
)

CUSTOMER_LOANS_SYNONYMS = (
    "loan status",
    "loan details",
    "loan balance",
    "owes",
    "owe",
    "outstanding",
    "ltv",
)

DUE_SOON_SYNONYMS = (
    "due soon",
    "coming due",
    "coming due next",
    "near due",
    "upcoming payment",
    "upcoming payments",
    "payments due",
)

PAYMENT_DUE_LITERAL_PHRASES = (
    "due today",
    "due tomorrow",
    "due this week",
    "due soon",
    "due next month",
)

PAYMENT_DUE_PHRASES = PAYMENT_DUE_LITERAL_PHRASES + (
    "who is due today",
    "who is due tomorrow",
    "who is due this week",
    "who is due soon",
    "any payments due today",
    "any payments due tomorrow",
    "any payments due this week",
    "who has a payment due today",
    "payments due today",
    "payments due tomorrow",
    "payments due this week",
    "payments due soon",
)

DUE_TODAY_PHRASES = (
    "who is due today",
    "any payments due today",
    "what payments are due today",
    "who has a payment due today",
    "payments due today",
    "due today",
)

DUE_TOMORROW_PHRASES = (
    "who is due tomorrow",
    "any payments due tomorrow",
    "payments due tomorrow",
    "due tomorrow",
)

DUE_THIS_WEEK_PHRASES = (
    "who is due this week",
    "payments due this week",
    "due this week",
)

DUE_SOON_PHRASES = (
    "who is due soon",
    "payments due soon",
    "upcoming payments",
    "what is coming due next",
    "due soon",
)

DUE_TODAY_PATTERNS = (
    re.compile(r"who(?:'s|\s+is)\s+due\s+today", re.IGNORECASE),
    re.compile(r"(?:any|which)\s+payments?\s+due\s+today", re.IGNORECASE),
    re.compile(r"what payments? (?:are )?due\s+today", re.IGNORECASE),
    re.compile(r"who\s+has\s+(?:a\s+)?payments?\s+due\s+today", re.IGNORECASE),
    re.compile(r"payments?\s+due\s+today", re.IGNORECASE),
    re.compile(r"^due\s+today\.?$", re.IGNORECASE),
)

DUE_TOMORROW_PATTERNS = (
    re.compile(r"who(?:'s|\s+is)\s+due\s+tomorrow", re.IGNORECASE),
    re.compile(r"(?:any|which)\s+payments?\s+due\s+tomorrow", re.IGNORECASE),
    re.compile(r"payments?\s+due\s+tomorrow", re.IGNORECASE),
    re.compile(r"^due\s+tomorrow\.?$", re.IGNORECASE),
)

DUE_THIS_WEEK_PATTERNS = (
    re.compile(r"who(?:'s|\s+is)\s+due\s+this\s+week", re.IGNORECASE),
    re.compile(r"payments?\s+due\s+this\s+week", re.IGNORECASE),
    re.compile(r"^due\s+this\s+week\.?$", re.IGNORECASE),
)

DUE_SOON_PATTERNS = (
    re.compile(r"who(?:'s|\s+is)\s+due\s+soon", re.IGNORECASE),
    re.compile(r"payments?\s+due\s+soon", re.IGNORECASE),
    re.compile(r"^due\s+soon\.?$", re.IGNORECASE),
    re.compile(r"upcoming payments?", re.IGNORECASE),
    re.compile(r"what(?:'s| is) coming due next\??", re.IGNORECASE),
)

MISSED_PAYMENT_SYNONYMS = (
    "missed payment",
    "missed payments",
    "did not pay",
    "failed payment",
)

CUSTOMER_COUNT_SYNONYMS = (
    "customer count",
    "how many customers",
    "number of customers",
    "total customers",
    "customers on file",
    "count customers",
)

LOAN_COUNT_SYNONYMS = (
    "loan count",
    "how many loans",
    "number of loans",
    "total loans",
    "active loans",
    "count loans",
)

ACCOUNT_COUNT_SYNONYMS = (
    "account count",
    "how many accounts",
    "number of accounts",
    "total accounts",
    "accounts on file",
    "count accounts",
)

TOTAL_OVERDUE_SYNONYMS = (
    "total overdue",
    "overdue amount",
    "how much overdue",
    "how much is overdue",
    "past due amount",
    "overdue exposure",
    "amount overdue",
)

PORTFOLIO_BALANCE_SYNONYMS = (
    "portfolio balance",
    "total portfolio balance",
    "total balance",
    "total loan balance",
    "outstanding balance",
    "loan balances total",
    "combined balance",
)

PORTFOLIO_SUMMARY_SYNONYMS = (
    "portfolio summary",
    "business overview",
    "portfolio snapshot",
    "portfolio overview",
    "overall portfolio",
    "how is the portfolio",
    "how is business",
    "business snapshot",
    "branch overview",
    "portfolio health",
    "portfolio metrics",
)

CUSTOMER_SEARCH_SYNONYMS = (
    "find customer",
    "search customer",
    "search for customer",
    "look up customer",
    "customer search",
    "find a customer",
    "search customers",
    "look up",
)

SEARCH_NAME_PATTERNS = (
    re.compile(r"find customer\s+(.+)", re.IGNORECASE),
    re.compile(r"search for customer\s+(.+)", re.IGNORECASE),
    re.compile(r"search customer\s+(.+)", re.IGNORECASE),
    re.compile(r"look up customer\s+(.+)", re.IGNORECASE),
    re.compile(r"search for\s+(.+)", re.IGNORECASE),
    re.compile(r"find\s+(.+)", re.IGNORECASE),
    re.compile(r"who is\s+(.+)", re.IGNORECASE),
)

SEARCH_NAME_BLOCKS = (
    "overdue",
    "past due",
    "delinquent",
    "late",
    "high risk",
    "collateral",
    "due today",
    "due tomorrow",
    "due this week",
    "due soon",
    "due next month",
    "the portfolio",
    "my portfolio",
    "the business",
)

SEARCH_GENERIC_NAMES = {
    "customer",
    "customers",
    "a customer",
    "client",
    "clients",
}

INTENT_PRIORITY = (
    CUSTOMER_LOANS,
    CUSTOMER_ACCOUNTS,
    CUSTOMER_SUMMARY,
    CUSTOMER_SEARCH,
    CUSTOMER_COUNT,
    LOAN_COUNT,
    ACCOUNT_COUNT,
    TOTAL_OVERDUE,
    PORTFOLIO_BALANCE,
    TODAYS_PRIORITIES,
    PORTFOLIO_SUMMARY,
    MISSED_PAYMENTS,
    OVERDUE_CUSTOMERS,
    HIGH_RISK_LOANS,
    COLLATERAL_RISK,
    DUE_TODAY,
    DUE_TOMORROW,
    DUE_THIS_WEEK,
    DUE_SOON,
)

INTENT_TO_ACTION = {
    TODAYS_PRIORITIES: "today_priorities",
    OVERDUE_CUSTOMERS: "overdue_customers",
    HIGH_RISK_LOANS: "high_risk_loans",
    COLLATERAL_RISK: "collateral_at_risk",
    CUSTOMER_SUMMARY: "customer_summary",
    CUSTOMER_ACCOUNTS: "customer_accounts",
    CUSTOMER_LOANS: "customer_loans",
    DUE_TODAY: "due_today_customers",
    DUE_TOMORROW: "due_tomorrow_customers",
    DUE_THIS_WEEK: "due_this_week_customers",
    DUE_SOON: "due_soon_customers",
    MISSED_PAYMENTS: "missed_payments",
    CUSTOMER_COUNT: "customer_count",
    LOAN_COUNT: "loan_count",
    ACCOUNT_COUNT: "account_count",
    TOTAL_OVERDUE: "total_overdue",
    PORTFOLIO_BALANCE: "portfolio_balance",
    CUSTOMER_SEARCH: "customer_search",
    PORTFOLIO_SUMMARY: "portfolio_summary",
}

INTENT_TO_TOOL = {
    TODAYS_PRIORITIES: "get_today_priorities",
    OVERDUE_CUSTOMERS: "get_overdue_customers",
    HIGH_RISK_LOANS: "get_high_risk_loans",
    COLLATERAL_RISK: "get_collateral_at_risk",
    CUSTOMER_SUMMARY: (
        "get_customer_accounts, get_customer_loans, "
        "get_customer_payments, get_customer_collateral"
    ),
    CUSTOMER_ACCOUNTS: "get_customer_accounts",
    CUSTOMER_LOANS: "get_customer_loans",
    DUE_TODAY: "get_due_today_customers",
    DUE_TOMORROW: "get_due_tomorrow_customers",
    DUE_THIS_WEEK: "get_due_this_week_customers",
    DUE_SOON: "get_due_soon_customers",
    MISSED_PAYMENTS: "get_missed_payments",
    CUSTOMER_COUNT: "get_customer_count",
    LOAN_COUNT: "get_loan_count",
    ACCOUNT_COUNT: "get_account_count",
    TOTAL_OVERDUE: "get_total_overdue_amount",
    PORTFOLIO_BALANCE: "get_total_portfolio_balance",
    CUSTOMER_SEARCH: "search_customers",
    PORTFOLIO_SUMMARY: "get_portfolio_summary",
    UNKNOWN: "(none)",
}

CUSTOMER_ID_PATTERN = re.compile(
    r"customer\s*(?:id\s*)?#?\s*(\d+)",
    re.IGNORECASE,
)

CUSTOMER_NAME_PATTERNS = (
    re.compile(r"how much money does\s+(.+?)\s+have", re.IGNORECASE),
    re.compile(r"tell me about\s+(.+?)[\.\?]?$", re.IGNORECASE),
    re.compile(r"give me a customer overview(?:\s+(?:for|of)\s+(.+?))?[\.\?]?$", re.IGNORECASE),
    re.compile(r"prepare me for a call with\s+(.+?)[\.\?]?$", re.IGNORECASE),
    re.compile(r"(?:what(?:'s| is)|show)\s+(.+?)'s loan(?:\s+status)?", re.IGNORECASE),
    re.compile(r"(?:what(?:'s| is)|show)\s+(.+?)'s (?:checking|account)(?:\s+balance)?", re.IGNORECASE),
)

RESERVED_CUSTOMER_NAMES = {
    "priorities",
    "priority",
    "today",
    "today's priorities",
    "today priorities",
    "due today",
    "due tomorrow",
    "due this week",
    "due soon",
    "due next month",
}


def is_payment_due_phrase(text: str) -> bool:
    normalized = _normalize(text)
    if not normalized:
        return False
    if normalized in PAYMENT_DUE_LITERAL_PHRASES:
        return True
    return _contains_any(normalized, PAYMENT_DUE_PHRASES)


def is_payment_due_query(text: str) -> bool:
    normalized = _normalize(text)
    if is_payment_due_phrase(normalized):
        return True
    return (
        _score_phrases(normalized, DUE_TODAY_PHRASES, score=1.0) > 0
        or _score_phrases(normalized, DUE_TOMORROW_PHRASES, score=1.0) > 0
        or _score_phrases(normalized, DUE_THIS_WEEK_PHRASES, score=1.0) > 0
        or _score_phrases(normalized, DUE_SOON_PHRASES, score=1.0) > 0
        or _matches_any(normalized, DUE_TODAY_PATTERNS)
        or _matches_any(normalized, DUE_TOMORROW_PATTERNS)
        or _matches_any(normalized, DUE_THIS_WEEK_PATTERNS)
        or _matches_any(normalized, DUE_SOON_PATTERNS)
    )


def payment_due_tool_for_phrase(text: str) -> str | None:
    normalized = _normalize(text)
    if (
        _score_phrases(normalized, DUE_TODAY_PHRASES, score=1.0) > 0
        or _matches_any(normalized, DUE_TODAY_PATTERNS)
    ):
        return "get_due_today_customers"
    if (
        _score_phrases(normalized, DUE_TOMORROW_PHRASES, score=1.0) > 0
        or _matches_any(normalized, DUE_TOMORROW_PATTERNS)
    ):
        return "get_due_tomorrow_customers"
    if (
        _score_phrases(normalized, DUE_THIS_WEEK_PHRASES, score=1.0) > 0
        or _matches_any(normalized, DUE_THIS_WEEK_PATTERNS)
    ):
        return "get_due_this_week_customers"
    if (
        _score_phrases(normalized, DUE_SOON_PHRASES, score=1.0) > 0
        or _matches_any(normalized, DUE_SOON_PATTERNS)
        or normalized == "due soon"
    ):
        return "get_due_soon_customers"
    return None

BLOCKS_TODAYS_PRIORITIES = (
    "overdue",
    "past due",
    "missed payment",
    "collateral",
    "forfeiture",
    "high risk",
    "high ltv",
    "high-risk",
    "riskiest",
    "loan balance",
    "loan status",
    "account balance",
    "checking balance",
    "summarize customer",
    "tell me about customer",
    "customer summary",
    "how much money",
    "how much does customer",
    "who owes",
    "behind on payment",
)


@dataclass
class IntentClassification:
    intent: str
    confidence: float
    action: str | None = None
    tool: str | None = None
    args: dict = field(default_factory=dict)
    customer_id: int | None = None
    customer_name: str | None = None

    @property
    def is_confident(self) -> bool:
        if self.intent == UNKNOWN:
            return False
        if self.confidence >= CONFIDENCE_THRESHOLD:
            return True
        return self.intent in OPERATIONAL_INTENTS and self.confidence > 0


def extract_customer_id(text: str) -> int | None:
    match = CUSTOMER_ID_PATTERN.search(text)
    if match:
        return int(match.group(1))
    return None


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower().strip())


def _contains_any(text: str, phrases: tuple[str, ...]) -> bool:
    return any(phrase in text for phrase in phrases)


def _matches_any(text: str, patterns: tuple) -> bool:
    return any(pattern.search(text) for pattern in patterns)


def _clean_name(name: str) -> str:
    cleaned = re.sub(r"\s+", " ", (name or "").strip(" .?!,"))
    if cleaned.lower().startswith("customer "):
        return ""
    return cleaned


def extract_customer_name(text: str) -> str | None:
    if is_payment_due_query(text):
        return None
    for pattern in CUSTOMER_NAME_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        group = match.group(1) if match.lastindex else None
        if not group:
            continue
        name = _clean_name(group)
        if name and not name.isdigit() and not is_payment_due_phrase(name):
            return name
    return None


def extract_search_name(text: str) -> str | None:
    if is_payment_due_query(text):
        return None
    for pattern in SEARCH_NAME_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        name = _clean_name(match.group(1))
        if not name or name.isdigit():
            continue
        lowered = name.lower()
        if lowered in RESERVED_CUSTOMER_NAMES or lowered in SEARCH_GENERIC_NAMES:
            continue
        if any(block in lowered for block in SEARCH_NAME_BLOCKS):
            continue
        if is_payment_due_phrase(name):
            continue
        return name
    return None


def _is_ambiguous(text: str) -> bool:
    if not text:
        return True
    if text in AMBIGUOUS_PHRASES:
        return True
    for phrase in AMBIGUOUS_PHRASES:
        if text == phrase or text.startswith(phrase + " "):
            return True
    words = text.split()
    if len(words) <= 2 and text in {"help", "help me", "details", "more"}:
        return True
    return False


def _blocked_from_todays_priorities(text: str) -> bool:
    return any(block in text for block in BLOCKS_TODAYS_PRIORITIES)


def _score_synonyms(
    text: str,
    synonyms: tuple[str, ...],
    *,
    context_words: tuple[str, ...] = (),
    require_context: bool = False,
) -> float:
    hits = sum(1 for synonym in synonyms if synonym in text)
    if hits == 0:
        return 0.0

    has_context = not context_words or any(word in text for word in context_words)
    if require_context and not has_context:
        return 0.0

    if hits >= 2:
        return 0.88 if has_context else 0.72
    if hits == 1:
        return 0.78 if has_context else 0.62
    return 0.0


def _is_today_executive_summary_query(text: str) -> bool:
    if _contains_any(text, (
        "give me an operations summary",
        "give me today's operations summary",
        "give me today's portfolio summary",
        "give me todays portfolio summary",
        "today's portfolio summary",
        "todays portfolio summary",
        "operations summary",
    )):
        return True
    return "today" in text and "portfolio summary" in text


def _score_todays_priorities(text: str) -> float:
    if _blocked_from_todays_priorities(text):
        return 0.0
    return max(
        _score_phrases(text, TODAYS_PRIORITIES_EXECUTIVE_PHRASES, score=0.98),
        _score_phrases(text, TODAYS_PRIORITIES_PHRASES, score=0.97),
        _score_patterns(text, TODAYS_PRIORITIES_PATTERNS, score=0.95),
        _score_synonyms(
            text,
            TODAYS_PRIORITIES_SYNONYMS,
            context_words=TODAYS_PRIORITIES_CONTEXT,
            require_context=True,
        ),
    )


def _score_portfolio_summary_intent(text: str) -> float:
    if _is_today_executive_summary_query(text):
        return 0.0
    return max(
        _score_phrases(text, (
            "portfolio summary",
            "business overview",
            "portfolio snapshot",
            "portfolio overview",
            "how is the portfolio",
            "how is business",
            "branch overview",
            "portfolio health",
        )),
        _score_patterns(text, (
            re.compile(r"(?:portfolio|business).*(?:summary|overview|snapshot|health|metrics)", re.IGNORECASE),
            re.compile(r"how is (?:the )?(?:portfolio|business)", re.IGNORECASE),
        )),
        _score_synonyms(text, PORTFOLIO_SUMMARY_SYNONYMS),
    )


def _score_phrases(text: str, phrases: tuple[str, ...], score: float = 0.95) -> float:
    return score if _contains_any(text, phrases) else 0.0


def _score_patterns(text: str, patterns: tuple, score: float = 0.88) -> float:
    return score if _matches_any(text, patterns) else 0.0


def _pick_best(scores: dict[str, float]) -> tuple[str, float]:
    candidates = [(intent, score) for intent, score in scores.items() if score > 0]
    if not candidates:
        return UNKNOWN, 0.0

    best_score = max(score for _, score in candidates)
    top = [intent for intent, score in candidates if score == best_score]
    if len(top) == 1:
        return top[0], best_score

    top.sort(key=lambda intent: INTENT_PRIORITY.index(intent))
    return top[0], best_score


def _build_result(intent: str, confidence: float, text: str) -> IntentClassification:
    if is_payment_due_query(text):
        customer_id = None
        customer_name = None
    else:
        customer_id = extract_customer_id(text)
        customer_name = extract_customer_name(text)

    if customer_id and not customer_name:
        pass
    elif customer_name and not customer_id:
        pass
    elif customer_id:
        customer_name = None

    action = INTENT_TO_ACTION.get(intent)
    tool = INTENT_TO_TOOL.get(intent, "(none)")
    args: dict = {}

    if intent in {CUSTOMER_SUMMARY, CUSTOMER_ACCOUNTS, CUSTOMER_LOANS}:
        if customer_id:
            args["customer_id"] = customer_id
        elif customer_name:
            args["customer_name"] = customer_name
        if customer_id and intent == CUSTOMER_SUMMARY:
            tool = (
                "get_customer_accounts, get_customer_loans, "
                "get_customer_payments, get_customer_collateral"
            )

    if intent == CUSTOMER_SEARCH:
        search_name = extract_search_name(text) or customer_name
        if search_name and is_payment_due_phrase(search_name):
            search_name = None
            customer_name = None
        if search_name:
            args["name"] = search_name
            customer_name = search_name
        else:
            tool = "list_customers"

    if intent == UNKNOWN:
        action = None
        tool = "(none)"

    return IntentClassification(
        intent=intent,
        confidence=round(confidence, 2),
        action=action,
        tool=tool,
        args=args,
        customer_id=customer_id,
        customer_name=customer_name,
    )


def classify_intent(message: str) -> IntentClassification:
    text = _normalize(message)
    if not text or _is_ambiguous(text):
        return _build_result(UNKNOWN, 0.0, text)

    scores: dict[str, float] = {}

    scores[CUSTOMER_LOANS] = max(
        _score_phrases(text, (
            "what's priya nair's loan status",
            "show customer 5 loan details",
            "how much does customer 2 owe",
            "loan status",
            "loan details",
        )),
        _score_patterns(text, (
            re.compile(r"how much does customer\s+\d+\s+owe", re.IGNORECASE),
            re.compile(r"show customer\s+\d+\s+loan", re.IGNORECASE),
            re.compile(r"(?:what(?:'s| is)|show)\s+.+'s loan", re.IGNORECASE),
            re.compile(r"customer\s+\d+.*loan", re.IGNORECASE),
        )),
        _score_synonyms(text, CUSTOMER_LOANS_SYNONYMS),
    )
    if extract_customer_id(text) and any(word in text for word in ("loan", "owe", "owes", "ltv")):
        scores[CUSTOMER_LOANS] = max(scores[CUSTOMER_LOANS], 0.92)

    scores[CUSTOMER_ACCOUNTS] = max(
        _score_phrases(text, (
            "how much money does",
            "show account balances",
            "checking balance",
            "account balances",
        )),
        _score_patterns(text, (
            re.compile(r"how much money does\s+.+\s+have", re.IGNORECASE),
            re.compile(r"customer\s+\d+'s checking balance", re.IGNORECASE),
            re.compile(r"what(?:'s| is) customer\s+\d+'s checking", re.IGNORECASE),
            re.compile(r"show .+'s account", re.IGNORECASE),
        )),
        _score_synonyms(text, CUSTOMER_ACCOUNTS_SYNONYMS),
    )
    if extract_customer_id(text) and any(word in text for word in ("account", "checking", "savings", "balance", "money")):
        scores[CUSTOMER_ACCOUNTS] = max(scores[CUSTOMER_ACCOUNTS], 0.90)
    if "loan" in text:
        scores[CUSTOMER_ACCOUNTS] *= 0.5

    scores[CUSTOMER_SUMMARY] = max(
        _score_phrases(text, (
            "summarize customer",
            "customer summary",
            "customer overview",
            "customer details",
            "prepare me for a call with",
            "give me a customer overview",
        )),
        _score_patterns(text, (
            re.compile(r"tell me about customer\s+\d+", re.IGNORECASE),
            re.compile(r"tell me about\s+[a-z]", re.IGNORECASE),
            re.compile(r"summarize customer\s+\d+", re.IGNORECASE),
            re.compile(r"show customer\s+\d+\s+details", re.IGNORECASE),
        )),
        _score_synonyms(text, CUSTOMER_SUMMARY_SYNONYMS),
    )
    if extract_customer_id(text) and any(word in text for word in ("summarize", "summary", "about", "details", "overview")):
        scores[CUSTOMER_SUMMARY] = max(scores[CUSTOMER_SUMMARY], 0.94)
    if extract_customer_name(text) and any(word in text for word in ("tell me about", "overview", "prepare me for a call")):
        scores[CUSTOMER_SUMMARY] = max(scores[CUSTOMER_SUMMARY], 0.93)

    scores[OVERDUE_CUSTOMERS] = max(
        _score_phrases(text, (
            "who is overdue",
            "which customers are behind on payments",
            "show overdue accounts",
            "who owes us money",
            "overdue customers",
            "overdue accounts",
            "past due",
        )),
        _score_patterns(text, (
            re.compile(r"who\s+(?:is|'s)\s+overdue", re.IGNORECASE),
            re.compile(r"show\s+overdue", re.IGNORECASE),
            re.compile(r"behind on payments?", re.IGNORECASE),
        )),
        _score_synonyms(text, OVERDUE_SYNONYMS),
        0.95 if text in {"overdue", "late"} else 0.0,
    )

    scores[MISSED_PAYMENTS] = max(
        _score_phrases(text, (
            "missed payment",
            "missed payments",
            "who missed payments",
            "who missed payment",
        )),
        _score_patterns(text, (re.compile(r"missed payments?", re.IGNORECASE),)),
        _score_synonyms(text, MISSED_PAYMENT_SYNONYMS),
    )

    scores[HIGH_RISK_LOANS] = max(
        _score_phrases(text, (
            "which loans are highest risk",
            "show high ltv loans",
            "which customer is riskiest",
            "high risk loan",
            "high risk loans",
            "high ltv",
            "show high risk",
        )),
        _score_patterns(text, (
            re.compile(r"highest[\s-]?risk(?:\s+loan|\s+customer)?", re.IGNORECASE),
            re.compile(r"riskiest", re.IGNORECASE),
            re.compile(r"biggest risk(?!.*today)", re.IGNORECASE),
            re.compile(r"high[\s-]?ltv", re.IGNORECASE),
            re.compile(r"show\s+high[\s-]?risk", re.IGNORECASE),
        )),
        _score_synonyms(text, HIGH_RISK_SYNONYMS),
    )

    scores[COLLATERAL_RISK] = max(
        _score_phrases(text, (
            "collateral at risk",
            "collateral nearing forfeiture",
            "assets are nearing forfeiture",
            "collateral requiring follow-up",
            "pledged assets should i review",
            "show collateral nearing",
        )),
        _score_patterns(text, (
            re.compile(r"collateral.*(?:at risk|risk|forfeiture|follow[- ]?up)", re.IGNORECASE),
            re.compile(r"(?:assets|collateral).*forfeiture", re.IGNORECASE),
            re.compile(r"pledged assets", re.IGNORECASE),
        )),
        _score_synonyms(text, COLLATERAL_SYNONYMS),
    )

    scores[DUE_TODAY] = max(
        _score_phrases(text, DUE_TODAY_PHRASES, score=0.98),
        _score_patterns(text, DUE_TODAY_PATTERNS, score=0.96),
    )

    scores[DUE_TOMORROW] = max(
        _score_phrases(text, DUE_TOMORROW_PHRASES, score=0.98),
        _score_patterns(text, DUE_TOMORROW_PATTERNS, score=0.96),
    )

    scores[DUE_THIS_WEEK] = max(
        _score_phrases(text, DUE_THIS_WEEK_PHRASES, score=0.98),
        _score_patterns(text, DUE_THIS_WEEK_PATTERNS, score=0.96),
    )

    scores[DUE_SOON] = max(
        _score_phrases(text, DUE_SOON_PHRASES, score=0.98),
        _score_phrases(text, (
            "coming due",
            "near due",
        ), score=0.90),
        _score_patterns(text, DUE_SOON_PATTERNS, score=0.96),
        _score_synonyms(text, DUE_SOON_SYNONYMS),
    )

    if is_payment_due_query(text):
        scores[CUSTOMER_SEARCH] = 0.0

    scores[CUSTOMER_COUNT] = max(
        _score_phrases(text, (
            "how many customers",
            "customer count",
            "number of customers",
            "total customers",
            "customers on file",
        )),
        _score_synonyms(text, CUSTOMER_COUNT_SYNONYMS),
    )

    scores[LOAN_COUNT] = max(
        _score_phrases(text, (
            "how many loans",
            "loan count",
            "number of loans",
            "total loans",
            "active loans",
        )),
        _score_synonyms(text, LOAN_COUNT_SYNONYMS),
    )

    scores[ACCOUNT_COUNT] = max(
        _score_phrases(text, (
            "how many accounts",
            "account count",
            "number of accounts",
            "total accounts",
            "accounts on file",
        )),
        _score_synonyms(text, ACCOUNT_COUNT_SYNONYMS),
    )

    scores[TOTAL_OVERDUE] = max(
        _score_phrases(text, (
            "total overdue amount",
            "total overdue",
            "how much is overdue",
            "how much overdue",
            "overdue amount",
            "past due amount",
        )),
        _score_patterns(text, (
            re.compile(r"how much.*overdue", re.IGNORECASE),
            re.compile(r"total.*overdue", re.IGNORECASE),
        )),
        _score_synonyms(text, TOTAL_OVERDUE_SYNONYMS),
    )
    if "overdue" in text and any(word in text for word in ("total", "amount", "how much", "exposure")):
        scores[TOTAL_OVERDUE] = max(scores[TOTAL_OVERDUE], 0.94)

    scores[PORTFOLIO_BALANCE] = max(
        _score_phrases(text, (
            "total portfolio balance",
            "portfolio balance",
            "total loan balance",
            "combined balance",
            "outstanding balance",
        )),
        _score_patterns(text, (
            re.compile(r"total.*balance", re.IGNORECASE),
            re.compile(r"portfolio.*balance", re.IGNORECASE),
        )),
        _score_synonyms(text, PORTFOLIO_BALANCE_SYNONYMS),
    )
    if "balance" in text and "account" not in text and "customer" not in text:
        scores[PORTFOLIO_BALANCE] = max(scores[PORTFOLIO_BALANCE], 0.82)

    scores[PORTFOLIO_SUMMARY] = _score_portfolio_summary_intent(text)

    search_name = extract_search_name(text)
    scores[CUSTOMER_SEARCH] = max(
        _score_phrases(text, (
            "find customer",
            "search customer",
            "look up customer",
            "customer search",
            "search customers",
            "find a customer",
        )),
        _score_patterns(text, (
            re.compile(r"find customer\b", re.IGNORECASE),
            re.compile(r"search(?: for)? customer", re.IGNORECASE),
            re.compile(r"look up customer", re.IGNORECASE),
        )),
        _score_synonyms(text, CUSTOMER_SEARCH_SYNONYMS),
        0.95 if search_name else 0.0,
    )

    scores[TODAYS_PRIORITIES] = _score_todays_priorities(text)

    best_intent, best_score = _pick_best(scores)
    return _build_result(best_intent, best_score, text)


def is_today_priorities_intent(text: str) -> bool:
    result = classify_intent(text)
    return result.intent == TODAYS_PRIORITIES and result.is_confident


def is_customer_summary_intent(text: str) -> bool:
    result = classify_intent(text)
    return result.intent == CUSTOMER_SUMMARY and result.is_confident


def is_overdue_intent(text: str) -> bool:
    result = classify_intent(text)
    return result.intent == OVERDUE_CUSTOMERS and result.is_confident


def is_high_risk_intent(text: str) -> bool:
    result = classify_intent(text)
    return result.intent == HIGH_RISK_LOANS and result.is_confident


def is_collateral_at_risk_intent(text: str) -> bool:
    result = classify_intent(text)
    return result.intent == COLLATERAL_RISK and result.is_confident


def is_reserved_customer_name(name: str) -> bool:
    normalized = _normalize(name)
    if not normalized:
        return False
    if normalized in RESERVED_CUSTOMER_NAMES:
        return True
    if is_payment_due_phrase(normalized):
        return True
    return is_today_priorities_intent(normalized)


def detect_operational_action(message: str) -> dict | None:
    result = classify_intent(message)
    if not result.is_confident or not result.action:
        return None

    payload = {"action": result.action}
    if result.customer_id is not None:
        payload["customer_id"] = result.customer_id
    if result.customer_name:
        payload["customer_name"] = result.customer_name
    return payload


def describe_intent(classification: IntentClassification | dict | None) -> str:
    if classification is None:
        return UNKNOWN
    if isinstance(classification, IntentClassification):
        return classification.intent
    return classification.get("action", UNKNOWN)


def tool_for_classification(classification: IntentClassification) -> str:
    return classification.tool or "(none)"


def args_for_classification(classification: IntentClassification) -> dict:
    return dict(classification.args)


def detect_forced_action(message: str) -> dict | None:
    return detect_operational_action(message)


def detect_forced_tool(message: str) -> str | None:
    result = classify_intent(message)
    if result.intent == TODAYS_PRIORITIES and result.is_confident:
        return "get_today_priorities"
    return None
