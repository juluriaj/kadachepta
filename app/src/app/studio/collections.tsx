import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { Pressable, ScrollView, View } from 'react-native';

import { Button, Card, Chip, ErrorState, Field, Loading, Text, useColors } from '@/components/ui';
import { api } from '@/lib/api';
import { space } from '@/lib/theme';

type Collection = { id: number; kind: 'festival' | 'theme' | 'age'; titles: Record<string, string>;
  descriptions: Record<string, string>; startsOn: string | null; endsOn: string | null; position: number; published: boolean;
  stories: { id: string; title: string; status: string }[] };
type Draft = Omit<Collection, 'id' | 'stories'> & { id?: number; assetIds: string[] };

const EMPTY: Draft = { kind: 'theme', titles: {}, descriptions: {}, startsOn: null, endsOn: null, position: 0, published: false,
  assetIds: [] };

// Editorial shelves on Home (P3-08): festivals with dates, themes, and age collections.
export default function Collections() {
  const colors = useColors();
  const query = useQuery({ queryKey: ['studio-collections'],
    queryFn: () => api<{ items: Collection[]; stories: { id: string; title: string }[] }>('/api/studio/collections', { profile: false }) });
  const [editing, setEditing] = useState<Draft | null>(null);

  if (query.isLoading) return <Loading />;
  if (query.error || !query.data) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  const { items, stories } = query.data;
  return (
    <ScrollView contentContainerStyle={{ padding: space.xl, gap: space.md, maxWidth: 1100, width: '100%', alignSelf: 'center' }}>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: space.md }}>
        <Text variant="title" style={{ flex: 1 }}>Collections</Text>
        <Button title="New collection" onPress={() => setEditing({ ...EMPTY, position: items.length })} />
      </View>
      <Text muted>
        Published collections appear on Home as shelves, in this order, between the listener’s own shelves and the listening
        moments. A festival collection shows only between its dates. Children see only the stories suitable for their age.
      </Text>
      {editing ? (
        <Editor draft={editing} stories={stories} onDone={() => { setEditing(null); void query.refetch(); }}
          onCancel={() => setEditing(null)} />
      ) : null}
      {items.map((collection) => (
        <Card key={collection.id}>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: space.md, flexWrap: 'wrap' }}>
            <View style={{ flex: 1, minWidth: 240 }}>
              <Text variant="heading">{collection.titles['en-IN'] ?? ''} {collection.titles['te-IN'] ? `· ${collection.titles['te-IN']}` : ''}</Text>
              <Text variant="small" muted>
                {[collection.kind, collection.published ? 'published' : 'draft',
                  collection.startsOn || collection.endsOn ? `${collection.startsOn ?? '…'} to ${collection.endsOn ?? '…'}` : null,
                  `${collection.stories.length} stories`].filter(Boolean).join(' · ')}
              </Text>
            </View>
            <Button kind="secondary" title="Edit" onPress={() => setEditing({ ...collection, assetIds: collection.stories.map((s) => s.id) })} />
            <Button kind="ghost" title="Delete" onPress={() => void api(`/api/studio/collections/${collection.id}`,
              { method: 'DELETE', profile: false }).then(() => query.refetch())} />
          </View>
          <Text variant="small" color={colors.muted}>{collection.stories.map((s) => s.title).join(' · ')}</Text>
        </Card>
      ))}
      {!items.length && !editing ? <Text muted>No collections yet.</Text> : null}
    </ScrollView>
  );
}

function Editor({ draft, stories, onDone, onCancel }: { draft: Draft; stories: { id: string; title: string }[]; onDone: () => void;
  onCancel: () => void }) {
  const colors = useColors();
  const [value, setValue] = useState<Draft>(draft);
  const [filter, setFilter] = useState('');
  const [error, setError] = useState<string | null>(null);
  const set = (patch: Partial<Draft>) => setValue({ ...value, ...patch });
  const chosen = new Set(value.assetIds);
  const byId = Object.fromEntries(stories.map((s) => [s.id, s.title]));
  const matches = stories.filter((s) => !chosen.has(s.id) && s.title.toLowerCase().includes(filter.toLowerCase())).slice(0, 12);

  const save = async () => {
    setError(null);
    try {
      const body = { ...value, startsOn: value.startsOn || null, endsOn: value.endsOn || null };
      await api(value.id ? `/api/studio/collections/${value.id}` : '/api/studio/collections', { method: 'POST', profile: false, body });
      onDone();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    }
  };
  const move = (index: number, offset: number) => {
    const ids = [...value.assetIds];
    const [item] = ids.splice(index, 1);
    ids.splice(Math.max(0, Math.min(ids.length, index + offset)), 0, item);
    set({ assetIds: ids });
  };

  return (
    <Card style={{ borderColor: colors.primary }}>
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: space.sm }}>
        {(['festival', 'theme', 'age'] as const).map((kind) => (
          <Chip key={kind} label={kind} selected={value.kind === kind} onPress={() => set({ kind })} />
        ))}
        <Chip label={value.published ? 'Published' : 'Draft'} selected={value.published} onPress={() => set({ published: !value.published })} />
      </View>
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: space.md }}>
        <View style={{ flex: 1, minWidth: 240 }}>
          <Field label="Title (English)" value={value.titles['en-IN'] ?? ''} onChangeText={(text) => set({ titles: { ...value.titles, 'en-IN': text } })} />
        </View>
        <View style={{ flex: 1, minWidth: 240 }}>
          <Field label="Title (Telugu)" value={value.titles['te-IN'] ?? ''} onChangeText={(text) => set({ titles: { ...value.titles, 'te-IN': text } })} />
        </View>
      </View>
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: space.md }}>
        <View style={{ flex: 1, minWidth: 160 }}>
          <Field label="Shows from (YYYY-MM-DD, optional)" value={value.startsOn ?? ''} onChangeText={(text) => set({ startsOn: text })} />
        </View>
        <View style={{ flex: 1, minWidth: 160 }}>
          <Field label="Until (optional)" value={value.endsOn ?? ''} onChangeText={(text) => set({ endsOn: text })} />
        </View>
        <View style={{ width: 120 }}>
          <Field label="Order" value={String(value.position)} keyboardType="number-pad"
            onChangeText={(text) => set({ position: Number(text.replace(/\D/g, '')) || 0 })} />
        </View>
      </View>
      <Text variant="label" muted>Stories ({value.assetIds.length})</Text>
      {value.assetIds.map((id, index) => (
        <View key={id} style={{ flexDirection: 'row', alignItems: 'center', gap: space.sm }}>
          <Text style={{ flex: 1 }}>{index + 1}. {byId[id] ?? id}</Text>
          <Pressable onPress={() => move(index, -1)} accessibilityRole="button" hitSlop={6}><Text color={colors.primary}>↑</Text></Pressable>
          <Pressable onPress={() => move(index, 1)} accessibilityRole="button" hitSlop={6}><Text color={colors.primary}>↓</Text></Pressable>
          <Pressable onPress={() => set({ assetIds: value.assetIds.filter((a) => a !== id) })} accessibilityRole="button" hitSlop={6}>
            <Text color={colors.danger}>Remove</Text>
          </Pressable>
        </View>
      ))}
      <Field label="Add stories (type part of a title)" value={filter} onChangeText={setFilter} />
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: space.xs }}>
        {matches.map((story) => (
          <Chip key={story.id} label={`+ ${story.title}`} onPress={() => set({ assetIds: [...value.assetIds, story.id] })} />
        ))}
      </View>
      {error ? <Text color={colors.danger}>{error}</Text> : null}
      <View style={{ flexDirection: 'row', gap: space.sm }}>
        <Button title="Save" onPress={() => void save()} />
        <Button kind="ghost" title="Cancel" onPress={onCancel} />
      </View>
    </Card>
  );
}
