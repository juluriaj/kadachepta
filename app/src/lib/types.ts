export type Teaser = { language: string; short: string | null; long: string | null };

export type Story = {
  id: string;
  title: string;
  album: string | null;
  narrator: string;
  language: string;
  duration: number;
  artworkUrl: string | null;
  audioUrl: string | null;
  audioUrlDataSaver: string | null;
  teaser?: Teaser;
  moments?: string[];
  favorite?: boolean;
  progress?: { position: number; completed: boolean; lastListenedAt: string | null } | null;
  metadata: {
    genres: string[];
    audienceAgeRange: string | null;
    moralTakeaway: string | null;
    contentWarnings: string[];
    episodeNumber: string | null;
  };
};

export type StoryDetail = Story & {
  themes: string[];
  ageSuggestion: string | null;
  waveform: number[];
  upNext: Story[];
  moreFromNarrator: Story[];
};

export type Shelf = { id: string; moment?: string; items: Story[] };

export type Stats = {
  totalSeconds: number;
  weekSeconds: number;
  screenOffShare: number | null;
  weekScreenOffShare: number | null;
  storiesStarted: number;
  storiesCompleted: number;
  favorites: number;
  streakDays: number;
  lastSevenDays: { day: string; seconds: number }[];
  genres: { genre: string; seconds: number }[];
  recent: { id: string; title: string; seconds: number; position: number; duration: number; completed: boolean;
    lastListenedAt: string; artworkUrl: string | null }[];
};

export type QcCheck = { code: string; level: 'warn' | 'fail'; message: string; tip?: string };

export type Submission = Story & {
  status: string;
  stage: string;
  stageLabel: string;
  qcVerdict: 'pass' | 'warn' | 'fail' | null;
  qc: { verdict?: string; checks?: QcCheck[] };
  mediaStatus: string;
  changesRequested: { reasons: string[]; texts: string[]; note: string; at: string; resolvedAt?: string } | null;
  series: { id: number; title: string } | null;
  seriesPosition: number | null;
  submittedAt: string | null;
  updatedAt: string | null;
  publishedAt: string | null;
  stats?: { listeners: number; seconds: number; completions: number; favorites: number } | null;
};

// P2-18: what mastering did to a story's listening copy (the original is always kept).
export type Mastering = {
  choice: 'auto' | 'full' | 'light' | 'none'; profile: string | null; level: 'full' | 'light' | 'none' | null;
  reason: string | null; fallback: string | null; beforeDb: number | null; afterDb: number | null;
  trimmedStart: number | null; trimmedEnd: number | null; compareUrl: string | null;
};

export type SubmissionDetail = Submission & {
  timeline: { key: string; label: string; state: 'done' | 'current' | 'todo' | 'blocked' }[];
  pipelineError: string | null;
  waveform: number[];
  mastering: Mastering;
  sourceText: string | null;
  draft: { shortText: string | null; longText: string | null; themes: string[]; ageSuggestion: string | null } | null;
  attestation: { sourceType?: string; sourceReference?: string };
  history: { action: string; notes: string | null; createdAt: string; actor: string }[];
};

export type NarratorProfile = {
  displayName: string | null; biography: string | null; languages: string[]; trustLevel: 'new' | 'trusted';
  onboarded: boolean; sampleUrl: string | null;
};

export type SeriesSummary = { id: number; title: string; description: string | null; language: string; chapters: number };

export type NarratorHome = {
  profile: NarratorProfile | null;
  totals: { published: number; inProgress: number; needsAttention: number; listeners: number; minutesListened: number;
    completions: number; favorites: number; publishedMinutes: number };
  unreadNotifications: number;
  submissions: Submission[];
  series: SeriesSummary[];
};

export type AppNotification = { id: number; kind: string; title: string; body: string | null; assetId: string | null;
  read: boolean; createdAt: string };
