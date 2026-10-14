import * as Updates from 'expo-updates';
import { useEffect } from 'react';

import { usePlayer } from './player/PlayerProvider';

// The JS bundle starts with the app, so this is close enough to the launch time.
const LAUNCHED_AT = Date.now();
// After this, someone is using the app: a downloaded update waits for the next start, as Expo does by default.
const STARTUP_WINDOW_MS = 30_000;

// Expo checks for an over-the-air update at every start, but only runs it on the start after it downloaded, so a
// published update needed two restarts. Switch to it as soon as the start-up download finishes instead, unless a
// story is already playing.
export function useApplyUpdateAtStartup() {
  const { isUpdatePending } = Updates.useUpdates();
  const { playing } = usePlayer();
  useEffect(() => {
    if (!Updates.isEnabled || !isUpdatePending || playing || Date.now() - LAUNCHED_AT > STARTUP_WINDOW_MS) return;
    Updates.reloadAsync().catch((error) => console.warn('Could not switch to the downloaded update', error));
  }, [isUpdatePending, playing]);
}
