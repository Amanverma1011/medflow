"""Feedback classifier: sentiment, category, urgency and theme.

ponytail: a transparent lexicon model, not a trained one. It is deterministic and
explainable, which suits a demo; swap `classify` for an LLM or fine-tuned
classifier when real, messier feedback needs it.
"""
import re
from dataclasses import dataclass

CATEGORY_TERMS = {
    "waiting_time": r"wait|waited|queue|delay|late|long time|hours|slow|took forever|on time|quick|prompt",
    "staff_behavior": r"staff|nurse|receptionist|rude|polite|friendly|helpful|attitude|courteous|dismissive|kind",
    "doctor_communication": r"doctor|dr\.|explain|listened|listen|rushed|consult|answered|questions|bedside",
    "billing": r"bill|billing|charge|invoice|payment|insurance|cost|refund|overcharg|price",
    "cleanliness": r"clean|dirty|hygien|smell|toilet|washroom|restroom|spotless|dust|stain|tidy",
    "appointment": r"appointment|booking|book|reschedul|cancel|slot|reminder|schedul",
    "facilities": r"parking|wheelchair|lift|elevator|seating|chairs|air ?condition|cafeteria|signage|wifi|room",
    "pharmacy": r"pharmac|prescription|medicine counter|dispens|out of stock",
    "emergency_care": r"emergency|\ber\b|\bed\b|triage|ambulance|casualty|urgent",
}
POSITIVE = r"excellent|great|good|wonderful|amazing|kind|friendly|helpful|quick|prompt|clean|spotless|thank|" \
           r"professional|caring|smooth|easy|comfortable|listened|clear|polite|courteous|impressed|on time|efficient"
NEGATIVE = r"bad|poor|terrible|awful|rude|dirty|slow|long|late|delay|unhelpful|confus|rushed|ignored|never|" \
           r"worst|unacceptable|disappoint|frustrat|overcharg|wrong|dismissive|no one|nobody|forever|extremely|filthy"
URGENT = r"unsafe|danger|negligen|wrong (medication|medicine|dose)|infection|fell|fall|injur|bleeding|unattended|" \
         r"in pain for|collapsed|ignored .{0,20}(pain|emergency)|allergic|lawsuit|legal"
THEMES = {
    "waiting_time": "{dept} congestion and long waits",
    "staff_behavior": "Staff conduct in {dept}",
    "doctor_communication": "Doctor communication in {dept}",
    "billing": "Billing clarity and charges",
    "cleanliness": "Cleanliness of {dept} areas",
    "appointment": "Appointment scheduling experience",
    "facilities": "Facilities and amenities",
    "pharmacy": "Pharmacy wait and stock",
    "emergency_care": "Emergency department care experience",
    "general": "General experience",
}


@dataclass(frozen=True)
class FeedbackLabel:
    sentiment: str
    category: str
    urgency: str
    theme: str


def _count(pattern: str, text: str) -> int:
    return len(re.findall(pattern, text))


def classify(comment: str, overall: int, department: str = "") -> FeedbackLabel:
    text = comment.lower()
    pos, neg = _count(POSITIVE, text), _count(NEGATIVE, text)
    # The star rating anchors sentiment; the words can move it one step.
    score = (overall - 3) + 0.75 * (pos - neg)
    sentiment = "positive" if score >= 1 else "negative" if score <= -1 else "neutral"

    hits = {c: _count(p, text) for c, p in CATEGORY_TERMS.items()}
    category = max(hits, key=hits.get) if any(hits.values()) else "general"
    # "Emergency" names the place more often than the problem: prefer a more specific complaint.
    if category == "emergency_care":
        others = {c: n for c, n in hits.items() if c != "emergency_care" and n}
        if others:
            category = max(others, key=others.get)

    if re.search(URGENT, text):
        urgency = "high"
    elif sentiment == "negative":
        urgency = "high" if overall == 1 and neg >= 3 else "medium"
    else:
        urgency = "low"

    dept = f"{department} department" if department else "Hospital"
    theme = THEMES[category].format(dept=dept)
    return FeedbackLabel(sentiment, category, urgency, theme[0].upper() + theme[1:])
