"""Deterministic routing from reviewed document metadata."""

from app.documents.enums import DocumentType, DrivePurpose

_ROUTES: dict[DocumentType, DrivePurpose] = {
    DocumentType.ARTICLES_OF_INCORPORATION: DrivePurpose.MASTER_DOCUMENTS,
    DocumentType.CERTIFICATE_OF_GOOD_STANDING: DrivePurpose.MASTER_DOCUMENTS,
    DocumentType.FOREIGN_QUALIFICATION: DrivePurpose.MASTER_DOCUMENTS,
    DocumentType.REGISTERED_AGENT_DOCUMENT: DrivePurpose.MASTER_DOCUMENTS,
    DocumentType.OWNERSHIP_DISCLOSURE: DrivePurpose.MASTER_DOCUMENTS,
    DocumentType.OFFICER_INFORMATION: DrivePurpose.MASTER_DOCUMENTS,
    DocumentType.CALL_RECORDING_POLICY: DrivePurpose.MASTER_DOCUMENTS,
    DocumentType.PRIVACY_POLICY: DrivePurpose.MASTER_DOCUMENTS,
    DocumentType.COMPLAINT_POLICY: DrivePurpose.MASTER_DOCUMENTS,
    DocumentType.SURETY_BOND: DrivePurpose.BONDS,
    DocumentType.BOND_RIDER: DrivePurpose.BONDS,
    DocumentType.BOND_CONTINUATION: DrivePurpose.BONDS,
    DocumentType.RENEWAL_APPLICATION: DrivePurpose.SUBMITTED_FILINGS,
    DocumentType.INITIAL_APPLICATION: DrivePurpose.SUBMITTED_FILINGS,
    DocumentType.ANNUAL_REPORT: DrivePurpose.SUBMITTED_FILINGS,
    DocumentType.PROOF_OF_SUBMISSION: DrivePurpose.SUBMITTED_FILINGS,
    DocumentType.SUBMISSION_RECEIPT: DrivePurpose.SUBMITTED_FILINGS,
    DocumentType.ISSUED_LICENSE: DrivePurpose.LICENSES_CERTIFICATES,
    DocumentType.LICENSE_CERTIFICATE: DrivePurpose.LICENSES_CERTIFICATES,
    DocumentType.COLLECTION_AGENCY_LICENSE: DrivePurpose.LICENSES_CERTIFICATES,
    DocumentType.DEBT_COLLECTION_LICENSE: DrivePurpose.LICENSES_CERTIFICATES,
    DocumentType.BUSINESS_LICENSE: DrivePurpose.LICENSES_CERTIFICATES,
    DocumentType.REGULATOR_NOTICE: DrivePurpose.REGULATOR_CORRESPONDENCE,
    DocumentType.DEFICIENCY_NOTICE: DrivePurpose.REGULATOR_CORRESPONDENCE,
    DocumentType.INFORMATION_REQUEST: DrivePurpose.REGULATOR_CORRESPONDENCE,
    DocumentType.INFORMATION_RESPONSE: DrivePurpose.REGULATOR_CORRESPONDENCE,
    DocumentType.INVOICE: DrivePurpose.PAYMENTS_RECEIPTS,
    DocumentType.PAYMENT_RECEIPT: DrivePurpose.PAYMENTS_RECEIPTS,
    DocumentType.OFFICIAL_FORM: DrivePurpose.OFFICIAL_FORMS_CHECKLISTS,
    DocumentType.STATE_CHECKLIST: DrivePurpose.OFFICIAL_FORMS_CHECKLISTS,
}


def route_document(document_type: str, *, quarantine: bool = False) -> DrivePurpose:
    if quarantine:
        return DrivePurpose.QUARANTINE
    try:
        kind = DocumentType(document_type)
    except ValueError:
        return DrivePurpose.WORKING_DOCUMENTS
    return _ROUTES.get(kind, DrivePurpose.WORKING_DOCUMENTS)
