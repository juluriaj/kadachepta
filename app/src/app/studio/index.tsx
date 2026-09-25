import Ionicons from '@expo/vector-icons/Ionicons';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { router } from 'expo-router';
import { useEffect, useMemo, useState } from 'react';
import { Platform, Pressable, ScrollView, TextInput, View } from 'react-native';

import { Button, Chip, Cover, ErrorState, Loading, Text, useColors } from '@/components/ui';
import { api } from '@/lib/api';
import { formatClock, LANGUAGE_LABELS } from '@/lib/i18n';
import { useSession } from '@/lib/session';
import { BACKGROUND_LABELS, hoursLabel, MASTERING_CHOICES, type QueueItem, type QueueResponse } from '@/lib/studio';
import { radius, space } from '@/lib/theme';

const VIEWS = [
  { id: 'review', label: 'To review' },
  { id: 'attention', label: 'Needs attention' },
  { id: 'waiting', label: 'Waiting on narrator' },
  { id: 'pipeline', label: 'Being prepared' },
  { id: 'transcription', label: 'Needs transcription (paid)' },
  { id: 'catalog', label: 'Catalog (not started)' },
  { id: 'published', label: 'Published' },
];

export default function Queue() {
  const colors = useColors();
  const queryClient = useQueryClient();
  const { session } = useSession();
  const isAdmin = (session.permissions ?? []).includes('jobs.manage');
  const [view, setView] = useState('review');
  const [search, setSearch] = useState('');
  const [language, setLanguage] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [cursor, setCursor] = useState(0);
  const [spotChecked, setSpotChecked] = useState(false);
  const [markOwned, setMarkOwned] = useState(true);
  const [background, setBackground] = useState<string | null>(null);
  const [masterChoice, setMasterChoice] = useState<string>('auto');
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const params = new URLSearchParams({ view, ...(search.trim() ? { q: search.trim() } : {}), ...(language ? { language } : {}),
    ...(background ? { mastering: background } : {}) });
  const queue = useQuery({ queryKey: ['studio-queue', view, search.trim(), language, background],
    queryFn: () => api<QueueResponse>(`/api/studio/queue?${params}`, { profile: false }), refetchInterval: 20_000 });
  const items = useMemo(() => queue.data?.items ?? [], [queue.data]);

  const changeView = (next: string) => {
    setView(next);
    setSelected(new Set());
    setCursor(0);
    setMessage(null);
  };
  const toggle = (id: string) => setSelected((current) => {
    const next = new Set(current);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    return next;
  });

  // Keyboard: j/k move, x selects, Enter or o opens. Ignored while typing in a field.
  useEffect(() => {
    if (Platform.OS !== 'web') return;
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target && ['INPUT', 'TEXTAREA'].includes(target.tagName)) return;
      if (event.key === 'j') setCursor((c) => Math.min(c + 1, Math.max(items.length - 1, 0)));
      else if (event.key === 'k') setCursor((c) => Math.max(c - 1, 0));
      else if (event.key === 'x' && items[cursor]) toggle(items[cursor].id);
      else if ((event.key === 'Enter' || event.key === 'o') && items[cursor]) router.push(`/studio/review/${items[cursor].id}`);
      else return;
      event.preventDefault();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [items, cursor]);

  const run = async (work: () => Promise<string>) => {
    setBusy(true);
    setMessage(null);
    try {
      setMessage(await work());
      setSelected(new Set());
      await queryClient.invalidateQueries({ queryKey: ['studio-queue'] });
    } catch (failure) {
      setMessage(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setBusy(false);
    }
  };

  const bulkPublish = () => run(async () => {
    const result = await api<{ published: number; results: { title: string; ok: boolean; problems: string[] }[] }>(
      '/api/studio/bulk-publish', { method: 'POST', profile: false, body: { assetIds: [...selected], spotChecked, markOwned } });
    const failed = result.results.filter((r) => !r.ok);
    return `Published ${result.published}.` + (failed.length ? ` Not published: ${failed.map((r) => `${r.title} (${r.problems.join('; ')})`).join(', ')}` : '');
  });

  const prepare = (allowTranscription: boolean) => run(async () => {
    const ids = [...selected];
    const result = await api<{ stories: number; stages: Record<string, number>; transcriptionMinutes: number; untranscribedMinutes: number }>(
      '/api/studio/prepare', { method: 'POST', profile: false, body: { assetIds: ids, allowTranscription } });
    const stages = Object.entries(result.stages).map(([stage, count]) => `${count} ${stage}`).join(', ');
    return `Prepared ${result.stories}: ${stages}.` + (result.transcriptionMinutes ? ` Transcribing about ${result.transcriptionMinutes} minutes (paid).`
      : result.untranscribedMinutes ? ` ${result.untranscribedMinutes} minutes wait for paid transcription (admin).` : '');
  });

  // P2-18: queue the selected stories for mastering (free, local workers); listeners keep the current copy meanwhile.
  const bulkMaster = () => run(async () => {
    const result = await api<{ queued: number; skipped: { title: string; reason: string }[] }>('/api/studio/audio/master',
      { method: 'POST', profile: false, body: { assetIds: [...selected], choice: masterChoice } });
    return `Queued ${result.queued} for mastering.` + (result.skipped.length
      ? ` Skipped: ${result.skipped.map((s) => `${s.title} (${s.reason})`).join(', ')}` : '');
  });

  const selectedItems = items.filter((item) => selected.has(item.id));
  const untranscribedMinutes = Math.round(selectedItems.filter((i) => !i.hasTranscript).reduce((s, i) => s + i.duration, 0) / 60);

  return (
    <ScrollView contentContainerStyle={{ padding: space.xl, gap: space.lg, maxWidth: 1280, width: '100%', alignSelf: 'center' }}>
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: space.sm }}>
        {VIEWS.map((v) => (
          <Chip key={v.id} label={`${v.label}${queue.data?.counts[v.id] != null ? ` · ${queue.data.counts[v.id]}` : ''}`}
            selected={view === v.id} onPress={() => changeView(v.id)} />
        ))}
      </View>
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: space.md, alignItems: 'center' }}>
        <TextInput value={search} onChangeText={setSearch} placeholder="Search title, series, or id" accessibilityLabel="Search"
          placeholderTextColor={colors.muted}
          style={{ flexGrow: 1, minWidth: 240, minHeight: 40, borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
            paddingHorizontal: space.md, color: colors.text, backgroundColor: colors.surface }} />
        {Object.entries(LANGUAGE_LABELS).map(([code, label]) => (
          <Chip key={code} label={label} selected={language === code} onPress={() => setLanguage(language === code ? null : code)} />
        ))}
      </View>
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: space.sm, alignItems: 'center' }}>
        <Text variant="small" muted>Background:</Text>
        {Object.entries(BACKGROUND_LABELS).filter(([code]) => code !== 'unknown').map(([code, label]) => (
          <Chip key={code} label={label} selected={background === code}
            onPress={() => { setBackground(background === code ? null : code); setSelected(new Set()); }} />
        ))}
      </View>

      <View style={{ gap: space.sm, padding: space.md, borderRadius: radius.md, backgroundColor: colors.surfaceAlt }}>
        <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: space.md, alignItems: 'center' }}>
          <Button kind="ghost" title="Select all" onPress={() => setSelected(new Set(items.map((i) => i.id)))} />
          {view === 'review' ? (
            <Button kind="ghost" title="Select all eligible to publish"
              onPress={() => setSelected(new Set(items.filter((i) => i.bulkEligible).map((i) => i.id)))} />
          ) : null}
          {selected.size ? <Button kind="ghost" title="Clear" onPress={() => setSelected(new Set())} /> : null}
          <Text variant="small">{selected.size} selected</Text>
        </View>
        {view === 'review' || view === 'catalog' || view === 'transcription' ? (
        <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: space.md, alignItems: 'center' }}>
          {view === 'review' ? (
            <>
              <Check label="I spot-checked a few of these" checked={spotChecked} onChange={setSpotChecked} />
              <Check label="Catalog stories: KathaChepta owns them" checked={markOwned} onChange={setMarkOwned} />
              <Button title={`Publish ${selected.size}`} disabled={!selected.size || !spotChecked} loading={busy}
                onPress={() => void bulkPublish()} />
            </>
          ) : (
            <>
              <Button title="Prepare (free: drafts and artwork)" disabled={!selected.size} loading={busy} onPress={() => void prepare(false)} />
              {isAdmin ? (
                <Button kind="secondary" disabled={!selected.size || busy}
                  title={`Prepare with transcription (paid, ~${untranscribedMinutes} min)`} onPress={() => void prepare(true)} />
              ) : null}
            </>
          )}
        </View>
        ) : null}
        <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: space.sm, alignItems: 'center' }}>
          <Text variant="small" muted>Mastering:</Text>
          {MASTERING_CHOICES.map(([value, label]) => (
            <Chip key={value} label={label} selected={masterChoice === value} onPress={() => setMasterChoice(value)} />
          ))}
          <Button kind="secondary" title={`Queue mastering (${selected.size})`} disabled={!selected.size} loading={busy}
            onPress={() => void bulkMaster()} />
        </View>
        <Text variant="small" muted>
          Free, on our own workers. Listeners keep the current audio until the new copy is ready. Automatic decides from
          the recording; the other choices are kept for each story. Words, pauses, and expression are never edited.
        </Text>
      </View>
      {message ? <Text>{message}</Text> : null}

      {queue.isLoading ? <Loading /> : queue.error ? <ErrorState error={queue.error} onRetry={() => void queue.refetch()} /> : null}
      {!queue.isLoading && !items.length ? <Text muted>Nothing here.</Text> : null}
      <View style={{ gap: 2 }}>
        {items.map((item, index) => (
          <Row key={item.id} item={item} focused={index === cursor} selected={selected.has(item.id)}
            showBlockers={view === 'review'} onToggle={() => toggle(item.id)} />
        ))}
      </View>
      {Platform.OS === 'web' ? <Text variant="small" muted>Keys: j / k move · x select · Enter open</Text> : null}
    </ScrollView>
  );
}

function Check({ label, checked, onChange }: { label: string; checked: boolean; onChange: (value: boolean) => void }) {
  const colors = useColors();
  return (
    <Pressable accessibilityRole="checkbox" accessibilityState={{ checked }} onPress={() => onChange(!checked)}
      style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
      <Ionicons name={checked ? 'checkbox' : 'square-outline'} size={20} color={colors.primary} />
      <Text variant="small">{label}</Text>
    </Pressable>
  );
}

function Badge({ text, color }: { text: string; color: string }) {
  return (
    <View style={{ borderWidth: 1, borderColor: color, borderRadius: 6, paddingHorizontal: 6, paddingVertical: 1 }}>
      <Text variant="label" color={color}>{text}</Text>
    </View>
  );
}

function Row({ item, focused, selected, showBlockers, onToggle }: {
  item: QueueItem; focused: boolean; selected: boolean; showBlockers: boolean; onToggle: () => void;
}) {
  const colors = useColors();
  const safetyColor = item.safetyRating === 'all-ages' ? colors.success : item.safetyRating === 'caution' ? colors.accent : colors.danger;
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', gap: space.md, padding: space.sm, borderRadius: radius.md,
      backgroundColor: focused ? colors.surfaceAlt : colors.surface, borderWidth: 1, borderColor: focused ? colors.primary : colors.border }}>
      <Pressable accessibilityRole="checkbox" accessibilityState={{ checked: selected }} accessibilityLabel={`Select ${item.title}`}
        onPress={onToggle} hitSlop={8}>
        <Ionicons name={selected ? 'checkbox' : 'square-outline'} size={22} color={colors.primary} />
      </Pressable>
      <Pressable accessibilityRole="link" onPress={() => router.push(`/studio/review/${item.id}`)}
        style={{ flex: 1, flexDirection: 'row', alignItems: 'center', gap: space.md }}>
        <Cover id={item.id} title={item.title} artworkUrl={item.artworkUrl} size={48} rounded={8} />
        <View style={{ flex: 1, gap: 2 }}>
          <Text variant="heading" numberOfLines={1}>{item.title}</Text>
          <Text variant="small" muted numberOfLines={1}>
            {[item.narrator + (item.trustLevel === 'trusted' ? ' ✓ trusted' : ''), item.series, item.language,
              formatClock(item.duration)].filter(Boolean).join(' · ')}
          </Text>
          {item.teaser ? <Text variant="small" numberOfLines={1}>{item.teaser}</Text> : null}
          {item.pipelineError ? <Text variant="small" color={colors.danger} numberOfLines={2}>{item.pipelineError}</Text> : null}
        </View>
        <View style={{ alignItems: 'flex-end', gap: 4, maxWidth: 320 }}>
          <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 4, justifyContent: 'flex-end' }}>
            <Badge text={item.stageLabel ?? item.stage} color={colors.muted} />
            {item.safetyRating ? <Badge text={item.safetyRating} color={safetyColor} /> : null}
            {item.qcVerdict && item.qcVerdict !== 'pass' ? <Badge text={`sound ${item.qcVerdict}`} color={colors.accent} /> : null}
            {item.transcriptReviewRequired ? <Badge text="read transcript" color={colors.accent} /> : null}
            {!item.hasTranscript && item.stage !== 'published' ? <Badge text="no transcript" color={colors.muted} /> : null}
            {item.mastering.processing ? <Badge text="mastering…" color={colors.primary} />
              : item.mastering.profile === 'tonal' ? <Badge text="steady tone: listen" color={colors.accent} />
              : item.mastering.level ? <Badge text={{ full: 'cleaned up', light: 'polished', none: 'as recorded' }[item.mastering.level]}
                color={colors.muted} /> : null}
          </View>
          {item.waitingHours != null ? (
            <Text variant="small" color={item.overdue ? colors.danger : colors.muted}>
              {item.overdue ? 'Overdue · ' : ''}waiting {hoursLabel(item.waitingHours)}
            </Text>
          ) : null}
          {showBlockers && !item.bulkEligible && item.bulkBlockers.length ? (
            <Text variant="small" muted numberOfLines={1}>Bulk: {item.bulkBlockers.join(', ')}</Text>
          ) : null}
        </View>
      </Pressable>
    </View>
  );
}
