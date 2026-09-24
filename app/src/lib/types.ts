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
