"""Medical safety layer: classify the question before retrieval, validate the answer after generation.

Deliberately rule-based. Safety decisions must be deterministic, auditable and
must not depend on an LLM being available or behaving.
"""
import re
from dataclasses import dataclass

DISCLAIMER = ("This AI assistant provides general medical information and is not a substitute for professional "
              "medical advice, diagnosis, or treatment.")
EMERGENCY_NOTICE = ("If you believe you are experiencing a medical emergency, contact your local emergency service "
                    "or seek immediate medical attention.")

CATEGORIES = ("GENERAL_INFORMATION", "SYMPTOM_INFORMATION", "MEDICATION_INFORMATION", "EMERGENCY",
              "DIAGNOSIS_REQUEST", "TREATMENT_REQUEST", "SELF_HARM", "HIGH_RISK", "HOSPITAL_NAVIGATION",
              "OUT_OF_SCOPE")

_SELF_HARM = re.compile(
    r"kill myself|suicid|end my life|want to die|self[- ]?harm|hurt myself|harm myself|take my own life|"
    r"don'?t want to (live|be alive)|better off dead")
_EMERGENCY = re.compile(
    r"chest (pain|tightness|pressure)|(difficulty|trouble|hard|struggling|unable|can'?t|cannot) (to )?breath|"
    r"short(ness)? of breath|not breathing|stopped breathing|\bstroke\b|face (is )?droop|slurred speech|"
    r"unconscious|passed out|unresponsive|seizure|severe bleeding|bleeding (heavily|a lot|won'?t stop)|"
    r"(coughing|vomiting|throwing) up blood|overdos|anaphyla|throat (is )?(closing|swelling)|heart attack|"
    r"choking|severe (allergic|burn|head injury|abdominal pain)|poison|"
    r"sudden (numbness|weakness|vision loss|confusion)|worst headache")
_PERSONAL = re.compile(
    r"\b(i am|i'm|im|i have|i've|i feel|i got|i think i|i can'?t|i cannot|me\b|my (chest|heart|head|arm|face|"
    r"husband|wife|partner|mother|mom|father|dad|son|daughter|child|baby|friend)|(he|she|someone|they) (is|are|has|"
    r"just)|is having|right now|having)")
_INFORMATIONAL = re.compile(r"^(what|which|how|why|when|explain|define|describe|tell me about|can you explain|"
                            r"is|are|does|do)\b")
_HIGH_RISK = re.compile(
    r"\b(double|triple|increase|raise|up|lower|reduce|decrease|cut|halve|skip|stop|quit|change|adjust)\w*"
    r"( taking)?( my| the| a| this| his| her)?( \w+)? (dose|doses|dosage|medication|medications|medicine|meds|"
    r"pills?|tablets?|insulin|blood thinners?|antibiotics?)\b|extra dose|more than (the )?prescribed|"
    r"(mix|combine)\w* .{0,30}(alcohol|medication|pills)")
_DIAGNOSIS = re.compile(
    r"\bdo (i|you think i) have\b|\bam i (diabetic|pregnant|sick|dying|having)|"
    r"\bis (it|this) (cancer|serious|a tumou?r|an infection|diabetes|normal)|diagnose (me|my)|"
    r"what('s| is) wrong with me|what (disease|condition|illness) do i have|\b(could|might) i have\b|"
    r"\bdoes (this|that) mean i have\b")
_TREATMENT = re.compile(
    r"treatment plan|how (do|should|can) i (treat|cure|fix)|what should i take|"
    r"(which|what) (medicine|medication|drug|antibiotic)s? (should|can|do) i|\b(cure|treat) my\b|"
    r"treatment for my|prescribe")
_NAVIGATION = re.compile(
    r"where (is|are|can i find|do i go)|where's|how (do|can) i (book|schedule|cancel|reschedule|get to|register|"
    r"pay|check in)|visiting hours|visitors?\b|parking|admission|admitted|billing|insurance|cafeteria|"
    r"opening hours|what time does|contact number|phone number|directions|which floor|documents? do i need|"
    r"book an appointment|wi-?fi|medical records? request|lost (and|&) found")
_MEDICATION = re.compile(
    r"medication|medicine|\bdrugs?\b|tablet|\bpills?\b|\bdos(e|age)\b|side effect|antibiotic|insulin|metformin|"
    r"aspirin|ibuprofen|paracetamol|acetaminophen|statin|inhaler|vaccine|blood thinner|warfarin|anticoagulant")
_SYMPTOM = re.compile(
    r"symptom|\bpain|ache|fever|cough|nausea|dizz|rash|swelling|swollen|fatigue|tired|vomit|headache|bleeding|"
    r"\bsore|itch|numb|breath|palpitation|cramp")
_HEALTH = re.compile(
    r"health|medical|medic|doctor|nurse|hospital|clinic|patient|blood|pressure|heart|sugar|diabet|hypertens|"
    r"cholesterol|test|scan|mri|x-?ray|ct\b|ultrasound|surgery|vaccin|infection|disease|condition|diet|exercise|"
    r"sleep|pregnan|cancer|asthma|allerg|treat|therapy|diagnos|appointment|discharge|ward|emergency|urgent|"
    r"hba1c|lab|fasting|wound|stroke|kidney|liver|lung|mental|anxiety|depress|hygiene|hand ?wash")


@dataclass(frozen=True)
class SafetyResult:
    category: str
    personal: bool = False  # the user is asking about their own situation
    health_related: bool = True

    @property
    def canned(self) -> str | None:
        return CANNED.get(self.category)

    @property
    def strict(self) -> bool:
        return self.category in {"EMERGENCY", "SELF_HARM", "HIGH_RISK", "DIAGNOSIS_REQUEST", "TREATMENT_REQUEST"}


CANNED = {
    "EMERGENCY": (
        "**This may be a medical emergency.**\n\n"
        "The symptoms you describe can be signs of a serious condition that needs to be assessed in person, "
        "right away.\n\n"
        "**Please seek immediate medical attention or contact your local emergency service now.** "
        "If you are at the hospital, go to the Emergency Department or alert the nearest member of staff.\n\n"
        "Do not rely on this chatbot to assess an emergency."),
    "SELF_HARM": (
        "I'm really sorry you're going through this. You don't have to face it alone, and you deserve support "
        "right now.\n\n"
        "**If you are in immediate danger or might act on these thoughts, please contact your local emergency "
        "service now, or go to the nearest Emergency Department.**\n\n"
        "If you can, reach out to someone you trust and stay with them, or call a local crisis helpline to talk "
        "with a trained listener. When you feel able, a doctor or mental health professional can help you find "
        "the right support.\n\n"
        "I'm an AI assistant and can't provide crisis care, but I didn't want to leave your message unanswered."),
}

PREFIX = {
    "HIGH_RISK": (
        "**I can't advise you to change, skip, stop or double a medication dose.** Changing a dose without "
        "guidance can be dangerous.\n\n"
        "Please keep to your prescribed dose and speak to your prescribing doctor or a pharmacist before making "
        "any change. If you have taken more than prescribed, or you feel unwell, seek urgent medical care."),
    "DIAGNOSIS_REQUEST": (
        "**I can't diagnose you or tell you whether you have a condition.** Only a qualified clinician who can "
        "examine you and review your test results can do that."),
    "TREATMENT_REQUEST": (
        "**I can't recommend a treatment or prescribe medication for your situation.** Treatment decisions "
        "depend on your history, examination and test results, so they need to come from your doctor."),
}
GENERAL_INFO_BRIDGE = "Here is some general information from the hospital's approved resources:"
OUT_OF_SCOPE = ("I can only help with healthcare and hospital-related questions. Try asking about a condition, "
                "a test, a medication in general terms, or how to use the hospital's services.")
INSUFFICIENT = (
    "I couldn't find enough information in the hospital's approved knowledge base to answer that reliably.\n\n"
    "I can provide general information, but you should consult a qualified healthcare professional for advice "
    "specific to your situation.")
BOOKING_HINT = "You can book an appointment from the Appointments page, and I can help you prepare questions for it."


def classify(question: str) -> SafetyResult:
    q = question.lower().strip()
    personal = bool(_PERSONAL.search(q)) or bool(re.search(r"\b(my|i)\b", q))
    if _SELF_HARM.search(q):
        return SafetyResult("SELF_HARM", True)
    if _EMERGENCY.search(q) and (_PERSONAL.search(q) or not _INFORMATIONAL.match(q)):
        return SafetyResult("EMERGENCY", True)
    for category, pattern in (("HIGH_RISK", _HIGH_RISK), ("DIAGNOSIS_REQUEST", _DIAGNOSIS),
                              ("TREATMENT_REQUEST", _TREATMENT), ("HOSPITAL_NAVIGATION", _NAVIGATION),
                              ("MEDICATION_INFORMATION", _MEDICATION), ("SYMPTOM_INFORMATION", _SYMPTOM)):
        if pattern.search(q):
            return SafetyResult(category, personal)
    return SafetyResult("GENERAL_INFORMATION", personal, health_related=bool(_HEALTH.search(q)))


# --------------------------------------------------------------------------- output validation
_CONDITIONAL = re.compile(r"\b(if|when|whether|unless|once|while|because|means)\b[^.]{0,24}$")
_DIAGNOSIS_CLAIM = re.compile(r"\byou (definitely |probably |likely |clearly )?(have|are suffering from) "
                              r"(?!questions|any\b|a right|the right|an appointment|been|to\b|not\b|access|trouble)")
_DOSE_INSTRUCTION = re.compile(r"\b(take|increase|double|reduce|raise|lower)\b[^.\n]{0,40}\b\d+(\.\d+)?\s?"
                               r"(mg|mcg|µg|g|ml|units?|iu|tablets?|pills?|capsules?)\b", re.I)
_DOCTOR_CLAIM = re.compile(r"\b(i am|i'm) (a|your) (doctor|physician|nurse)|as (a|your) (doctor|physician)\b", re.I)
_CITATION = re.compile(r"\[(\d+)\]")


def validate_output(answer: str, n_sources: int) -> tuple[str, list[str]]:
    """Return (possibly amended answer, list of safety flags raised)."""
    flags: list[str] = []
    for m in _DIAGNOSIS_CLAIM.finditer(answer.lower()):
        if not _CONDITIONAL.search(answer.lower()[max(0, m.start() - 40): m.start()]):
            flags.append("diagnosis_claim")
            break
    if _DOSE_INSTRUCTION.search(answer):
        flags.append("dose_instruction")
    if _DOCTOR_CLAIM.search(answer):
        flags.append("claims_clinician")
    if flags:
        return ("I'm not able to give a safe answer to that. Please speak to a qualified healthcare professional "
                "about your specific situation."), flags
    # Citations that point at nothing are removed rather than shown.
    cleaned = _CITATION.sub(lambda m: m.group(0) if 1 <= int(m.group(1)) <= n_sources else "", answer)
    if cleaned != answer:
        flags.append("invalid_citation_removed")
    return cleaned, flags


def cited_indices(answer: str) -> list[int]:
    return sorted({int(n) for n in _CITATION.findall(answer)})
