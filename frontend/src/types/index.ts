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
