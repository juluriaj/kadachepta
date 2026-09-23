import Ionicons from '@expo/vector-icons/Ionicons';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';
import { Pressable, ScrollView, View } from 'react-native';

import { minutes, StoryRow } from '@/components/stories';
import { Chip, ErrorState, Loading, Screen, Text, useColors } from '@/components/ui';
import { api } from '@/lib/api';
import { downloadsSupported, listDownloads, removeDownload, type DownloadEntry } from '@/lib/downloads';
import { useI18n } from '@/lib/i18n';
import { useSession } from '@/lib/session';
import { space } from '@/lib/theme';
import type { Story } from '@/lib/types';

type Tab = 'favorites' | 'downloads' | 'history';

export default function Library() {
  const { t } = useI18n();
  const colors = useColors();
  const queryClient = useQueryClient();
  const { profile } = useSession();
  const [tab, setTab] = useState<Tab>('favorites');
  const [downloads, setDownloads] = useState<Record<string, DownloadEntry>>({});
  const catalog = useQuery({
    queryKey: ['catalog', profile?.id], enabled: !!profile,
    queryFn: () => api<{ items: Story[] }>('/api/catalog'),
  });

  useFocusEffect(useCallback(() => {
    void listDownloads().then(setDownloads);
    void queryClient.invalidateQueries({ queryKey: ['catalog', profile?.id] });
  }, [queryClient, profile?.id]));

  if (catalog.isLoading) return <Loading />;
  const items = catalog.data?.items ?? [];
  const favorites = items.filter((s) => s.favorite);
  const history = items.filter((s) => s.progress?.lastListenedAt)
    .sort((a, b) => (b.progress!.lastListenedAt ?? '').localeCompare(a.progress!.lastListenedAt ?? ''));
  const downloaded = Object.values(downloads);

  const empty = (message: string) => (
    <View style={{ padding: space.xl, alignItems: 'center', gap: space.sm }}>
      <Ionicons name={tab === 'favorites' ? 'heart-outline' : tab === 'downloads' ? 'download-outline' : 'time-outline'} size={36} color={colors.muted} />
      <Text muted style={{ textAlign: 'center' }}>{message}</Text>
    </View>
  );

  return (
    <Screen>
      <ScrollView contentContainerStyle={{ gap: space.lg, paddingVertical: space.lg }}>
        <Text variant="title" accessibilityRole="header">{t('tabs.library')}</Text>
        <View style={{ flexDirection: 'row', gap: space.sm }}>
          <Chip label={t('library.favorites')} selected={tab === 'favorites'} onPress={() => setTab('favorites')} />
          <Chip label={t('library.downloads')} selected={tab === 'downloads'} onPress={() => setTab('downloads')} />
          <Chip label={t('library.history')} selected={tab === 'history'} onPress={() => setTab('history')} />
        </View>
        {catalog.error ? <ErrorState error={catalog.error} onRetry={() => void catalog.refetch()} /> : null}

        {tab === 'favorites' && (favorites.length ? favorites.map((story) => <StoryRow key={story.id} story={story} />)
          : empty(t('library.noFavorites')))}

        {tab === 'history' && (history.length ? history.map((story) => (
          <StoryRow key={story.id} story={story} right={story.progress?.completed
            ? <Ionicons name="checkmark-circle" size={22} color={colors.success} accessibilityLabel="Finished" /> : undefined} />
        )) : empty(t('library.noHistory')))}

        {tab === 'downloads' && (!downloadsSupported ? empty(t('library.downloadsWebOnly'))
          : downloaded.length ? downloaded.map((entry) => (
            <StoryRow key={entry.story.id} story={entry.story} right={
              <Pressable accessibilityRole="button" accessibilityLabel={`${t('library.remove')} ${entry.story.title}`} hitSlop={12}
                onPress={async () => { await removeDownload(entry.story.id); setDownloads(await listDownloads()); }}>
                <Ionicons name="trash-outline" size={22} color={colors.muted} />
              </Pressable>
            } />
          )) : empty(t('library.noDownloads')))}
        {tab === 'downloads' && downloaded.length ? (
          <Text variant="small" muted>
            {downloaded.length} · {Math.round(downloaded.reduce((sum, d) => sum + d.bytes, 0) / 1_000_000)} MB ·{' '}
            {t('common.min', { n: downloaded.reduce((sum, d) => sum + minutes(d.story.duration), 0) })}
          </Text>
        ) : null}
      </ScrollView>
    </Screen>
  );
}
