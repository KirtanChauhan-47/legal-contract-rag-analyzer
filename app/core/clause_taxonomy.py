"""Fixed taxonomy of contract clause types this system detects and
analyzes. Internal keys are stable strings, stored as-is in
clause_analyses.clause_type and used as API identifiers -- do not rename
an existing key without a migration plan, since it's persisted data.
"""
import enum


class ClauseType(str, enum.Enum):
    CONFIDENTIALITY = "confidentiality"
    TERMINATION = "termination"
    GOVERNING_LAW = "governing_law"
    JURISDICTION = "jurisdiction"
    PAYMENT = "payment"
    LIMITATION_OF_LIABILITY = "limitation_of_liability"
    INDEMNIFICATION = "indemnification"
    NON_COMPETE = "non_compete"
    NON_SOLICITATION = "non_solicitation"
    INTELLECTUAL_PROPERTY = "intellectual_property"
    DISPUTE_RESOLUTION = "dispute_resolution"
    RENEWAL = "renewal"
    ASSIGNMENT = "assignment"
    FORCE_MAJEURE = "force_majeure"
    DATA_PROTECTION = "data_protection"
    NOTICES = "notices"
    WARRANTIES = "warranties"
    OBLIGATIONS = "obligations"
    EFFECTIVE_DATE = "effective_date"
    PARTIES = "parties"


class RiskLevel(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    UNKNOWN = "unknown"


VALID_RISK_LEVELS = {level.value for level in RiskLevel}

# Human-readable label + short description per clause type, used to build
# the LLM prompt (see app/prompts/clause_detection_prompt.py).
CLAUSE_INFO: dict[ClauseType, dict[str, str]] = {
    ClauseType.CONFIDENTIALITY: {
        "label": "Confidentiality",
        "description": "obligations to keep disclosed information secret and not share it with third parties",
    },
    ClauseType.TERMINATION: {
        "label": "Termination",
        "description": "how and when the agreement can be ended, notice periods, termination for cause/convenience",
    },
    ClauseType.GOVERNING_LAW: {
        "label": "Governing Law",
        "description": "which jurisdiction's substantive law governs interpretation of the agreement",
    },
    ClauseType.JURISDICTION: {
        "label": "Jurisdiction",
        "description": "which courts or venue have authority to hear disputes under the agreement",
    },
    ClauseType.PAYMENT: {
        "label": "Payment",
        "description": "fees, royalties, consideration, invoicing, payment timing, and permitted deductions",
    },
    ClauseType.LIMITATION_OF_LIABILITY: {
        "label": "Limitation of Liability",
        "description": "caps or exclusions on damages either party can be held liable for",
    },
    ClauseType.INDEMNIFICATION: {
        "label": "Indemnification",
        "description": "obligations to compensate or defend the other party against claims or losses",
    },
    ClauseType.NON_COMPETE: {
        "label": "Non-Compete",
        "description": "restrictions on competing with the other party or operating in a market",
    },
    ClauseType.NON_SOLICITATION: {
        "label": "Non-Solicitation",
        "description": "restrictions on soliciting the other party's employees or customers",
    },
    ClauseType.INTELLECTUAL_PROPERTY: {
        "label": "Intellectual Property",
        "description": "ownership, licensing, or assignment of intellectual property rights",
    },
    ClauseType.DISPUTE_RESOLUTION: {
        "label": "Dispute Resolution",
        "description": "arbitration, mediation, or litigation procedures for resolving disputes",
    },
    ClauseType.RENEWAL: {
        "label": "Renewal",
        "description": "automatic renewal, extension terms, or renewal notice requirements",
    },
    ClauseType.ASSIGNMENT: {
        "label": "Assignment",
        "description": "whether and how a party may assign or transfer the agreement",
    },
    ClauseType.FORCE_MAJEURE: {
        "label": "Force Majeure",
        "description": "excuse from performance due to events beyond a party's reasonable control",
    },
    ClauseType.DATA_PROTECTION: {
        "label": "Data Protection",
        "description": "handling of personal data, privacy obligations, and data security requirements",
    },
    ClauseType.NOTICES: {
        "label": "Notices",
        "description": "how formal notices under the agreement must be delivered",
    },
    ClauseType.WARRANTIES: {
        "label": "Warranties",
        "description": "representations and warranties made by the parties, or disclaimers of warranty",
    },
    ClauseType.OBLIGATIONS: {
        "label": "Obligations",
        "description": "core duties and responsibilities each party owes the other under the agreement",
    },
    ClauseType.EFFECTIVE_DATE: {
        "label": "Effective Date",
        "description": "when the agreement begins, its term/duration, and expiration",
    },
    ClauseType.PARTIES: {
        "label": "Parties",
        "description": "identification of the parties entering into the agreement",
    },
}

# One or more targeted search queries/aliases per clause type, used to
# retrieve candidate chunks before ever calling the LLM. More than one
# alias per clause guards against a single narrow query missing a clause
# that happens to be phrased differently in a given contract.
CLAUSE_SEARCH_QUERIES: dict[ClauseType, list[str]] = {
    ClauseType.CONFIDENTIALITY: ["confidentiality", "confidential information non-disclosure"],
    ClauseType.TERMINATION: ["termination", "terminate this agreement notice period"],
    ClauseType.GOVERNING_LAW: ["governing law", "laws of the state govern this agreement"],
    ClauseType.JURISDICTION: ["jurisdiction", "exclusive venue courts"],
    ClauseType.PAYMENT: ["payment", "royalty fees consideration net revenue deductions"],
    ClauseType.LIMITATION_OF_LIABILITY: ["limitation of liability", "liability cap consequential damages"],
    ClauseType.INDEMNIFICATION: ["indemnification", "indemnify defend hold harmless"],
    ClauseType.NON_COMPETE: ["non-compete", "non-competition restriction on competing"],
    ClauseType.NON_SOLICITATION: ["non-solicitation", "solicit employees or customers"],
    ClauseType.INTELLECTUAL_PROPERTY: ["intellectual property ownership", "IP rights license grant"],
    ClauseType.DISPUTE_RESOLUTION: ["dispute resolution", "arbitration mediation disputes"],
    ClauseType.RENEWAL: ["renewal", "automatic renewal term extension"],
    ClauseType.ASSIGNMENT: ["assignment", "assign this agreement without consent"],
    ClauseType.FORCE_MAJEURE: ["force majeure", "acts of god beyond reasonable control"],
    ClauseType.DATA_PROTECTION: ["data protection privacy", "personal data security"],
    ClauseType.NOTICES: ["notices", "notice shall be delivered in writing"],
    ClauseType.WARRANTIES: ["warranties representations", "disclaimer of warranties"],
    ClauseType.OBLIGATIONS: ["obligations of each party", "duties and responsibilities"],
    ClauseType.EFFECTIVE_DATE: ["effective date term", "commencement date duration expiration"],
    ClauseType.PARTIES: ["parties to this agreement", "entered into by and between"],
}
