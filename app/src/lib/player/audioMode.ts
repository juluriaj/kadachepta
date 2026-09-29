import { setAudioModeAsync } from 'expo-audio';

// expo-audio keeps one app-wide audio mode, and every setAudioModeAsync call replaces all of it: an option
// left out goes back to its default. On Android that default for shouldPlayInBackground is false, which
// pauses stories as soon as the screen locks. So every caller goes through here and keeps the playback
// settings, changing only what it needs (the recorder turns recording on and off).
const PLAYBACK = { playsInSilentMode: true, shouldPlayInBackground: true, interruptionMode: 'doNotMix' } as const;

export function setAudioMode(options: { allowsRecording?: boolean } = {}) {
  return setAudioModeAsync({ ...PLAYBACK, allowsRecording: options.allowsRecording ?? false });
}
