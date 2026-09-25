import Ionicons from '@expo/vector-icons/Ionicons';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import * as DocumentPicker from 'expo-document-picker';
import { router, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { Pressable, ScrollView, View } from 'react-native';

import { SourcePicker, type SourceType } from '@/components/narrator';
import { Recorder, type Take } from '@/components/Recorder';
import { Button, Card, Chip, Field, ProgressBar, Screen, Text, useColors } from '@/components/ui';
import { api } from '@/lib/api';
import { LANGUAGE_LABELS, useI18n } from '@/lib/i18n';
import { space } from '@/lib/theme';
import type { NarratorHome, Submission } from '@/lib/types';
import { uploadFile, type LocalFile } from '@/lib/uploads';

type Picked = LocalFile & { size?: number | null };

async function pick(type: string[]): Promise<Picked | null> {
  const result = await DocumentPicker.getDocumentAsync({ type, copyToCacheDirectory: true, multiple: false });
  if (result.canceled || !result.assets?.length) return null;
  const asset = result.assets[0];
  return { uri: asset.uri, name: asset.name, size: asset.size ?? null, file: (asset as { file?: Blob }).file ?? null } as Picked;
}

// One screen: record (or pick a file), say what it is and where it's from, send. With ?replace=<id> it only
// re-records the audio of an existing submission.
export default function NewSubmission() {
  const { t } = useI18n();
  const colors = useColors();
  const queryClient = useQueryClient();
  const { replace } = useLocalSearchParams<{ replace?: string }>();
  const home = useQuery({ queryKey: ['narrator-home'], queryFn: () => api<NarratorHome>('/api/narrator/home') });
  const languages = home.data?.profile?.languages?.length ? home.data.profile.languages : ['te-IN'];

  const [takes, setTakes] = useState<Take[]>([]);
  const [file, setFile] = useState<Picked | null>(null);
  const [title, setTitle] = useState('');
  const [language, setLanguage] = useState<string | null>(null);
  const [seriesId, setSeriesId] = useState<number | 'new' | null>(null);
  const [seriesName, setSeriesName] = useState('');
  const [chapter, setChapter] = useState('');
  const [text, setText] = useState('');
  const [source, setSource] = useState<SourceType | null>(null);
  const [reference, setReference] = useState('');
  const [evidence, setEvidence] = useState<Picked | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const recordings: LocalFile[] = file ? [file] : takes;
  const chosenLanguage = language ?? languages[0];
  const ready = recordings.length > 0 && (replace || (title.trim() && source && confirmed
    && (seriesId !== 'new' || seriesName.trim())));

  const send = async () => {
    setError(null);
    setProgress(0);
    try {
      const sizes = recordings.map((r) => r.size ?? 0);
      const total = sizes.reduce((a, b) => a + b, 0) || recordings.length;
      let done = 0;
      const uploadIds: string[] = [];
      for (const [index, recording] of recordings.entries()) {
        uploadIds.push(await uploadFile(recording, 'audio', (sent, size) =>
          setProgress((done + (sizes[index] ? sent : (sent / size))) / total)));
        done += sizes[index] || 1;
      }
      let submission: Submission;
      if (replace) {
        submission = await api<Submission>(`/api/narrator/submissions/${replace}/replace-audio`, {
          method: 'POST', profile: false, body: { uploadIds } });
      } else {
        let series: number | null = typeof seriesId === 'number' ? seriesId : null;
        if (seriesId === 'new') {
          series = (await api<{ id: number }>('/api/narrator/series', { method: 'POST', profile: false,
            body: { title: seriesName.trim(), language: chosenLanguage } })).id;
        }
        const evidenceUploadId = evidence ? await uploadFile(evidence, 'evidence') : undefined;
        submission = await api<Submission>('/api/narrator/submissions', { method: 'POST', profile: false, body: {
          uploadIds, title: title.trim(), language: chosenLanguage, seriesId: series,
          seriesPosition: series && Number(chapter) > 0 ? Number(chapter) : null, sourceText: text.trim() || null,
          attestation: { sourceType: source, sourceReference: reference.trim(), evidenceUploadId } } });
      }
      await queryClient.invalidateQueries({ queryKey: ['narrator-home'] });
      await queryClient.invalidateQueries({ queryKey: ['submission', submission.id] });
      router.replace(`/narrate/submission/${submission.id}`);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
      setProgress(null);
    }
  };

  return (
    <Screen>
      <ScrollView contentContainerStyle={{ gap: space.lg, paddingVertical: space.lg }} keyboardShouldPersistTaps="handled">
        <Pressable accessibilityRole="button" accessibilityLabel={t('common.back')} onPress={() => router.back()} hitSlop={12}>
          <Ionicons name="chevron-back" size={26} color={colors.text} />
        </Pressable>
        <Text variant="title" accessibilityRole="header">{replace ? t('status.replace') : t('narrate.new')}</Text>

        {!replace ? (
          <Field label={t('rec.teleprompter')} value={text} onChangeText={setText} multiline
            style={{ minHeight: 72, paddingTop: space.md }} />
        ) : null}
        <Card>
          {file ? (
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: space.sm }}>
              <Ionicons name="document-attach-outline" size={22} color={colors.primary} />
              <Text style={{ flex: 1 }}>{t('rec.fileChosen', { name: file.name })}</Text>
              <Pressable accessibilityRole="button" accessibilityLabel={t('library.remove')} onPress={() => setFile(null)} hitSlop={12}>
                <Ionicons name="close" size={22} color={colors.muted} />
              </Pressable>
            </View>
          ) : (
            <>
              <Recorder takes={takes} onChange={setTakes} teleprompter={text.trim() || undefined} />
              {!takes.length ? (
                <>
                  <Text variant="small" muted style={{ textAlign: 'center' }}>{t('rec.or')}</Text>
                  <Button kind="secondary" title={t('rec.upload')} icon={<Ionicons name="cloud-upload-outline" size={18} color={colors.text} />}
                    onPress={() => void pick(['audio/*']).then((picked) => picked && setFile(picked))} />
                </>
              ) : null}
            </>
          )}
        </Card>

        {!replace ? (
          <>
            <Text variant="heading">{t('sub.details')}</Text>
            <Field label={t('sub.title')} value={title} onChangeText={setTitle} />
            <Text variant="label" muted>{t('sub.language')}</Text>
            <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: space.sm }}>
              {languages.map((code) => (
                <Chip key={code} label={LANGUAGE_LABELS[code] ?? code} selected={chosenLanguage === code} onPress={() => setLanguage(code)} />
              ))}
            </View>
            <Text variant="label" muted>{t('sub.series')}</Text>
            <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: space.sm }}>
              <Chip label={t('sub.noSeries')} selected={seriesId === null} onPress={() => setSeriesId(null)} />
              {(home.data?.series ?? []).map((s) => (
                <Chip key={s.id} label={s.title} selected={seriesId === s.id} onPress={() => { setSeriesId(s.id); setChapter(String(s.chapters + 1)); }} />
              ))}
              <Chip label={t('sub.newSeries')} selected={seriesId === 'new'} onPress={() => { setSeriesId('new'); setChapter('1'); }} />
            </View>
            {seriesId === 'new' ? <Field label={t('sub.seriesName')} value={seriesName} onChangeText={setSeriesName} /> : null}
            {seriesId !== null ? (
              <Field label={t('sub.chapter')} value={chapter} onChangeText={(v) => setChapter(v.replace(/\D/g, ''))} keyboardType="number-pad" />
            ) : null}

            <Text variant="heading">{t('sub.source')}</Text>
            <SourcePicker value={source} onChange={setSource} />
            {source && source !== 'original' ? <Field label={t('sub.reference')} value={reference} onChangeText={setReference} /> : null}
            {source === 'licensed' ? (
              <Button kind="secondary" title={evidence ? t('rec.fileChosen', { name: evidence.name }) : t('sub.evidence')}
                icon={<Ionicons name="attach" size={18} color={colors.text} />}
                onPress={() => void pick(['application/pdf', 'image/*']).then((picked) => picked && setEvidence(picked))} />
            ) : null}
            <Pressable accessibilityRole="checkbox" accessibilityState={{ checked: confirmed }} onPress={() => setConfirmed(!confirmed)}
              style={{ flexDirection: 'row', alignItems: 'center', gap: space.sm, minHeight: 44 }}>
              <Ionicons name={confirmed ? 'checkbox' : 'square-outline'} size={24} color={colors.primary} />
              <Text style={{ flex: 1 }}>{t('sub.confirm')}</Text>
            </Pressable>
          </>
        ) : null}

        {progress !== null ? (
          <View style={{ gap: space.xs }}>
            <Text variant="small">{t('sub.uploading', { percent: Math.round(progress * 100) })}</Text>
            <ProgressBar value={progress} height={6} />
            <Text variant="small" muted>{t('sub.resumeHint')}</Text>
          </View>
        ) : null}
        {error ? <Text color={colors.danger}>{error}</Text> : null}
        {!recordings.length ? <Text variant="small" muted>{t('sub.needAudio')}</Text> : null}
        <Button title={t('sub.send')} disabled={!ready} loading={progress !== null} onPress={() => void send()}
          icon={<Ionicons name="send" size={18} color={colors.onPrimary} />} />
      </ScrollView>
    </Screen>
  );
}
