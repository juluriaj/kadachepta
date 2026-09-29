import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { ScrollView, View } from 'react-native';

import { Button, Card, ErrorState, Field, Loading, Text, useColors } from '@/components/ui';
import { api } from '@/lib/api';
import { fontFor, space } from '@/lib/theme';

type Prompts = { texts?: Record<string, string[]>; status?: 'draft' | 'approved'; by?: string };
type Item = { id: string; title: string; titles: Record<string, string>; prompts: Prompts; pending: boolean };

const LABELS: Record<string, string> = { 'te-IN': 'Telugu', 'en-IN': 'English' };

// Conversation starters (P3-07): drafted by the local model, shown to parents only after an editor approves them.
// The refresh also computes recommendations for published stories.
export default function PromptsPage() {
  const colors = useColors();
  const [message, setMessage] = useState<string | null>(null);
  const [showApproved, setShowApproved] = useState(false);
  const query = useQuery({
    queryKey: ['studio-prompts'],
    queryFn: () => api<{ languages: string[]; items: Item[] }>('/api/studio/prompts', { profile: false }),
    refetchInterval: (q) => (q.state.data?.items.some((item) => item.pending) ? 10_000 : false),
  });

  const refresh = async () => {
    setMessage(null);
    try {
      const result = await api<{ queued: Record<string, number>; embedded: number }>('/api/studio/community/refresh',
        { method: 'POST', profile: false });
      const parts = Object.entries(result.queued).map(([job, n]) => `${n} ${job === 'embed' ? 'recommendation' : 'conversation-starter'} jobs`);
      setMessage(parts.length ? `Queued ${parts.join(' and ')} for the AI worker. ${result.embedded} stories already have recommendations.`
        : `Nothing to do: ${result.embedded} stories have recommendations, and every story has conversation starters or had a try.`);
      await query.refetch();
    } catch (failure) {
      setMessage(failure instanceof Error ? failure.message : String(failure));
    }
  };

  if (query.isLoading) return <Loading />;
  if (query.error || !query.data) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  const { languages, items } = query.data;
  const waiting = items.filter((item) => item.prompts.status !== 'approved');
  const shown = showApproved ? items : waiting;
  return (
    <ScrollView contentContainerStyle={{ padding: space.xl, gap: space.md, maxWidth: 1100, width: '100%', alignSelf: 'center' }}>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: space.md, flexWrap: 'wrap' }}>
        <Text variant="title" style={{ flex: 1 }}>Conversation starters</Text>
        <Button kind="secondary" title="Prepare recommendations and starters" onPress={() => void refresh()} />
      </View>
      <Text muted>
        Two or three questions parents can ask after a story. The local model drafts them; they reach parents only after you
        approve them here or on the review screen. Leave every box empty and save to remove them.
      </Text>
      {message ? <Text variant="small">{message}</Text> : null}
      <Button kind="ghost" title={showApproved ? `Hide approved (${items.length - waiting.length})`
        : `Show approved (${items.length - waiting.length})`} onPress={() => setShowApproved(!showApproved)} />
      {shown.map((item) => <PromptEditor key={item.id} item={item} languages={languages} onSaved={() => void query.refetch()} />)}
      {!shown.length ? <Text muted>Every published story’s conversation starters are approved.</Text> : null}
      <Text variant="small" color={colors.muted}>{waiting.length} stories waiting</Text>
    </ScrollView>
  );
}

function PromptEditor({ item, languages, onSaved }: { item: Item; languages: string[]; onSaved: () => void }) {
  const colors = useColors();
  const [texts, setTexts] = useState<Record<string, string>>(() =>
    Object.fromEntries(languages.map((lang) => [lang, (item.prompts.texts?.[lang] ?? []).join('\n')])));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const body = { texts: Object.fromEntries(Object.entries(texts).map(([lang, value]) => [lang, value.split('\n')])) };
      await api(`/api/studio/prompts/${item.id}`, { method: 'POST', profile: false, body });
      onSaved();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setBusy(false);
    }
  };
  const status = item.pending ? 'AI working…' : item.prompts.status === 'approved' ? 'approved'
    : item.prompts.texts ? 'AI draft: check it' : 'none yet';
  return (
    <Card>
      <Text variant="heading" style={{ fontFamily: fontFor(item.title, 'bold') }}>
        {item.title}{item.titles['en-IN'] && item.titles['en-IN'] !== item.title ? ` · ${item.titles['en-IN']}` : ''}
      </Text>
      <Text variant="small" color={item.prompts.status === 'approved' ? colors.success : colors.accent}>{status}</Text>
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: space.md }}>
        {languages.map((lang) => (
          <View key={lang} style={{ flex: 1, minWidth: 280 }}>
            <Field label={`${LABELS[lang] ?? lang} (one question per line)`} value={texts[lang]} multiline
              onChangeText={(value) => setTexts({ ...texts, [lang]: value })}
              style={{ minHeight: 90, paddingTop: 12, fontFamily: fontFor(texts[lang]) }} />
          </View>
        ))}
      </View>
      {error ? <Text variant="small" color={colors.danger}>{error}</Text> : null}
      <Button title={item.prompts.status === 'approved' ? 'Save' : 'Approve'} loading={busy} onPress={() => void save()} />
    </Card>
  );
}
