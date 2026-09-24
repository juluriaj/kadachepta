import Ionicons from '@expo/vector-icons/Ionicons';
import { useAudioPlayer, useAudioPlayerStatus } from 'expo-audio';
import { useEffect, useState } from 'react';
import { Platform, Pressable, View } from 'react-native';

import { Text, useColors } from '@/components/ui';
import { mediaUrl } from '@/lib/api';
import { formatClock } from '@/lib/i18n';
import { getEngine } from '@/lib/player/engine';
import { space } from '@/lib/theme';

const SPEEDS = [1, 1.25, 1.5, 2];

// The editor's review player: waveform to jump around, speed for skimming, keyboard on the web
// (Space play/pause, [ and ] ten seconds back and forward), ignored while typing.
export function StudioPlayer({ url, waveform, duration }: { url: string | null; waveform: number[]; duration: number }) {
  const colors = useColors();
  const player = useAudioPlayer(url ? { uri: mediaUrl(url)! } : null);
  const status = useAudioPlayerStatus(player);
  const [speed, setSpeed] = useState(1);
  const [width, setWidth] = useState(1);
  const total = status.duration || duration || 1;
  const position = status.currentTime || 0;

  const toggle = () => {
    if (status.playing) player.pause();
    else {
      if (getEngine().getSnapshot().playing) getEngine().toggle();
      player.play();
    }
  };

  useEffect(() => {
    if (Platform.OS !== 'web') return;
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target && ['INPUT', 'TEXTAREA'].includes(target.tagName)) return;
      if (event.key === ' ') {
        if (player.playing) player.pause();
        else player.play();
      } else if (event.key === '[') void player.seekTo(Math.max(0, player.currentTime - 10));
      else if (event.key === ']') void player.seekTo(player.currentTime + 10);
      else return;
      event.preventDefault();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [player]);

  const bars = waveform.length ? waveform : Array.from({ length: 80 }, () => 0.3);
  return (
    <View style={{ gap: space.sm }}>
      <Pressable accessibilityRole="adjustable" accessibilityLabel="Seek in the recording"
        onLayout={(event) => setWidth(event.nativeEvent.layout.width)}
        onPress={(event) => void player.seekTo((event.nativeEvent.locationX / width) * total)}
        style={{ flexDirection: 'row', alignItems: 'center', height: 64, gap: 1 }}>
        {bars.map((value, index) => (
          <View key={index} style={{ flex: 1, height: Math.max(2, value * 60), borderRadius: 1,
            backgroundColor: index / bars.length <= position / total ? colors.primary : colors.border }} />
        ))}
      </Pressable>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: space.lg }}>
        <Pressable accessibilityRole="button" accessibilityLabel="Back 10 seconds" onPress={() => void player.seekTo(Math.max(0, position - 10))}>
          <Ionicons name="play-back" size={24} color={colors.text} />
        </Pressable>
        <Pressable accessibilityRole="button" accessibilityLabel={status.playing ? 'Pause' : 'Play'} onPress={toggle}
          style={{ width: 48, height: 48, borderRadius: 24, backgroundColor: colors.primary, alignItems: 'center', justifyContent: 'center' }}>
          <Ionicons name={status.playing ? 'pause' : 'play'} size={24} color={colors.onPrimary} />
        </Pressable>
        <Pressable accessibilityRole="button" accessibilityLabel="Forward 10 seconds" onPress={() => void player.seekTo(position + 10)}>
          <Ionicons name="play-forward" size={24} color={colors.text} />
        </Pressable>
        <Text variant="small">{formatClock(position)} / {formatClock(total)}</Text>
        <View style={{ flex: 1 }} />
        <Pressable accessibilityRole="button" accessibilityLabel="Playback speed" onPress={() => {
          const next = SPEEDS[(SPEEDS.indexOf(speed) + 1) % SPEEDS.length];
          setSpeed(next);
          player.setPlaybackRate(next);
        }}>
          <Text variant="heading">{speed}×</Text>
        </Pressable>
      </View>
    </View>
  );
}
