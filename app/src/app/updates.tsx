import Ionicons from '@expo/vector-icons/Ionicons';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { router } from 'expo-router';
import { useEffect } from 'react';
import { Pressable, ScrollView, Switch, View } from 'react-native';

import { StoryRow } from '@/components/stories';
import { Card, ErrorState, Loading, Screen, Text, useColors } from '@/components/ui';
import { api } from '@/lib/api';
import { useI18n, type TranslationKey } from '@/lib/i18n';
import { useSession } from '@/lib/session';
import { space } from '@/lib/theme';
import type { Updates as UpdatesData } from '@/lib/types';

// Opt-in updates for grown-ups (P3-09): new stories from followed narrators and the next chapter of a series.
export default function Updates() {
  const { t } = useI18n();
  const colors = useColors();
  const { profile } = useSession();
  const queryClient = useQueryClient();
  const updates = useQuery({ queryKey: ['updates', profile?.id], enabled: !!profile,
    queryFn: () => api<UpdatesData>('/api/me/updates') });

  const unread = updates.data?.unread ?? 0;
  useEffect(() => {  // opening the list marks everything read
    if (unread) void api('/api/me/updates/read', { method: 'POST' }).then(() => queryClient.invalidateQueries({ queryKey: ['updates'] }));
  }, [unread, queryClient]);

  if (updates.isLoading) return <Loading />;
  if (updates.error || !updates.data) return <Screen><ErrorState error={updates.error} onRetry={() => void updates.refetch()} /></Screen>;
  const { items, settings } = updates.data;

  const change = async (key: 'followed' | 'series', value: boolean) => {
    queryClient.setQueryData(['updates', profile?.id], { ...updates.data, settings: { ...settings!, [key]: value } });
    await api('/api/me/notification-settings', { method: 'POST', body: { [key]: value } });
    await updates.refetch();
  };

  type Followed = NonNullable<UpdatesData['following']>[number];
  const unfollow = async (item: Followed) => {
    queryClient.setQueryData(['updates', profile?.id], { ...updates.data,
      following: (updates.data.following ?? []).filter((other) => other.key !== item.key) });
    await (item.narratorId != null
      ? api(`/api/narrators/${item.narratorId}/follow`, { method: 'POST', body: { following: false } })
      : api('/api/me/follows/remove', { method: 'POST', body: { kind: item.kind === 'series' ? 'series' : 'narrators', key: item.key } }));
    await updates.refetch();
    void queryClient.invalidateQueries({ queryKey: ['narrator'] });
    void queryClient.invalidateQueries({ queryKey: ['community'] });
  };

  return (
    <Screen back>
      <ScrollView contentContainerStyle={{ gap: space.lg, paddingVertical: space.lg, maxWidth: 640, width: '100%', alignSelf: 'center' }}>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: space.sm }}>
          <Text variant="title" accessibilityRole="header">{t('updates.title')}</Text>
        </View>
        {settings ? (
          <Card>
            <Text variant="heading">{t('updates.settings')}</Text>
            <Setting label={t('updates.settingFollowed')} value={settings.followed} onChange={(v) => void change('followed', v)} />
            <Setting label={t('updates.settingSeries')} value={settings.series} onChange={(v) => void change('series', v)} />
            <Text variant="small" muted>{t('updates.note')}</Text>
          </Card>
        ) : null}
        {updates.data.following ? (
          <Card>
            <Text variant="heading">{t('updates.following')}</Text>
            {!updates.data.following.length ? <Text variant="small" muted>{t('updates.followingEmpty')}</Text> : null}
            {updates.data.following.map((item) => (
              <View key={item.key} style={{ flexDirection: 'row', alignItems: 'center', gap: space.md, minHeight: 44 }}>
                <Ionicons name={item.kind === 'series' ? 'albums-outline' : 'mic-outline'} size={20} color={colors.muted} />
                <Pressable style={{ flex: 1 }} disabled={item.kind === 'series'} accessibilityRole={item.kind === 'series' ? 'text' : 'link'}
                  onPress={() => router.push(`/narrator/${item.narratorId ?? encodeURIComponent(item.name)}`)}>
                  <Text>{item.name}</Text>
                  <Text variant="small" muted>{t(item.kind === 'series' ? 'updates.seriesLabel' : 'updates.narratorLabel')}</Text>
                </Pressable>
                <Pressable onPress={() => void unfollow(item)} hitSlop={8} accessibilityRole="button"
                  accessibilityLabel={t('updates.unfollow', { name: item.name })}>
                  <Ionicons name="close-circle-outline" size={22} color={colors.muted} />
                </Pressable>
              </View>
            ))}
          </Card>
        ) : null}
        {!items.length ? <Text muted>{t('updates.empty')}</Text> : null}
        {items.map((item) => (
          <View key={item.id} style={{ gap: 2 }}>
            <Text variant="small" color={item.read ? colors.muted : colors.primary}>
              {t(`updates.${item.kind}` as TranslationKey)} · {new Date(item.createdAt).toLocaleDateString()}
            </Text>
            <StoryRow story={item.story} />
          </View>
        ))}
      </ScrollView>
    </Screen>
  );
}

function Setting({ label, value, onChange }: { label: string; value: boolean; onChange: (value: boolean) => void }) {
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', gap: space.md, minHeight: 44 }}>
      <Text style={{ flex: 1 }}>{label}</Text>
      <Switch value={value} onValueChange={onChange} accessibilityLabel={label} />
    </View>
  );
}
