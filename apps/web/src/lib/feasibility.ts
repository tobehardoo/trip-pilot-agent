import type { PlanEvaluation } from './api'

// ── Feasibility report wire types (mirror of the Java FeasibilityReport) ──

export type FeasibilityStatus = 'VERIFIED' | 'NEEDS_REPAIR' | 'UNVERIFIED'

export type RuleOutcome = 'PASS' | 'FAIL' | 'UNKNOWN' | 'NOT_APPLICABLE'

export type EvidenceState = 'VERIFIED' | 'UNKNOWN' | 'STALE' | 'CONFLICTING'

export interface EvidenceReference {
  evidenceId: string
  evidenceType: string
  state: EvidenceState
  hardConstraintEligible: boolean
}

export interface FeasibilitySummary {
  totalCount: number
  passCount: number
  failCount: number
  unknownCount: number
  notApplicableCount: number
  missingRequiredCount: number
}

export interface FeasibilityRuleResult {
  ruleId: string
  ruleVersion: string
  outcome: RuleOutcome
  reasonCode: string
  message: string
  affectedDates: string[]
  affectedEntityRefs: string[]
  evidenceRefs: EvidenceReference[]
  repairable: boolean
}

export interface RepairAttempt {
  attemptIndex: number
  triggeringRuleIds: string[]
  actionCodes: string[]
  affectedDates: string[]
  affectedEntityRefs: string[]
  beforeFingerprint: string
  afterFingerprint: string
  resultingStatus: FeasibilityStatus
}

export interface FeasibilityReport {
  schemaVersion: number
  reportId: string
  validatorVersion: string
  itineraryFingerprint: string
  status: FeasibilityStatus
  validatedAt: string
  requiredRuleIds: string[]
  missingRequiredRuleIds: string[]
  summary: FeasibilitySummary
  ruleResults: FeasibilityRuleResult[]
  repairAttempts: RepairAttempt[]
}

/** VersionSummary.feasibility metadata (null = no historical validation). */
export interface VersionFeasibilityMetadata {
  reportId: string
  schemaVersion: number
  validatorVersion: string
  status: FeasibilityStatus
  itineraryFingerprint: string
  validatedAt: string
}

// ── Candidate itinerary (review-required v1 wire shape) ──────────────────

export interface CandidateItinerary {
  title: string
  days: CandidateDay[]
  estimatedTotalCost: number
}

export interface CandidateDay {
  date: string
  dayType: string | null
  activities: CandidateActivity[]
  transitLegs: CandidateTransitLeg[]
}

export interface CandidateActivity {
  activityId: string | null
  title: string
  startTime: string
  endTime: string
  estimatedCost: number
  source: string
  providerPoiId: string | null
  coordinates: { longitude: number; latitude: number } | null
  address: string | null
  typeCode: string | null
  typeName: string | null
  kind: string | null
  timeFixed: boolean | null
}

export interface CandidateTransitLeg {
  transitId: string | null
  fromActivityIndex: number
  toActivityIndex: number
  mode: string
  distanceMeters: number
  durationSeconds: number
  provider: string
  estimated: boolean
  polyline: Array<{ longitude: number; latitude: number }>
  estimatedCost: number | null
  costSource: string | null
}

// ── Typed entity references (hard-validator-v4 grammar) ──────────────────

export type TypedEntityKind = 'activity' | 'transit' | 'poi' | 'text' | 'unknown'

export interface TypedEntityReference {
  kind: TypedEntityKind
  value: string
}

const KNOWN_KINDS = new Set(['activity', 'transit', 'poi', 'text'])
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

export function parseTypedEntityReference(ref: string): TypedEntityReference {
  if (typeof ref !== 'string') return { kind: 'unknown', value: String(ref ?? '') }
  const separator = ref.indexOf(':')
  if (separator <= 0) return { kind: 'unknown', value: ref }
  const kind = ref.slice(0, separator)
  const value = ref.slice(separator + 1)
  if (!KNOWN_KINDS.has(kind)) return { kind: 'unknown', value }
  if (value.trim().length === 0) return { kind: 'unknown', value: '' }
  if ((kind === 'activity' || kind === 'transit') && !UUID_PATTERN.test(value)) {
    return { kind: 'unknown', value }
  }
  return { kind: kind as 'activity' | 'transit' | 'poi' | 'text', value }
}

// ── Runtime-safe reading (display safety, not business re-validation) ─────

export type ReadResult<T> = { ok: true; value: T } | { ok: false; reason: string }

const REPORT_STATUSES = new Set(['VERIFIED', 'NEEDS_REPAIR', 'UNVERIFIED'])
const RULE_OUTCOMES = new Set(['PASS', 'FAIL', 'UNKNOWN', 'NOT_APPLICABLE'])
const EVIDENCE_STATES = new Set(['VERIFIED', 'UNKNOWN', 'STALE', 'CONFLICTING'])
const VALIDATOR_VERSIONS = new Set([
  'feasibility-v1',
  'hard-validator-v1',
  'hard-validator-v2',
  'hard-validator-v3',
  'hard-validator-v4',
])

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === 'string')
}

function readStringArray(input: unknown, field: string): string[] | null {
  if (input === undefined || input === null) return null
  if (!isStringArray(input)) return null
  return input
}

function readEvidenceReferences(input: unknown): EvidenceReference[] | null {
  if (input === undefined || input === null) return null
  if (!Array.isArray(input)) return null
  const refs: EvidenceReference[] = []
  for (const item of input) {
    if (!isRecord(item)) return null
    if (typeof item.evidenceId !== 'string' || typeof item.evidenceType !== 'string') return null
    if (typeof item.hardConstraintEligible !== 'boolean') return null
    if (typeof item.state !== 'string' || !EVIDENCE_STATES.has(item.state)) return null
    refs.push({
      evidenceId: item.evidenceId,
      evidenceType: item.evidenceType,
      state: item.state as EvidenceState,
      hardConstraintEligible: item.hardConstraintEligible,
    })
  }
  return refs
}

function readRuleResults(input: unknown): FeasibilityRuleResult[] | null {
  if (!Array.isArray(input)) return null
  const results: FeasibilityRuleResult[] = []
  for (const item of input) {
    if (!isRecord(item)) return null
    if (typeof item.ruleId !== 'string' || typeof item.ruleVersion !== 'string'
      || typeof item.reasonCode !== 'string' || typeof item.message !== 'string'
      || typeof item.repairable !== 'boolean') return null
    if (typeof item.outcome !== 'string' || !RULE_OUTCOMES.has(item.outcome)) return null
    const affectedDates = readStringArray(item.affectedDates, 'affectedDates')
    const affectedEntityRefs = readStringArray(item.affectedEntityRefs, 'affectedEntityRefs')
    const evidenceRefs = readEvidenceReferences(item.evidenceRefs)
    if (affectedDates === null || affectedEntityRefs === null || evidenceRefs === null) return null
    results.push({
      ruleId: item.ruleId,
      ruleVersion: item.ruleVersion,
      outcome: item.outcome as RuleOutcome,
      reasonCode: item.reasonCode,
      message: item.message,
      affectedDates,
      affectedEntityRefs,
      evidenceRefs,
      repairable: item.repairable,
    })
  }
  return results
}

function readRepairAttempts(input: unknown): RepairAttempt[] | null {
  if (input === undefined || input === null) return null
  if (!Array.isArray(input)) return null
  const attempts: RepairAttempt[] = []
  for (const item of input) {
    if (!isRecord(item)) return null
    if (typeof item.attemptIndex !== 'number' || !Number.isSafeInteger(item.attemptIndex)
      || item.attemptIndex < 1) return null
    if (typeof item.resultingStatus !== 'string' || !REPORT_STATUSES.has(item.resultingStatus)) return null
    if (typeof item.beforeFingerprint !== 'string' || typeof item.afterFingerprint !== 'string') return null
    const triggeringRuleIds = readStringArray(item.triggeringRuleIds, 'triggeringRuleIds')
    const actionCodes = readStringArray(item.actionCodes, 'actionCodes')
    const affectedDates = readStringArray(item.affectedDates, 'affectedDates')
    const affectedEntityRefs = readStringArray(item.affectedEntityRefs, 'affectedEntityRefs')
    if (triggeringRuleIds === null || actionCodes === null
      || affectedDates === null || affectedEntityRefs === null) return null
    attempts.push({
      attemptIndex: item.attemptIndex,
      triggeringRuleIds,
      actionCodes,
      affectedDates,
      affectedEntityRefs,
      beforeFingerprint: item.beforeFingerprint,
      afterFingerprint: item.afterFingerprint,
      resultingStatus: item.resultingStatus as FeasibilityStatus,
    })
  }
  return attempts
}

function readSummary(input: unknown): FeasibilitySummary | null {
  if (!isRecord(input)) return null
  const fields: Array<keyof FeasibilitySummary> = [
    'totalCount', 'passCount', 'failCount', 'unknownCount', 'notApplicableCount', 'missingRequiredCount',
  ]
  for (const field of fields) {
    if (typeof input[field] !== 'number' || !Number.isSafeInteger(input[field])
      || (input[field] as number) < 0) return null
  }
  return {
    totalCount: input.totalCount as number,
    passCount: input.passCount as number,
    failCount: input.failCount as number,
    unknownCount: input.unknownCount as number,
    notApplicableCount: input.notApplicableCount as number,
    missingRequiredCount: input.missingRequiredCount as number,
  }
}

/**
 * Reads a FeasibilityReport from an unknown wire value for display purposes
 * only.  This validates shape and enum values so the UI never renders
 * garbage or guesses a status; it deliberately does not re-derive report
 * status from rule outcomes (the backend is the single authority).
 */
export function readFeasibilityReport(input: unknown): ReadResult<FeasibilityReport> {
  if (input === null || input === undefined) {
    return { ok: false, reason: 'report is absent' }
  }
  if (!isRecord(input)) {
    return { ok: false, reason: 'report is not an object' }
  }
  if (typeof input.status !== 'string' || !REPORT_STATUSES.has(input.status)) {
    return { ok: false, reason: `unknown report status: ${String(input.status)}` }
  }
  if (typeof input.schemaVersion !== 'number' || input.schemaVersion !== 1) {
    return { ok: false, reason: `unsupported schemaVersion: ${String(input.schemaVersion)}` }
  }
  if (typeof input.reportId !== 'string'
    || typeof input.validatorVersion !== 'string'
    || !VALIDATOR_VERSIONS.has(input.validatorVersion)
    || typeof input.itineraryFingerprint !== 'string'
    || typeof input.validatedAt !== 'string') {
    return { ok: false, reason: 'report is missing required scalar fields or has an unknown validatorVersion' }
  }
  const requiredRuleIds = readStringArray(input.requiredRuleIds, 'requiredRuleIds')
  const missingRequiredRuleIds = readStringArray(input.missingRequiredRuleIds, 'missingRequiredRuleIds')
  if (requiredRuleIds === null || missingRequiredRuleIds === null) {
    return { ok: false, reason: 'report rule id arrays are invalid' }
  }
  const summary = readSummary(input.summary)
  if (summary === null) return { ok: false, reason: 'report summary is invalid' }
  const ruleResults = readRuleResults(input.ruleResults)
  if (ruleResults === null) return { ok: false, reason: 'report ruleResults are invalid' }
  const repairAttempts = readRepairAttempts(input.repairAttempts)
  if (repairAttempts === null) return { ok: false, reason: 'report repairAttempts are invalid' }

  return {
    ok: true,
    value: {
      schemaVersion: input.schemaVersion,
      reportId: input.reportId,
      validatorVersion: input.validatorVersion,
      itineraryFingerprint: input.itineraryFingerprint,
      status: input.status as FeasibilityStatus,
      validatedAt: input.validatedAt,
      requiredRuleIds,
      missingRequiredRuleIds,
      summary,
      ruleResults,
      repairAttempts,
    },
  }
}

/**
 * Reads the VersionSummary.feasibility metadata (or null when the version
 * has no validation record).  Null must not be coerced to UNVERIFIED.
 */
export function readVersionFeasibilityMetadata(
  input: unknown,
): ReadResult<VersionFeasibilityMetadata | null> {
  if (input === null || input === undefined) return { ok: true, value: null }
  if (!isRecord(input)) return { ok: false, reason: 'feasibility metadata is not an object' }
  if (typeof input.status !== 'string' || !REPORT_STATUSES.has(input.status)) {
    return { ok: false, reason: `unknown feasibility status: ${String(input.status)}` }
  }
  if (typeof input.reportId !== 'string'
    || typeof input.schemaVersion !== 'number'
    || typeof input.validatorVersion !== 'string'
    || typeof input.itineraryFingerprint !== 'string'
    || typeof input.validatedAt !== 'string') {
    return { ok: false, reason: 'feasibility metadata is missing required fields' }
  }
  return {
    ok: true,
    value: {
      reportId: input.reportId,
      schemaVersion: input.schemaVersion,
      validatorVersion: input.validatorVersion,
      status: input.status as FeasibilityStatus,
      itineraryFingerprint: input.itineraryFingerprint,
      validatedAt: input.validatedAt,
    },
  }
}

// ── Candidate itinerary reading ───────────────────────────────────────────

function readCandidateActivities(input: unknown): CandidateActivity[] | null {
  if (!Array.isArray(input)) return null
  const activities: CandidateActivity[] = []
  for (const item of input) {
    if (!isRecord(item)) return null
    if (typeof item.title !== 'string' || typeof item.startTime !== 'string'
      || typeof item.endTime !== 'string' || typeof item.estimatedCost !== 'number'
      || !Number.isFinite(item.estimatedCost)) {
      return null
    }
    activities.push({
      activityId: typeof item.activityId === 'string' ? item.activityId : null,
      title: item.title,
      startTime: item.startTime,
      endTime: item.endTime,
      estimatedCost: item.estimatedCost,
      source: typeof item.source === 'string' ? item.source : '',
      providerPoiId: typeof item.providerPoiId === 'string' ? item.providerPoiId : null,
      coordinates: isRecord(item.coordinates) && typeof item.coordinates.longitude === 'number'
        && typeof item.coordinates.latitude === 'number'
        && Number.isFinite(item.coordinates.longitude)
        && Number.isFinite(item.coordinates.latitude)
        ? { longitude: item.coordinates.longitude, latitude: item.coordinates.latitude }
        : null,
      address: typeof item.address === 'string' ? item.address : null,
      typeCode: typeof item.typeCode === 'string' ? item.typeCode : null,
      typeName: typeof item.typeName === 'string' ? item.typeName : null,
      kind: typeof item.kind === 'string' ? item.kind : null,
      timeFixed: typeof item.timeFixed === 'boolean' ? item.timeFixed : null,
    })
  }
  return activities
}

function readCandidateTransitLegs(input: unknown): CandidateTransitLeg[] | null {
  if (input === undefined || input === null) return []
  if (!Array.isArray(input)) return null
  const legs: CandidateTransitLeg[] = []
  for (const item of input) {
    if (!isRecord(item)) return null
    if (typeof item.fromActivityIndex !== 'number' || !Number.isSafeInteger(item.fromActivityIndex)
      || item.fromActivityIndex < 0
      || typeof item.toActivityIndex !== 'number' || !Number.isSafeInteger(item.toActivityIndex)
      || item.toActivityIndex < 0
      || typeof item.distanceMeters !== 'number' || !Number.isSafeInteger(item.distanceMeters)
      || item.distanceMeters < 0
      || typeof item.durationSeconds !== 'number' || !Number.isSafeInteger(item.durationSeconds)
      || item.durationSeconds < 0
      || typeof item.mode !== 'string' || item.mode.trim().length === 0
      || typeof item.provider !== 'string' || item.provider.trim().length === 0
      || typeof item.estimated !== 'boolean'
      || !Array.isArray(item.polyline)) {
      return null
    }
    const polyline: Array<{ longitude: number; latitude: number }> = []
    for (const point of item.polyline) {
      if (!isRecord(point) || typeof point.longitude !== 'number' || typeof point.latitude !== 'number'
        || !Number.isFinite(point.longitude) || !Number.isFinite(point.latitude)) {
        return null
      }
      polyline.push({ longitude: point.longitude, latitude: point.latitude })
    }
    legs.push({
      transitId: typeof item.transitId === 'string' ? item.transitId : null,
      fromActivityIndex: item.fromActivityIndex,
      toActivityIndex: item.toActivityIndex,
      mode: item.mode,
      distanceMeters: item.distanceMeters,
      durationSeconds: item.durationSeconds,
      provider: item.provider,
      estimated: item.estimated,
      polyline,
      estimatedCost: typeof item.estimatedCost === 'number' && Number.isFinite(item.estimatedCost)
        ? item.estimatedCost : null,
      costSource: typeof item.costSource === 'string' ? item.costSource : null,
    })
  }
  return legs
}

/**
 * Reads a candidate itinerary for read-only display.  The candidate is never
 * written back as a formal itinerary; this only validates the display shape.
 */
export function readCandidateItinerary(input: unknown): ReadResult<CandidateItinerary> {
  if (!isRecord(input)) return { ok: false, reason: 'candidate is not an object' }
  if (typeof input.title !== 'string' || input.title.length === 0) {
    return { ok: false, reason: 'candidate is missing a title' }
  }
  if (typeof input.estimatedTotalCost !== 'number') {
    return { ok: false, reason: 'candidate is missing estimatedTotalCost' }
  }
  if (!Array.isArray(input.days) || input.days.length === 0) {
    return { ok: false, reason: 'candidate is missing days' }
  }
  const days: CandidateDay[] = []
  for (const day of input.days) {
    if (!isRecord(day) || typeof day.date !== 'string') {
      return { ok: false, reason: 'candidate day is invalid' }
    }
    const activities = readCandidateActivities(day.activities)
    if (activities === null || activities.length === 0) {
      return { ok: false, reason: 'candidate day has no valid activities' }
    }
    const transitLegs = readCandidateTransitLegs(day.transitLegs)
    if (transitLegs === null) return { ok: false, reason: 'candidate transit legs are invalid' }
    for (const leg of transitLegs) {
      if (leg.fromActivityIndex >= activities.length || leg.toActivityIndex >= activities.length) {
        return { ok: false, reason: 'candidate transit leg index is out of bounds' }
      }
    }
    days.push({
      date: day.date,
      dayType: typeof day.dayType === 'string' ? day.dayType : null,
      activities,
      transitLegs,
    })
  }
  return { ok: true, value: { title: input.title, days, estimatedTotalCost: input.estimatedTotalCost } }
}

// ── Display mappings (authoritative status only, never re-derived) ────────

export const FEASIBILITY_STATUS_LABEL: Record<FeasibilityStatus, string> = {
  VERIFIED: '已验证',
  NEEDS_REPAIR: '待修复',
  UNVERIFIED: '未验证',
}

export const RULE_OUTCOME_LABEL: Record<RuleOutcome, string> = {
  PASS: '通过',
  FAIL: '失败',
  UNKNOWN: '未知',
  NOT_APPLICABLE: '不适用',
}

export const EVIDENCE_STATE_LABEL: Record<EvidenceState, string> = {
  VERIFIED: '证据已验证',
  UNKNOWN: '证据未知',
  STALE: '证据过期',
  CONFLICTING: '证据冲突',
}

/** Rule ids to stable Chinese labels.  Unknown ids fall back to the raw id. */
const RULE_ID_LABELS: Record<string, string> = {
  TRIP_DATE_RANGE: '行程日期范围',
  FIXED_SCHEDULE_COVERAGE: '固定安排覆盖',
  BUDGET_LIMIT: '预算上限',
  MUST_VISIT_COVERAGE: '必去地点覆盖',
  DUPLICATE_POI: '重复地点',
  ACTIVITY_OVERLAP: '活动时间重叠',
  ROUTE_ENDPOINT_CONTINUITY: '路线端点连续',
  CROSS_DAY_CONTINUITY: '跨日连续',
  OPENING_HOURS: '营业时间',
  VISIT_DURATION: '游玩时长',
  MEAL_WINDOW: '用餐时段',
}

export function ruleIdLabel(ruleId: string): string {
  return RULE_ID_LABELS[ruleId] ?? ruleId
}

export function formatValidatedAt(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
    timeZone: 'Asia/Shanghai',
  }).format(date)
}

// ── PlanEvaluation safe reader (completed-only companion) ────────────────

const WARNING_SEVERITIES = new Set(['INFO', 'WARNING', 'CRITICAL'])
const SUBJECT_TYPES = new Set(['PLAN', 'DAY', 'ACTIVITY', 'TRANSIT'])

function readScoreField(value: unknown): boolean {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 && value <= 100
}

function readNullableScoreField(value: unknown): boolean {
  return value === null || readScoreField(value)
}

/**
 * Reads a PlanEvaluation for display safety.  The evaluation is experience
 * quality only; feasibility is never derived from it.  A malformed evaluation
 * is rejected so completed outcomes fail closed instead of rendering a
 * half-parsed score.
 */
export function readPlanEvaluation(input: unknown): ReadResult<PlanEvaluation> {
  if (!isRecord(input)) return { ok: false, reason: 'evaluation is not an object' }
  if (typeof input.schemaVersion !== 'number' || !Number.isSafeInteger(input.schemaVersion)) {
    return { ok: false, reason: 'evaluation schemaVersion is invalid' }
  }
  if (typeof input.evaluatorVersion !== 'string' || input.evaluatorVersion.trim().length === 0) {
    return { ok: false, reason: 'evaluation evaluatorVersion is invalid' }
  }
  if (typeof input.feasible !== 'boolean') {
    return { ok: false, reason: 'evaluation feasible is invalid' }
  }
  if (!readScoreField(input.overallScore)) {
    return { ok: false, reason: 'evaluation overallScore is invalid' }
  }
  if (!isRecord(input.dimensions)) {
    return { ok: false, reason: 'evaluation dimensions are invalid' }
  }
  const dimensions = input.dimensions
  const constraintSatisfaction = dimensions.constraintSatisfaction
  const timeFeasibility = dimensions.timeFeasibility
  const budgetFit = dimensions.budgetFit
  const routeEfficiency = dimensions.routeEfficiency
  const interestMatch = dimensions.interestMatch
  if (!readScoreField(constraintSatisfaction)
    || !readScoreField(timeFeasibility)
    || !readNullableScoreField(budgetFit)
    || !readScoreField(routeEfficiency)
    || !readNullableScoreField(interestMatch)) {
    return { ok: false, reason: 'evaluation dimensions are invalid' }
  }
  if (!Array.isArray(input.warnings) || !Array.isArray(input.decisions)) {
    return { ok: false, reason: 'evaluation warnings/decisions are invalid' }
  }
  const warnings: PlanEvaluation['warnings'] = []
  for (const item of input.warnings) {
    if (!isRecord(item) || typeof item.code !== 'string' || typeof item.message !== 'string'
      || typeof item.severity !== 'string' || !WARNING_SEVERITIES.has(item.severity)
      || typeof item.entityType !== 'string' || !SUBJECT_TYPES.has(item.entityType)) {
      return { ok: false, reason: 'evaluation warning is invalid' }
    }
    warnings.push({
      code: item.code,
      severity: item.severity as PlanEvaluation['warnings'][number]['severity'],
      message: item.message,
      entityType: item.entityType as PlanEvaluation['warnings'][number]['entityType'],
      dayIndex: typeof item.dayIndex === 'number' ? item.dayIndex : null,
      entityId: typeof item.entityId === 'string' ? item.entityId : null,
      metricKey: typeof item.metricKey === 'string' ? item.metricKey : null,
      actualValue: typeof item.actualValue === 'number' ? item.actualValue : null,
      threshold: typeof item.threshold === 'number' ? item.threshold : null,
    })
  }
  const decisions: PlanEvaluation['decisions'] = []
  for (const item of input.decisions) {
    if (!isRecord(item) || typeof item.summary !== 'string'
      || typeof item.subjectType !== 'string' || !SUBJECT_TYPES.has(item.subjectType)
      || !Array.isArray(item.reasonCodes) || !isStringArray(item.reasonCodes)
      || !Array.isArray(item.reasons) || !isStringArray(item.reasons)) {
      return { ok: false, reason: 'evaluation decision is invalid' }
    }
    decisions.push({
      subjectType: item.subjectType as PlanEvaluation['decisions'][number]['subjectType'],
      subjectId: typeof item.subjectId === 'string' ? item.subjectId : null,
      summary: item.summary,
      reasonCodes: item.reasonCodes,
      reasons: item.reasons,
      constraintRefs: isStringArray(item.constraintRefs) ? item.constraintRefs : [],
      evidence: Array.isArray(item.evidence) ? item.evidence as PlanEvaluation['decisions'][number]['evidence'] : [],
      dayIndex: typeof item.dayIndex === 'number' ? item.dayIndex : null,
    })
  }
  if (typeof input.summary !== 'string' || typeof input.evaluatedAt !== 'string') {
    return { ok: false, reason: 'evaluation summary/evaluatedAt are invalid' }
  }
  return {
    ok: true,
    value: {
      schemaVersion: input.schemaVersion as number,
      evaluatorVersion: input.evaluatorVersion as string,
      feasible: input.feasible as boolean,
      overallScore: input.overallScore as number,
      dimensions: {
        constraintSatisfaction: constraintSatisfaction as number,
        timeFeasibility: timeFeasibility as number,
        budgetFit: budgetFit as number | null,
        routeEfficiency: routeEfficiency as number,
        interestMatch: interestMatch as number | null,
      },
      warnings,
      decisions,
      summary: input.summary as string,
      evaluatedAt: input.evaluatedAt as string,
    },
  }
}

// ── Unified outcome parser (Task API / SSE live / SSE replay) ─────────────

export type PlanningOutcome =
  | { kind: 'completed'; report: FeasibilityReport; evaluation: PlanEvaluation }
  | { kind: 'review'; report: FeasibilityReport; candidate: CandidateItinerary }
  | { kind: 'queued' }
  | { kind: 'failed'; errorMessage: string | null }
  | { kind: 'cancelled' }
  | { kind: 'malformed'; reason: string }

function present(value: unknown): boolean {
  return value !== undefined && value !== null
}

function readTerminalOutcome(
  status: string,
  reportInput: unknown,
  candidateInput: unknown,
  evaluationInput: unknown,
  errorText: string | null,
): PlanningOutcome {
  if (status === 'QUEUED' || status === 'RUNNING') {
    if (present(reportInput) || present(candidateInput) || present(evaluationInput)) {
      return { kind: 'malformed', reason: `${status} must not carry outcome fields` }
    }
    return { kind: 'queued' }
  }
  if (status === 'FAILED' || status === 'CANCELLED') {
    if (present(reportInput) || present(candidateInput) || present(evaluationInput)) {
      return { kind: 'malformed', reason: `${status} must not carry report/candidate/evaluation` }
    }
    return status === 'FAILED'
      ? { kind: 'failed', errorMessage: errorText }
      : { kind: 'cancelled' }
  }
  if (status === 'SUCCEEDED') {
    const report = readFeasibilityReport(reportInput)
    if (!report.ok) {
      return { kind: 'malformed', reason: `completed report is invalid: ${report.reason}` }
    }
    if (report.value.status !== 'VERIFIED') {
      return { kind: 'malformed', reason: `completed report must be VERIFIED, got ${report.value.status}` }
    }
    if (present(candidateInput)) {
      return { kind: 'malformed', reason: 'completed outcome must not carry a candidate' }
    }
    const evaluation = readPlanEvaluation(evaluationInput)
    if (!evaluation.ok) {
      return { kind: 'malformed', reason: `completed evaluation is invalid: ${evaluation.reason}` }
    }
    return { kind: 'completed', report: report.value, evaluation: evaluation.value }
  }
  if (status === 'WAITING_USER') {
    const report = readFeasibilityReport(reportInput)
    if (!report.ok) {
      return { kind: 'malformed', reason: `review report is invalid: ${report.reason}` }
    }
    if (report.value.status === 'VERIFIED') {
      return { kind: 'malformed', reason: 'review report must not be VERIFIED' }
    }
    if (present(evaluationInput)) {
      return { kind: 'malformed', reason: 'review outcome must not carry an evaluation' }
    }
    const candidate = readCandidateItinerary(candidateInput)
    if (!candidate.ok) {
      return { kind: 'malformed', reason: `review candidate is invalid: ${candidate.reason}` }
    }
    return { kind: 'review', report: report.value, candidate: candidate.value }
  }
  return { kind: 'malformed', reason: `unknown task status: ${status}` }
}

/**
 * Single parsing entry for Task API responses
 * (GET /api/planning-tasks/{id} and /api/trips/{tripId}/planning-tasks/latest).
 * The backend read model already fail-closed the stored outcome, but the
 * frontend re-validates so a corrupt wire body can never render an
 * authoritative status.
 */
export function readPlanningTaskOutcome(task: {
  status: string
  errorMessage?: string | null
  feasibilityReport?: unknown
  candidateItinerary?: unknown
  evaluation?: unknown
}): PlanningOutcome {
  return readTerminalOutcome(
    task.status,
    task.feasibilityReport,
    task.candidateItinerary,
    task.evaluation,
    task.errorMessage ?? null,
  )
}

const EVENT_TYPE_STATUS: Record<string, string> = {
  PLANNING_COMPLETED: 'SUCCEEDED',
  PLANNING_REVIEW_REQUIRED: 'WAITING_USER',
  PLANNING_FAILED: 'FAILED',
  PLANNING_CANCELLED: 'CANCELLED',
  PLANNING_QUEUED: 'QUEUED',
  PLANNING_PROGRESS: 'RUNNING',
}

/**
 * Single parsing entry for SSE events (live and replay share this path).
 * The eventType and payload.status must agree; any mismatch or invalid
 * outcome shape fails closed as malformed.
 */
export function readPlanningEventOutcome(event: {
  eventType: string
  payload: {
    status?: string
    message?: string
    errorMessage?: string
    safeMessage?: string
    feasibilityReport?: unknown
    candidateItinerary?: unknown
    evaluation?: unknown
    conflicts?: unknown
    relaxationSuggestions?: unknown
    [key: string]: unknown
  }
}): PlanningOutcome {
  const expectedStatus = EVENT_TYPE_STATUS[event.eventType]
  if (!expectedStatus) {
    return { kind: 'malformed', reason: `unknown eventType: ${event.eventType}` }
  }
  const { status, feasibilityReport, candidateItinerary, evaluation } = event.payload
  if (typeof status !== 'string' || status !== expectedStatus) {
    return {
      kind: 'malformed',
      reason: `event ${event.eventType} status ${String(status)} does not match expected ${expectedStatus}`,
    }
  }
  const errorParts: string[] = []
  const primaryError = [event.payload.message, event.payload.errorMessage, event.payload.safeMessage]
    .find((value): value is string => typeof value === 'string' && value.trim().length > 0)
  if (primaryError) errorParts.push(primaryError)
  if (Array.isArray(event.payload.conflicts)) {
    for (const conflict of event.payload.conflicts) {
      if (conflict && typeof conflict === 'object' && 'message' in conflict
        && typeof conflict.message === 'string' && conflict.message.trim()
        && !errorParts.includes(conflict.message)) {
        errorParts.push(conflict.message)
      }
    }
  }
  if (Array.isArray(event.payload.relaxationSuggestions)) {
    for (const suggestion of event.payload.relaxationSuggestions) {
      if (suggestion && typeof suggestion === 'object' && 'message' in suggestion
        && typeof suggestion.message === 'string' && suggestion.message.trim()) {
        errorParts.push(`建议：${suggestion.message}`)
      }
    }
  }
  const errorText = errorParts.length > 0 ? errorParts.join('；') : null
  return readTerminalOutcome(status, feasibilityReport, candidateItinerary, evaluation, errorText)
}

export type { PlanEvaluation }
