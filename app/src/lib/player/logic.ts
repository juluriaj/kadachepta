// Pure playback rules, free of React Native imports so they run under `node --test`.

export type SleepMode = 'off' | 'end' | number; // number = minutes

export const SLEEP_CHOICES: SleepMode[] = ['off', 10, 20, 30, 45, 'end'];
export const SPEEDS = [0.75, 1, 1.25, 1.5, 2];
export const FADE_SECONDS = 45;
export const RESUME_REWIND_SECONDS = 3;

/** Seconds left on a minutes-based sleep timer, or null when no countdown is running. */
export function sleepRemaining(endsAt: number | null, now: number): number | null {
  if (endsAt == null) return null;
  return Math.max(0, (endsAt - now) / 1000);
}

/** Volume multiplier for a gentle fade-out over the last FADE_SECONDS of a sleep timer. */
export function fadeVolume(remaining: number | null, fadeSeconds = FADE_SECONDS): number {
  if (remaining == null || remaining >= fadeSeconds) return 1;
  if (remaining <= 0) return 0;
  // Ease-out curve: the drop is barely noticeable at first, like someone lowering their voice.
  const x = remaining / fadeSeconds;
  return Math.round(x * x * 1000) / 1000;
}

export type FinishContext = { bedtime: boolean; sleep: SleepMode; hasNext: boolean; autoContinue: boolean };

/**
 * What to do when a story ends. Bedtime never rolls into a new story, and neither does
 * "stop at end of story". Otherwise continue only when the listener opted in (a series or drive mode).
 */
export function onStoryFinished({ bedtime, sleep, hasNext, autoContinue }: FinishContext): 'stop' | 'goodnight' | 'next' {
  if (bedtime || sleep === 'end') return 'goodnight';
  if (hasNext && autoContinue) return 'next';
  return 'stop';
}

/** Where to resume: a few seconds before the saved position, unless it was finished or barely started. */
export function resumePosition(saved: { position: number; completed: boolean } | null | undefined, duration: number): number {
  if (!saved || saved.completed || saved.position < 10) return 0;
  if (duration && saved.position > duration - 15) return 0;
  return Math.max(0, saved.position - RESUME_REWIND_SECONDS);
}

/**
 * Listening seconds between two status updates. Only real forward playback counts:
 * seeks (big jumps or backwards) and gaps longer than a few seconds are ignored.
 */
export function listenedDelta(previous: number | null, current: number, rate = 1): number {
  if (previous == null) return 0;
  const delta = current - previous;
  if (delta <= 0 || delta > 5 * Math.max(rate, 1)) return 0;
  return delta / Math.max(rate, 0.1);
}

export function nextSpeed(current: number): number {
  const index = SPEEDS.indexOf(current);
  return SPEEDS[(index + 1) % SPEEDS.length] ?? 1;
}

export function nextSleep(current: SleepMode): SleepMode {
  const index = SLEEP_CHOICES.indexOf(current);
  return SLEEP_CHOICES[(index + 1) % SLEEP_CHOICES.length] ?? 'off';
}
