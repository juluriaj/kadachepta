import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { ScrollView, View } from 'react-native';

import { Button, Card, Chip, ErrorState, Loading, Text, useColors } from '@/components/ui';
import { api } from '@/lib/api';
import { space } from '@/lib/theme';

type Sender = { userId: number; name: string; username: string | null; role: string; email: string | null;
  phone: string | null; contactChannel: string | null };
type Item = { id: number; message: string; page: string | null; platform: string | null; status: 'new' | 'done';
  createdAt: string; resolvedAt: string | null; from: Sender | null };
type Status = 'new' | 'done' | 'all';

// What listeners, parents and narrators sent with "Send feedback". Email is off, so reply by phone or WhatsApp.
export default function FeedbackInbox() {
  const colors = useColors();
  const [status, setStatus] = useState<Status>('new');
  const [error, setError] = useState<string | null>(null);
  const query = useQuery({ queryKey: ['studio-feedback', status],
    queryFn: () => api<{ items: Item[]; counts: { new: number; done: number } }>(`/api/studio/feedback?status=${status}`,
      { profile: false }) });

  const mark = async (item: Item, done: boolean) => {
    setError(null);
    try {
      await api(`/api/studio/feedback/${item.id}`, { method: 'POST', profile: false, body: { done } });
      await query.refetch();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    }
  };

  if (query.isLoading) return <Loading />;
  if (query.error || !query.data) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  const { items, counts } = query.data;
  return (
    <ScrollView contentContainerStyle={{ padding: space.xl, gap: space.md, maxWidth: 1100, width: '100%', alignSelf: 'center' }}>
      <Text variant="title">Feedback</Text>
      <Text muted>
        Messages people sent from the app (Family › Send feedback, or the Narrate tab). Reply the way they asked to be
        contacted, then mark the message done.
      </Text>
      <View style={{ flexDirection: 'row', gap: space.sm, flexWrap: 'wrap' }}>
        <Chip role="radio" label={`New (${counts.new})`} selected={status === 'new'} onPress={() => setStatus('new')} />
        <Chip role="radio" label={`Done (${counts.done})`} selected={status === 'done'} onPress={() => setStatus('done')} />
        <Chip role="radio" label="All" selected={status === 'all'} onPress={() => setStatus('all')} />
      </View>
      {error ? <Text color={colors.danger}>{error}</Text> : null}
      {!items.length ? <Text variant="small" muted>{status === 'new' ? 'Nothing new.' : 'Nothing here yet.'}</Text> : null}
      {items.map((item) => (
        <Card key={item.id}>
          <View style={{ flexDirection: 'row', gap: space.md, flexWrap: 'wrap', alignItems: 'flex-start' }}>
            <View style={{ flex: 1, minWidth: 260, gap: space.xs }}>
              <Text selectable>{item.message}</Text>
              <Text variant="small" muted>
                {new Date(item.createdAt).toLocaleString()}
                {item.page ? ` · from ${item.page}` : ''}{item.platform ? ` · ${item.platform}` : ''}
              </Text>
              {item.from ? (
                <Text variant="small" selectable>
                  {item.from.name}{item.from.username ? ` (@${item.from.username})` : ''} · {item.from.role}
                  {item.from.phone ? ` · ${item.from.phone}` : ''}{item.from.email ? ` · ${item.from.email}` : ''}
                  {item.from.contactChannel ? ` · prefers ${item.from.contactChannel}` : ''}
                </Text>
              ) : <Text variant="small" muted>Account deleted</Text>}
            </View>
            {item.status === 'new'
              ? <Button kind="secondary" title="Mark done" onPress={() => void mark(item, true)} />
              : <Button kind="ghost" title="Reopen" onPress={() => void mark(item, false)} />}
          </View>
        </Card>
      ))}
    </ScrollView>
  );
}
