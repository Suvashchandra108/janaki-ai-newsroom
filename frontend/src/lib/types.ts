export type Me = {
  kind: string
  user_id: string | null
  email: string | null
  tenant_id: string | null
  is_platform_admin: boolean
  permissions: string[]
  mfa_enrollment_required: boolean
}
export type Tenant = {
  id: string
  slug: string
  name: string
  status: string
  default_language: string
  settings: Record<string, unknown>
}
export type Summary = {
  as_of: string
  day_start: string
  discovery: {
    items_today: number
    daily_item_quota: number
    quota_remaining: number
    paused: boolean
    next_scheduled_run: string | null
    events_today: number
  }
  pipeline: {
    discovered: number
    researching: number
    verified_candidates: number
    generating: number
    research_cap: number
    research_remaining: number
  }
  articles: {
    generated_today: number
    awaiting_review: number
    needs_review: number
    rejected: number
    sent_to_website: number
    published: number
  }
  failures: { jobs_24h: number; deliveries: number }
  usage: {
    ai_calls_today: number
    ai_input_tokens_today: number
    ai_output_tokens_today: number
    ai_calls_month: number
    ai_tokens_month: number
    ai_cost_known: boolean
    search_provider: string | null
    images_selected_month: number
    illustrations_today: number
    illustrations_limit: number
  }
  cms: {
    connected: boolean
    base_url: string | null
    auto_deliver: boolean
    last_error: string | null
  }
}
export type Notification = {
  kind: 'job_failed' | 'draft_ready' | 'sent_to_website' | 'delivery_failed' | 'website_status'
  severity: 'info' | 'warning' | 'error'
  at: string
  target_type: string | null
  target_id: string | null
  data: Record<string, unknown>
}
export type Job = {
  id: string
  job_type: string
  trigger: string
  status: string
  attempts: number
  created_at: string
  started_at: string | null
  finished_at: string | null
  error: string | null
  result: Record<string, unknown>
}
export type NewsEvent = {
  id: string
  title: string
  language: string
  category: string | null
  region: string | null
  status: string
  item_count: number
  publisher_count: number
  first_seen_at: string
  last_seen_at: string
}
export type Item = {
  id: string
  title: string
  url: string
  publisher_domain: string
  description: string | null
  published_at: string | null
  retrieved_at: string
}
export type EventDetail = NewsEvent & { keywords: string[]; items: Item[] }
export type Evidence = {
  id: string
  url: string
  publisher_domain: string
  excerpt: string
  relationship: string
  published_at: string | null
}
export type Claim = {
  id: string
  text: string
  claim_type: string
  status: string
  status_reason: string | null
  independent_sources: number
  editor_note: string | null
  evidence: Evidence[]
}
export type Flag = { code: string; severity: string; message: string; paragraph?: number }
export type Version = {
  version: number
  headline: string
  alt_headline: string | null
  summary: string
  paragraphs: { text: string; claim_ids: string[] }[]
  image_caption: string | null
  seo_title: string
  seo_description: string
  keywords: string[]
  category: string | null
  location: string | null
  social: Record<string, string>
  flags: Flag[]
  attribution: string
  created_by_kind: string
  model: string | null
  note: string | null
  created_at: string
}
export type ArticleSummary = {
  id: string
  event_id: string
  angle: string
  language: string
  slug: string
  status: string
  current_version: number
  regenerations: number
  rejection_reason: string | null
  updated_at: string
  headline: string
  flag_count: number
}
export type Article = ArticleSummary & { current: Version; versions: number[] }
export type Media = {
  id: string
  kind: string
  status: string
  role: string | null
  article_id: string | null
  provider: string
  title: string
  creator: string | null
  source_page_url: string | null
  licence_name: string | null
  licence_url: string | null
  attribution_text: string | null
  publishable: boolean
  licence_notes: string | null
  restrictions: string[]
  ai_generated: boolean
  label: string | null
  caption: string | null
  derivatives: { name: string; width: number }[]
  width: number | null
  height: number | null
}
export type Delivery = {
  article_id: string
  status: string
  attempts: number
  retryable: boolean
  last_error: string | null
  remote_id: string | null
  remote_status: string | null
  remote_published_at: string | null
  delivered_at: string | null
}
export type Source = {
  id: string
  name: string
  kind: string
  feed_url: string | null
  allowed_domains: string[]
  category: string | null
  credibility: string | null
  is_enabled: boolean
  last_fetched_at: string | null
  last_error: string | null
  consecutive_failures: number
}
export type User = {
  id: string
  email: string
  full_name: string
  kind: string
  is_active: boolean
  mfa_enabled: boolean
  last_login_at: string | null
  roles: string[]
}
export type CmsConnection = {
  base_url: string
  enabled: boolean
  auto_deliver: boolean
  category_map: Record<string, unknown>
  api_key_last4: string
  last_ok_at: string | null
  last_error: string | null
}
