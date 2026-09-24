import Ionicons from '@expo/vector-icons/Ionicons';
import { router } from 'expo-router';
import { FlatList, Pressable, View } from 'react-native';

import { mediaUrl } from '@/lib/api';
import { useI18n } from '@/lib/i18n';
import { usePlayer } from '@/lib/player/PlayerProvider';
import { radius, space, touch } from '@/lib/theme';
import type { Story } from '@/lib/types';

import { Cover, ProgressBar, Text, useColors } from './ui';

export function minutes(seconds: number) {
  return Math.max(1, Math.round((seconds || 0) / 60));
}

export function StoryCard({ story, width = 150 }: { story: Story; width?: number }) {
  const { t } = useI18n();
  const colors = useColors();
  const progress = story.progress && !story.progress.completed && story.duration
    ? story.progress.position / story.duration : null;
  return (
    <Pressable
      accessibilityRole="button" accessibilityLabel={`${story.title}, ${t('common.min', { n: minutes(story.duration) })}`}
      onPress={() => router.push(`/story/${story.id}`)}
      style={({ pressed }) => ({ width, gap: space.sm, opacity: pressed ? 0.8 : 1 })}>
      <Cover id={story.id} title={story.title} artworkUrl={mediaUrl(story.artworkUrl)} size={width} />
      {progress !== null ? <ProgressBar value={progress} /> : null}
      <Text variant="heading" numberOfLines={2} style={{ fontSize: 15, lineHeight: 21 }}>{story.title}</Text>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
        <Ionicons name="time-outline" size={13} color={colors.muted} />
        <Text variant="small" muted>{t('common.min', { n: minutes(story.duration) })}</Text>
        {story.favorite ? <Ionicons name="heart" size={13} color={colors.accent} /> : null}
      </View>
    </Pressable>
  );
}

export function Shelf({ title, items, onSeeAll }: { title: string; items: Story[]; onSeeAll?: () => void }) {
  return (
    <View style={{ gap: space.md }}>
      <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: space.lg }}>
        <Text variant="title" accessibilityRole="header" style={{ fontSize: 19 }}>{title}</Text>
        {onSeeAll ? <Pressable onPress={onSeeAll} hitSlop={12}><Ionicons name="chevron-forward" size={20} /></Pressable> : null}
      </View>
      <FlatList
        horizontal data={items} keyExtractor={(item) => item.id} showsHorizontalScrollIndicator={false}
        contentContainerStyle={{ paddingHorizontal: space.lg, gap: space.lg }}
        renderItem={({ item }) => <StoryCard story={item} />}
      />
    </View>
  );
}

export function StoryRow({ story, right }: { story: Story; right?: React.ReactNode }) {
  const { t } = useI18n();
  return (
    <Pressable onPress={() => router.push(`/story/${story.id}`)} accessibilityRole="button"
      style={({ pressed }) => ({ flexDirection: 'row', alignItems: 'center', gap: space.md, minHeight: 72, opacity: pressed ? 0.8 : 1 })}>
      <Cover id={story.id} title={story.title} artworkUrl={mediaUrl(story.artworkUrl)} size={56} rounded={radius.sm} />
      <View style={{ flex: 1, gap: 2 }}>
        <Text variant="heading" numberOfLines={1} style={{ fontSize: 15 }}>{story.title}</Text>
        <Text variant="small" muted numberOfLines={1}>{story.narrator} · {t('common.min', { n: minutes(story.duration) })}</Text>
      </View>
      {right}
    </Pressable>
  );
}

// Compact player above the tab bar: the one control a parent needs while driving or cooking.
export function MiniPlayer() {
  const player = usePlayer();
  const colors = useColors();
  const { t } = useI18n();
  if (!player.story) return null;
  const { story } = player;
  return (
    <Pressable
      onPress={() => router.push('/player')} accessibilityRole="button" accessibilityLabel={t('player.nowPlaying')}
      style={{ flexDirection: 'row', alignItems: 'center', gap: space.md, padding: space.sm, paddingRight: space.md,
        backgroundColor: colors.surface, borderTopWidth: 1, borderColor: colors.border }}>
      <Cover id={story.id} title={story.title} artworkUrl={mediaUrl(story.artworkUrl)} size={48} rounded={radius.sm} />
      <View style={{ flex: 1 }}>
        <Text variant="heading" numberOfLines={1} style={{ fontSize: 14 }}>{story.title}</Text>
        <ProgressBar value={player.duration ? player.position / player.duration : 0} />
      </View>
      <Pressable onPress={player.toggle} hitSlop={10} accessibilityRole="button"
        accessibilityLabel={player.playing ? t('player.pause') : t('player.play')}
        style={{ width: touch, height: touch, borderRadius: touch / 2, alignItems: 'center', justifyContent: 'center',
          backgroundColor: colors.accent }}>
        <Ionicons name={player.playing ? 'pause' : 'play'} size={24} color={colors.onAccent} />
      </Pressable>
    </Pressable>
  );
}
