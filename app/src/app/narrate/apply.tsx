import Ionicons from '@expo/vector-icons/Ionicons';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { router } from 'expo-router';
import { useState } from 'react';
import { Pressable, ScrollView, View } from 'react-native';

import { Recorder, type Take } from '@/components/Recorder';
import { Button, Card, Chip, Field, Loading, Screen, Text, useColors } from '@/components/ui';
import { api } from '@/lib/api';
import { LANGUAGE_LABELS, useI18n } from '@/lib/i18n';
import { useSession } from '@/lib/session';
import { space } from '@/lib/theme';
import { uploadFile } from '@/lib/uploads';

type Agreement = { version: string; items: string[]; payouts: string };

export default function ApplyToNarrate() {
  const { t } = useI18n();
  const colors = useColors();
  const queryClient = useQueryClient();
  const { refresh, household } = useSession();
  const agreement = useQuery({ queryKey: ['narrator-agreement'], queryFn: () => api<Agreement>('/api/narrator/agreement') });
  const [name, setName] = useState(household?.profiles.find((p) => p.kind === 'adult')?.name ?? '');
  const [bio, setBio] = useState('');
  const [languages, setLanguages] = useState<string[]>(['te-IN']);
  const [agreed, setAgreed] = useState(false);
  const [sample, setSample] = useState<Take[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (agreement.isLoading || !agreement.data) return <Loading />;

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const sampleUploadId = sample.length ? await uploadFile(sample[sample.length - 1], 'sample') : undefined;
      await api('/api/narrator/apply', { method: 'POST', profile: false, body: {
        displayName: name.trim(), biography: bio.trim(), languages, agreementVersion: agreement.data.version, sampleUploadId } });
      await refresh();
      await queryClient.invalidateQueries({ queryKey: ['narrator-home'] });
      router.replace('/(tabs)/narrate');
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Screen>
      <ScrollView contentContainerStyle={{ gap: space.lg, paddingVertical: space.lg }} keyboardShouldPersistTaps="handled">
        <Pressable accessibilityRole="button" accessibilityLabel={t('common.back')} onPress={() => router.back()} hitSlop={12}>
          <Ionicons name="chevron-back" size={26} color={colors.text} />
        </Pressable>
        <Text variant="title" accessibilityRole="header">{t('apply.title')}</Text>
        <Field label={t('apply.name')} value={name} onChangeText={setName} autoComplete="name" />
        <Field label={t('apply.bio')} value={bio} onChangeText={setBio} multiline style={{ minHeight: 72, paddingTop: space.md }} />
        <Text variant="label" muted>{t('apply.languages')}</Text>
        <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: space.sm }}>
          {Object.entries(LANGUAGE_LABELS).map(([code, label]) => (
            <Chip key={code} label={label} selected={languages.includes(code)}
              onPress={() => setLanguages(languages.includes(code) ? languages.filter((l) => l !== code) : [...languages, code])} />
          ))}
        </View>

        <Card>
          <Text variant="heading">{t('apply.agreement')}</Text>
          {agreement.data.items.map((item) => (
            <View key={item} style={{ flexDirection: 'row', gap: space.sm }}>
              <Text muted>•</Text>
              <Text style={{ flex: 1 }}>{item}</Text>
            </View>
          ))}
          <Pressable accessibilityRole="checkbox" accessibilityState={{ checked: agreed }} onPress={() => setAgreed(!agreed)}
            style={{ flexDirection: 'row', alignItems: 'center', gap: space.sm, minHeight: 44 }}>
            <Ionicons name={agreed ? 'checkbox' : 'square-outline'} size={24} color={colors.primary} />
            <Text variant="heading" style={{ flex: 1 }}>{t('apply.agree')}</Text>
          </Pressable>
          <Text variant="small" muted>{t('apply.payouts')}</Text>
        </Card>

        <Card>
          <Text variant="heading">{t('apply.sample')}</Text>
          <Text variant="small" muted>{t('apply.sampleHint')}</Text>
          <Recorder takes={sample} onChange={(takes) => setSample(takes.slice(-1))} maxSeconds={90} />
        </Card>

        {error ? <Text color={colors.danger}>{error}</Text> : null}
        <Button title={t('apply.submit')} loading={busy} disabled={!name.trim() || !languages.length || !agreed}
          onPress={() => void submit()} />
      </ScrollView>
    </Screen>
  );
}
