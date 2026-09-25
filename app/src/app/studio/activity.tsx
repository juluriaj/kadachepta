import { useQuery } from '@tanstack/react-query';
import { router } from 'expo-router';
import { Pressable, ScrollView, View } from 'react-native';

import { ErrorState, Loading, Text, useColors } from '@/components/ui';
import { api } from '@/lib/api';
import { space } from '@/lib/theme';

type Event = { id: number; assetId: string | null; title: string | null; action: string; actor: string; notes: string | null;
  createdAt: string };

// The audit trail of editorial decisions and pipeline steps, newest first.
export default function Activity() {
  const colors = useColors();
  const query = useQuery({ queryKey: ['studio-activity'], refetchInterval: 30_000,
    queryFn: () => api<{ items: Event[] }>('/api/studio/activity?limit=200', { profile: false }) });
  if (query.isLoading) return <Loading />;
  if (query.error) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  return (
    <ScrollView contentContainerStyle={{ padding: space.xl, gap: space.xs, maxWidth: 1100, width: '100%', alignSelf: 'center' }}>
      <Text variant="title">Activity</Text>
      {query.data!.items.map((event) => (
        <View key={event.id} style={{ flexDirection: 'row', flexWrap: 'wrap', gap: space.sm, paddingVertical: 6,
          borderBottomWidth: 1, borderColor: colors.border }}>
          <Text variant="small" muted style={{ width: 150 }}>{new Date(event.createdAt).toLocaleString()}</Text>
          <Text variant="small" style={{ width: 120 }}>{event.actor}</Text>
          <Text variant="small" style={{ width: 200 }}>{event.action}</Text>
          {event.assetId ? (
            <Pressable onPress={() => router.push(`/studio/review/${event.assetId}`)}>
              <Text variant="small" color={colors.primary}>{event.title}</Text>
            </Pressable>
          ) : null}
          {event.notes ? <Text variant="small" muted style={{ flexBasis: '100%' }}>{event.notes}</Text> : null}
        </View>
      ))}
    </ScrollView>
  );
}
