import { useQuery, useQueryClient } from '@tanstack/react-query';
import * as DocumentPicker from 'expo-document-picker';
import { useState } from 'react';
import { ScrollView, View } from 'react-native';

import { Button, Card, Cover, ErrorState, Field, Loading, Screen, Text, useColors } from '@/components/ui';
import { api, apiSendFile } from '@/lib/api';
import { useI18n } from '@/lib/i18n';
import { space } from '@/lib/theme';
import type { NarratorHome, NarratorProfile } from '@/lib/types';

// What families see on the narrator's page (P3-10): a photo (an editor approves it first) and a few lines.
export default function NarratorProfileScreen() {
  const home = useQuery({ queryKey: ['narrator-home'], queryFn: () => api<NarratorHome>('/api/narrator/home') });
  if (home.isLoading) return <Loading />;
  if (home.error || !home.data?.profile) return <Screen back><ErrorState error={home.error} onRetry={() => void home.refetch()} /></Screen>;
  return <ProfileForm profile={home.data.profile} />;
}

function ProfileForm({ profile }: { profile: NarratorProfile }) {
  const { t } = useI18n();
  const colors = useColors();
  const queryClient = useQueryClient();
  const [name, setName] = useState(profile.displayName ?? '');
  const [bio, setBio] = useState(profile.biography ?? '');
  const [photo, setPhoto] = useState({ approved: profile.photoUrl, pending: profile.pendingPhotoUrl });
  const [busy, setBusy] = useState<'photo' | 'save' | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const run = async (which: 'photo' | 'save', work: () => Promise<void>) => {
    setBusy(which);
    setError(null);
    setMessage(null);
    try {
      await work();
      await queryClient.invalidateQueries({ queryKey: ['narrator-home'] });
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setBusy(null);
    }
  };

  const upload = () => run('photo', async () => {
    const result = await DocumentPicker.getDocumentAsync({ type: ['image/jpeg', 'image/png', 'image/webp'], multiple: false });
    if (result.canceled || !result.assets?.length) return;
    const picked = result.assets[0];
    const file = (picked as { file?: Blob }).file ?? await (await fetch(picked.uri)).blob();
    const saved = await apiSendFile<NarratorProfile>('/api/narrator/profile/photo', file, picked.mimeType ?? file.type ?? 'image/jpeg');
    setPhoto({ approved: saved.photoUrl, pending: saved.pendingPhotoUrl });
  });

  const save = () => run('save', async () => {
    await api('/api/narrator/profile', { method: 'POST', profile: false,
      body: { displayName: name.trim(), biography: bio.trim(), languages: profile.languages } });
    setMessage(t('narrate.saved'));
  });

  const shown = photo.pending ?? photo.approved;
  return (
    <Screen back>
      <ScrollView contentContainerStyle={{ gap: space.lg, paddingVertical: space.lg, maxWidth: 640, width: '100%', alignSelf: 'center' }}
        keyboardShouldPersistTaps="handled">
        <Text variant="title" accessibilityRole="header">{t('narrate.page')}</Text>
        <Text muted>{t('narrate.pageHint')}</Text>
        <Card style={{ gap: space.md }}>
          <Text variant="label" muted>{t('narrate.photo')}</Text>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: space.lg, flexWrap: 'wrap' }}>
            <Cover id={`narrator-${profile.displayName ?? 'me'}`} title={name || '?'} artworkUrl={shown} size={96} rounded={48} />
            <View style={{ flex: 1, minWidth: 200, gap: space.sm }}>
              <Button kind="secondary" title={t('narrate.photoUpload')} loading={busy === 'photo'} onPress={() => void upload()} />
              <Text variant="small" muted>{photo.pending ? t('narrate.photoPending') : t('narrate.photoRules')}</Text>
            </View>
          </View>
        </Card>
        <Field label={t('narrate.name')} value={name} onChangeText={setName} maxLength={120} />
        <Field label={t('narrate.bio')} value={bio} onChangeText={setBio} multiline maxLength={4000}
          style={{ minHeight: 120, paddingTop: space.md, textAlignVertical: 'top' }} />
        {error ? <Text color={colors.danger} accessibilityLiveRegion="polite">{error}</Text> : null}
        {message ? <Text color={colors.success} accessibilityLiveRegion="polite">{message}</Text> : null}
        <Button title={t('common.save')} loading={busy === 'save'} disabled={!name.trim()} onPress={() => void save()} />
      </ScrollView>
    </Screen>
  );
}
