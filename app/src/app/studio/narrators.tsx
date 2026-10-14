import { useQuery } from '@tanstack/react-query';
import { router } from 'expo-router';
import { useState } from 'react';
import { Linking, Pressable, ScrollView, View } from 'react-native';

import { Button, Card, ErrorState, Loading, Text, useColors } from '@/components/ui';
import { api, mediaUrl } from '@/lib/api';
import { LANGUAGE_LABELS } from '@/lib/i18n';
import { space } from '@/lib/theme';

type Narrator = { userId: number; name: string; email: string | null; phone: string | null; contactChannel: string;
  contactNotes: string; languages: string[]; trustLevel: 'new' | 'trusted';
  onboardedAt: string | null; sampleUrl: string | null; published: number; rejected: number; inReview: number;
  suggestTrust: boolean; narration: Narration };
type Narration = { score: number | null; count: number; weight: number } | null;
// Narrators the catalog credits by name only: no account, so no contact details or trust level.
type CatalogNarrator = { name: string; languages: string[]; published: number; notPublished: number; rejected: number;
  narration: Narration; stories: { id: string; title: string; status: string }[] };

const rating = (narration: Narration) => narration?.score != null
  ? `${narration.score.toFixed(2)} from ${narration.count} ratings` : `not enough ratings yet (${narration?.count ?? 0})`;

export default function Narrators() {
  const colors = useColors();
  const query = useQuery({ queryKey: ['studio-narrators'],
    queryFn: () => api<{ items: Narrator[]; catalog: CatalogNarrator[] }>('/api/studio/narrators', { profile: false }) });
  const [error, setError] = useState<string | null>(null);

  const setTrust = async (narrator: Narrator, trustLevel: 'new' | 'trusted') => {
    setError(null);
    try {
      await api(`/api/studio/narrators/${narrator.userId}/trust`, { method: 'POST', profile: false, body: { trustLevel } });
      await query.refetch();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    }
  };

  if (query.isLoading) return <Loading />;
  if (query.error) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  return (
    <ScrollView contentContainerStyle={{ padding: space.xl, gap: space.md, maxWidth: 1100, width: '100%', alignSelf: 'center' }}>
      <Text variant="title">Narrators</Text>
      <Text muted>Trusted narrators skip the queue and can be published in bulk when every automatic check passes.</Text>
      {error ? <Text color={colors.danger}>{error}</Text> : null}
      {query.data!.items.map((narrator) => (
        <Card key={narrator.userId}>
          <View style={{ flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: space.md }}>
            <View style={{ flex: 1, minWidth: 220 }}>
              <Text variant="heading">{narrator.name}</Text>
              <Text variant="small" muted>{[narrator.email, narrator.phone, narrator.languages.join(', ')].filter(Boolean).join(' · ')}</Text>
              <Text variant="small">Prefers {narrator.contactChannel}{narrator.contactNotes ? ` · ${narrator.contactNotes}` : ''}</Text>
              <Text variant="small">
                {narrator.published} published · {narrator.inReview} in progress · {narrator.rejected} rejected
              </Text>
              <Text variant="small">Narration rating: {rating(narrator.narration)}</Text>
              {narrator.suggestTrust ? <Text variant="small" color={colors.success}>Clean track record: consider trusting.</Text> : null}
            </View>
            {narrator.sampleUrl ? (
              <Pressable onPress={() => void Linking.openURL(mediaUrl(narrator.sampleUrl)!)}>
                <Text variant="small" color={colors.primary}>Sample</Text>
              </Pressable>
            ) : null}
            <Text variant="heading" color={narrator.trustLevel === 'trusted' ? colors.success : colors.muted}>{narrator.trustLevel}</Text>
            <Button kind="secondary" title={narrator.trustLevel === 'trusted' ? 'Remove trust' : 'Trust'}
              onPress={() => void setTrust(narrator, narrator.trustLevel === 'trusted' ? 'new' : 'trusted')} />
          </View>
        </Card>
      ))}
      {query.data!.catalog.length ? (
        <>
          <Text variant="heading" style={{ marginTop: space.lg }}>In the catalog ({query.data!.catalog.length})</Text>
          <Text muted>
            Credited by name on catalog stories, without an account yet, so there are no contact details or trust level.
            Co-narrated stories count for each person.
          </Text>
          {query.data!.catalog.map((narrator) => <CatalogCard key={narrator.name} narrator={narrator} />)}
        </>
      ) : null}
    </ScrollView>
  );
}

function CatalogCard({ narrator }: { narrator: CatalogNarrator }) {
  const colors = useColors();
  const [open, setOpen] = useState(false);
  return (
    <Card>
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: space.md }}>
        <View style={{ flex: 1, minWidth: 220 }}>
          <Text variant="heading">{narrator.name}</Text>
          <Text variant="small" muted>{narrator.languages.map((code) => LANGUAGE_LABELS[code] ?? code).join(', ')}</Text>
          <Text variant="small">
            {[`${narrator.published} published`, `${narrator.notPublished} not yet published`,
              narrator.rejected ? `${narrator.rejected} rejected` : null].filter(Boolean).join(' · ')}
          </Text>
          {narrator.published ? <Text variant="small">Narration rating: {rating(narrator.narration)}</Text> : null}
        </View>
        <Button kind="secondary" title={open ? 'Hide stories' : `Stories (${narrator.stories.length})`} onPress={() => setOpen(!open)} />
      </View>
      {open ? (
        <View style={{ gap: 2 }}>
          {narrator.stories.map((story) => (
            <Pressable key={story.id} accessibilityRole="link" onPress={() => router.push(`/studio/review/${story.id}`)}
              style={{ flexDirection: 'row', gap: space.sm, paddingVertical: 4 }}>
              <Text variant="small" color={colors.primary} style={{ flex: 1 }} numberOfLines={1}>{story.title}</Text>
              <Text variant="small" color={story.status === 'published' ? colors.success : colors.muted}>{story.status}</Text>
            </Pressable>
          ))}
        </View>
      ) : null}
    </Card>
  );
}
