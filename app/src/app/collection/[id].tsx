import Ionicons from '@expo/vector-icons/Ionicons';
import { useQuery } from '@tanstack/react-query';
import { router, useLocalSearchParams } from 'expo-router';
import { FlatList, Pressable, View } from 'react-native';

import { setTitle, shuffled } from '@/components/sets';
import { minutes, StoryRow } from '@/components/stories';
import { Button, Cover, ErrorState, Loading, Screen, Text, useColors } from '@/components/ui';
import { api } from '@/lib/api';
import { formatListening, useI18n } from '@/lib/i18n';
import { usePlayer } from '@/lib/player/PlayerProvider';
import { useSession } from '@/lib/session';
import { space } from '@/lib/theme';
import type { Story, StorySetPage } from '@/lib/types';

// A story set (Tenali Ramakrishna, Akbar Birbal): standalone stories, so any can be heard first. Play all goes in
// the set's order, Shuffle mixes them; either way the next story starts on its own. Ticks mark the ones heard.
export default function CollectionScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { t, language } = useI18n();
  const colors = useColors();
  const player = usePlayer();
  const { profile } = useSession();
  const page = useQuery({ queryKey: ['collection', Number(id), profile?.id], enabled: !!id && !!profile,
    queryFn: () => api<StorySetPage>(`/api/collections/${id}`) });

  if (page.isLoading) return <Loading />;
  if (page.error || !page.data) {
    return <Screen><Back /><ErrorState error={page.error} onRetry={() => void page.refetch()} /></Screen>;
  }
  const set = page.data;
  const name = setTitle(set, language);
  const description = set.descriptions[`${language}-IN`] ?? set.descriptions['en-IN'] ?? Object.values(set.descriptions)[0];
  const playFrom = (stories: Story[]) => {
    const [first, ...rest] = stories;
    if (!first) return;
    void player.play(first, { queue: rest, autoContinue: true });
    router.push('/player');
  };

  const header = (
    <View style={{ gap: space.lg, paddingBottom: space.md }}>
      <Back />
      <View style={{ alignItems: 'center', gap: space.md }}>
        <Cover id={`set-${set.id}`} title={name} artworkUrl={set.artworkUrl} size={200} />
        <Text variant="display" style={{ textAlign: 'center' }} accessibilityRole="header">{name}</Text>
        <Text muted style={{ textAlign: 'center' }}>
          {t('collection.count', { n: set.storyCount })} · {formatListening(t, set.duration)}
          {set.heard ? ` · ${t('collection.heard', { n: set.heard, total: set.storyCount })}` : ''}
        </Text>
      </View>
      {description ? <Text style={{ lineHeight: 24 }}>{description}</Text> : null}
      <View style={{ flexDirection: 'row', gap: space.md }}>
        <Button title={t('playlist.playAll')} style={{ flex: 1 }} onPress={() => playFrom(set.stories)}
          icon={<Ionicons name="play" size={18} color={colors.onPrimary} />} />
        <Button kind="secondary" title={t('playlist.shuffle')} style={{ flex: 1 }} onPress={() => playFrom(shuffled(set.stories))}
          icon={<Ionicons name="shuffle" size={18} color={colors.text} />} />
      </View>
      {set.heard === set.storyCount ? <Text variant="small" muted>{t('collection.allHeard')}</Text> : null}
    </View>
  );

  return (
    <Screen>
      <FlatList data={set.stories} keyExtractor={(story) => story.id} ListHeaderComponent={header} initialNumToRender={12}
        contentContainerStyle={{ paddingVertical: space.lg, maxWidth: 640, width: '100%', alignSelf: 'center' }}
        renderItem={({ item }) => <StoryRow story={item} right={<Heard story={item} />} />} />
    </Screen>
  );
}

// A tick once a story is heard to the end; minutes left when it was stopped part way.
function Heard({ story }: { story: Story }) {
  const { t } = useI18n();
  const colors = useColors();
  if (story.progress?.completed) {
    return <Ionicons name="checkmark-circle" size={22} color={colors.success} accessibilityLabel={t('collection.heardMark')} />;
  }
  if (story.progress && story.progress.position >= 10) {
    return <Text variant="small" muted>{t('book.left', { min: minutes(story.duration - story.progress.position) })}</Text>;
  }
  return null;
}

function Back() {
  const { t } = useI18n();
  const colors = useColors();
  return (
    <Pressable onPress={() => (router.canGoBack() ? router.back() : router.replace('/'))} accessibilityRole="button"
      accessibilityLabel={t('common.back')} hitSlop={12} style={{ alignSelf: 'flex-start' }}>
      <Ionicons name="chevron-back" size={26} color={colors.text} />
    </Pressable>
  );
}
