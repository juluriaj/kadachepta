import Ionicons from '@expo/vector-icons/Ionicons';
import { router } from 'expo-router';
import { useEffect, useRef, useState } from 'react';
import { FlatList, Platform, Pressable, View } from 'react-native';

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
      onPress={() => router.push(`/story/${story.id}`)} testID="story-card"
      style={(state) => ({ width, gap: space.sm, opacity: state.pressed ? 0.8 : 1, borderRadius: radius.md,
        // react-native-web reports keyboard focus: show where the arrow keys are
        ...(Platform.OS === 'web' ? { outlineStyle: 'solid', outlineOffset: 4, outlineColor: colors.primary,
          outlineWidth: (state as { focused?: boolean }).focused ? 3 : 0 } as object : {}) })}>
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

// On a computer there's no swipe: arrow buttons scroll a shelf, and the arrow keys move between stories
// (left/right within a shelf, up/down between shelves; Enter opens). Phones keep swiping.
const canHover = () => Platform.OS === 'web' && typeof window !== 'undefined'
  && !!window.matchMedia?.('(hover: hover) and (pointer: fine)').matches;

function moveFocus(event: KeyboardEvent) {
  if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
  if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) return;
  const active = document.activeElement as HTMLElement | null;
  const shelves = [...document.querySelectorAll<HTMLElement>('[data-testid="shelf"]')];
  const cardsOf = (shelf: HTMLElement) => [...shelf.querySelectorAll<HTMLElement>('[data-testid="story-card"]')];
  const go = (card: HTMLElement | undefined) => {
    if (!card) return;
    event.preventDefault();
    card.focus({ preventScroll: true });
    card.scrollIntoView({ block: 'nearest', inline: 'nearest', behavior: 'smooth' });
  };
  const card = active?.closest<HTMLElement>('[data-testid="story-card"]');
  if (!card) {
    // Nothing chosen yet: left/right starts at the first story (up/down keep scrolling the page).
    const typing = active && ['INPUT', 'TEXTAREA', 'SELECT'].includes(active.tagName);
    if (!typing && (event.key === 'ArrowRight' || event.key === 'ArrowLeft') && shelves[0]) go(cardsOf(shelves[0])[0]);
    return;
  }
  const shelf = card.closest<HTMLElement>('[data-testid="shelf"]');
  if (!shelf) return;
  const cards = cardsOf(shelf);
  const index = cards.indexOf(card);
  if (event.key === 'ArrowRight') go(cards[index + 1]);
  else if (event.key === 'ArrowLeft') go(cards[index - 1]);
  else {
    const next = shelves[shelves.indexOf(shelf) + (event.key === 'ArrowDown' ? 1 : -1)];
    if (next) {
      const target = cardsOf(next);
      go(target[Math.min(index, target.length - 1)]);
    }
  }
}

let keyListeners = 0;

function useArrowKeys() {
  useEffect(() => {
    if (Platform.OS !== 'web') return;
    if (keyListeners++ === 0) window.addEventListener('keydown', moveFocus);
    return () => {
      if (--keyListeners === 0) window.removeEventListener('keydown', moveFocus);
    };
  }, []);
}

export function Shelf({ title, items, onSeeAll }: { title: string; items: Story[]; onSeeAll?: () => void }) {
  const { t } = useI18n();
  const colors = useColors();
  const list = useRef<FlatList<Story>>(null);
  const [offset, setOffset] = useState(0);
  const [visible, setVisible] = useState(0);
  const [content, setContent] = useState(0);
  const [hover] = useState(canHover);
  useArrowKeys();
  const scrollBy = (direction: 1 | -1) => list.current?.scrollToOffset({
    offset: Math.max(0, Math.min(content - visible, offset + direction * visible * 0.8)), animated: true });
  const arrow = (direction: 1 | -1, enabled: boolean) => (
    <Pressable accessibilityRole="button" accessibilityLabel={t(direction === 1 ? 'shelf.next' : 'shelf.previous')}
      disabled={!enabled} onPress={() => scrollBy(direction)} hitSlop={8}
      style={{ width: 36, height: 36, borderRadius: 18, alignItems: 'center', justifyContent: 'center',
        borderWidth: 1, borderColor: colors.border, opacity: enabled ? 1 : 0.35 }}>
      <Ionicons name={direction === 1 ? 'chevron-forward' : 'chevron-back'} size={20} color={colors.text} />
    </Pressable>
  );
  return (
    <View style={{ gap: space.md }} testID="shelf">
      <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: space.sm,
        paddingHorizontal: space.lg }}>
        <Text variant="title" accessibilityRole="header" style={{ fontSize: 19, flex: 1 }}>{title}</Text>
        {hover && content > visible + 1 ? (
          <>
            {arrow(-1, offset > 1)}
            {arrow(1, offset < content - visible - 1)}
          </>
        ) : null}
        {onSeeAll ? <Pressable onPress={onSeeAll} hitSlop={12}><Ionicons name="chevron-forward" size={20} /></Pressable> : null}
      </View>
      <FlatList
        ref={list} horizontal data={items} keyExtractor={(item) => item.id} showsHorizontalScrollIndicator={false}
        contentContainerStyle={{ paddingHorizontal: space.lg, gap: space.lg }}
        onLayout={(event) => setVisible(event.nativeEvent.layout.width)}
        onContentSizeChange={(width) => setContent(width)}
        onScroll={(event) => setOffset(event.nativeEvent.contentOffset.x)} scrollEventThrottle={100}
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
