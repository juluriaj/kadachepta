import Ionicons from '@expo/vector-icons/Ionicons';
import { useQuery } from '@tanstack/react-query';
import { router, useLocalSearchParams } from 'expo-router';
import { Pressable, View } from 'react-native';

import { resumeLabel } from '@/components/sets';
import { minutes, NarratedBy, StoryList } from '@/components/stories';
import { Button, Cover, ErrorState, Loading, ProgressBar, Screen, Text, useColors } from '@/components/ui';
import { api } from '@/lib/api';
import { formatListening, useI18n } from '@/lib/i18n';
import { usePlayer } from '@/lib/player/PlayerProvider';
import { useSession } from '@/lib/session';
import { space, touch } from '@/lib/theme';
import type { BookPage, Story } from '@/lib/types';

// An audiobook: one work heard in order over many sittings. One button picks up where this listener left off;
// every chapter shows whether it's finished or part-heard, and the chapters play on one after another.
export default function BookScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { t } = useI18n();
  const colors = useColors();
  const player = usePlayer();
  const { profile } = useSession();
  const page = useQuery({ queryKey: ['book', Number(id), profile?.id], enabled: !!id && !!profile,
    queryFn: () => api<BookPage>(`/api/books/${id}`) });

  if (page.isLoading) return <Loading />;
  if (page.error || !page.data) {
    return <Screen back><ErrorState error={page.error} onRetry={() => void page.refetch()} /></Screen>;
  }
  const book = page.data;
  const playFrom = (index: number) => {
    const chapter = book.chapters[index];
    if (!chapter) return;
    if (player.story?.id === chapter.id) player.toggle();
    else void player.play(chapter, { queue: book.chapters.slice(index + 1), autoContinue: true });
    router.push('/player');
  };
  const resumeIndex = book.resume.state === 'continue'
    ? Math.max(0, book.chapters.findIndex((chapter) => chapter.id === book.resume.chapterId)) : 0;

  const header = (
    <View style={{ gap: space.lg, paddingBottom: space.md }}>
      <View style={{ alignItems: 'center', gap: space.md }}>
        <Cover id={`book-${book.id}`} title={book.title} artworkUrl={book.artworkUrl} size={220} />
        <Text variant="display" style={{ textAlign: 'center' }} accessibilityRole="header">{book.title}</Text>
        <Text muted style={{ textAlign: 'center' }}><NarratedBy story={book} /></Text>
        <Text muted style={{ textAlign: 'center' }}>
          {t('book.chapters', { n: book.chapterCount })} · {formatListening(t, book.duration)}
        </Text>
      </View>
      {book.finished ? (
        <View style={{ gap: space.xs }}>
          <ProgressBar value={book.finished / Math.max(1, book.chapterCount)} height={5} />
          <Text variant="small" muted>{t('book.progress', { n: book.finished, total: book.chapterCount })}</Text>
        </View>
      ) : null}
      <Button title={resumeLabel(t, book)} onPress={() => playFrom(resumeIndex)}
        icon={<Ionicons name={book.resume.state === 'finished' ? 'refresh' : 'play'} size={20} color={colors.onPrimary} />} />
      {book.description ? <Text style={{ fontSize: 17, lineHeight: 28 }}>{book.description}</Text> : null}
    </View>
  );

  // Tapping a chapter, row or tile, plays from there; the chapters after it follow on.
  return (
    <Screen back>
      <StoryList stories={book.chapters} header={header} title={t('book.chapters', { n: book.chapterCount })} chapterView
        initialNumToRender={15} onPress={(_, index) => playFrom(index)}
        contentContainerStyle={{ paddingVertical: space.lg, maxWidth: 640, width: '100%', alignSelf: 'center' }}
        row={(chapter, index) => (
          <ChapterRow chapter={chapter} number={index + 1} current={player.story?.id === chapter.id} onPress={() => playFrom(index)} />
        )} />
    </Screen>
  );
}

function ChapterRow({ chapter, number, current, onPress }: { chapter: Story; number: number; current: boolean;
  onPress: () => void }) {
  const { t, title } = useI18n();
  const colors = useColors();
  const { progress } = chapter;
  const nearEnd = !!progress && chapter.duration > 0 && progress.position >= chapter.duration - 15;
  const finished = !!progress && (progress.completed || nearEnd);
  const partial = !finished && !!progress && progress.position >= 10;
  const state = finished ? t('book.finished')
    : partial ? t('book.left', { min: minutes(chapter.duration - progress!.position) }) : t('common.min', { n: minutes(chapter.duration) });
  return (
    <Pressable onPress={onPress} accessibilityRole="button"
      accessibilityLabel={`${t('book.chapter', { n: number })}: ${title(chapter)}, ${state}`}
      style={({ pressed }) => ({ flexDirection: 'row', alignItems: 'center', gap: space.md, minHeight: touch + 16,
        opacity: pressed ? 0.8 : 1 })}>
      <View style={{ width: 36, height: 36, borderRadius: 18, alignItems: 'center', justifyContent: 'center',
        backgroundColor: current ? colors.accent : colors.surfaceAlt }}>
        {current ? <Ionicons name="volume-high" size={18} color={colors.onAccent} />
          : <Text variant="small" style={{ fontWeight: '700' }}>{number}</Text>}
      </View>
      <View style={{ flex: 1, gap: 4 }}>
        <Text numberOfLines={1} style={{ fontSize: 15, opacity: finished ? 0.7 : 1 }}>{title(chapter)}</Text>
        {partial ? <ProgressBar value={progress!.position / chapter.duration} /> : null}
        <Text variant="small" muted>{state}</Text>
      </View>
      {finished ? <Ionicons name="checkmark-circle" size={22} color={colors.success} />
        : partial ? <Ionicons name="pie-chart-outline" size={20} color={colors.accent} /> : null}
    </Pressable>
  );
}
