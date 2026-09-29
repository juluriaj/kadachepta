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
  const updates = useQuery({ queryKey: ['updates', profile?.id],
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

  return (
    <Screen>
      <ScrollView contentContainerStyle={{ gap: space.lg, paddingVertical: space.lg, maxWidth: 640, width: '100%', alignSelf: 'center' }}>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: space.sm }}>
          <Pressable onPress={() => (router.canGoBack() ? router.back() : router.replace('/'))} accessibilityRole="button"
            accessibilityLabel={t('common.back')} hitSlop={12}>
            <Ionicons name="chevron-back" size={26} color={colors.text} />
          </Pressable>
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
