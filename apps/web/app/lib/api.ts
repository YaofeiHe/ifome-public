export type ApiEnvelope<T> = {
  success: boolean;
  data: T;
  error?: string | null;
  trace_id?: string | null;
};

export type RenderedItemCard = {
  item_id: string;
  summary_one_line: string;
  company: string | null;
  role: string | null;
  city: string | null;
  location_note: string | null;
  ddl: string | null;
  interview_time: string | null;
  event_time: string | null;
  priority: "P0" | "P1" | "P2" | "P3" | null;
  content_category:
    | "job_posting"
    | "interview_notice"
    | "talk_event"
    | "referral"
    | "general_update"
    | "noise"
    | "unknown";
  source_type: "text" | "link" | "image" | null;
  workflow_status: string;
  source_ref: string | null;
  has_source_file: boolean;
  source_file_name: string | null;
  source_file_path: string | null;
  updated_at: string | null;
  message_time: string | null;
  generated_at: string | null;
  ai_score: number | null;
  insight_summary: string | null;
  advice: string | null;
  is_market_signal: boolean;
  market_group_kind: string | null;
  market_parent_item_id: string | null;
  market_child_item_ids: string[];
  market_child_previews: string[];
  job_group_kind: string | null;
  job_parent_item_id: string | null;
  job_child_item_ids: string[];
  job_child_previews: string[];
  tags: string[];
};

export type ReminderTask = {
  id: string;
  title: string;
  description: string | null;
  trigger_time: string;
  due_time: string | null;
  priority: "P0" | "P1" | "P2" | "P3";
  status: string;
};

export type IngestResult = {
  item_id: string | null;
  status: string;
  card: RenderedItemCard | null;
  reminder_count: number;
  model_routing: Record<string, string>;
};

export type AutoIngestResponse = {
  detected_input_kind: string;
  visited_links: string[];
  analysis_reasons: string[];
  results: IngestResult[];
};

export type UnifiedAttachmentResult = {
  display_name: string;
  source_ref: string;
  source_type: string;
  extraction_kind: string;
  text_length: number;
};

export type UnifiedIngestResponse = {
  detected_input_kind: string;
  visited_links: string[];
  analysis_reasons: string[];
  results: IngestResult[];
  attachments: UnifiedAttachmentResult[];
  resolved_local_paths: string[];
};

export type ItemListResponse = {
  items: RenderedItemCard[];
};

export type ReminderListResponse = {
  reminders: ReminderTask[];
};

export type MemoryResponse = {
  profile_memory: {
    target_roles: string[];
    priority_domains: string[];
    skills: string[];
    persona_keywords: string[];
    projects: {
      name: string;
      summary: string;
      role: string | null;
      tech_stack: string[];
      highlight_points: string[];
      interview_story_hooks: string[];
      source_file_name: string | null;
      source_file_path: string | null;
    }[];
    location_preferences: string[];
    soft_preferences: string[];
    excluded_companies: string[];
    summary: string | null;
    resume_snapshot:
      | {
          file_name: string | null;
          source_file_name: string | null;
          source_file_path: string | null;
          text: string;
          summary: string | null;
          structured_profile:
            | {
                headline: string | null;
                sections: {
                  title: string;
                  items: string[];
                }[];
              }
            | null;
          updated_at: string;
        }
      | null;
  } | null;
  career_state_memory: {
    watched_companies: string[];
    market_watch_sources: string[];
    market_article_fetch_limit: number;
    today_focus: string[];
    active_priorities: string[];
    notes: string | null;
    last_market_refresh_at: string | null;
  } | null;
};

export type RuntimeProviderSettingsPayload = {
  enabled: boolean;
  api_key: string | null;
  base_url: string | null;
  model: string | null;
  fallback_models: string[];
  request_timeout_seconds: number;
};

export type RuntimeOCRSettingsPayload = {
  enabled: boolean;
  provider_label: string;
  api_key: string | null;
  base_url: string | null;
  model: string | null;
  request_timeout_seconds: number;
};

export type SourceFileSettingsPayload = {
  max_age_days: number;
  max_total_size_mb: number;
  delete_when_item_deleted: boolean;
  filter_patterns: string[];
};

export type SourceFileCleanupReport = {
  trigger: string;
  scanned_file_count: number;
  deleted_file_count: number;
  reclaimed_bytes: number;
  remaining_bytes: number;
  deleted_orphan_file_count: number;
  deleted_due_to_age_count: number;
  deleted_due_to_size_count: number;
  deleted_due_to_filter_count: number;
  deleted_paths: string[];
};

export type RuntimeSettingsResponse = {
  llm: RuntimeProviderSettingsPayload;
  ocr: RuntimeOCRSettingsPayload;
  source_files: SourceFileSettingsPayload;
};

export type ChatQueryResponse = {
  answer: string;
  supporting_item_ids: string[];
  citations: {
    doc_id: string;
    item_id: string | null;
    source_label: string;
    snippet: string;
    score: number;
  }[];
  retrieval_mode: string;
  query_plan?: {
    intent: string;
    search_hints: string[];
    rewritten_query?: string | null;
    retrieval_queries?: string[];
    web_search_queries?: string[];
    profile_update_hints: string[];
    career_update_hints: string[];
    should_update_memory: boolean;
    needs_resume: boolean;
    recent_days: number;
  } | null;
  memory_update?: {
    applied: boolean;
    profile_fields: string[];
    career_fields: string[];
    notes: string[];
  } | null;
  attachments?: {
    display_name: string;
    source_ref: string;
    extraction_kind: string;
    attachment_kind: string;
    summary: string;
    persisted_to_profile: boolean;
    text_length: number;
    processing_error?: string | null;
  }[];
};

export type ChatSessionSummaryTurn = {
  mode: string;
  user_message: string;
  answer: string;
  strategy?: string | null;
};

export type ChatSessionSummaryResponse = {
  title: string;
  summary: string;
  keywords: string[];
  compressed_transcript: string;
  summary_source: string;
};

export type ItemDetailResponse = {
  item: {
    trace_id: string;
    source_ref: string | null;
    source_metadata: Record<string, unknown>;
    issues: {
      node_name: string;
      severity: string;
      message: string;
    }[];
    normalized_item: {
      raw_content: string;
      normalized_text: string;
      source_title: string | null;
    } | null;
    extracted_signal: {
      summary_one_line: string;
      company: string | null;
      role: string | null;
      city: string | null;
      location_note: string | null;
      ddl: string | null;
      interview_time: string | null;
      event_time: string | null;
      apply_url: string | null;
      confidence: number;
      tags: string[];
      evidence: {
        field_name: string;
        snippet: string;
        confidence: number;
      }[];
    } | null;
    reminder_tasks: {
      id: string;
      title: string;
      trigger_time: string;
      due_time: string | null;
      priority: "P0" | "P1" | "P2" | "P3";
    }[];
    render_card: RenderedItemCard | null;
  };
};

export type BatchDeleteItemsResponse = {
  deleted_item_ids: string[];
  missing_item_ids: string[];
};

export type DeleteItemResponse = {
  item_id: string;
  deleted_item_ids: string[];
};

export type BatchAnalyzeItemsResponse = {
  analysis: string;
  analyzed_item_ids: string[];
  missing_item_ids: string[];
  retrieval_mode: string;
};

export type MarketRefreshResponse = {
  refreshed: boolean;
  reason: string;
  refreshed_count: number;
  last_market_refresh_at: string | null;
  results: IngestResult[];
};

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

export async function apiRequest<T>(
  path: string,
  init?: RequestInit,
): Promise<ApiEnvelope<T>> {
  const isFormData = init?.body instanceof FormData;
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: isFormData
      ? init?.headers
      : {
          "Content-Type": "application/json",
          ...(init?.headers ?? {}),
        },
    cache: "no-store",
  });

  const payload = (await response.json()) as ApiEnvelope<T>;
  if (!response.ok || !payload.success) {
    throw new Error(payload.error || `Request failed: ${response.status}`);
  }
  return payload;
}
