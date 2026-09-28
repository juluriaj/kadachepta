import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { ScrollView, View } from 'react-native';

import { Button, Card, Chip, ErrorState, Field, Loading, Text, useColors } from '@/components/ui';
import { api } from '@/lib/api';
import { fontFor, space } from '@/lib/theme';

type TitleEntry = { text: string; by: string; confirmed: boolean };
type Item = { id: string; title: string; status: string; album: string | null; titles: Record<string, TitleEntry>;
  pending: boolean; done: boolean };

const LABELS: Record<string, string> = { 'te-IN': 'Telugu', 'en-IN': 'English' };

// Titles in each app language. Listeners see a title once it is confirmed here (or on the review screen);
// until then they see the title as recorded. The local AI model suggests; the editor corrects and confirms.
export default function Titles() {
  const colors = useColors();
  const [scope, setScope] = useState<'published' | 'all'>('published');
  const [showDone, setShowDone] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const query = useQuery({
    queryKey: ['studio-titles', scope],
    queryFn: () => api<{ languages: string[]; items: Item[] }>(`/api/studio/titles?scope=${scope}`, { profile: false }),
    refetchInterval: (q) => (q.state.data?.items.some((item) => item.pending) ? 10_000 : false),
  });

  const suggest = async () => {
    setMessage(null);
    try {
      const result = await api<{ queued: number }>('/api/studio/titles/suggest', { method: 'POST', profile: false, body: { scope } });
      setMessage(result.queued ? `Asked the AI for ${result.queued} stories. Suggestions appear here as they finish (about 2 seconds each, `
        + 'when the AI worker is running).' : 'Every story already has a suggestion or a confirmed title.');
      await query.refetch();
    } catch (failure) {
      setMessage(failure instanceof Error ? failure.message : String(failure));
    }
  };

  if (query.isLoading) return <Loading />;
  if (query.error) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  const { languages, items } = query.data!;
  const todo = items.filter((item) => !item.done);
  const shown = showDone ? items : todo;

  return (
    <ScrollView contentContainerStyle={{ padding: space.xl, gap: space.md, maxWidth: 1100, width: '100%', alignSelf: 'center' }}>
      <Text variant="title">Titles</Text>
      <Text muted>
        Listeners see a story’s title in the app language they choose (Telugu or English) once it is confirmed here.
        Until then they see the title as recorded. AI suggestions are drafts from the local model: check the spelling
        and the meaning, then confirm.
      </Text>
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: space.sm, alignItems: 'center' }}>
        <Chip label="Published" selected={scope === 'published'} onPress={() => setScope('published')} />
        <Chip label="All stories" selected={scope === 'all'} onPress={() => setScope('all')} />
        <Chip label={`Show confirmed (${items.length - todo.length})`} selected={showDone} onPress={() => setShowDone(!showDone)} />
        <View style={{ flex: 1 }} />
        <Button kind="secondary" title="Suggest missing titles with AI" onPress={() => void suggest()} />
      </View>
      {message ? <Text variant="small">{message}</Text> : null}
      <Text variant="small" muted>{todo.length} of {items.length} need a confirmed title</Text>
      {shown.map((item) => <TitleRow key={item.id} item={item} languages={languages} onSaved={() => void query.refetch()} />)}
      {!shown.length ? <Text muted>All titles are confirmed.</Text> : null}
      <View style={{ height: space.xl }} />
      <Text variant="small" color={colors.muted}>Renaming a story clears its translated titles, and they are suggested again.</Text>
    </ScrollView>
  );
}

function TitleRow({ item, languages, onSaved }: { item: Item; languages: string[]; onSaved: () => void }) {
  const colors = useColors();
  const [values, setValues] = useState<Record<string, string>>(
    () => Object.fromEntries(languages.map((lang) => [lang, item.titles[lang]?.text ?? ''])));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const titles = Object.fromEntries(Object.entries(values).filter(([lang, text]) =>
        text.trim() && !(item.titles[lang]?.by === 'original' && item.titles[lang]?.text === text)));
      await api(`/api/studio/titles/${item.id}`, { method: 'POST', profile: false, body: { titles } });
      onSaved();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', alignItems: 'flex-end', gap: space.md }}>
        <View style={{ minWidth: 200, flex: 1, gap: 2 }}>
          <Text variant="heading" style={{ fontFamily: fontFor(item.title, 'bold') }}>{item.title}</Text>
          <Text variant="small" muted>{[item.album, item.status].filter(Boolean).join(' · ')}</Text>
        </View>
        {languages.map((lang) => {
          const entry = item.titles[lang];
          const hint = !entry ? (item.pending ? 'AI working…' : 'none yet') : entry.confirmed
            ? (entry.by === 'original' ? 'as recorded' : 'confirmed') : 'AI suggestion';
          return (
            <View key={lang} style={{ minWidth: 220, flex: 1 }}>
              <Field label={`${LABELS[lang] ?? lang} · ${hint}`} value={values[lang]} editable={entry?.by !== 'original'}
                onChangeText={(text) => setValues({ ...values, [lang]: text })} style={{ fontFamily: fontFor(values[lang]) }} />
            </View>
          );
        })}
        <Button title={item.done ? 'Save' : 'Confirm'} loading={busy} onPress={() => void save()}
          disabled={languages.some((lang) => !values[lang]?.trim())} />
      </View>
      {error ? <Text variant="small" color={colors.danger}>{error}</Text> : null}
    </Card>
  );
}
