import Ionicons from '@expo/vector-icons/Ionicons';
import {
  RecordingPresets, requestRecordingPermissionsAsync, setAudioModeAsync, useAudioRecorder, useAudioRecorderState,
  type RecordingOptions,
} from 'expo-audio';
import { useKeepAwake } from 'expo-keep-awake';
import { useState } from 'react';
import { Platform, Pressable, ScrollView, View } from 'react-native';

import { Button, Text, useColors } from '@/components/ui';
import { formatClock, useI18n } from '@/lib/i18n';
import { getEngine } from '@/lib/player/engine';
import { levelFromDb, levelHint } from '@/lib/recording';
import { radius, space } from '@/lib/theme';

export type Take = { uri: string; name: string; seconds: number };

// Mono AAC at 96 kbps is plenty for speech and keeps a 30-minute story around 20 MB.
const OPTIONS: RecordingOptions = {
  ...RecordingPresets.HIGH_QUALITY, numberOfChannels: 1, bitRate: 96000, isMeteringEnabled: true,
  web: { mimeType: 'audio/webm', bitsPerSecond: 96000 },
};

function KeepAwake() {
  useKeepAwake();
  return null;
}

// Record a story in parts: pause and continue within a part, finish a part, and redo the last part.
// The parts are joined in order on the server.
export function Recorder({ takes, onChange, teleprompter, maxSeconds }: {
  takes: Take[]; onChange: (takes: Take[]) => void; teleprompter?: string; maxSeconds?: number;
}) {
  const { t } = useI18n();
  const colors = useColors();
  const recorder = useAudioRecorder(OPTIONS);
  const state = useAudioRecorderState(recorder, 120);
  const [active, setActive] = useState(false);
  const [paused, setPaused] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const level = levelFromDb(state.metering);
  const hint = active && !paused ? levelHint(state.metering) : null;
  const recorded = takes.reduce((sum, take) => sum + take.seconds, 0) + (active ? state.durationMillis / 1000 : 0);

  const start = async () => {
    setError(null);
    const permission = await requestRecordingPermissionsAsync();
    if (!permission.granted) {
      setError(t('rec.permission'));
      return;
    }
    if (getEngine().getSnapshot().playing) getEngine().toggle(); // never record over a playing story
    await setAudioModeAsync({ allowsRecording: true, playsInSilentMode: true });
    await recorder.prepareToRecordAsync();
    recorder.record(maxSeconds ? { forDuration: maxSeconds } : undefined);
    setActive(true);
    setPaused(false);
  };

  const togglePause = () => {
    if (paused) recorder.record();
    else recorder.pause();
    setPaused(!paused);
  };

  const finish = async () => {
    const seconds = state.durationMillis / 1000;
    await recorder.stop();
    await setAudioModeAsync({ allowsRecording: false, playsInSilentMode: true });
    setActive(false);
    setPaused(false);
    const uri = recorder.uri;
    if (uri) {
      const extension = Platform.OS === 'web' ? 'webm' : 'm4a';
      onChange([...takes, { uri, seconds, name: `part-${takes.length + 1}.${extension}` }]);
    }
  };

  return (
    <View style={{ gap: space.md }}>
      {active ? <KeepAwake /> : null}
      {teleprompter ? (
        <ScrollView style={{ maxHeight: 220, borderRadius: radius.md, backgroundColor: colors.surfaceAlt, padding: space.md }}>
          <Text style={{ fontSize: 20, lineHeight: 34 }}>{teleprompter}</Text>
        </ScrollView>
      ) : null}
      <View style={{ alignItems: 'center', gap: space.sm, paddingVertical: space.md }}>
        <Text variant="display" accessibilityLiveRegion="polite">{formatClock(recorded)}</Text>
        <Text variant="small" muted>
          {active ? (paused ? t('rec.paused') : t('rec.recording')) : t('rec.takes', { n: takes.length, time: formatClock(recorded) })}
        </Text>
        <View accessibilityRole="progressbar" accessibilityValue={{ min: 0, max: 100, now: Math.round(level * 100) }}
          style={{ width: '100%', height: 10, borderRadius: 5, backgroundColor: colors.border, overflow: 'hidden' }}>
          <View style={{ width: `${level * 100}%`, height: 10, backgroundColor: hint === 'loud' ? colors.danger : colors.success }} />
        </View>
        {hint ? (
          <Text variant="small" color={hint === 'good' ? colors.success : colors.danger}>
            {hint === 'quiet' ? t('rec.tooQuiet') : hint === 'loud' ? t('rec.tooLoud') : t('rec.good')}
          </Text>
        ) : null}
      </View>
      {error ? <Text color={colors.danger}>{error}</Text> : null}
      {active ? (
        <View style={{ flexDirection: 'row', gap: space.md }}>
          <Button style={{ flex: 1 }} kind="secondary" title={paused ? t('rec.resume') : t('rec.pause')}
            icon={<Ionicons name={paused ? 'mic' : 'pause'} size={20} color={colors.text} />} onPress={togglePause} />
          <Button style={{ flex: 1 }} title={t('rec.stop')} icon={<Ionicons name="stop" size={20} color={colors.onPrimary} />}
            onPress={() => void finish()} />
        </View>
      ) : (
        <View style={{ gap: space.sm }}>
          <RecordButton onPress={() => void start()} label={t('rec.start')} />
          {takes.length ? (
            <Button kind="ghost" title={t('rec.retake')} icon={<Ionicons name="arrow-undo" size={18} color={colors.primary} />}
              onPress={() => onChange(takes.slice(0, -1))} />
          ) : null}
        </View>
      )}
      <Text variant="small" muted>{t('rec.tips')}</Text>
    </View>
  );
}

function RecordButton({ onPress, label }: { onPress: () => void; label: string }) {
  const colors = useColors();
  return (
    <Pressable accessibilityRole="button" accessibilityLabel={label} onPress={onPress}
      style={({ pressed }) => ({ alignSelf: 'center', alignItems: 'center', gap: space.sm, opacity: pressed ? 0.8 : 1 })}>
      <View style={{ width: 84, height: 84, borderRadius: 42, backgroundColor: colors.danger, alignItems: 'center',
        justifyContent: 'center' }}>
        <Ionicons name="mic" size={40} color="#fff" />
      </View>
      <Text variant="heading">{label}</Text>
    </Pressable>
  );
}
