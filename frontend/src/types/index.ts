export type Actor = {
  user_id: string;
  display_name: string | null;
  principal_name: string | null;
  roles: string[];
  capabilities: string[];
};
export type RequestedItem = {
  item: string;
  category: string;
  required: boolean;
  evidence_quote: string;
};
export type Classification = {
  vendor: string | null;
  email_type: string;
  states: string[];
  license_types: string[];
  license_numbers: string[];
  action_required: boolean;
  requested_information: RequestedItem[];
  documents: {
    filename: string;
    document_type: string;
    relationship: string;
  }[];
  due_date: string | null;
  summary: string;
  proposed_action: string;
  suggested_destination: string;
  confidence: number;
  requires_human_review: boolean;
  review_reasons: string[];
};
export type Review = {
  id: string;
  classification_id: string;
  decision: string;
  reviewer_principal: string | null;
  claimed_at: string | null;
  claim_expires_at: string | null;
  revision: number;
  review_notes: string | null;
  reviewed_at: string | null;
};
export type ReviewItem = {
  review: Review;
  classification: Classification;
  classification_version: number;
  email_id: string;
  received_at: string | null;
  sender: string | null;
  subject: string | null;
  has_attachments: boolean;
};
export type ReviewDetail = ReviewItem & {
  current_message_body: string;
  quoted_history: string;
  rule_evidence: Record<string, unknown>[];
  previous_versions: number[];
};
export type Task = {
  id: string;
  title: string;
  queue: string;
  status: string;
  due_date: string | null;
  assigned_to: string | null;
  backup_assigned_to: string | null;
  priority: string;
  vendor: string | null;
  email_type: string | null;
  email_id: string | null;
  classification_id: string | null;
  review_id: string | null;
  draft_required: boolean;
  draft_status: string;
  communication_status?: string;
  destination_folder_name?: string | null;
  destination_folder_id?: string | null;
  created_at: string;
  updated_at: string;
  requested_items?: Array<{
    id: string;
    item_text: string;
    category: string;
    required: boolean;
    evidence_quote: string | null;
    status: string;
    owner: string | null;
  }>;
  comments?: Array<{
    id: string;
    body: string;
    comment_type: string;
    created_at: string;
  }>;
  events?: Array<{
    id: string;
    event_type: string;
    from_status: string | null;
    to_status: string | null;
    actor_id: string | null;
    metadata: Record<string, unknown>;
    occurred_at: string;
  }>;
};

export type ResponsePlan = {
  id: string;
  task_id: string;
  email_id: string;
  classification_id: string;
  response_type: string;
  response_required: boolean;
  readiness_status: string;
  readiness_blockers: string[];
  selected_template_version_id: string | null;
  recipient_mode: string;
  reply_all_reviewed: boolean;
  bcc_authorized: boolean;
  destination_folder_name: string | null;
  move_attempts?: MoveAttempt[];
  completion?: WorkflowCompletion | null;
};

export type OutboundDraft = {
  id: string;
  response_plan_id: string;
  task_id: string;
  email_id: string;
  subject: string;
  body_text: string | null;
  body_html: string | null;
  to_recipients: Array<{ address: string; name: string }>;
  cc_recipients: Array<{ address: string; name: string }>;
  bcc_recipients: Array<{ address: string; name: string }>;
  draft_status: string;
  local_revision: number;
  graph_draft_message_id: string | null;
  graph_change_key: string | null;
  graph_etag: string | null;
  approval_snapshot_sha256: string | null;
  pending_approval_snapshot_sha256: string | null;
  created_by_actor: string | null;
  last_edited_by_actor: string | null;
  delivery_status: string;
  created_at?: string;
  updated_at?: string;
  graph_draft_created_at?: string | null;
  graph_last_synced_at?: string | null;
  submitted_for_approval_at?: string | null;
  approved_at?: string | null;
  send_queued_at?: string | null;
  sent_at?: string | null;
  sender_mailbox?: string | null;
  recipient_domains?: string[];
  external_recipient_domains?: string[];
  validation_findings?: string[];
  attachments: Array<{
    id: string;
    filename: string;
    size_bytes: number;
    status: string;
    content_sha256?: string;
    document_id?: string | null;
    document_version_id: string | null;
    graph_attachment_id?: string | null;
    upload_method?: string | null;
    document_approval_status?: string | null;
    document_lifecycle_status?: string | null;
    document_confidentiality?: string | null;
    document_expiry_date?: string | null;
    document_storage_status?: string | null;
    is_current_version?: boolean;
  }>;
  response_plan?: ResponsePlan | null;
  template?: {
    id: string | null;
    name: string | null;
    version_id: string;
    version: number;
    status: string;
    template_sha256: string;
  } | null;
  task?: {
    id: string;
    title: string;
    status: string;
    owner: string | null;
    due_date: string | null;
    communication_status: string;
    destination_folder_name: string | null;
  } | null;
  requested_items?: Array<{
    id: string;
    item_text: string;
    category: string | null;
    required: boolean;
    status: string;
    evidence_quote: string | null;
    owner: string | null;
  }>;
  source_email?: {
    id: string;
    subject: string | null;
    sender_name: string | null;
    sender_email: string | null;
    received_at: string | null;
    body_text: string | null;
    body_html: string | null;
    processing_state: string;
    current_graph_folder_id: string | null;
    immutable_graph_message_id: string;
  } | null;
  reviewed_classification?: {
    id: string;
    version: number;
    vendor: string | null;
    email_type: string;
    states: string[];
    summary: string | null;
    proposed_action: string | null;
    review_status: string;
    reviewed_by_actor: string | null;
    reviewed_at: string | null;
  } | null;
  approvals?: SendApproval[];
  send_attempts?: SendAttempt[];
  move_attempts?: MoveAttempt[];
  completion?: WorkflowCompletion | null;
};

export type DraftVersion = {
  id: string;
  revision: number;
  subject: string;
  body_text: string | null;
  body_html: string | null;
  to_recipients: Array<{ address: string; name: string }>;
  cc_recipients: Array<{ address: string; name: string }>;
  bcc_recipients: Array<{ address: string; name: string }>;
  attachment_manifest: Array<{
    id: string;
    filename: string;
    size_bytes: number;
    status: string;
  }>;
  body_sha256: string;
  recipient_set_sha256: string;
  attachment_set_sha256: string;
  snapshot_sha256: string;
  change_reason: string | null;
  created_by_actor: string | null;
  created_at: string;
};

export type SendApproval = {
  id: string;
  decision: string;
  approver_actor: string;
  approval_snapshot_sha256: string;
  approval_notes: string | null;
  approved_at: string | null;
  created_at: string;
  invalidated_at: string | null;
  invalidation_reason: string | null;
};

export type SendAttempt = {
  id: string;
  attempt_number: number;
  status: string;
  http_status: number | null;
  started_at: string;
  accepted_at: string | null;
  sent_copy_verified_at: string | null;
  sent_graph_message_id: string | null;
  error_code: string | null;
};

export type MoveAttempt = {
  id: string;
  attempt_number: number;
  status: string;
  destination_folder_name: string;
  destination_folder_id: string;
  returned_graph_message_id: string | null;
  returned_parent_folder_id: string | null;
  started_at: string;
  verified_at: string | null;
  error_code: string | null;
};

export type WorkflowCompletion = {
  id: string;
  completion_type: string;
  communication_status: string;
  task_status_at_completion: string;
  destination_folder_name: string;
  final_graph_message_id: string;
  completed_at: string;
};

export type ControlledDocument = {
  id: string;
  current_version_id: string | null;
  canonical_title: string;
  current_filename: string;
  document_type: string;
  lifecycle_status: string;
  approval_status: string;
  confidentiality_level: string;
  jurisdiction: string | null;
  expiry_date: string | null;
  approved_for_reuse: boolean;
  size_bytes: number;
};

export type CommunicationTemplate = {
  id: string;
  template_key: string;
  name: string;
  response_type: string;
  is_active: boolean;
  active_version_id: string | null;
};

export type LegalEntity = {
  id: string;
  entity_key: string;
  legal_name: string;
  display_name: string | null;
  status: string;
  is_in_scope: boolean;
};

export type LicenseRecord = {
  id: string;
  license_key: string;
  legal_entity_id: string;
  jurisdiction_id: string;
  license_type_id: string;
  license_number: string | null;
  nmls_license_id: string | null;
  filing_channel: string;
  current_status: string;
  expiration_date: string | null;
  renewal_due_date: string | null;
  responsible_owner: string | null;
  source_confidence: string;
};

export type RequirementAssessment = {
  id: string;
  assessment_key: string;
  legal_entity_id: string;
  operating_profile_id: string;
  status: string;
  requested_jurisdictions: string[];
  created_at: string;
};

export type RequirementResult = {
  id: string;
  jurisdiction_id: string;
  outcome: string;
  filing_channels: string[];
  explanation: string;
  facts_used: Record<string, unknown>;
  missing_facts: unknown[];
  matched_rule_ids: string[];
  source_citations: Array<Record<string, unknown>>;
  source_freshness_status: string;
  requires_human_review: boolean;
  requires_counsel_review: boolean;
  reviewed_outcome: string | null;
};

export type ComplianceCase = {
  id: string;
  case_key: string;
  obligation_id: string;
  legal_entity_id: string;
  case_type: string;
  current_stage: string;
  status: string;
  priority: string;
  statutory_due_date: string | null;
  internal_target_date: string | null;
  assigned_owner: string | null;
  blocked_reason: string | null;
};

export type CalendarEntry = {
  deadline_id: string;
  obligation_id: string;
  compliance_case_id: string | null;
  legal_entity_id: string;
  jurisdiction_id: string | null;
  obligation_type: string;
  title: string;
  deadline_type: string;
  due_at: string;
  internal_target_at: string | null;
  status: string;
  severity: string;
  assigned_owner: string | null;
  escalation_level: string | null;
  is_statutory: boolean;
};

export type InformationValue = {
  id: string;
  information_definition_id: string;
  legal_entity_id: string | null;
  value_version: number;
  display_value_redacted: string | null;
  status: string;
  valid_to: string | null;
  owner_actor: string | null;
  last_used_at: string | null;
};

export type DashboardSummary = {
  licenses_total: number;
  licenses_active: number;
  licenses_expiring: Record<string, number>;
  obligations_overdue: number;
  cases_open: number;
  cases_blocked: number;
  cases_overdue: number;
  cases_by_stage: Record<string, number>;
  information_requests_open: number;
  information_values_stale: number;
  forms_waiting_signature: number;
  forms_waiting_information: number;
  packets_missing_items: number;
  sources_stale: number;
  source_changes_pending: number;
  assessments_counsel_review: number;
  advisory_notice: string;
};

export type PortalDefinition = {
  id: string;
  portal_key: string;
  name: string;
  portal_type: string;
  base_url: string;
  hostname: string;
  jurisdiction_id: string | null;
  supported_filing_types: string[];
  approved_automation_level: string;
  status: string;
  credential_model: string;
  mfa_model: string | null;
  captcha_expected: boolean;
  terms_review_required: boolean;
  terms_review_expires_at: string | null;
  final_submit_human_only: boolean;
  payment_human_only: boolean;
  attestation_human_only: boolean;
  signature_human_only: boolean;
  last_verified_at: string | null;
};

export type PortalRun = {
  id: string;
  run_key: string;
  portal_definition_id: string;
  compliance_case_id: string;
  legal_entity_id: string;
  license_id: string | null;
  form_instance_id: string | null;
  document_packet_id: string | null;
  filing_type: string;
  automation_level: string;
  status: string;
  current_stage: string;
  assigned_operator_id: string | null;
  assigned_signatory_id: string | null;
  assigned_payment_approver_id: string | null;
  deadline_at: string | null;
  last_error_code: string | null;
  last_error_message: string | null;
};

export type PortalBrowserSession = {
  id: string;
  portal_run_id: string;
  operator_user_id: string;
  session_status: string;
  browser_type: string;
  started_at: string;
  last_activity_at: string;
  expires_at: string;
  closed_at: string | null;
  close_reason: string | null;
};

export type PortalHandoff = {
  id: string;
  portal_run_id: string;
  browser_session_id: string | null;
  handoff_type: string;
  status: string;
  requested_from_user_id: string | null;
  requested_at: string;
  accepted_at: string | null;
  completed_at: string | null;
  result: string | null;
  operator_confirmation: string | null;
  evidence_reference: string | null;
  expires_at: string | null;
};

export type PortalRunField = {
  id: string;
  portal_field_key: string;
  label: string | null;
  approved_source_type: string | null;
  displayed_value_redacted: string | null;
  status: string;
  discrepancy_code: string | null;
};

export type PortalRunDocument = {
  id: string;
  document_id: string;
  document_version_id: string;
  expected_filename: string;
  expected_sha256: string;
  portal_document_category: string | null;
  status: string;
  portal_display_name: string | null;
  portal_size_bytes: number | null;
};

export type PreSubmissionSnapshot = {
  id: string;
  portal_run_id: string;
  version: number;
  field_manifest: Array<Record<string, unknown>>;
  document_manifest: Array<Record<string, unknown>>;
  portal_validation_messages: Array<Record<string, unknown>>;
  discrepancy_report: Array<Record<string, unknown>>;
  snapshot_sha256: string;
  status: string;
  created_by_actor: string | null;
  reviewed_by_actor: string | null;
  reviewed_at: string | null;
};

export type PortalPayment = {
  id: string;
  status: string;
  expected_fee_amount: string | null;
  currency: string | null;
  portal_fee_summary: Record<string, unknown> | null;
  payment_reference_redacted: string | null;
  receipt_document_id: string | null;
};

export type PortalAttestation = {
  id: string;
  portal_run_id: string;
  attestation_type: string;
  required_actor_id: string | null;
  status: string;
  attestation_text_fingerprint: string | null;
  displayed_text_reference: string | null;
  completed_by_actor: string | null;
  completed_at: string | null;
  evidence_reference: string | null;
};

export type PortalSubmissionEvidence = {
  id: string;
  evidence_type: string;
  confirmation_number: string | null;
  filing_reference: string | null;
  submission_status: string | null;
  submitted_by_actor: string | null;
  submitted_at: string | null;
  source_document_id: string | null;
  verified_at: string | null;
};
