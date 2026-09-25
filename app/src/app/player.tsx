import Ionicons from '@expo/vector-icons/Ionicons';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { router } from 'expo-router';
import { useEffect, useRef, useState } from 'react';
import { Pressable, ScrollView, View, type LayoutChangeEvent } from 'react-native';

import { Button, Chip, Cover, Screen, Text, useColors } from '@/components/ui';
import { api, mediaUrl } from '@/lib/api';
import { formatClock, useI18n } from '@/lib/i18n';
import { usePlayer } from '@/lib/player/PlayerProvider';
import { SLEEP_CHOICES, SPEEDS } from '@/lib/player/logic';
import { useSession } from '@/lib/session';
import { space, touch } from '@/lib/theme';
import type { StoryDetail } from '@/lib/types';

export default function Player() {
  const { t } = useI18n();
  const colors = useColors();
  const player = usePlayer();
  const [barWidth, setBarWidth] = useState(1);
  const [reading, setReading] = useState(false);
  const { story } = player;
  const detail = useStoryDetail(story?.id);
  const canRead = !!detail.data?.readAlong;

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
          {reading && canRead ? (
            <ReadAlong storyId={story.id} position={player.position} onSeek={player.seekTo} />
          ) : (
            <Cover id={story.id} title={story.title} artworkUrl={mediaUrl(story.artworkUrl)} size={280} />
          )}
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: space.md }}>
            {canRead ? (
              <Pressable onPress={() => setReading(!reading)} hitSlop={12} accessibilityRole="button"
                accessibilityState={{ selected: reading }} accessibilityLabel={reading ? t('player.showCover') : t('player.readAlong')}
                style={{ width: 40, height: 40, alignItems: 'center', justifyContent: 'center' }}>
                <Ionicons name={reading ? 'image-outline' : 'document-text-outline'} size={26} color={colors.text} />
              </Pressable>
            ) : <View style={{ width: 40 }} />}
            <View style={{ flexShrink: 1, alignItems: 'center', gap: space.xs }}>
              <Text variant="title" style={{ textAlign: 'center' }}>{story.title}</Text>
              <Text muted>{story.narrator}</Text>
            </View>
            <FavoriteButton storyId={story.id} fallback={!!story.favorite} />
          </View>
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

// Save to favorites without leaving the player. Shares the story page's cached data, so both stay in step.
function FavoriteButton({ storyId, fallback }: { storyId: string; fallback: boolean }) {
  const { t } = useI18n();
  const colors = useColors();
  const queryClient = useQueryClient();
  const { profile } = useSession();
  const key = ['story', storyId, profile?.id];
  const detail = useStoryDetail(storyId);
  const [pending, setPending] = useState<boolean | null>(null);
  const saved = pending ?? detail.data?.favorite ?? fallback;

  const toggle = async () => {
    const next = !saved;
    setPending(next);
    try {
      await api('/api/me/favorites', { method: 'POST', body: { assetId: storyId, saved: next } });
      queryClient.setQueryData<StoryDetail>(key, (old) => (old ? { ...old, favorite: next } : old));
      void queryClient.invalidateQueries({ queryKey: ['home'] });
      void queryClient.invalidateQueries({ queryKey: ['catalog'] });
    } catch {
      // Offline or failed: show the real state again.
    } finally {
      setPending(null);
    }
  };

  return (
    <Pressable onPress={() => void toggle()} hitSlop={12} accessibilityRole="button" accessibilityState={{ selected: saved }}
      accessibilityLabel={saved ? t('story.removeFavorite') : t('story.addFavorite')}
      style={{ width: 40, height: 40, alignItems: 'center', justifyContent: 'center' }}>
      <Ionicons name={saved ? 'heart' : 'heart-outline'} size={28} color={saved ? colors.accent : colors.text} />
    </Pressable>
  );
}

// The story page's data (favorite, read-along availability), shared through the query cache.
function useStoryDetail(storyId: string | undefined) {
  const { profile } = useSession();
  return useQuery({ queryKey: ['story', storyId, profile?.id], enabled: !!storyId && !!profile,
    queryFn: () => api<StoryDetail>(`/api/stories/${storyId}`) });
}

type Passage = { start: number | null; end: number | null; text: string };

// P2-19: read along. The passage being spoken is highlighted and kept in view; tap a passage to jump to it.
// Offered only when an editor turned captions on, which means they read and approved the text.
function ReadAlong({ storyId, position, onSeek }: { storyId: string; position: number; onSeek: (seconds: number) => void }) {
  const { t } = useI18n();
  const colors = useColors();
  const { profile } = useSession();
  const text = useQuery({ queryKey: ['read-along', storyId, profile?.id], enabled: !!profile, staleTime: Infinity,
    queryFn: () => api<{ timed: boolean; passages: Passage[] }>(`/api/stories/${storyId}/read-along`) });
  const scroller = useRef<ScrollView>(null);
  const offsets = useRef<number[]>([]);
  const passages = text.data?.passages ?? [];
  let current = -1;
  passages.forEach((passage, index) => {
    if (passage.start != null && passage.start <= position) current = index;
  });

  useEffect(() => {
    if (current >= 0 && offsets.current[current] != null) {
      scroller.current?.scrollTo({ y: Math.max(0, offsets.current[current] - 60), animated: true });
    }
  }, [current]);

  return (
    <View style={{ height: 320, width: '100%', borderRadius: 16, borderWidth: 1, borderColor: colors.border,
      backgroundColor: colors.surface, overflow: 'hidden' }}>
      {text.isLoading ? <Text muted style={{ padding: space.lg }}>…</Text> : text.error ? (
        <Text muted style={{ padding: space.lg }}>{t('player.readAlongUnavailable')}</Text>
      ) : (
        <ScrollView ref={scroller} contentContainerStyle={{ padding: space.lg, gap: space.md }}>
          {passages.map((passage, index) => {
            const active = index === current;
            return (
              <Pressable key={index} disabled={passage.start == null} onPress={() => passage.start != null && onSeek(passage.start)}
                onLayout={(event) => { offsets.current[index] = event.nativeEvent.layout.y; }}
                accessibilityRole={passage.start == null ? 'text' : 'button'}
                style={{ borderRadius: 8, padding: space.xs, backgroundColor: active ? colors.surfaceAlt : 'transparent' }}>
                <Text style={{ fontSize: 18, lineHeight: 30, opacity: current < 0 || active ? 1 : 0.6 }}>{passage.text}</Text>
              </Pressable>
            );
          })}
        </ScrollView>
      )}
    </View>
  );
}
