import Ionicons from '@expo/vector-icons/Ionicons';
import { router } from 'expo-router';
import { useState } from 'react';
import { Pressable, ScrollView, View, type LayoutChangeEvent } from 'react-native';

import { Button, Chip, Cover, Screen, Text, useColors } from '@/components/ui';
import { mediaUrl } from '@/lib/api';
import { formatClock, useI18n } from '@/lib/i18n';
import { usePlayer } from '@/lib/player/PlayerProvider';
import { SLEEP_CHOICES, SPEEDS } from '@/lib/player/logic';
import { space, touch } from '@/lib/theme';

export default function Player() {
  const { t } = useI18n();
  const colors = useColors();
  const player = usePlayer();
  const [barWidth, setBarWidth] = useState(1);
  const { story } = player;

  if (!story) {
    return (
      <Screen>
        <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center', gap: space.lg }}>
          <Text muted>{t('home.empty')}</Text>
          <Button title={t('common.back')} kind="secondary" onPress={() => router.back()} />
        </View>
      </Screen>
    );
  }

  const progress = player.duration ? player.position / player.duration : 0;
  const sleepLabel = (mode: (typeof SLEEP_CHOICES)[number]) =>
    mode === 'off' ? t('player.sleepOff') : mode === 'end' ? t('player.sleepEnd') : t('common.min', { n: mode });

  return (
    <Screen>
      <ScrollView contentContainerStyle={{ gap: space.xl, paddingVertical: space.lg, maxWidth: 520, width: '100%', alignSelf: 'center' }}>
        <View style={{ flexDirection: 'row', alignItems: 'center' }}>
          <Pressable onPress={() => router.back()} hitSlop={12} accessibilityRole="button" accessibilityLabel={t('player.close')}>
            <Ionicons name="chevron-down" size={28} color={colors.text} />
          </Pressable>
          <Text variant="label" muted style={{ flex: 1, textAlign: 'center' }}>{t('player.nowPlaying')}</Text>
          <Pressable onPress={() => { player.setDriveMode(true); router.push('/drive'); }} hitSlop={12} accessibilityRole="button"
            accessibilityLabel={t('player.drive')}>
            <Ionicons name="car-outline" size={26} color={colors.text} />
          </Pressable>
        </View>

        <View style={{ alignItems: 'center', gap: space.md }}>
          <Cover id={story.id} title={story.title} artworkUrl={mediaUrl(story.artworkUrl)} size={280} />
          <Text variant="title" style={{ textAlign: 'center' }}>{story.title}</Text>
          <Text muted>{story.narrator}</Text>
        </View>

        {player.goodnight ? (
          <View style={{ alignItems: 'center', gap: space.sm }}>
            <Ionicons name="moon" size={36} color={colors.primary} />
            <Text variant="heading">{t('player.goodnight')}</Text>
          </View>
        ) : null}
        {player.error ? <Text color={colors.danger}>{player.error}</Text> : null}

        <View style={{ gap: space.sm }}>
          <Pressable
            onLayout={(e: LayoutChangeEvent) => setBarWidth(e.nativeEvent.layout.width || 1)}
            onPress={(e) => player.seekTo((e.nativeEvent.locationX / barWidth) * player.duration)}
            accessibilityRole="adjustable" accessibilityLabel="Playback position"
            accessibilityValue={{ min: 0, max: Math.round(player.duration), now: Math.round(player.position), text: formatClock(player.position) }}
            accessibilityActions={[{ name: 'increment' }, { name: 'decrement' }]}
            onAccessibilityAction={(e) => player.seekBy(e.nativeEvent.actionName === 'increment' ? 30 : -15)}
            style={{ height: 28, justifyContent: 'center' }}>
            <View style={{ height: 6, borderRadius: 3, backgroundColor: colors.border }}>
              <View style={{ width: `${progress * 100}%`, height: 6, borderRadius: 3, backgroundColor: colors.accent }} />
            </View>
          </Pressable>
          <View style={{ flexDirection: 'row', justifyContent: 'space-between' }}>
            <Text variant="small" muted>{formatClock(player.position)}</Text>
            <Text variant="small" muted>-{formatClock(Math.max(0, player.duration - player.position))}</Text>
          </View>
        </View>

        <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-evenly' }}>
          <Round icon="play-skip-back" label={t('player.previous')} onPress={player.previous} />
          <Round icon="play-back" label={t('player.back15')} onPress={() => player.seekBy(-15)} badge="15" />
          <Pressable onPress={player.toggle} accessibilityRole="button" accessibilityLabel={player.playing ? t('player.pause') : t('player.play')}
            style={{ width: 84, height: 84, borderRadius: 42, backgroundColor: colors.accent, alignItems: 'center', justifyContent: 'center' }}>
            <Ionicons name={player.playing ? 'pause' : 'play'} size={40} color={colors.onAccent} />
          </Pressable>
          <Round icon="play-forward" label={t('player.forward30')} onPress={() => player.seekBy(30)} badge="30" />
          <Round icon="play-skip-forward" label={t('player.next')} onPress={player.next} disabled={!player.queue.length} />
        </View>

        <Section title={t('player.sleep')} detail={player.sleepSecondsLeft != null
          ? t('player.sleepIn', { time: formatClock(player.sleepSecondsLeft) }) : undefined}>
          {SLEEP_CHOICES.map((mode) => (
            <Chip key={String(mode)} label={sleepLabel(mode)} selected={player.sleep === mode} onPress={() => player.setSleep(mode)} />
          ))}
        </Section>

        <Section title={t('player.speed')}>
          {SPEEDS.map((speed) => (
            <Chip key={speed} label={`${speed}×`} selected={player.rate === speed} onPress={() => player.setRate(speed)} />
          ))}
        </Section>

        <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: space.sm }}>
          <Chip label={t('player.bedtime')} selected={player.bedtime} onPress={() => player.setBedtime(!player.bedtime)}
            icon={<Ionicons name="moon-outline" size={16} color={player.bedtime ? colors.onPrimary : colors.text} />} />
          <Chip label={t('player.dataSaver')} selected={player.dataSaver} onPress={() => player.setDataSaver(!player.dataSaver)}
            icon={<Ionicons name="cellular-outline" size={16} color={player.dataSaver ? colors.onPrimary : colors.text} />} />
        </View>
        {player.bedtime ? <Text variant="small" muted>{t('player.bedtimeOn')}</Text> : null}
      </ScrollView>
    </Screen>
  );
}

function Section({ title, detail, children }: { title: string; detail?: string; children: React.ReactNode }) {
  return (
    <View style={{ gap: space.sm }}>
      <View style={{ flexDirection: 'row', justifyContent: 'space-between' }}>
        <Text variant="label" muted>{title}</Text>
        {detail ? <Text variant="label" muted>{detail}</Text> : null}
      </View>
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: space.sm }}>{children}</View>
    </View>
  );
}

function Round({ icon, label, onPress, badge, disabled }: { icon: keyof typeof Ionicons.glyphMap; label: string; onPress: () => void;
  badge?: string; disabled?: boolean }) {
  const colors = useColors();
  return (
    <Pressable onPress={onPress} disabled={disabled} accessibilityRole="button" accessibilityLabel={label}
      style={{ width: touch + 4, height: touch + 4, alignItems: 'center', justifyContent: 'center', opacity: disabled ? 0.35 : 1 }}>
      <Ionicons name={icon} size={28} color={colors.text} />
      {badge ? <Text variant="label" muted style={{ fontSize: 10, lineHeight: 12 }}>{badge}</Text> : null}
    </Pressable>
  );
}
