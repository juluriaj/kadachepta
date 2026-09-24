import Ionicons from '@expo/vector-icons/Ionicons';
import { useQuery } from '@tanstack/react-query';
import { Redirect, router } from 'expo-router';
import { Pressable, RefreshControl, ScrollView, View } from 'react-native';

import { StageBadge } from '@/components/narrator';
import { Button, Card, Cover, ErrorState, Loading, Screen, Text, useColors } from '@/components/ui';
import { api } from '@/lib/api';
import { formatClock, useI18n } from '@/lib/i18n';
import { space } from '@/lib/theme';
import type { AppNotification, NarratorHome } from '@/lib/types';

const ATTENTION = new Set(['needs-fix', 'changes-requested', 'awaiting-submit']);

export default function NarratorStudio() {
  const { t } = useI18n();
  const colors = useColors();
  const home = useQuery({ queryKey: ['narrator-home'], queryFn: () => api<NarratorHome>('/api/narrator/home'),
    refetchInterval: (query) => (query.state.data?.totals.inProgress ? 15_000 : false) });
  const updates = useQuery({ queryKey: ['notifications'], queryFn: () => api<{ items: AppNotification[]; unread: number }>(
    '/api/notifications', { profile: false }) });

  if (home.isLoading) return <Loading />;
  if (home.error) return <Screen><ErrorState error={home.error} onRetry={() => void home.refetch()} /></Screen>;
  const data = home.data!;
  if (!data.profile?.onboarded) return <Redirect href="/narrate/apply" />;
  const attention = data.submissions.filter((s) => ATTENTION.has(s.stage));
  const others = data.submissions.filter((s) => !ATTENTION.has(s.stage));
  const unread = (updates.data?.items ?? []).filter((n) => !n.read).slice(0, 3);

  return (
    <Screen>
      <ScrollView contentContainerStyle={{ gap: space.lg, paddingVertical: space.lg }}
        refreshControl={<RefreshControl refreshing={home.isRefetching} onRefresh={() => { void home.refetch(); void updates.refetch(); }} />}>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: space.sm }}>
          <Text variant="title" accessibilityRole="header" style={{ flex: 1 }}>{t('narrate.title')}</Text>
          {data.profile.trustLevel === 'trusted' ? (
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 4 }}>
              <Ionicons name="shield-checkmark" size={16} color={colors.success} />
              <Text variant="label" color={colors.success}>{t('narrate.trusted')}</Text>
            </View>
          ) : null}
        </View>

        <Button title={t('narrate.new')} icon={<Ionicons name="mic" size={20} color={colors.onPrimary} />}
          onPress={() => router.push('/narrate/new')} />

        <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: space.md }}>
          <Metric label={t('narrate.published')} value={data.totals.published} />
          <Metric label={t('narrate.inProgress')} value={data.totals.inProgress} />
          <Metric label={t('narrate.listeners')} value={data.totals.listeners} />
          <Metric label={t('narrate.minutesListened')} value={data.totals.minutesListened} />
        </View>

        {unread.length ? (
          <Card>
            <Text variant="heading">{t('narrate.updates')}</Text>
            {unread.map((n) => (
              <Pressable key={n.id} accessibilityRole="link" onPress={() => n.assetId && router.push(`/narrate/submission/${n.assetId}`)}>
                <Text>{n.title}</Text>
                {n.body ? <Text variant="small" muted numberOfLines={2}>{n.body}</Text> : null}
              </Pressable>
            ))}
            <Button kind="ghost" title={t('common.done')} onPress={() => void api('/api/notifications/read', { method: 'POST', profile: false })
              .then(() => updates.refetch())} />
          </Card>
        ) : null}

        {attention.length ? <Text variant="heading">{t('narrate.needsAttention')}</Text> : null}
        {attention.map((s) => <SubmissionRow key={s.id} submission={s} />)}

        <Text variant="heading">{t('narrate.stories')}</Text>
        {data.submissions.length === 0 ? <Text muted>{t('narrate.empty')}</Text> : null}
        {others.map((s) => <SubmissionRow key={s.id} submission={s} />)}
      </ScrollView>
    </Screen>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  const colors = useColors();
  return (
    <View style={{ minWidth: 130, flexGrow: 1, padding: space.md, borderRadius: 14, backgroundColor: colors.surface,
      borderWidth: 1, borderColor: colors.border }}>
      <Text variant="title">{String(value)}</Text>
      <Text variant="small" muted>{label}</Text>
    </View>
  );
}

function SubmissionRow({ submission }: { submission: NarratorHome['submissions'][number] }) {
  const { t } = useI18n();
  return (
    <Pressable accessibilityRole="button" accessibilityLabel={`${submission.title}, ${t(`stage.${submission.stage}` as never)}`}
      onPress={() => router.push(`/narrate/submission/${submission.id}`)}
      style={{ flexDirection: 'row', alignItems: 'center', gap: space.md }}>
      <Cover id={submission.id} title={submission.title} artworkUrl={submission.artworkUrl} size={56} />
      <View style={{ flex: 1, gap: 2 }}>
        <Text variant="heading" numberOfLines={1}>{submission.title}</Text>
        <Text variant="small" muted numberOfLines={1}>
          {[submission.series?.title, submission.duration ? formatClock(submission.duration) : null].filter(Boolean).join(' · ')}
        </Text>
        <StageBadge stage={submission.stage} />
      </View>
      {submission.stats ? <Text variant="small" muted>{`▶ ${submission.stats.listeners}`}</Text> : null}
    </Pressable>
  );
}
