import Ionicons from '@expo/vector-icons/Ionicons';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { router } from 'expo-router';
import { Fragment, useEffect, useRef, useState, useSyncExternalStore, type ReactElement, type ReactNode } from 'react';
import {
  FlatList, Platform, Pressable, StyleSheet, useWindowDimensions, View, type FlatListProps, type StyleProp, type ViewStyle,
} from 'react-native';

import { mediaUrl } from '@/lib/api';
import { downloadStory, downloadsSupported, localUri } from '@/lib/downloads';
import { useI18n } from '@/lib/i18n';
import { usePlayer } from '@/lib/player/PlayerProvider';
import { radius, space, touch } from '@/lib/theme';
import type { NarratorCredit, NarratorSummary, Story } from '@/lib/types';

import { Button, Cover, ProgressBar, Text, useColors } from './ui';

export function minutes(seconds: number) {
  return Math.max(1, Math.round((seconds || 0) / 60));
}

// A chapter on a shelf stands for its book ("Barister Parvateesam · Ch 12 of 58") and opens the book, except in a
// list of the book's own chapters (chapterView), where each card is that chapter.
export function StoryCard({ story, width = 150, chapterView, onPress }: { story: Story; width?: number; chapterView?: boolean;
  onPress?: () => void }) {
  const { t, title } = useI18n();
  const colors = useColors();
  const progress = story.progress && !story.progress.completed && story.duration
    ? story.progress.position / story.duration : null;
  const book = chapterView ? null : story.book;
  const name = book ? book.title : title(story);
  const detail = book ? t('book.chShort', { n: book.chapter, total: book.chapters })
    : story.book ? t('book.chapter', { n: story.book.chapter }) : t('common.min', { n: minutes(story.duration) });
  return (
    <Pressable
      accessibilityRole="button" accessibilityLabel={`${name}, ${detail}`}
      onPress={onPress ?? (() => router.push(book ? `/book/${book.id}` : `/story/${story.id}`))} testID="story-card"
      style={(state) => ({ width, gap: space.sm, opacity: state.pressed ? 0.8 : 1, borderRadius: radius.md,
        // react-native-web reports keyboard focus: show where the arrow keys are
        ...(Platform.OS === 'web' ? { outlineStyle: 'solid', outlineOffset: 4, outlineColor: colors.primary,
          outlineWidth: (state as { focused?: boolean }).focused ? 3 : 0 } as object : {}) })}>
      <Cover id={story.id} title={name} artworkUrl={mediaUrl(story.artworkUrl)} size={width} />
      {progress !== null ? <ProgressBar value={progress} /> : null}
      <Text variant="heading" numberOfLines={2} style={{ fontSize: 15, lineHeight: 21 }}>{name}</Text>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
        <Ionicons name={book ? 'book-outline' : 'time-outline'} size={13} color={colors.muted} />
        <Text variant="small" muted>{detail}</Text>
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

export function Shelf({ title, items, onSeeAll, chapterView }: { title: string; items: Story[]; onSeeAll?: () => void;
  chapterView?: boolean }) {
  return <ShelfRow title={title} items={items} onSeeAll={onSeeAll} keyOf={(item) => item.id}
    render={(item) => <StoryCard story={item} chapterView={chapterView} />} />;
}

// A titled, sideways-scrolling row of tiles: stories, story sets, or audiobooks.
export function ShelfRow<T>({ title, items, onSeeAll, keyOf, render }: { title: string; items: T[]; onSeeAll?: () => void;
  keyOf: (item: T) => string; render: (item: T) => ReactElement }) {
  const { t } = useI18n();
  const colors = useColors();
  const list = useRef<FlatList<T>>(null);
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
        ref={list} horizontal data={items} keyExtractor={keyOf} showsHorizontalScrollIndicator={false}
        contentContainerStyle={{ paddingHorizontal: space.lg, gap: space.lg }}
        onLayout={(event) => setVisible(event.nativeEvent.layout.width)}
        onContentSizeChange={(width) => setContent(width)}
        onScroll={(event) => setOffset(event.nativeEvent.contentOffset.x)} scrollEventThrottle={100}
        renderItem={({ item }) => render(item)}
      />
    </View>
  );
}

export function StoryRow({ story, right }: { story: Story; right?: React.ReactNode }) {
  const { t, title } = useI18n();
  return (
    <Pressable onPress={() => router.push(`/story/${story.id}`)} accessibilityRole="button"
      style={({ pressed }) => ({ flexDirection: 'row', alignItems: 'center', gap: space.md, minHeight: 72, opacity: pressed ? 0.8 : 1 })}>
      <Cover id={story.id} title={title(story)} artworkUrl={mediaUrl(story.artworkUrl)} size={56} rounded={radius.sm} />
      <View style={{ flex: 1, gap: 2 }}>
        <Text variant="heading" numberOfLines={1} style={{ fontSize: 15 }}>{title(story)}</Text>
        <Text variant="small" muted numberOfLines={1}>{story.narrator} · {t('common.min', { n: minutes(story.duration) })}</Text>
      </View>
      {right}
    </Pressable>
  );
}

// Long lists of stories show as cover tiles in a grid or as compact rows. The listener picks one for the whole app
// and this device remembers it, the way the player remembers read along.
export type StoryView = 'tiles' | 'list';
const STORY_VIEW = 'kc.storyView';
let storyView: StoryView = 'list';
const storyViewListeners = new Set<() => void>();
const showStoriesAs = (view: StoryView) => {
  storyView = view;
  storyViewListeners.forEach((listener) => listener());
};
const watchStoryView = (listener: () => void) => {
  storyViewListeners.add(listener);
  return () => { storyViewListeners.delete(listener); };
};
AsyncStorage.getItem(STORY_VIEW).then((value) => {
  if (value === 'tiles' || value === 'list') showStoriesAs(value);
}).catch(() => {});

export function useStoryView() {
  const view = useSyncExternalStore(watchStoryView, () => storyView, () => storyView);
  const choose = (next: StoryView) => {
    showStoriesAs(next);
    AsyncStorage.setItem(STORY_VIEW, next).catch(() => {});
  };
  return [view, choose] as const;
}

// Two tiles across a phone, more as the screen widens.
const TILE_MIN = 140;
function grid(width: number) {
  const columns = Math.max(2, Math.floor((width + space.lg) / (TILE_MIN + space.lg)));
  return { columns, tile: Math.floor((width - space.lg * (columns - 1)) / columns) };
}

function TileGap() {
  return <View style={{ height: space.lg }} />;
}

export function StoryViewToggle() {
  const { t } = useI18n();
  const colors = useColors();
  const [view, setView] = useStoryView();
  return (
    <View accessibilityRole="radiogroup" accessibilityLabel={t('stories.viewAs')}
      style={{ flexDirection: 'row', padding: 2, borderRadius: radius.pill, borderWidth: 1, borderColor: colors.border,
        backgroundColor: colors.surface }}>
      {(['tiles', 'list'] as const).map((option) => {
        const selected = view === option;
        return (
          // aria-checked rather than accessibilityState, which react-native-web no longer passes to the page
          <Pressable key={option} onPress={() => setView(option)} accessibilityRole="radio" aria-checked={selected}
            accessibilityLabel={t(option === 'tiles' ? 'stories.tiles' : 'stories.list')} hitSlop={4} testID={`story-view-${option}`}
            style={{ width: 44, height: 40, borderRadius: radius.pill, alignItems: 'center', justifyContent: 'center',
              backgroundColor: selected ? colors.primary : 'transparent' }}>
            <Ionicons name={option === 'tiles' ? 'grid-outline' : 'list'} size={20} color={selected ? colors.onPrimary : colors.text} />
          </Pressable>
        );
      })}
    </View>
  );
}

type StoryListProps = {
  stories: Story[];
  // Beside the toggle: a heading ("58 chapters") or any label.
  title?: ReactNode;
  // With a header, the list does its own scrolling (a FlatList, with the header above the toggle) and takes FlatList
  // props; without one, it sits inside the screen's ScrollView.
  header?: ReactElement;
  // Something for each story: at the end of its row, under its tile.
  accessory?: (story: Story, index: number, view: StoryView) => ReactNode;
  // A row other than StoryRow (a book's chapters), and what tapping a tile does instead of opening the story.
  row?: (story: Story, index: number) => ReactElement;
  onPress?: (story: Story, index: number) => void;
  chapterView?: boolean;
} & Omit<FlatListProps<Story>, 'data' | 'renderItem' | 'keyExtractor' | 'numColumns' | 'columnWrapperStyle'
  | 'ItemSeparatorComponent' | 'ListHeaderComponent'>;

export function StoryList({ stories, title, header, accessory, row, onPress, chapterView, ...list }: StoryListProps) {
  const [view] = useStoryView();
  const screen = useWindowDimensions();
  const [width, setWidth] = useState<number | null>(null);
  // Until the list has measured itself: the screen less its margins, or the list's own maximum width if narrower.
  const maxWidth = StyleSheet.flatten(list.contentContainerStyle)?.maxWidth;
  const guess = Math.min(screen.width - space.lg * 2, typeof maxWidth === 'number' ? maxWidth : Infinity);
  const { columns, tile } = grid(width ?? guess);
  const tiles = view === 'tiles';

  const bar = stories.length ? (
    <View onLayout={(event) => setWidth(event.nativeEvent.layout.width)}
      style={{ flexDirection: 'row', alignItems: 'center', gap: space.md, minHeight: touch, marginBottom: space.sm }}>
      <View style={{ flex: 1 }}>
        {typeof title === 'string' ? <Text variant="heading" accessibilityRole="header">{title}</Text> : title}
      </View>
      <StoryViewToggle />
    </View>
  ) : null;
  const item = (story: Story, index: number) => tiles ? (
    <View style={{ width: tile, gap: space.xs }}>
      <StoryCard story={story} width={tile} chapterView={chapterView} onPress={onPress && (() => onPress(story, index))} />
      {accessory ? <View style={{ flexDirection: 'row', alignItems: 'center' }}>{accessory(story, index, 'tiles')}</View> : null}
    </View>
  ) : row ? row(story, index) : <StoryRow story={story} right={accessory?.(story, index, 'list')} />;

  if (header) {
    return (
      <FlatList {...list} key={tiles ? `tiles-${columns}` : 'list'} data={stories} keyExtractor={(story) => story.id}
        numColumns={tiles ? columns : 1} columnWrapperStyle={tiles ? { gap: space.lg } : undefined}
        ItemSeparatorComponent={tiles ? TileGap : undefined}
        ListHeaderComponent={<>{header}{bar}</>} renderItem={({ item: story, index }) => item(story, index)} />
    );
  }
  return (
    <View>
      {bar}
      <View style={tiles ? { flexDirection: 'row', flexWrap: 'wrap', gap: space.lg } : undefined}>
        {stories.map((story, index) => <Fragment key={story.id}>{item(story, index)}</Fragment>)}
      </View>
    </View>
  );
}

// A narrator's page: by account when they have one, otherwise by the name the catalog credits them with.
export function narratorHref(person: NarratorCredit) {
  return { pathname: '/narrator/[id]' as const, params: { id: person.id != null ? String(person.id) : person.name } };
}

type Credited = Pick<Story, 'narrator' | 'narrators' | 'narratorId'>;

function narratorsOf(story: Credited): NarratorCredit[] {
  return story.narrators ?? (story.narratorId ? [{ name: story.narrator, id: story.narratorId }] : []);
}

// Each credited narrator's name opens their stories. Goes inside a <Text>.
export function NarratorLinks({ story }: { story: Credited }) {
  const people = narratorsOf(story);
  if (!people.length) return <>{story.narrator}</>;
  return (
    <>
      {people.map((person, index) => (
        <Fragment key={person.id ?? person.name}>
          {index ? ', ' : ''}
          <Text muted onPress={() => router.push(narratorHref(person))} accessibilityRole="link"
            style={{ textDecorationLine: 'underline' }}>{person.name}</Text>
        </Fragment>
      ))}
    </>
  );
}

// "Narrated by …" with linked names, placed wherever the translation puts {name}. Goes inside a <Text>.
export function NarratedBy({ story }: { story: Credited }) {
  const { t } = useI18n();
  const [before, after = ''] = t('story.narratedBy', { name: '\u0000' }).split('\u0000');
  return <>{before}<NarratorLinks story={story} />{after}</>;
}

export function NarratorRow({ person }: { person: NarratorSummary }) {
  const { t } = useI18n();
  const colors = useColors();
  return (
    <Pressable onPress={() => router.push(narratorHref(person))} accessibilityRole="link"
      style={({ pressed }) => ({ flexDirection: 'row', alignItems: 'center', gap: space.md, minHeight: 56, opacity: pressed ? 0.8 : 1 })}>
      <View style={{ width: 40, height: 40, borderRadius: 20, backgroundColor: colors.surfaceAlt, alignItems: 'center',
        justifyContent: 'center' }}>
        <Ionicons name="mic" size={20} color={colors.primary} />
      </View>
      <View style={{ flex: 1, gap: 2 }}>
        <Text variant="heading" numberOfLines={1} style={{ fontSize: 15 }}>{person.name}</Text>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: space.sm }}>
          <Text variant="small" muted>{t('narrator.storyCount', { n: person.stories })}</Text>
          <NarratorScore person={person} />
        </View>
      </View>
      <Ionicons name="chevron-forward" size={18} color={colors.muted} />
    </Pressable>
  );
}

// A narrator on the home shelf: a round tile with their initial, so voices read differently from story covers.
export function NarratorTile({ person, width = 110 }: { person: NarratorSummary; width?: number }) {
  const { t } = useI18n();
  return (
    <Pressable onPress={() => router.push(narratorHref(person))} testID="story-card" accessibilityRole="link"
      accessibilityLabel={[person.name, t('narrator.storyCount', { n: person.stories }),
        person.narration?.score != null ? `${t('narrator.score')} ${person.narration.score.toFixed(1)}` : null].filter(Boolean).join(', ')}
      style={({ pressed }) => ({ width, alignItems: 'center', gap: space.sm, opacity: pressed ? 0.8 : 1 })}>
      <Cover id={`narrator-${person.id ?? person.name}`} title={person.name} artworkUrl={null} size={width} rounded={width / 2} />
      <Text variant="heading" numberOfLines={2} style={{ fontSize: 15, lineHeight: 21, textAlign: 'center' }}>{person.name}</Text>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: space.sm }}>
        <Text variant="small" muted>{t('narrator.storyCount', { n: person.stories })}</Text>
        <NarratorScore person={person} />
      </View>
    </Pressable>
  );
}

// "★ 4.6": the narrator's score, once enough grown-ups rated them (children's lists carry no scores).
function NarratorScore({ person }: { person: NarratorSummary }) {
  const colors = useColors();
  const score = person.narration?.score;
  if (score == null) return null;
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', gap: 2 }}>
      <Ionicons name="star" size={12} color={colors.accent} />
      <Text variant="small">{score.toFixed(1)}</Text>
    </View>
  );
}

// Save a story for listening offline, from its page or while it plays. The web app streams only, so it shows nothing.
export function DownloadButton({ story, onError, style }: { story: Story; onError: (message: string | null) => void;
  style?: StyleProp<ViewStyle> }) {
  const { t } = useI18n();
  const colors = useColors();
  const player = usePlayer();
  const [saved, setSaved] = useState<{ storyId: string; downloaded: boolean } | null>(null);
  const [downloading, setDownloading] = useState(false);
  useEffect(() => {
    let current = true;
    void localUri(story.id).then((uri) => { if (current) setSaved({ storyId: story.id, downloaded: !!uri }); });
    return () => { current = false; };
  }, [story.id]);
  if (!downloadsSupported) return null;
  const downloaded = saved?.storyId === story.id && saved.downloaded;

  const download = async () => {
    setDownloading(true);
    onError(null);
    try {
      await downloadStory(story, player.dataSaver);
      setSaved({ storyId: story.id, downloaded: true });
    } catch (failure) {
      onError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setDownloading(false);
    }
  };

  return (
    <Button title={downloaded ? t('story.downloaded') : downloading ? t('story.downloading') : t('story.download')}
      kind="secondary" style={style} loading={downloading} disabled={downloaded}
      icon={<Ionicons name={downloaded ? 'checkmark-circle' : 'download-outline'} size={18} color={colors.text} />}
      onPress={() => void download()} />
  );
}

// Compact player above the tab bar: the one control a parent needs while driving or cooking.
export function MiniPlayer() {
  const player = usePlayer();
  const colors = useColors();
  const { t, title } = useI18n();
  if (!player.story) return null;
  const { story } = player;
  return (
    <Pressable
      onPress={() => router.push('/player')} accessibilityRole="button" accessibilityLabel={t('player.nowPlaying')}
      style={{ flexDirection: 'row', alignItems: 'center', gap: space.md, padding: space.sm, paddingRight: space.md,
        backgroundColor: colors.surface, borderTopWidth: 1, borderColor: colors.border }}>
      <Cover id={story.id} title={title(story)} artworkUrl={mediaUrl(story.artworkUrl)} size={48} rounded={radius.sm} />
      <View style={{ flex: 1 }}>
        <Text variant="heading" numberOfLines={1} style={{ fontSize: 14 }}>{title(story)}</Text>
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
