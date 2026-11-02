import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { View } from 'react-native';

import { Button, Card, Field, Text, useColors } from '@/components/ui';
import { api, ApiError } from '@/lib/api';
import type { ThreadMessage } from '@/lib/types';
import { space } from '@/lib/theme';

type Labels = { title: string; hint: string; empty: string; field: string; send: string };

// The conversation on a submission between editors and its narrator (P3-11): the narrator's submission page and
// the studio review page show the same thread. Opening it marks the other side's messages read.
export function Thread({ path, labels }: { path: string; labels: Labels }) {
  const colors = useColors();
  const queryClient = useQueryClient();
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const query = useQuery({ queryKey: ['thread', path], queryFn: () => api<{ items: ThreadMessage[] }>(path, { profile: false }) });

  const send = async () => {
    setBusy(true);
    setError(null);
    try {
      const result = await api<{ items: ThreadMessage[] }>(path, { method: 'POST', profile: false, body: { text: text.trim() } });
      queryClient.setQueryData(['thread', path], result);
      setText('');
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : String(failure));
    } finally {
      setBusy(false);
    }
  };

  const items = query.data?.items ?? [];
  return (
    <Card style={{ gap: space.md }}>
      <Text variant="heading">{labels.title}</Text>
      <Text variant="small" muted>{labels.hint}</Text>
      {!items.length && !query.isLoading ? <Text variant="small" muted>{labels.empty}</Text> : null}
      {items.map((message) => (
        <View key={message.id} style={{ alignSelf: message.mine ? 'flex-end' : 'flex-start', maxWidth: '88%', gap: 2,
          padding: space.md, borderRadius: 12, backgroundColor: message.mine ? colors.surfaceAlt : colors.background,
          borderWidth: 1, borderColor: colors.border }}>
          <Text variant="small" muted>{message.author} · {new Date(message.createdAt).toLocaleString()}</Text>
          <Text selectable>{message.text}</Text>
        </View>
      ))}
      <Field label={labels.field} value={text} onChangeText={setText} multiline maxLength={4000}
        style={{ minHeight: 80, paddingTop: space.md, textAlignVertical: 'top' }} />
      {error ? <Text variant="small" color={colors.danger}>{error}</Text> : null}
      <Button title={labels.send} kind="secondary" loading={busy} disabled={!text.trim()} onPress={() => void send()} />
    </Card>
  );
}
