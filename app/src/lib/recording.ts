// Recorder metering is dBFS (about -160 silent to 0 full scale) on iOS, Android, and web.
export function levelFromDb(db: number | undefined | null) {
  if (db == null || !Number.isFinite(db)) return 0;
  return Math.min(1, Math.max(0, (db + 60) / 60));
}

// Speech sits around -30 to -10 dBFS when the phone is a hand's width away.
export function levelHint(db: number | undefined | null): 'quiet' | 'good' | 'loud' | null {
  if (db == null || !Number.isFinite(db) || db < -55) return null; // silence between words: no nagging
  if (db < -38) return 'quiet';
  if (db > -4) return 'loud';
  return 'good';
}
