import Ionicons from '@expo/vector-icons/Ionicons';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useAudioPlayer, useAudioPlayerStatus } from 'expo-audio';
import { router } from 'expo-router';
import { createContext, useContext, useEffect, useRef, useState } from 'react';
import { Pressable, ScrollView, TextInput, View } from 'react-native';

import { Button, Chip, Cover, ErrorState, Loading, Text, useColors } from '@/components/ui';
import { api, ApiError, mediaUrl } from '@/lib/api';
import { formatClock } from '@/lib/i18n';
import { getEngine } from '@/lib/player/engine';
import { AGE_RANGES } from '@/lib/studio';
import { fontFor, radius, space } from '@/lib/theme';

type Spot = 'start' | 'middle' | 'end';
type Item = {
  id: string; title: string; collection: string | null; language: string; duration: number; audioUrl: string | null;
  artworkUrl: string | null; qcVerdict: string | null; series: { title: string; position: number } | null;
  titles: Record<string, string>; teasers: Record<string, { short: string; long: string }>; draftLanguage: string | null;
  age: string | null; moral: string | null; genres: string[]; warnings: string[]; prompts: string[];
  safety: { rating: string | null; summary: string | null; flags: { category: string; severity: string; evidence?: string }[] } | null;
  transcript: { text: string; confidence: number | null; reviewRequired: boolean } | null; fullReview: string[];
};
type Page = { groups: { name: string | null; count: number }[]; total: number; items: Item[] };

const PAGE = 20;
const SPOTS: [Spot, string, number][] = [['start', 'Start', 0], ['middle', 'Middle', 0.5], ['end', 'End', 0.92]];
const LANGUAGE_NAMES: Record<string, string> = { 'te-IN': 'Telugu', 'en-IN': 'English' };

// One player for the page: jumping to a spot in a story stops whatever else was playing.
type Player = { playing: string | null; jump: (item: Item, spot: Spot, at: number) => void; stop: () => void; heard: Record<string, Spot[]> };
const PlayerContext = createContext<Player | null>(null);

function usePagePlayer(): Player {
  const player = useAudioPlayer(null);
  const status = useAudioPlayerStatus(player);
  const [current, setCurrent] = useState<string | null>(null);
  const [heard, setHeard] = useState<Record<string, Spot[]>>({});
  const pending = useRef<number | null>(null);

  useEffect(() => {  // a new source can only seek once it has loaded
    if (status.isLoaded && pending.current != null) {
      const at = pending.current;
      pending.current = null;
      void player.seekTo(at).then(() => player.play());
    }
  }, [status.isLoaded, player]);

  return {
    playing: status.playing ? current : null, heard,
    jump: (item, spot, at) => {
      if (!item.audioUrl) return;
      if (getEngine().getSnapshot().playing) getEngine().toggle();
      const seconds = Math.max(0, at * item.duration);
      if (current === item.id && status.isLoaded) void player.seekTo(seconds).then(() => player.play());
      else {
        pending.current = seconds;
        player.replace({ uri: mediaUrl(item.audioUrl)! });
        setCurrent(item.id);
      }
      setHeard((all) => ({ ...all, [item.id]: [...new Set([...(all[item.id] ?? []), spot])] }));
    },
    stop: () => player.pause(),
  };
}

// Batch review of ready catalog stories (seed catalog only). Each card is one approval: listen to the start, a
// middle section and the end, confirm the age band, titles and teaser, then publish. Anything flagged opens the
// full review instead.
export default function BatchReview() {
  const colors = useColors();
  const [group, setGroup] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);
  const [done, setDone] = useState<Set<string>>(new Set());
  const player = usePagePlayer();
  const params = new URLSearchParams({ limit: String(PAGE), offset: String(offset), ...(group ? { group } : {}) });
  const query = useQuery({ queryKey: ['studio-batch', group, offset],
    queryFn: () => api<Page>(`/api/studio/batch?${params}`, { profile: false }) });

  const pick = (name: string | null) => {
    setGroup(name);
    setOffset(0);
  };
  const data = query.data;
  const items = (data?.items ?? []).filter((item) => !done.has(item.id));

  return (
    <PlayerContext.Provider value={player}>
      <ScrollView contentContainerStyle={{ padding: space.xl, gap: space.lg, maxWidth: 1280, width: '100%', alignSelf: 'center' }}>
        <Text variant="title">Batch review</Text>
        <Text muted>
          Catalog stories that are ready, one card each. Play the start, a middle section and the end (the buttons on each card), check
          the age band against the safety notes, fix the titles and teaser if needed, then publish. Captions are shown only if you
          tick that you read the transcript. Cards marked “Full review” have something that needs a closer look.
        </Text>
        <View accessibilityRole="radiogroup" accessibilityLabel={"Group"} style={{ flexDirection: 'row', flexWrap: 'wrap', gap: space.sm }}>
          <Chip role="radio" label={`All · ${data?.groups.reduce((sum, g) => sum + g.count, 0) ?? ''}`} selected={!group} onPress={() => pick(null)} />
          {data?.groups.map((g) => (
            <Chip key={g.name ?? '-'} role="radio" label={`${g.name ?? 'Other'} · ${g.count}`} selected={group === g.name}
              onPress={() => pick(g.name)} />
          ))}
        </View>
        {query.isLoading ? <Loading /> : query.error ? <ErrorState error={query.error} onRetry={() => void query.refetch()} /> : null}
        {data && !items.length ? <Text muted>Nothing ready here. Stories appear as the AI drafts finish.</Text> : null}
        {items.map((item) => (
          <BatchCard key={item.id} item={item} onPublished={() => setDone((all) => new Set(all).add(item.id))} />
        ))}
        {data && data.total > PAGE ? (
          <View style={{ flexDirection: 'row', gap: space.md, alignItems: 'center' }}>
            <Button kind="secondary" title="Previous" disabled={offset === 0} onPress={() => setOffset(Math.max(0, offset - PAGE))} />
            <Text variant="small">{offset + 1}–{Math.min(offset + PAGE, data.total)} of {data.total}</Text>
            <Button kind="secondary" title="Next" disabled={offset + PAGE >= data.total} onPress={() => setOffset(offset + PAGE)} />
          </View>
        ) : null}
        {done.size ? (
          <Text variant="small" color={colors.success}>Published {done.size} on this visit.</Text>
        ) : null}
      </ScrollView>
    </PlayerContext.Provider>
  );
}

function BatchCard({ item, onPublished }: { item: Item; onPublished: () => void }) {
  const colors = useColors();
  const queryClient = useQueryClient();
  const player = useContext(PlayerContext)!;
  const [title, setTitle] = useState(item.title);
  const [titles, setTitles] = useState<Record<string, string>>(item.titles);
  const [teasers, setTeasers] = useState<Record<string, string>>(
    Object.fromEntries(Object.entries(item.teasers).map(([lang, text]) => [lang, text.short])));
  const [age, setAge] = useState(item.age ?? '');
  const [moral, setMoral] = useState(item.moral ?? '');
  const [keepPrompts, setKeepPrompts] = useState(true);
  const [transcriptOpen, setTranscriptOpen] = useState(false);
  const [transcriptChecked, setTranscriptChecked] = useState(false);
  const [checked, setChecked] = useState(false);
  const [busy, setBusy] = useState(false);
  const [problems, setProblems] = useState<string[]>([]);

  const heard = player.heard[item.id] ?? [];
  const listened = SPOTS.every(([spot]) => heard.includes(spot));
  const safety = item.safety;
  const safetyColor = safety?.rating === 'all-ages' ? colors.success : safety?.rating === 'caution' ? colors.accent : colors.danger;
  const needsTranscript = !!item.transcript?.reviewRequired;
  const blocked = item.fullReview.length > 0;
  const canPublish = listened && checked && !!age && !!moral.trim() && !!title.trim() && (!needsTranscript || transcriptChecked);

  const publish = async () => {
    setBusy(true);
    setProblems([]);
    try {
      await api(`/api/studio/batch/${item.id}/publish`, { method: 'POST', profile: false, body: {
        title, titles: Object.fromEntries(Object.entries(titles).filter(([, text]) => text.trim())), teasers, age, moral,
        keepPrompts, transcriptChecked, checked } });
      if (player.playing === item.id) player.stop();
      onPublished();
      void queryClient.invalidateQueries({ queryKey: ['studio-queue'] });
    } catch (failure) {
      if (failure instanceof ApiError && Array.isArray(failure.body.problems)) setProblems(failure.body.problems as string[]);
      else setProblems([failure instanceof Error ? failure.message : String(failure)]);
    } finally {
      setBusy(false);
    }
  };

  return (
    <View style={{ gap: space.md, padding: space.lg, borderRadius: radius.lg, borderWidth: 1, borderColor: colors.border,
      backgroundColor: colors.surface }}>
      <View style={{ flexDirection: 'row', gap: space.md, alignItems: 'flex-start' }}>
        <Cover id={item.id} title={item.title} artworkUrl={item.artworkUrl} size={88} rounded={10} />
        <View style={{ flex: 1, gap: 4 }}>
          <Text variant="small" muted>
            {[item.collection, item.series ? `Chapter ${item.series.position} of ${item.series.title}` : null, formatClock(item.duration),
              item.qcVerdict && item.qcVerdict !== 'pass' ? `sound ${item.qcVerdict}` : null].filter(Boolean).join(' · ')}
          </Text>
          <Input label="Title (as recorded)" value={title} onChange={setTitle} />
          <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: space.md }}>
            {Object.keys(titles).map((lang) => (
              <View key={lang} style={{ flex: 1, minWidth: 220 }}>
                <Input label={`${LANGUAGE_NAMES[lang] ?? lang} title`} value={titles[lang]}
                  onChange={(text) => setTitles({ ...titles, [lang]: text })} />
              </View>
            ))}
          </View>
        </View>
      </View>

      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: space.sm, alignItems: 'center' }}>
        <Text variant="small" muted>Listen:</Text>
        {SPOTS.map(([spot, label, at]) => (
          <Chip key={spot} label={label} selected={heard.includes(spot)} onPress={() => player.jump(item, spot, at)}
            icon={<Ionicons name={heard.includes(spot) ? 'checkmark' : 'play'} size={14}
              color={heard.includes(spot) ? colors.onPrimary : colors.text} />} />
        ))}
        {player.playing === item.id ? <Button kind="ghost" title="Pause" onPress={player.stop} /> : null}
      </View>

      {safety ? (
        <View style={{ gap: 2 }}>
          <Text variant="small" color={safetyColor}>Safety: {safety.rating ?? 'unknown'}{safety.summary ? ` · ${safety.summary}` : ''}</Text>
          {safety.flags.map((flag, index) => (
            <Text key={index} variant="small" muted>• {flag.category} ({flag.severity}){flag.evidence ? `: ${flag.evidence}` : ''}</Text>
          ))}
          {item.warnings.length ? <Text variant="small" muted>Warnings: {item.warnings.join(', ')}</Text> : null}
        </View>
      ) : null}
      <View accessibilityRole="radiogroup" accessibilityLabel={"Age"} style={{ flexDirection: 'row', flexWrap: 'wrap', gap: space.sm, alignItems: 'center' }}>
        <Text variant="small" muted>Age:</Text>
        {AGE_RANGES.map((band) => <Chip key={band} role="radio" label={band} selected={age === band} onPress={() => setAge(band)} />)}
      </View>

      {Object.keys(teasers).map((lang) => (
        <Input key={lang} label={`Teaser (${LANGUAGE_NAMES[lang] ?? lang})`} value={teasers[lang]} multiline
          onChange={(text) => setTeasers({ ...teasers, [lang]: text })} />
      ))}
      <Input label="Moral (one line)" value={moral} onChange={setMoral} />
      {item.prompts.length ? (
        <View style={{ gap: 2 }}>
          <Toggle label="Keep these conversation starters" checked={keepPrompts} onChange={setKeepPrompts} />
          {item.prompts.map((prompt, index) => <Text key={index} variant="small" muted>• {prompt}</Text>)}
        </View>
      ) : null}

      {item.transcript ? (
        <View style={{ gap: space.xs }}>
          <Pressable onPress={() => setTranscriptOpen(!transcriptOpen)} accessibilityRole="button">
            <Text variant="small" color={needsTranscript ? colors.accent : colors.primary}>
              {transcriptOpen ? 'Hide' : 'Show'} transcript
              {item.transcript.confidence != null ? ` (confidence ${Math.round(item.transcript.confidence * 100)}%)` : ''}
              {needsTranscript ? ' · looks unreliable: read it before publishing' : ''}
            </Text>
          </Pressable>
          {transcriptOpen ? (
            <Text style={{ fontFamily: fontFor(item.transcript.text), maxHeight: 260, overflow: 'scroll' }}>{item.transcript.text}</Text>
          ) : null}
          <Toggle label="I read the transcript (captions will be shown)" checked={transcriptChecked} onChange={setTranscriptChecked} />
        </View>
      ) : null}

      <Toggle checked={checked} onChange={setChecked}
        label="I listened to the start, middle and end; the age band fits the safety notes; it's a human narration; the teaser has no spoilers or invented facts." />
      {problems.length ? problems.map((problem) => <Text key={problem} variant="small" color={colors.danger}>{problem}</Text>) : null}
      {blocked ? <Text variant="small" color={colors.accent}>Full review needed: {item.fullReview.join(', ')}</Text> : null}
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: space.md, alignItems: 'center' }}>
        {!blocked ? <Button title="Publish" loading={busy} disabled={!canPublish} onPress={() => void publish()} /> : null}
        <Button kind={blocked ? 'primary' : 'ghost'} title="Open full review" onPress={() => router.push(`/studio/review/${item.id}`)} />
        {!blocked && !listened ? <Text variant="small" muted>Play the start, middle and end first.</Text> : null}
      </View>
    </View>
  );
}

function Input({ label, value, onChange, multiline }: { label: string; value: string; onChange: (text: string) => void; multiline?: boolean }) {
  const colors = useColors();
  return (
    <View style={{ gap: 2 }}>
      <Text variant="label" muted>{label}</Text>
      <TextInput value={value} onChangeText={onChange} multiline={multiline} accessibilityLabel={label}
        style={{ minHeight: multiline ? 56 : 38, borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
          paddingHorizontal: space.sm, paddingVertical: 6, color: colors.text, backgroundColor: colors.background,
          fontFamily: fontFor(value) }} />
    </View>
  );
}

function Toggle({ label, checked, onChange }: { label: string; checked: boolean; onChange: (value: boolean) => void }) {
  const colors = useColors();
  return (
    <Pressable accessibilityRole="checkbox" aria-checked={checked} onPress={() => onChange(!checked)}
      style={{ flexDirection: 'row', alignItems: 'flex-start', gap: 6 }}>
      <Ionicons name={checked ? 'checkbox' : 'square-outline'} size={20} color={colors.primary} />
      <Text variant="small" style={{ flex: 1 }}>{label}</Text>
    </Pressable>
  );
}
