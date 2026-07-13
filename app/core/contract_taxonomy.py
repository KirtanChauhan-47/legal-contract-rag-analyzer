"""Fixed taxonomy of contract types this system can classify a document
as. Internal keys are stable strings, stored as-is in
contract_summaries.contract_type -- do not rename an existing key without
a migration plan, since it's persisted data."""
import enum


class ContractType(str, enum.Enum):
    NDA = "nda"
    EMPLOYMENT = "employment"
    SERVICE = "service"
    CONSULTING = "consulting"
    VENDOR = "vendor"
    LEASE = "lease"
    LICENSING = "licensing"
    PARTNERSHIP = "partnership"
    PURCHASE = "purchase"
    GENERAL_BUSINESS = "general_business"


VALID_CONTRACT_TYPES = {contract_type.value for contract_type in ContractType}
