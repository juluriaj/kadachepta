import Ionicons from '@expo/vector-icons/Ionicons';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { router } from 'expo-router';
import { type ReactNode, useEffect, useMemo, useState } from 'react';
import { Platform, Pressable, ScrollView, TextInput, View } from 'react-native';

import { AddToCollection, useCollectionsByStory } from '@/components/StudioCollections';
import { Button, Card, Chip, Cover, ErrorState, Loading, Text, useColors } from '@/components/ui';
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
  { id: 'transcription', label: 'Needs transcription (admin, paid)' },
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
  const [busy, setBusy] = useState<string | null>(null);  // the action running

  const params = new URLSearchParams({ view, ...(search.trim() ? { q: search.trim() } : {}), ...(language ? { language } : {}),
    ...(background ? { mastering: background } : {}) });
  const queue = useQuery({ queryKey: ['studio-queue', view, search.trim(), language, background],
    queryFn: () => api<QueueResponse>(`/api/studio/queue?${params}`, { profile: false }), refetchInterval: 20_000 });
  const items = useMemo(() => queue.data?.items ?? [], [queue.data]);
  const inCollections = useCollectionsByStory();

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

  const run = async (action: string, work: () => Promise<string>) => {
    setBusy(action);
    setMessage(null);
    try {
      setMessage(await work());
      setSelected(new Set());
      await queryClient.invalidateQueries({ queryKey: ['studio-queue'] });
    } catch (failure) {
      setMessage(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setBusy(null);
    }
  };

  const bulkPublish = () => run('publish', async () => {
    const result = await api<{ published: number; results: { title: string; ok: boolean; problems: string[] }[] }>(
      '/api/studio/bulk-publish', { method: 'POST', profile: false, body: { assetIds: [...selected], spotChecked, markOwned } });
    const failed = result.results.filter((r) => !r.ok);
    return `Published ${result.published}.` + (failed.length ? ` Not published: ${failed.map((r) => `${r.title} (${r.problems.join('; ')})`).join(', ')}` : '');
  });

  const prepare = (allowTranscription: boolean) => run(allowTranscription ? 'transcribe' : 'prepare', async () => {
    const result = await api<PrepareResult>('/api/studio/prepare',
      { method: 'POST', profile: false, body: { assetIds: [...selected], allowTranscription } });
    return prepareSummary(result, isAdmin);
  });

  // P2-18: queue the selected stories for mastering (free, local workers); listeners keep the current copy meanwhile.
  const bulkMaster = () => run('master', async () => {
    const result = await api<{ queued: number; skipped: { title: string; reason: string }[] }>('/api/studio/audio/master',
      { method: 'POST', profile: false, body: { assetIds: [...selected], choice: masterChoice } });
    return `Queued ${result.queued} for mastering.` + (result.skipped.length
      ? ` Skipped: ${result.skipped.map((s) => `${s.title} (${s.reason})`).join(', ')}` : '');
  });

  const selectedItems = items.filter((item) => selected.has(item.id));
  const untranscribed = selectedItems.filter((i) => !i.hasTranscript);
  const untranscribedMinutes = Math.round(untranscribed.reduce((s, i) => s + i.duration, 0) / 60);
  const transcribed = selectedItems.length - untranscribed.length;
  const allSelected = items.length > 0 && items.every((item) => selected.has(item.id));
  const eligible = items.filter((i) => i.bulkEligible);
  const count = selected.size;
  const stories = (n: number) => `${n} ${n === 1 ? 'story' : 'stories'}`;

  return (
    <ScrollView contentContainerStyle={{ padding: space.xl, gap: space.lg, maxWidth: 1280, width: '100%', alignSelf: 'center' }}>
      <View accessibilityRole="radiogroup" accessibilityLabel={"Queue"} style={{ flexDirection: 'row', flexWrap: 'wrap', gap: space.sm }}>
        {VIEWS.map((v) => (
          <Chip key={v.id} role="radio" label={`${v.label}${queue.data?.counts[v.id] != null ? ` · ${queue.data.counts[v.id]}` : ''}`}
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

      {/* Each kind of work is its own card: what it does, what it costs, and one button for the selected stories. */}
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: space.md, alignItems: 'stretch' }}>
        {view === 'review' ? (
          <ActionCard title="Publish" summary="Stories that passed every automatic check go live for listeners.">
            <Check label="I spot-checked a few of these" checked={spotChecked} onChange={setSpotChecked} />
            <Check label="Catalog stories: KathaChepta owns them" checked={markOwned} onChange={setMarkOwned} />
            <Button title={count ? `Publish ${stories(count)}` : 'Publish'} disabled={!count || !spotChecked || !!busy}
              loading={busy === 'publish'} onPress={() => void bulkPublish()} style={{ alignSelf: 'flex-start' }} />
          </ActionCard>
        ) : null}

        {view === 'catalog' || view === 'transcription' ? (
          <ActionCard title="Prepare for review"
            summary="Transcript, then AI drafts (teaser, details, safety), titles and starters, then artwork. Prepared stories move to To review.">
            <AdminOnly>
              {isAdmin ? "Paid transcription is admin-only: editors can't start it, so stories without a transcript wait for you in Needs transcription. It is billed per minute of audio."
                : view === 'transcription' ? "Paid transcription is admin-only. These stories have no transcript, so they wait here until an admin transcribes them. Editors can't start it; ask an admin."
                : "Paid transcription is admin-only. You can prepare stories that already have a transcript (free); the rest move to Needs transcription and wait for an admin."}
            </AdminOnly>
            {!count ? (isAdmin || view === 'catalog' ? <Text variant="small" muted>Tick stories in the list below.</Text> : null) : (
              <View style={{ gap: 2 }}>
                {transcribed ? <Text variant="small">{stories(transcribed)} with a transcript: drafts and artwork start right away (free).</Text> : null}
                {untranscribed.length ? (
                  <Text variant="small">
                    {stories(untranscribed.length)} without a transcript (~{untranscribedMinutes} min of audio): drafts and artwork
                    are written from the transcript, so these need paid transcription by an admin first.
                  </Text>
                ) : null}
              </View>
            )}
            <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: space.sm }}>
              {isAdmin ? (
                <Button title={count ? `Transcribe and prepare ${stories(count)} (admin, paid, ~${untranscribedMinutes} min)` : 'Transcribe and prepare (admin, paid)'}
                  icon={<Ionicons name="lock-closed" size={16} color={colors.onPrimary} />}
                  disabled={!count || !!busy} loading={busy === 'transcribe'} onPress={() => void prepare(true)} />
              ) : null}
              {view === 'catalog' ? (
                <Button kind={isAdmin ? 'secondary' : 'primary'} title={count ? `Prepare ${stories(count)} (free only)` : 'Prepare (free only)'}
                  disabled={!count || !!busy} loading={busy === 'prepare'} onPress={() => void prepare(false)} />
              ) : null}
            </View>
          </ActionCard>
        ) : null}

        {view === 'published' ? (
          <ActionCard title="Collections" summary="Add the selected stories to a story set or collection.">
            <AddToCollection assetIds={[...selected]} />
          </ActionCard>
        ) : null}

        <ActionCard title="Clean up audio (mastering)"
          summary="Free, on our own workers. Changes only how a story sounds: words, pauses, and expression are never edited. Listeners keep the current audio until the new copy is ready.">
          <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: space.sm }}>
            {MASTERING_CHOICES.map(([value, label]) => (
              <Chip key={value} label={label} selected={masterChoice === value} onPress={() => setMasterChoice(value)} />
            ))}
          </View>
          <Text variant="small" muted>Automatic decides from each recording; the other choices are kept for each story.</Text>
          <Button kind={['review', 'catalog', 'transcription'].includes(view) ? 'secondary' : 'primary'}
            title={count ? `Master ${stories(count)}` : 'Master'} disabled={!count || !!busy} loading={busy === 'master'}
            onPress={() => void bulkMaster()} style={{ alignSelf: 'flex-start' }} />
        </ActionCard>
      </View>
      {message ? (
        <View style={{ padding: space.md, borderRadius: radius.md, backgroundColor: colors.surfaceAlt }}>
          <Text>{message}</Text>
        </View>
      ) : null}

      {queue.isLoading ? <Loading /> : queue.error ? <ErrorState error={queue.error} onRetry={() => void queue.refetch()} /> : null}
      {!queue.isLoading && !items.length ? <Text muted>Nothing here.</Text> : null}
      {items.length ? (
        <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: space.md, alignItems: 'center', paddingHorizontal: space.sm }}>
          <Pressable accessibilityRole="checkbox" accessibilityState={{ checked: allSelected }}
            onPress={() => setSelected(allSelected ? new Set() : new Set(items.map((i) => i.id)))}
            style={{ flexDirection: 'row', alignItems: 'center', gap: space.md, minHeight: 40 }}>
            <Ionicons name={allSelected ? 'checkbox' : count ? 'remove-circle-outline' : 'square-outline'} size={22} color={colors.primary} />
            <Text variant="small">{allSelected ? 'Unselect all' : `Select all ${items.length}`}</Text>
          </Pressable>
          {view === 'review' && eligible.length ? (
            <Button kind="ghost" title={`Select the ${eligible.length} eligible to publish`}
              onPress={() => setSelected(new Set(eligible.map((i) => i.id)))} />
          ) : null}
          {count && !allSelected ? <Button kind="ghost" title="Clear" onPress={() => setSelected(new Set())} /> : null}
          <View style={{ flex: 1 }} />
          <Text variant="small" muted>{count ? `${stories(count)} selected` : 'Tick stories to act on them'}</Text>
        </View>
      ) : null}
      <View style={{ gap: 2 }}>
        {items.map((item, index) => (
          <Row key={item.id} item={item} focused={index === cursor} selected={selected.has(item.id)}
            showBlockers={view === 'review'} collections={inCollections.get(item.id) ?? []} onToggle={() => toggle(item.id)} />
        ))}
      </View>
      {Platform.OS === 'web' ? <Text variant="small" muted>Keys: j / k move · x select · Enter open</Text> : null}
    </ScrollView>
  );
}

function Check({ label, checked, onChange }: { label: string; checked: boolean; onChange: (value: boolean) => void }) {
  const colors = useColors();
  return (
    <Pressable accessibilityRole="checkbox" aria-checked={checked} onPress={() => onChange(!checked)}
      style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
      <Ionicons name={checked ? 'checkbox' : 'square-outline'} size={20} color={colors.primary} />
      <Text variant="small">{label}</Text>
    </Pressable>
  );
}

function AdminOnly({ children }: { children: ReactNode }) {
  const colors = useColors();
  return (
    <View accessibilityRole="text" style={{ flexDirection: 'row', gap: space.sm, alignItems: 'flex-start', padding: space.sm,
      borderRadius: radius.md, borderWidth: 1, borderColor: colors.accent }}>
      <Ionicons name="lock-closed" size={16} color={colors.accent} style={{ marginTop: 2 }} />
      <Text variant="small" style={{ flex: 1 }}>{children}</Text>
    </View>
  );
}

function ActionCard({ title, summary, children }: { title: string; summary: string; children: ReactNode }) {
  return (
    <Card style={{ flexGrow: 1, flexBasis: 360, gap: space.md }}>
      <View style={{ gap: 2 }}>
        <Text variant="heading">{title}</Text>
        <Text variant="small" muted>{summary}</Text>
      </View>
      {children}
    </Card>
  );
}

type PrepareResult = { stories: number; stages: Record<string, number>; transcriptionMinutes: number; untranscribedMinutes: number };

// What happened to the prepared stories, in the words of the queue's tabs.
const PREPARE_OUTCOMES: Record<string, string> = {
  checking: 'getting an audio check first', transcribing: 'being transcribed (paid)', drafting: 'getting drafts, then artwork',
  illustrating: 'getting artwork', ready: 'ready to review', 'needs-fix': 'need a sound fix (Needs attention)',
  failed: 'stuck (Needs attention)', published: 'already published',
};

function prepareSummary(result: PrepareResult, isAdmin: boolean): string {
  const waiting = result.stages['waiting-transcript'] ?? 0;
  if (!result.stories) return 'Nothing to prepare: these stories are already published or belong to a narrator.';
  if (waiting === result.stories) {
    return `Nothing could start: ${waiting === 1 ? 'this story has' : `these ${waiting} stories have`} no transcript, and drafts `
      + 'and artwork are written from it. ' + (isAdmin ? 'Use "Transcribe and prepare" (paid) to start them.'
        : 'An admin can start paid transcription from the Needs transcription tab.');
  }
  const parts = Object.entries(result.stages).filter(([stage]) => stage !== 'waiting-transcript')
    .map(([stage, n]) => `${n} ${PREPARE_OUTCOMES[stage] ?? stage}`);
  if (waiting) parts.push(`${waiting} waiting for paid transcription (Needs transcription)`);
  return `Prepared ${result.stories}: ${parts.join(', ')}.`
    + (result.transcriptionMinutes ? ` About ${result.transcriptionMinutes} minutes of paid transcription queued.` : '');
}

function Badge({ text, color }: { text: string; color: string }) {
  return (
    <View style={{ borderWidth: 1, borderColor: color, borderRadius: 6, paddingHorizontal: 6, paddingVertical: 1 }}>
      <Text variant="label" color={color}>{text}</Text>
    </View>
  );
}

function Row({ item, focused, selected, showBlockers, collections, onToggle }: {
  item: QueueItem; focused: boolean; selected: boolean; showBlockers: boolean; collections: string[]; onToggle: () => void;
}) {
  const colors = useColors();
  const safetyColor = item.safetyRating === 'all-ages' ? colors.success : item.safetyRating === 'caution' ? colors.accent : colors.danger;
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', gap: space.md, padding: space.sm, borderRadius: radius.md,
      backgroundColor: focused ? colors.surfaceAlt : colors.surface, borderWidth: 1, borderColor: focused ? colors.primary : colors.border }}>
      <Pressable accessibilityRole="checkbox" aria-checked={selected} accessibilityLabel={`Select ${item.title}`}
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
            {collections.map((name, index) => <Badge key={index} text={`in ${name}`} color={colors.primary} />)}
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
