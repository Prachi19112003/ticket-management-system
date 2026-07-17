import re
from app.models.ticket import Ticket

class GuardrailService:
    def __init__(self) -> None:
        # Regexes for flagging commitments
        self.rules = [
            {
                "type": "time_commitment",
                "pattern": re.compile(
                    r"\b(?:within|in|next|for|under|at\s+most|less\s+than)\b\s*(?:the\s*)?\b(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s*(?:business\s*)?(?:hour|day|week|month)s?\b",
                    re.IGNORECASE
                ),
                "reason": "Specific time promise found in draft but not in source or references."
            },
            {
                "type": "refund_commitment",
                "pattern": re.compile(
                    r"\b(?:refund|reimburse|reimbursement)\b\s*(?:of\s*)?\b\$?\d+(?:\.\d{2})?(?:%)?\b|\b\$?\d+(?:\.\d{2})?(?:%)?\s*(?:refund|reimbursement)\b",
                    re.IGNORECASE
                ),
                "reason": "Refund or reimbursement commitment found in draft but not in source or references."
            },
            {
                "type": "discount_commitment",
                "pattern": re.compile(
                    r"\b(?:\d+%\s*(?:off|discount)?|discount\s+of\s+\d+%)\b",
                    re.IGNORECASE
                ),
                "reason": "Discount promise found in draft but not in source or references."
            },
            {
                "type": "guarantee_commitment",
                "pattern": re.compile(
                    r"\b(?:guarante[esd]{1,3}\b|guaranteeing\b|by\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|tomorrow|tonight))\b",
                    re.IGNORECASE
                ),
                "reason": "Guarantee promise or deadline found in draft but not in source or references."
            },
            {
                "type": "unauthorized_price_quote",
                "pattern": re.compile(
                    r"(?:\b|\B)\$\s*\d+(?:\,\d{3})*(?:\.\d{2})?\b|\b\d+(?:\,\d{3})*(?:\.\d{2})?\s*(?:dollars|usd)\b",
                    re.IGNORECASE
                ),
                "reason": "Specific pricing/dollar quote found in draft but not in source or references."
            }
        ]

    def scan_draft(self, ticket: Ticket, retrieved_references: list = None) -> list[dict]:
        """
        Scans a ticket's draft reply for commitments and malformed state.
        Returns:
            list[dict]: A list of flag objects: [{"type": str, "matched_text": str, "reason": str}]
        """
        flags = []
        
        draft_json = ticket.draft_json or {}
        if not isinstance(draft_json, dict):
            flags.append({
                "type": "malformed_json",
                "matched_text": "",
                "reason": "Draft JSON is not a dictionary/JSON object."
            })
            return flags

        # Check required fields
        required_fields = ["draft_reply", "category_confirmation", "cc_list", "confidence_score"]
        missing = [f for f in required_fields if f not in draft_json]
        if missing:
            flags.append({
                "type": "incomplete_json",
                "matched_text": "",
                "reason": f"Draft is missing required schema fields: {', '.join(missing)}"
            })
            return flags

        draft_reply = draft_json.get("draft_reply", "")
        if not isinstance(draft_reply, str):
            flags.append({
                "type": "malformed_json",
                "matched_text": "",
                "reason": "draft_reply is not a string."
            })
            return flags

        # Build authorization context string (all text from source ticket and references)
        auth_parts = []
        if ticket.raw_subject:
            auth_parts.append(ticket.raw_subject)
        if ticket.cleaned_body:
            auth_parts.append(ticket.cleaned_body)
            
        if retrieved_references:
            for ref in retrieved_references:
                if isinstance(ref, dict):
                    auth_parts.append(ref.get("subject") or "")
                    auth_parts.append(ref.get("cleaned_body") or "")
                    auth_parts.append(ref.get("resolution") or "")
                else:
                    auth_parts.append(getattr(ref, "raw_subject", "") or getattr(ref, "subject", "") or "")
                    auth_parts.append(getattr(ref, "cleaned_body", "") or "")
                    draft_data = getattr(ref, "draft_json", None) or {}
                    res = draft_data.get("draft_reply", "") if isinstance(draft_data, dict) else ""
                    auth_parts.append(res or getattr(ref, "resolution", "") or "")
        
        auth_context = " ".join(auth_parts).lower()

        # Run regex scans
        for rule in self.rules:
            matches = rule["pattern"].finditer(draft_reply)
            for m in matches:
                matched_text = m.group(0)
                # Check if matched text is explicitly present in the auth context
                if matched_text.lower() not in auth_context:
                    flags.append({
                        "type": rule["type"],
                        "matched_text": matched_text,
                        "reason": rule["reason"]
                    })
                    
        return flags
