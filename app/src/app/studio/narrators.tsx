import { useQuery } from '@tanstack/react-query';
import * as DocumentPicker from 'expo-document-picker';
import { router } from 'expo-router';
import { useState } from 'react';
import { Linking, Pressable, ScrollView, View } from 'react-native';

import { Button, Card, Cover, ErrorState, Field, Loading, Text, useColors } from '@/components/ui';
import { api, apiSendFile, mediaUrl } from '@/lib/api';
import { LANGUAGE_LABELS } from '@/lib/i18n';
import { space } from '@/lib/theme';

type Narrator = { userId: number; name: string; email: string | null; phone: string | null; contactChannel: string;
  contactNotes: string; languages: string[]; trustLevel: 'new' | 'trusted';
  onboardedAt: string | null; sampleUrl: string | null; published: number; rejected: number; inReview: number;
  suggestTrust: boolean; narration: Narration; biography: string | null; photoUrl: string | null;
  pendingPhotoUrl: string | null; acceptsNotes: boolean };
type Narration = { score: number | null; count: number; weight: number } | null;
// Narrators the catalog credits by name only: no account, so no contact details or trust level.
type CatalogNarrator = { name: string; languages: string[]; published: number; notPublished: number; rejected: number;
  narration: Narration; stories: { id: string; title: string; status: string }[]; key: string; biography: string | null;
  photoUrl: string | null };

// Pick an image and send it as the request body (the same way as book covers).
async function pickAndSend(path: string) {
  const result = await DocumentPicker.getDocumentAsync({ type: ['image/jpeg', 'image/png', 'image/webp'], multiple: false });
  if (result.canceled || !result.assets?.length) return false;
  const picked = result.assets[0];
  const file = (picked as { file?: Blob }).file ?? await (await fetch(picked.uri)).blob();
  await apiSendFile(path, file, picked.mimeType ?? file.type ?? 'image/jpeg');
  return true;
}

const rating = (narration: Narration) => narration?.score != null
  ? `${narration.score.toFixed(2)} from ${narration.count} ratings` : `not enough ratings yet (${narration?.count ?? 0})`;

export default function Narrators() {
  const colors = useColors();
  const query = useQuery({ queryKey: ['studio-narrators'],
    queryFn: () => api<{ items: Narrator[]; catalog: CatalogNarrator[] }>('/api/studio/narrators', { profile: false }) });
  const [error, setError] = useState<string | null>(null);

  const run = async (work: () => Promise<unknown>) => {
    setError(null);
    try {
      await work();
      await query.refetch();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    }
  };
  const setTrust = (narrator: Narrator, trustLevel: 'new' | 'trusted') => run(() =>
    api(`/api/studio/narrators/${narrator.userId}/trust`, { method: 'POST', profile: false, body: { trustLevel } }));
  const decidePhoto = (narrator: Narrator, approve: boolean) => run(() =>
    api(`/api/studio/narrators/${narrator.userId}/photo`, { method: 'POST', profile: false, body: { approve } }));
  const waiting = query.data?.items.filter((narrator) => narrator.pendingPhotoUrl) ?? [];

  if (query.isLoading) return <Loading />;
  if (query.error) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  return (
    <ScrollView contentContainerStyle={{ padding: space.xl, gap: space.md, maxWidth: 1100, width: '100%', alignSelf: 'center' }}>
      <Text variant="title">Narrators</Text>
      <Text muted>Trusted narrators skip the queue and can be published in bulk when every automatic check passes.</Text>
      {error ? <Text color={colors.danger}>{error}</Text> : null}
      {waiting.length ? (
        <Card style={{ gap: space.md, borderColor: colors.accent }}>
          <Text variant="heading">Photos waiting for approval ({waiting.length})</Text>
          <Text variant="small" muted>A clear photo of the narrator: no children, no text or logos. Families see it once you approve.</Text>
          {waiting.map((narrator) => (
            <View key={narrator.userId} style={{ flexDirection: 'row', alignItems: 'center', gap: space.md, flexWrap: 'wrap' }}>
              <Cover id={`photo-${narrator.userId}`} title={narrator.name} artworkUrl={narrator.pendingPhotoUrl} size={72} rounded={36} />
              <Text variant="heading" style={{ flex: 1, minWidth: 140 }}>{narrator.name}</Text>
              <Button title="Approve" onPress={() => void decidePhoto(narrator, true)} />
              <Button kind="ghost" title="Decline" onPress={() => void decidePhoto(narrator, false)} />
            </View>
          ))}
        </Card>
      ) : null}
      {query.data!.items.map((narrator) => (
        <Card key={narrator.userId}>
          <View style={{ flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: space.md }}>
            <Cover id={`narrator-${narrator.userId}`} title={narrator.name} artworkUrl={narrator.photoUrl} size={56} rounded={28} />
            <View style={{ flex: 1, minWidth: 220 }}>
              <Text variant="heading">{narrator.name}</Text>
              <Text variant="small" muted>{[narrator.email, narrator.phone, narrator.languages.join(', ')].filter(Boolean).join(' · ')}</Text>
              <Text variant="small">Prefers {narrator.contactChannel}{narrator.contactNotes ? ` · ${narrator.contactNotes}` : ''}</Text>
              <Text variant="small">
                {narrator.published} published · {narrator.inReview} in progress · {narrator.rejected} rejected
              </Text>
              <Text variant="small">Narration rating: {rating(narrator.narration)}</Text>
              {narrator.suggestTrust ? <Text variant="small" color={colors.success}>Clean track record: consider trusting.</Text> : null}
              <Text variant="small" muted>{narrator.acceptsNotes ? 'Takes thank-you notes from families' : 'Not taking notes'}</Text>
            </View>
            <Button kind="ghost" title="Set photo" onPress={() => void run(() => pickAndSend(`/api/studio/narrators/${narrator.userId}/photo`))} />
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
          {query.data!.catalog.map((narrator) => <CatalogCard key={narrator.name} narrator={narrator}
            onChanged={() => void query.refetch()} />)}
        </>
      ) : null}
    </ScrollView>
  );
}

// Narrators without an account can't write their own bio or upload a photo, so editors do it for them (P3-10).
function CatalogCard({ narrator, onChanged }: { narrator: CatalogNarrator; onChanged: () => void }) {
  const colors = useColors();
  const [open, setOpen] = useState(false);
  const [bio, setBio] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const act = async (work: () => Promise<unknown>, done: string) => {
    setMessage(null);
    try {
      await work();
      setMessage(done);
      onChanged();
    } catch (failure) {
      setMessage(failure instanceof Error ? failure.message : String(failure));
    }
  };
  return (
    <Card>
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: space.md }}>
        <Cover id={`narrator-${narrator.name}`} title={narrator.name} artworkUrl={narrator.photoUrl} size={56} rounded={28} />
        <View style={{ flex: 1, minWidth: 220 }}>
          <Text variant="heading">{narrator.name}</Text>
          <Text variant="small" muted>{narrator.languages.map((code) => LANGUAGE_LABELS[code] ?? code).join(', ')}</Text>
          <Text variant="small">
            {[`${narrator.published} published`, `${narrator.notPublished} not yet published`,
              narrator.rejected ? `${narrator.rejected} rejected` : null].filter(Boolean).join(' · ')}
          </Text>
          {narrator.published ? <Text variant="small">Narration rating: {rating(narrator.narration)}</Text> : null}
          {narrator.biography && bio === null ? <Text variant="small" numberOfLines={2}>{narrator.biography}</Text> : null}
        </View>
        <Button kind="ghost" title="Set photo" onPress={() => void act(() =>
          pickAndSend(`/api/studio/narrators/credited/photo?name=${encodeURIComponent(narrator.name)}`), 'Photo saved.')} />
        <Button kind="ghost" title={narrator.biography ? 'Edit bio' : 'Add bio'} onPress={() => setBio(narrator.biography ?? '')} />
        <Button kind="secondary" title={open ? 'Hide stories' : `Stories (${narrator.stories.length})`} onPress={() => setOpen(!open)} />
      </View>
      {bio !== null ? (
        <View style={{ gap: space.sm }}>
          <Field label="Bio shown on their page" value={bio} onChangeText={setBio} multiline maxLength={4000}
            style={{ minHeight: 100, paddingTop: space.md, textAlignVertical: 'top' }} />
          <View style={{ flexDirection: 'row', gap: space.sm }}>
            <Button title="Save bio" onPress={() => void act(() => api('/api/studio/narrators/credited', { method: 'POST', profile: false,
              body: { name: narrator.name, biography: bio } }).then(() => setBio(null)), 'Bio saved.')} />
            <Button kind="ghost" title="Cancel" onPress={() => setBio(null)} />
          </View>
        </View>
      ) : null}
      {message ? <Text variant="small" color={colors.muted}>{message}</Text> : null}
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
