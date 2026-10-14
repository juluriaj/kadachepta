import Ionicons from '@expo/vector-icons/Ionicons';
import { router } from 'expo-router';
import { Platform, Pressable, View } from 'react-native';

import { formatListening, useI18n, type Translate } from '@/lib/i18n';
import { radius, space } from '@/lib/theme';
import type { BookSummary, StorySet } from '@/lib/types';

import { minutes } from './stories';
import { Cover, ProgressBar, Text, useColors } from './ui';

// Story sets are browsed and shuffled; audiobooks are one work heard in order. Each gets its own tile and row.

export function setTitle(set: { titles: Record<string, string> }, language: string) {
  return set.titles[`${language}-IN`] ?? set.titles['en-IN'] ?? Object.values(set.titles)[0] ?? '';
}

export function shuffled<T>(items: T[]): T[] {
  const copy = [...items];
  for (let i = copy.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [copy[i], copy[j]] = [copy[j], copy[i]];
  }
  return copy;
}

// The one button on a book's page: "Start", "Continue · Chapter 12, 8 min left", or "Listen again".
export function resumeLabel(t: Translate, book: BookSummary) {
  const { resume } = book;
  if (resume.state === 'start') return t('book.start');
  if (resume.state === 'finished') return t('book.again');
  return resume.position >= 10 ? t('book.continue', { n: resume.chapter, min: minutes(resume.remaining) })
    : t('book.continueChapter', { n: resume.chapter });
}

const focusOutline = (focused: boolean, color: string) => (Platform.OS === 'web'
  ? { outlineStyle: 'solid', outlineOffset: 4, outlineColor: color, outlineWidth: focused ? 3 : 0 } as object : {});

// testID "story-card" puts tiles in the shelves' arrow-key navigation on computers.
export function SetTile({ set, width = 150 }: { set: StorySet; width?: number }) {
  const { t, language } = useI18n();
  const colors = useColors();
  const name = setTitle(set, language);
  return (
    <Pressable onPress={() => router.push(`/collection/${set.id}`)} testID="story-card" accessibilityRole="button"
      accessibilityLabel={`${name}, ${t('collection.count', { n: set.storyCount })}`}
      style={(state) => ({ width, gap: space.sm, opacity: state.pressed ? 0.8 : 1, borderRadius: radius.md,
        ...focusOutline(!!(state as { focused?: boolean }).focused, colors.primary) })}>
      <View style={{ paddingTop: 6 }}>
        {/* A second card peeking out behind the cover: this is a set of stories, not one story. */}
        <View style={{ position: 'absolute', top: 0, left: 8, right: 8, height: 12, borderRadius: radius.md,
          backgroundColor: colors.muted, opacity: 0.35 }} />
        <Cover id={`set-${set.id}`} title={name} artworkUrl={set.artworkUrl} size={width} />
      </View>
      <Text variant="heading" numberOfLines={2} style={{ fontSize: 15, lineHeight: 21 }}>{name}</Text>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
        <Ionicons name="albums-outline" size={13} color={colors.muted} />
        <Text variant="small" muted>
          {set.heard ? t('collection.heard', { n: set.heard, total: set.storyCount }) : t('collection.count', { n: set.storyCount })}
        </Text>
      </View>
    </Pressable>
  );
}

export function BookTile({ book, width = 150 }: { book: BookSummary; width?: number }) {
  const { t } = useI18n();
  const colors = useColors();
  const started = book.resume.state === 'continue' && !!book.lastListenedAt;
  return (
    <Pressable onPress={() => router.push(`/book/${book.id}`)} testID="story-card" accessibilityRole="button"
      accessibilityLabel={`${book.title}, ${t('book.chapters', { n: book.chapterCount })}`}
      style={(state) => ({ width, gap: space.sm, opacity: state.pressed ? 0.8 : 1, borderRadius: radius.md,
        ...focusOutline(!!(state as { focused?: boolean }).focused, colors.primary) })}>
      <Cover id={`book-${book.id}`} title={book.title} artworkUrl={book.artworkUrl} size={width} />
      {started ? <ProgressBar value={book.finished / Math.max(1, book.chapterCount)} /> : null}
      <Text variant="heading" numberOfLines={2} style={{ fontSize: 15, lineHeight: 21 }}>{book.title}</Text>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
        <Ionicons name="book-outline" size={13} color={colors.muted} />
        <Text variant="small" muted numberOfLines={1} style={{ flexShrink: 1 }}>
          {started ? t('book.chShort', { n: book.resume.chapter, total: book.chapterCount })
            : `${t('book.chapters', { n: book.chapterCount })} · ${formatListening(t, book.duration)}`}
        </Text>
      </View>
    </Pressable>
  );
}

function Row({ cover, title, detail, icon, onPress }: { cover: React.ReactNode; title: string; detail: string;
  icon: keyof typeof Ionicons.glyphMap; onPress: () => void }) {
  const colors = useColors();
  return (
    <Pressable onPress={onPress} accessibilityRole="button" accessibilityLabel={`${title}, ${detail}`}
      style={({ pressed }) => ({ flexDirection: 'row', alignItems: 'center', gap: space.md, minHeight: 72, opacity: pressed ? 0.8 : 1 })}>
      {cover}
      <View style={{ flex: 1, gap: 2 }}>
        <Text variant="heading" numberOfLines={1} style={{ fontSize: 15 }}>{title}</Text>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
          <Ionicons name={icon} size={13} color={colors.muted} />
          <Text variant="small" muted numberOfLines={1} style={{ flexShrink: 1 }}>{detail}</Text>
        </View>
      </View>
      <Ionicons name="chevron-forward" size={18} color={colors.muted} />
    </Pressable>
  );
}

export function SetRow({ set }: { set: StorySet }) {
  const { t, language } = useI18n();
  const name = setTitle(set, language);
  return (
    <Row title={name} icon="albums-outline" onPress={() => router.push(`/collection/${set.id}`)}
      detail={set.heard ? t('collection.heard', { n: set.heard, total: set.storyCount }) : t('collection.count', { n: set.storyCount })}
      cover={<Cover id={`set-${set.id}`} title={name} artworkUrl={set.artworkUrl} size={56} rounded={radius.sm} />} />
  );
}

export function BookRow({ book }: { book: BookSummary }) {
  const { t } = useI18n();
  return (
    <Row title={book.title} icon="book-outline" onPress={() => router.push(`/book/${book.id}`)}
      detail={`${book.narrator} · ${t('book.chapters', { n: book.chapterCount })} · ${formatListening(t, book.duration)}`}
      cover={<Cover id={`book-${book.id}`} title={book.title} artworkUrl={book.artworkUrl} size={56} rounded={radius.sm} />} />
  );
}
