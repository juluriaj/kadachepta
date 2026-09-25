import { Platform, type GestureResponderEvent } from 'react-native';

// Where along a seek bar a press landed, as a fraction 0–1, or null when it can't be told (a key press).
// On native the event carries locationX. On the web, react-native-web passes Pressable.onPress the raw
// MouseEvent, which has no locationX, so measure clientX against the bar's own box instead; this also
// stays right when the click lands on a child (a waveform bar, the filled part of the track).
export function pressFraction(event: GestureResponderEvent, width: number): number | null {
  const native = event.nativeEvent as unknown as { locationX?: number; clientX?: number };
  let x = native.locationX;
  if (Platform.OS === 'web') {
    const rect = (event.currentTarget as unknown as HTMLElement | null)?.getBoundingClientRect?.();
    if (!rect || typeof native.clientX !== 'number') return null;
    x = native.clientX - rect.left;
    width = rect.width;
  }
  if (typeof x !== 'number' || !Number.isFinite(x) || !(width > 0)) return null;
  return Math.min(1, Math.max(0, x / width));
}
