// Types and constants for the editor studio (English-only staff UI).
import type { QcCheck } from './types';

export const GENRES = ['Folklore', 'Fable', 'Mythology', 'History', 'Adventure', 'Fantasy', 'Humor', 'Family', 'Science',
  'Moral', 'Biography', 'Mystery', 'Poetry', 'Devotional', 'Nature'];
export const AGE_RANGES = ['3-5', '4-8', '6-8', '6-10', '9-12', '10-14', '13+', 'All ages'];
export const MOMENTS = ['bedtime', 'drive', 'run', 'work', 'learn'];

export type QueueItem = {
  id: string; title: string; narrator: string; language: string; duration: number; status: string; stage: string;
  stageLabel: string; pipelineError: string | null; isSubmission: boolean; trustLevel: 'new' | 'trusted' | null;
  readyForReviewAt: string | null; waitingHours: number | null; overdue: boolean; qcVerdict: string | null;
  safetyRating: string | null; teaser: string | null; hasTranscript: boolean; transcriptReviewRequired: boolean;
  artworkUrl: string | null; series: string | null; bulkEligible: boolean; bulkBlockers: string[]; publishedAt: string | null;
};

export type QueueResponse = { view: string; items: QueueItem[]; counts: Record<string, number>; slaHours: number };

export type SafetyFlag = { category: string; severity: 'low' | 'medium' | 'high'; evidence: string };

export type Review = {
  asset: {
    id: string; title: string; narrator: string; language: string; duration: number; status: string; audioUrl: string | null;
    originalAudioUrl?: string | null; artworkUrl: string | null; isSubmission: boolean; mediaStatus: string;
    metadata: {
      title: string; album: string | null; genres: string[]; language: string; audienceAgeRange: string | null;
      mood: string | null; moralTakeaway: string | null; sourceAdaptation: string | null; listeningContexts: string[];
      contentWarnings: string[]; keywords: string[]; episodeNumber: string | null;
    };
  };
  stage: string; stageLabel: string; pipelineError: string | null; waveform: number[];
  qc: { verdict?: string; checks?: QcCheck[]; integratedLufs?: number; noiseFloorDb?: number; speechRatio?: number };
  waitingHours: number | null; overdue: boolean; captionsEnabled: boolean; sourceText: string | null;
  changesRequested: { reasons: string[]; texts: string[]; note: string; by: string; at: string } | null;
  series: { id: number; title: string; position: number | null } | null;
  narrator: { userId: number; name: string; trustLevel: string | null; sampleUrl: string | null; published?: number;
    rejected?: number; changesRequested?: number } | null;
  transcript: { id: number; status: string; language: string; text: string; introRemoved: string | null;
    confidence: number | null; quality: { reasons?: string[]; charsPerSecond?: number; coverage?: number };
    reviewRequired: boolean; provider: string | null; model: string | null } | null;
  draft: { id: number; status: string; language: string; shortText: string | null; longText: string | null;
    alternates: Record<string, { short?: string; long?: string }>; themes: string[]; mood: string[];
    ageSuggestion: string | null; warnings: string[]; model: string | null; promptVersion: string | null;
    safety: { rating?: string; minAge?: number | null; flags?: SafetyFlag[]; summary?: string };
    suggestions: { genres?: string[]; keywords?: string[]; listeningContexts?: string[]; englishTitle?: string | null } } | null;
  rights: { status: string; sourceType?: string | null; rightsHolder?: string | null; message: string;
    attestation: { sourceType?: string; sourceReference?: string; notes?: string; by?: string; attestedAt?: string };
    evidenceUrl: string | null };
  policy: { checklist: { id: string; text: string; required: boolean }[]; changeReasons: Record<string, string>;
    ageRubric: { band: string; allows: string }[]; safetyCategories: Record<string, string> };
  readiness: string[];
  jobs: { id: number; jobType: string; status: string; queueStatus: string; error: string | null; updatedAt: string }[];
  history: { action: string; actor: string; notes: string | null; createdAt: string }[];
};

export type SettingSpec = { key: string; kind: 'text' | 'bool' | 'int' | 'float' | 'choice' | 'map' | 'patterns';
  label: string; help: string; default: unknown; choices: string[]; minimum: number | null; maximum: number | null };

export type SettingsPage = {
  specs: SettingSpec[]; values: Record<string, unknown>; availableModels: string[];
  workers: { name: string; capabilities: string[]; lastSeenAt: string | null; online: boolean; disabled: boolean;
    info: Record<string, any> }[];
  queue: Record<string, number>; deadLastWeek: Record<string, number>; transcriptionMinutesToday: number;
};

export function hoursLabel(hours: number | null) {
  if (hours == null) return '';
  if (hours < 1) return `${Math.max(1, Math.round(hours * 60))} min`;
  if (hours < 48) return `${Math.round(hours)} h`;
  return `${Math.round(hours / 24)} days`;
}

export function listText(values: string[] | null | undefined) {
  return (values ?? []).join(', ');
}

export function parseList(text: string) {
  return [...new Set(text.split(',').map((part) => part.trim()).filter(Boolean))];
}
