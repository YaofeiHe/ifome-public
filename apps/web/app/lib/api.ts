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
    location_preferences: string[];
    soft_preferences: string[];
    excluded_companies: string[];
    summary: string | null;
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

const API_BASE_URL =
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
