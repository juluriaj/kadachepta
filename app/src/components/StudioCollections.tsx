import Ionicons from '@expo/vector-icons/Ionicons';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useMemo, useState } from 'react';
import { TextInput, View } from 'react-native';

import { Button, Card, Chip, Text, useColors } from '@/components/ui';
import { api } from '@/lib/api';
import type { StudioCollection } from '@/lib/studio';
import { radius, space } from '@/lib/theme';

// Editors put stories on Home shelves from wherever they are: the Published list, or a story's own page.
// Every place shares one cached list, so the Collections screen shows the change too.
export function useStudioCollections() {
  return useQuery({ queryKey: ['studio-collections'],
    queryFn: () => api<{ items: StudioCollection[]; stories: { id: string; title: string }[] }>('/api/studio/collections',
      { profile: false }) });
}

function label(collection: StudioCollection) {
  const title = [collection.titles['en-IN'], collection.titles['te-IN']].filter(Boolean).join(' · ');
  return collection.published ? title : `${title} (draft)`;
}

// The collections each story is in, by their short name, to show beside it in lists.
export function useCollectionsByStory() {
  const collections = useStudioCollections();
  return useMemo(() => {
    const names = new Map<string, string[]>();
    for (const collection of collections.data?.items ?? []) {
      const name = collection.titles['en-IN'] || collection.titles['te-IN'] || `#${collection.id}`;
      for (const story of collection.stories) names.set(story.id, [...(names.get(story.id) ?? []), name]);
    }
    return names;
  }, [collections.data]);
}

function errorText(failure: unknown) {
  return failure instanceof Error ? failure.message : String(failure);
}

// A new collection starts as a draft: it reaches Home once an editor publishes it on the Collections screen.
function NewCollection({ assetIds, onCreated }: { assetIds: string[]; onCreated: (title: string) => void }) {
  const colors = useColors();
  const [title, setTitle] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const create = async () => {
    setBusy(true);
    setError(null);
    try {
      await api('/api/studio/collections', { method: 'POST', profile: false,
        body: { titles: { 'en-IN': title.trim() }, assetIds, published: false } });
      onCreated(title.trim());
      setTitle('');
    } catch (failure) {
      setError(errorText(failure));
    } finally {
      setBusy(false);
    }
  };
  return (
    <View style={{ gap: space.xs }}>
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: space.sm, alignItems: 'center' }}>
        <TextInput value={title} onChangeText={setTitle} placeholder="New collection title (English)"
          accessibilityLabel="New collection title" placeholderTextColor={colors.muted}
          onSubmitEditing={() => { if (title.trim() && assetIds.length) void create(); }}
          style={{ flexGrow: 1, minWidth: 200, minHeight: 40, borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
            paddingHorizontal: space.md, color: colors.text, backgroundColor: colors.surface }} />
        <Button kind="secondary" title="Create draft" disabled={!title.trim() || !assetIds.length} loading={busy}
          onPress={() => void create()} />
      </View>
      {error ? <Text variant="small" color={colors.danger}>{error}</Text> : null}
    </View>
  );
}

// The Published list: put the selected stories in a collection. Each collection shows how many of them it already
// has (a tick when all of them); tapping adds the missing ones, and tapping a ticked one takes them all out again.
export function AddToCollection({ assetIds }: { assetIds: string[] }) {
  const colors = useColors();
  const queryClient = useQueryClient();
  const collections = useStudioCollections();
  const [busy, setBusy] = useState<number | null>(null);
  // Kept with the selection it was about, so a new selection doesn't show an old result.
  const [result, setResult] = useState<{ selection: string; text: string; failed?: boolean } | null>(null);
  const selection = [...assetIds].sort().join(',');
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['studio-collections'] });
  const stories = (count: number) => `${count} ${count === 1 ? 'story' : 'stories'}`;

  const toggle = async (collection: StudioCollection, all: boolean) => {
    setBusy(collection.id);
    setResult(null);
    try {
      if (all) {
        const done = await api<{ removed: number }>(`/api/studio/collections/${collection.id}/stories/remove`,
          { method: 'POST', profile: false, body: { assetIds } });
        await refresh();
        setResult({ selection, text: `Took ${stories(done.removed)} out of ${label(collection)}.` });
      } else {
        const done = await api<{ added: number; already: number }>(`/api/studio/collections/${collection.id}/stories`,
          { method: 'POST', profile: false, body: { assetIds } });
        await refresh();
        setResult({ selection, text: `Added ${stories(done.added)} to ${label(collection)}.`
          + (done.already ? ` ${done.already} ${done.already === 1 ? 'was' : 'were'} already there.` : '') });
      }
    } catch (failure) {
      setResult({ selection, text: errorText(failure), failed: true });
    } finally {
      setBusy(null);
    }
  };

  if (!assetIds.length) return <Text variant="small" muted>Select stories, then choose a collection to add them to.</Text>;
  const chosen = new Set(assetIds);
  return (
    <View style={{ gap: space.sm }}>
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: space.sm, alignItems: 'center' }}>
        <Text variant="small" muted>Collections for the {stories(assetIds.length)} selected:</Text>
        {collections.isLoading ? <Text variant="small" muted>…</Text> : null}
        {collections.data?.items.map((collection) => {
          const inside = collection.stories.filter((story) => chosen.has(story.id)).length;
          const all = inside === assetIds.length;
          const name = label(collection) + (inside && !all ? ` · ${inside} of ${assetIds.length}` : '');
          return (
            <Chip key={collection.id} label={busy === collection.id ? `${name} …` : name} selected={all}
              icon={<Ionicons name={all ? 'checkmark' : inside ? 'remove' : 'add'} size={16}
                color={all ? colors.onPrimary : colors.text} />}
              onPress={() => { if (busy == null) void toggle(collection, all); }} />
          );
        })}
      </View>
      {result?.selection === selection ? (
        <Text variant="small" color={result.failed ? colors.danger : colors.success}>{result.text}</Text>
      ) : null}
      <NewCollection assetIds={assetIds}
        onCreated={(title) => { void refresh(); setResult({ selection, text: `Made the draft collection ${title} with `
          + `${stories(assetIds.length)}. Publish it on the Collections screen.` }); }} />
    </View>
  );
}

// A story's page: which collections it is in. Tap to add it, tap again to take it out.
export function StoryCollections({ assetId, published }: { assetId: string; published: boolean }) {
  const colors = useColors();
  const queryClient = useQueryClient();
  const collections = useStudioCollections();
  const [busy, setBusy] = useState<number | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['studio-collections'] });

  const toggle = async (collection: StudioCollection, inside: boolean) => {
    setBusy(collection.id);
    setMessage(null);
    try {
      if (inside) {
        await api(`/api/studio/collections/${collection.id}/stories/${assetId}`, { method: 'DELETE', profile: false });
      } else {
        await api(`/api/studio/collections/${collection.id}/stories`, { method: 'POST', profile: false, body: { assetIds: [assetId] } });
      }
      await refresh();
    } catch (failure) {
      setMessage(errorText(failure));
    } finally {
      setBusy(null);
    }
  };

  const items = collections.data?.items ?? [];
  return (
    <Card>
      <Text variant="heading">Collections</Text>
      <Text variant="small" muted>
        {published ? 'Tap a collection to add this story to it; tap again to take it out.'
          : 'Listeners see it in a collection once the story is published.'}
      </Text>
      {collections.error ? <Text variant="small" color={colors.danger}>{errorText(collections.error)}</Text> : null}
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: space.sm }}>
        {items.map((collection) => {
          const inside = collection.stories.some((story) => story.id === assetId);
          return (
            <Chip key={collection.id} label={busy === collection.id ? `${label(collection)} …` : label(collection)} selected={inside}
              icon={<Ionicons name={inside ? 'checkmark' : 'add'} size={16} color={inside ? colors.onPrimary : colors.text} />}
              onPress={() => { if (busy == null) void toggle(collection, inside); }} />
          );
        })}
      </View>
      {!collections.isLoading && !items.length ? <Text variant="small" muted>No collections yet.</Text> : null}
      <NewCollection assetIds={[assetId]}
        onCreated={(title) => { void refresh(); setMessage(`Made the draft collection ${title} with this story. Publish it on the Collections screen.`); }} />
      {message ? <Text variant="small">{message}</Text> : null}
    </Card>
  );
}
