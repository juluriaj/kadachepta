import Ionicons from '@expo/vector-icons/Ionicons';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { router, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { Alert, Platform, Pressable, ScrollView, View } from 'react-native';

import { minutes, StoryRow } from '@/components/stories';
import { Button, ErrorState, Field, Loading, Screen, Text, useColors } from '@/components/ui';
import { api } from '@/lib/api';
import { useI18n } from '@/lib/i18n';
import { usePlayer } from '@/lib/player/PlayerProvider';
import { useSession } from '@/lib/session';
import { space, touch } from '@/lib/theme';
import type { PlaylistDetail, Story } from '@/lib/types';

function confirm(message: string): Promise<boolean> {
  if (Platform.OS === 'web') return Promise.resolve(window.confirm(message));
  return new Promise((resolve) => Alert.alert('', message, [
    { text: 'Cancel', style: 'cancel', onPress: () => resolve(false) },
    { text: 'OK', style: 'destructive', onPress: () => resolve(true) },
  ]));
}

function shuffled<T>(items: T[]): T[] {
  const copy = [...items];
  for (let i = copy.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [copy[i], copy[j]] = [copy[j], copy[i]];
  }
  return copy;
}

// One playlist: play it in order or shuffled (the rest of the list becomes the queue), reorder, rename, delete.
export default function Playlist() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { t, title } = useI18n();
  const colors = useColors();
  const player = usePlayer();
  const queryClient = useQueryClient();
  const { profile } = useSession();
  const [renaming, setRenaming] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const query = useQuery({ queryKey: ['playlist', Number(id), profile?.id], enabled: !!id,
    queryFn: () => api<PlaylistDetail>(`/api/me/playlists/${id}`) });

  if (query.isLoading) return <Loading />;
  if (query.error || !query.data) return <Screen><ErrorState error={query.error} onRetry={() => void query.refetch()} /></Screen>;
  const playlist = query.data;
  const url = `/api/me/playlists/${playlist.id}`;

  const change = async (work: () => Promise<PlaylistDetail | unknown>) => {
    setError(null);
    try {
      const result = await work();
      if (result && typeof result === 'object' && 'stories' in result) {
        queryClient.setQueryData(['playlist', playlist.id, profile?.id], result);
      }
      void queryClient.invalidateQueries({ queryKey: ['playlists'] });
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    }
  };
  const playFrom = (stories: Story[]) => {
    const [first, ...rest] = stories;
    if (!first) return;
    void player.play(first, { queue: rest, autoContinue: true });
    router.push('/player');
  };
  const move = (index: number, offset: -1 | 1) => {
    const ids = playlist.stories.map((s) => s.id);
    const target = index + offset;
    if (target < 0 || target >= ids.length) return;
    [ids[index], ids[target]] = [ids[target], ids[index]];
    void change(() => api<PlaylistDetail>(`${url}/order`, { method: 'POST', body: { assetIds: ids } }));
  };

  return (
    <Screen>
      <ScrollView contentContainerStyle={{ gap: space.lg, paddingVertical: space.lg, maxWidth: 640, width: '100%', alignSelf: 'center' }}>
        <Pressable onPress={() => (router.canGoBack() ? router.back() : router.replace('/(tabs)/library'))}
          accessibilityRole="button" accessibilityLabel={t('common.back')} hitSlop={12}>
          <Ionicons name="chevron-back" size={26} color={colors.text} />
        </Pressable>
        {renaming !== null ? (
          <View style={{ gap: space.sm }}>
            <Field label={t('playlist.name')} value={renaming} onChangeText={setRenaming} maxLength={80} autoFocus />
            <View style={{ flexDirection: 'row', gap: space.sm }}>
              <Button title={t('common.save')} disabled={!renaming.trim()} onPress={() => void change(async () => {
                const result = await api<PlaylistDetail>(url, { method: 'POST', body: { name: renaming.trim() } });
                setRenaming(null);
                return result;
              })} />
              <Button kind="ghost" title={t('common.cancel')} onPress={() => setRenaming(null)} />
            </View>
          </View>
        ) : (
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: space.sm }}>
            <View style={{ flex: 1 }}>
              <Text variant="title" accessibilityRole="header">{playlist.name}</Text>
              <Text variant="small" muted>
                {t('playlist.count', { n: playlist.count })} · {t('common.min', { n: minutes(playlist.duration) })}
              </Text>
            </View>
            <Pressable onPress={() => setRenaming(playlist.name)} accessibilityRole="button" accessibilityLabel={t('playlist.rename')}
              hitSlop={10}>
              <Ionicons name="pencil" size={20} color={colors.text} />
            </Pressable>
          </View>
        )}
        {playlist.stories.length ? (
          <View style={{ flexDirection: 'row', gap: space.md }}>
            <Button title={t('playlist.playAll')} style={{ flex: 1 }} onPress={() => playFrom(playlist.stories)}
              icon={<Ionicons name="play" size={18} color={colors.onPrimary} />} />
            <Button kind="secondary" title={t('playlist.shuffle')} style={{ flex: 1 }} onPress={() => playFrom(shuffled(playlist.stories))}
              icon={<Ionicons name="shuffle" size={18} color={colors.text} />} />
          </View>
        ) : <Text muted>{t('playlist.noStories')}</Text>}
        {error ? <Text variant="small" color={colors.danger}>{error}</Text> : null}
        {playlist.stories.map((story, index) => (
          <StoryRow key={story.id} story={story} right={
            <View style={{ flexDirection: 'row' }}>
              <Small icon="chevron-up" label={t('queue.moveUp')} disabled={index === 0} onPress={() => move(index, -1)} />
              <Small icon="chevron-down" label={t('queue.moveDown')} disabled={index === playlist.stories.length - 1}
                onPress={() => move(index, 1)} />
              <Small icon="close" label={`${t('playlist.remove')}: ${title(story)}`}
                onPress={() => void change(() => api<PlaylistDetail>(`${url}/items/${story.id}`, { method: 'DELETE' }))} />
            </View>
          } />
        ))}
        <Button kind="ghost" title={t('playlist.delete')} onPress={() => void confirm(t('playlist.deleteConfirm')).then((ok) => {
          if (ok) void change(() => api(url, { method: 'DELETE' })).then(() => router.back());
        })} />
      </ScrollView>
    </Screen>
  );
}

function Small({ icon, label, onPress, disabled }: { icon: keyof typeof Ionicons.glyphMap; label: string; onPress: () => void;
  disabled?: boolean }) {
  const colors = useColors();
  return (
    <Pressable onPress={onPress} disabled={disabled} accessibilityRole="button" accessibilityLabel={label}
      style={{ width: 36, height: touch, alignItems: 'center', justifyContent: 'center', opacity: disabled ? 0.3 : 1 }}>
      <Ionicons name={icon} size={20} color={colors.text} />
    </Pressable>
  );
}
