import Ionicons from '@expo/vector-icons/Ionicons';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Pressable, View } from 'react-native';

import { Button, Card, Field, Text, useColors } from '@/components/ui';
import { api } from '@/lib/api';
import { useI18n } from '@/lib/i18n';
import { useSession } from '@/lib/session';
import { space, touch } from '@/lib/theme';
import type { PlaylistDetail, PlaylistSummary } from '@/lib/types';

export function usePlaylists() {
  const { profile } = useSession();
  return useQuery({ queryKey: ['playlists', profile?.id],
    queryFn: () => api<{ items: PlaylistSummary[] }>('/api/me/playlists') });
}

export async function createPlaylist(name: string) {
  return api<PlaylistDetail>('/api/me/playlists', { method: 'POST', body: { name } });
}

// Name a new playlist (shared by the Library and the "Add to playlist" panel).
export function NewPlaylist({ onCreated, onCancel }: { onCreated: (playlist: PlaylistDetail) => void; onCancel?: () => void }) {
  const { t } = useI18n();
  const colors = useColors();
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const create = async () => {
    setBusy(true);
    setError(null);
    try {
      onCreated(await createPlaylist(name.trim()));
      setName('');
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setBusy(false);
    }
  };
  return (
    <View style={{ gap: space.sm }}>
      <Field label={t('playlist.name')} value={name} onChangeText={setName} placeholder={t('playlist.namePlaceholder')}
        maxLength={80} autoFocus onSubmitEditing={() => name.trim() && void create()} />
      {error ? <Text variant="small" color={colors.danger}>{error}</Text> : null}
      <View style={{ flexDirection: 'row', gap: space.sm }}>
        <Button title={t('playlist.create')} loading={busy} disabled={!name.trim()} onPress={() => void create()} />
        {onCancel ? <Button kind="ghost" title={t('common.cancel')} onPress={onCancel} /> : null}
      </View>
    </View>
  );
}

// "Add to playlist": every playlist with a tick when the story is in it (tap to add or take out), plus a new one.
export function AddToPlaylist({ storyId }: { storyId: string }) {
  const { t } = useI18n();
  const colors = useColors();
  const queryClient = useQueryClient();
  const { profile } = useSession();
  const playlists = usePlaylists();
  const [open, setOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const items = playlists.data?.items ?? [];
  const inLists = items.filter((p) => p.storyIds.includes(storyId));

  const toggle = async (playlist: PlaylistSummary) => {
    setError(null);
    try {
      const url = `/api/me/playlists/${playlist.id}/items`;
      if (playlist.storyIds.includes(storyId)) await api(`${url}/${storyId}`, { method: 'DELETE' });
      else await api(url, { method: 'POST', body: { assetId: storyId } });
      await queryClient.invalidateQueries({ queryKey: ['playlists', profile?.id] });
      void queryClient.invalidateQueries({ queryKey: ['playlist', playlist.id] });
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    }
  };

  if (!open) {
    return (
      <Button kind="secondary" onPress={() => setOpen(true)}
        title={inLists.length === 1 ? t('playlist.inList', { name: inLists[0].name }) : t('playlist.add')}
        icon={<Ionicons name={inLists.length ? 'list' : 'add'} size={18} color={colors.text} />} />
    );
  }
  return (
    <Card>
      <View style={{ flexDirection: 'row', alignItems: 'center' }}>
        <Text variant="heading" style={{ flex: 1 }}>{t('playlist.add')}</Text>
        <Pressable onPress={() => setOpen(false)} accessibilityRole="button" accessibilityLabel={t('common.done')} hitSlop={10}>
          <Ionicons name="close" size={22} color={colors.text} />
        </Pressable>
      </View>
      {items.map((playlist) => {
        const inside = playlist.storyIds.includes(storyId);
        return (
          <Pressable key={playlist.id} onPress={() => void toggle(playlist)} accessibilityRole="checkbox"
            accessibilityState={{ checked: inside }}
            style={{ flexDirection: 'row', alignItems: 'center', gap: space.md, minHeight: touch }}>
            <Ionicons name={inside ? 'checkmark-circle' : 'ellipse-outline'} size={24} color={inside ? colors.primary : colors.muted} />
            <Text style={{ flex: 1 }}>{playlist.name}</Text>
            <Text variant="small" muted>{t('playlist.count', { n: playlist.count })}</Text>
          </Pressable>
        );
      })}
      {creating ? (
        <NewPlaylist onCancel={() => setCreating(false)} onCreated={(playlist) => {
          setCreating(false);
          void toggle({ ...playlist, storyIds: [] });
        }} />
      ) : (
        <Button kind="ghost" title={t('playlist.new')} onPress={() => setCreating(true)}
          icon={<Ionicons name="add" size={18} color={colors.primary} />} />
      )}
      {error ? <Text variant="small" color={colors.danger}>{error}</Text> : null}
    </Card>
  );
}
