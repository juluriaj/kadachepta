import Ionicons from '@expo/vector-icons/Ionicons';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { router, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { Alert, Platform, Pressable, RefreshControl, ScrollView, View } from 'react-native';

import { MasteringCompare } from '@/components/MasteringCompare';
import { QcList, StageBadge, Timeline } from '@/components/narrator';
import { Button, Card, Cover, ErrorState, Loading, Screen, Text, useColors } from '@/components/ui';
import { api } from '@/lib/api';
import { formatClock, formatListening, useI18n, type TranslationKey } from '@/lib/i18n';
import { space } from '@/lib/theme';
import type { SubmissionDetail } from '@/lib/types';

const WORKING = new Set(['checking', 'transcribing', 'drafting', 'illustrating']);

function confirmAction(message: string): Promise<boolean> {
  if (Platform.OS === 'web') return Promise.resolve(window.confirm(message));
  return new Promise((resolve) => Alert.alert('', message, [
    { text: 'Cancel', style: 'cancel', onPress: () => resolve(false) },
    { text: 'OK', style: 'destructive', onPress: () => resolve(true) },
  ]));
}

export default function SubmissionStatus() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { t, language } = useI18n();
  const colors = useColors();
  const queryClient = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const query = useQuery({
    queryKey: ['submission', id], queryFn: () => api<SubmissionDetail>(`/api/narrator/submissions/${id}`),
    refetchInterval: (q) => (WORKING.has(q.state.data?.stage ?? '') ? 5_000 : false),
  });

  if (query.isLoading) return <Loading />;
  if (query.error) return <Screen><ErrorState error={query.error} onRetry={() => void query.refetch()} /></Screen>;
  const s = query.data!;
  const checks = s.qc?.checks ?? [];

  const act = async (path: string, after?: () => void) => {
    setBusy(true);
    setError(null);
    try {
      await api(path, { method: 'POST', profile: false });
      await queryClient.invalidateQueries({ queryKey: ['narrator-home'] });
      if (after) after();
      else await query.refetch();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Screen>
      <ScrollView contentContainerStyle={{ gap: space.lg, paddingVertical: space.lg }}
        refreshControl={<RefreshControl refreshing={query.isRefetching} onRefresh={() => void query.refetch()} />}>
        <Pressable accessibilityRole="button" accessibilityLabel={t('common.back')} hitSlop={12}
          onPress={() => (router.canGoBack() ? router.back() : router.replace('/(tabs)/narrate'))}>
          <Ionicons name="chevron-back" size={26} color={colors.text} />
        </Pressable>
        <View style={{ flexDirection: 'row', gap: space.md, alignItems: 'center' }}>
          <Cover id={s.id} title={s.title} artworkUrl={s.artworkUrl} size={88} />
          <View style={{ flex: 1, gap: space.xs }}>
            <Text variant="title" accessibilityRole="header">{s.title}</Text>
            <Text variant="small" muted>
              {[s.series ? `${s.series.title}${s.seriesPosition ? ` · ${s.seriesPosition}` : ''}` : null,
                s.duration ? formatClock(s.duration) : null].filter(Boolean).join(' · ')}
            </Text>
            <StageBadge stage={s.stage} />
          </View>
        </View>

        <Card><Timeline steps={s.timeline} /></Card>

        {s.changesRequested && s.stage === 'changes-requested' ? (
          <Card style={{ borderColor: colors.accent }}>
            <Text variant="heading">{t('status.editorNote')}</Text>
            {s.changesRequested.reasons.map((code, index) => {
              const key = `reason.${code}` as TranslationKey;
              return <Text key={code}>• {language === 'en' ? s.changesRequested!.texts[index] : t(key)}</Text>;
            })}
            {s.changesRequested.note ? <Text style={{ fontStyle: 'italic' }}>“{s.changesRequested.note}”</Text> : null}
          </Card>
        ) : null}

        {s.mediaStatus === 'ready' && s.mastering?.level && s.mastering.level !== 'none' ? (
          <Card>
            <Text variant="heading">{t('master.title')}</Text>
            <Text variant="small" muted>{t(s.mastering.level === 'full' ? 'master.full' : 'master.light')}</Text>
            <MasteringCompare audioUrl={s.audioUrl} mastering={s.mastering} waveform={s.waveform} duration={s.duration}
              labels={{ mastered: t('master.mastered'), original: t('master.original') }} />
            <Text variant="small" muted>{t('master.editor')}</Text>
          </Card>
        ) : null}

        {s.mediaStatus === 'ready' ? (
          <Card>
            <Text variant="heading">{checks.length ? t('status.checks') : t('status.checksPassed')}</Text>
            {checks.length ? <QcList checks={checks} /> : <Ionicons name="checkmark-circle" size={28} color={colors.success} />}
          </Card>
        ) : null}

        {s.pipelineError && s.stage === 'failed' ? <Text variant="small" muted>{s.pipelineError}</Text> : null}

        {s.draft?.longText ? (
          <Card>
            <Text variant="heading">{t('status.teaser')}</Text>
            <Text>{s.draft.longText}</Text>
          </Card>
        ) : null}

        {s.stats ? (
          <Card>
            <Text variant="heading">{t('status.listening')}</Text>
            <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: space.xl }}>
              <Stat label={t('narrate.listeners')} value={String(s.stats.listeners)} />
              <Stat label={t('narrate.minutesListened')} value={formatListening(t, s.stats.seconds)} />
              <Stat label={t('status.completions')} value={String(s.stats.completions)} />
              <Stat label={t('status.favorites')} value={String(s.stats.favorites)} />
            </View>
          </Card>
        ) : null}

        {error ? <Text color={colors.danger}>{error}</Text> : null}
        {s.stage === 'awaiting-submit' ? (
          <Button title={t('status.submit')} loading={busy} onPress={() => void act(`/api/narrator/submissions/${s.id}/submit`)} />
        ) : null}
        {s.stage === 'changes-requested' ? (
          <Button title={t('status.resubmit')} loading={busy} onPress={() => void act(`/api/narrator/submissions/${s.id}/submit`)} />
        ) : null}
        {['needs-fix', 'changes-requested', 'awaiting-submit'].includes(s.stage) ? (
          <Button kind="secondary" title={t('status.replace')} icon={<Ionicons name="mic" size={18} color={colors.text} />}
            onPress={() => router.push(`/narrate/new?replace=${s.id}`)} />
        ) : null}
        {s.status !== 'published' && s.status !== 'archived' ? (
          <Button kind="ghost" title={t('status.withdraw')} disabled={busy}
            onPress={() => void confirmAction(t('status.withdrawConfirm')).then((ok) => {
              if (ok) void act(`/api/narrator/submissions/${s.id}/withdraw`, () => router.replace('/(tabs)/narrate'));
            })} />
        ) : null}
      </ScrollView>
    </Screen>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <View>
      <Text variant="heading">{value}</Text>
      <Text variant="small" muted>{label}</Text>
    </View>
  );
}
