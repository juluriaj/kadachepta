import Ionicons from '@expo/vector-icons/Ionicons';
import { useQuery } from '@tanstack/react-query';
import { Image } from 'expo-image';
import { useState } from 'react';
import { Pressable, ScrollView, TextInput, View } from 'react-native';

import { Button, Card, Chip, ErrorState, Field, Loading, Text, useColors } from '@/components/ui';
import { api, mediaUrl } from '@/lib/api';
import type { SettingSpec, SettingsPage } from '@/lib/studio';
import { radius, space } from '@/lib/theme';

// P2-14: AI models, providers, and pipeline switches, stored in the database and sent with every job.
// API keys stay in .env and never reach the browser.
export default function Settings() {
  const query = useQuery({ queryKey: ['studio-settings'], refetchInterval: 30_000,
    queryFn: () => api<SettingsPage>('/api/studio/settings', { profile: false }) });
  if (query.isLoading) return <Loading />;
  if (query.error) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  return <SettingsForm key={JSON.stringify(query.data!.values)} page={query.data!} refetch={() => void query.refetch()} />;
}

const JSON_KINDS = new Set(['map', 'patterns']);

function SettingsForm({ page, refetch }: { page: SettingsPage; refetch: () => void }) {
  const colors = useColors();
  const [values, setValues] = useState<Record<string, unknown>>(page.values);
  const [jsonText, setJsonText] = useState<Record<string, string>>(() => Object.fromEntries(page.specs
    .filter((s) => JSON_KINDS.has(s.kind)).map((s) => [s.key, JSON.stringify(page.values[s.key], null, 2)])));
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const parsed = (): Record<string, unknown> | string => {
    const result = { ...values };
    for (const [key, text] of Object.entries(jsonText)) {
      try {
        result[key] = JSON.parse(text);
      } catch {
        return `${page.specs.find((s) => s.key === key)?.label}: not valid JSON`;
      }
    }
    return result;
  };
  const changed = (all: Record<string, unknown>) => Object.fromEntries(Object.entries(all)
    .filter(([key, value]) => JSON.stringify(value) !== JSON.stringify(page.values[key])));

  const save = async () => {
    const all = parsed();
    if (typeof all === 'string') return setMessage(all);
    setBusy(true);
    setMessage(null);
    try {
      const result = await api<{ changed: string[] }>('/api/studio/settings', { method: 'PUT', profile: false,
        body: { values: changed(all) } });
      setMessage(result.changed.length ? `Saved: ${result.changed.join(', ')}. The next jobs use them.` : 'Nothing changed.');
      refetch();
    } catch (failure) {
      setMessage(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setBusy(false);
    }
  };

  const groups = [['AI models', 'ai.'], ['Audio', 'audio.'], ['Pipeline', 'pipeline.'], ['Review', 'review.'], ['Narrators', 'narrators.']] as const;
  return (
    <ScrollView contentContainerStyle={{ padding: space.xl, gap: space.lg, maxWidth: 1100, width: '100%', alignSelf: 'center' }}>
      <Text variant="title">AI & processing</Text>
      <Text muted>Changes apply to the next job without restarting anything. Every change is recorded in the audit log.</Text>

      <Card>
        <Text variant="heading">Workers</Text>
        {page.workers.map((worker) => (
          <View key={worker.name} style={{ flexDirection: 'row', flexWrap: 'wrap', gap: space.sm, alignItems: 'center' }}>
            <Ionicons name="ellipse" size={10} color={worker.online ? colors.success : colors.danger} />
            <Text variant="heading">{worker.name}</Text>
            <Text variant="small" muted>{worker.capabilities.join(', ')} · {worker.online ? 'online' : `last seen ${worker.lastSeenAt ?? 'never'}`}</Text>
            {worker.info?.artwork?.gpu ? <Text variant="small" muted>· GPU {worker.info.artwork.gpu}</Text> : null}
            {worker.info?.artwork && worker.info.artwork.localModelInstalled === false ? (
              <Text variant="small" color={colors.danger}>· local artwork not installed</Text>
            ) : null}
          </View>
        ))}
        <Text variant="small" muted>
          Queued: {Object.entries(page.queue).map(([type, n]) => `${type} ${n}`).join(', ') || 'nothing'} ·
          Failed this week: {Object.entries(page.deadLastWeek).map(([type, n]) => `${type} ${n}`).join(', ') || 'none'} ·
          Transcribed today: {page.transcriptionMinutesToday} min
        </Text>
      </Card>

      {groups.map(([label, prefix]) => (
        <Card key={prefix}>
          <Text variant="heading">{label}</Text>
          {page.specs.filter((spec) => spec.key.startsWith(prefix)).map((spec) => (
            <SettingField key={spec.key} spec={spec} value={values[spec.key]} json={jsonText[spec.key]}
              models={page.availableModels}
              onChange={(value) => setValues({ ...values, [spec.key]: value })}
              onJson={(text) => setJsonText({ ...jsonText, [spec.key]: text })} />
          ))}
        </Card>
      ))}
      {message ? <Text>{message}</Text> : null}
      <Button title="Save settings" loading={busy} onPress={() => void save()} />

      <TestPanel values={(() => { const all = parsed(); return typeof all === 'string' ? {} : changed(all); })()} />
    </ScrollView>
  );
}

function SettingField({ spec, value, json, models, onChange, onJson }: {
  spec: SettingSpec; value: unknown; json?: string; models: string[]; onChange: (value: unknown) => void;
  onJson: (text: string) => void;
}) {
  const colors = useColors();
  return (
    <View style={{ gap: space.xs, paddingVertical: space.sm }}>
      {spec.kind === 'bool' ? (
        <Pressable accessibilityRole="switch" accessibilityState={{ checked: !!value }} onPress={() => onChange(!value)}
          style={{ flexDirection: 'row', alignItems: 'center', gap: space.sm }}>
          <Ionicons name={value ? 'toggle' : 'toggle-outline'} size={32} color={value ? colors.primary : colors.muted} />
          <Text variant="heading">{spec.label}</Text>
        </Pressable>
      ) : <Text variant="heading">{spec.label}</Text>}
      <Text variant="small" muted>{spec.help}</Text>
      {spec.kind === 'choice' ? (
        <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: space.sm }}>
          {spec.choices.map((choice) => <Chip key={choice} label={choice} selected={value === choice} onPress={() => onChange(choice)} />)}
        </View>
      ) : null}
      {spec.kind === 'text' ? (
        <>
          <Field label={spec.key} value={String(value ?? '')} onChangeText={onChange} autoCapitalize="none" />
          {spec.key === 'ai.llm.model' && models.length ? (
            <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: space.sm }}>
              {models.map((model) => <Chip key={model} label={model} selected={value === model} onPress={() => onChange(model)} />)}
            </View>
          ) : null}
        </>
      ) : null}
      {spec.kind === 'int' || spec.kind === 'float' ? (
        <Field label={`${spec.key} (${spec.minimum ?? ''}–${spec.maximum ?? ''})`} value={String(value ?? '')}
          keyboardType="numeric" onChangeText={(text) => onChange(text === '' ? '' : Number(text))} />
      ) : null}
      {json !== undefined ? (
        <TextInput multiline value={json} onChangeText={onJson} accessibilityLabel={spec.label} autoCapitalize="none"
          style={{ minHeight: 90, borderWidth: 1, borderColor: colors.border, borderRadius: radius.md, padding: space.md,
            color: colors.text, fontFamily: 'monospace', fontSize: 13 }} />
      ) : null}
    </View>
  );
}

type TestJob = { id: number; status: string; queueStatus: string; error: string | null; logTail: string | null;
  result: Record<string, any> };

function TestPanel({ values }: { values: Record<string, unknown> }) {
  const colors = useColors();
  const [assetId, setAssetId] = useState('');
  const [task, setTask] = useState<'drafts' | 'artwork'>('drafts');
  const [jobId, setJobId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const job = useQuery({ queryKey: ['studio-test-job', jobId], enabled: jobId != null,
    queryFn: () => api<TestJob>(`/api/studio/jobs/${jobId}`, { profile: false }),
    refetchInterval: (q) => (['queued', 'leased', 'failed'].includes(q.state.data?.queueStatus ?? 'queued') ? 3000 : false) });

  const run = async () => {
    try {
      const started = await api<{ jobId: number }>('/api/studio/settings/test', { method: 'POST', profile: false,
        body: { task, assetId: assetId.trim(), values } });
      setJobId(started.jobId);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    }
  };

  const result = job.data?.result;
  return (
    <Card>
      <Text variant="heading">Test on one story</Text>
      <Text variant="small" muted>Runs one job with the settings above (saved or not). The story itself is never changed.</Text>
      <View style={{ flexDirection: 'row', gap: space.sm }}>
        <Chip label="AI drafts" selected={task === 'drafts'} onPress={() => setTask('drafts')} />
        <Chip label="Artwork" selected={task === 'artwork'} onPress={() => setTask('artwork')} />
      </View>
      <Field label="Story id (from the review page address)" value={assetId} onChangeText={setAssetId} autoCapitalize="none" />
      <Button title="Run test" disabled={!assetId.trim()} onPress={() => void run()} />
      {error ? <Text color={colors.danger}>{error}</Text> : null}
      {job.data ? <Text variant="small" muted>Job {job.data.id}: {job.data.queueStatus}{job.data.error ? ` · ${job.data.error}` : ''}</Text> : null}
      {result?.url ? <Image source={{ uri: mediaUrl(result.url)! }} style={{ width: 256, height: 256, borderRadius: radius.md }} /> : null}
      {result?.texts ? (
        <View style={{ gap: space.xs }}>
          {Object.entries(result.texts as Record<string, { short: string; long: string }>).map(([language, text]) => (
            <Text key={language}>{language}: {text.long}</Text>
          ))}
          {result.safety ? <Text variant="small">Safety: {result.safety.rating} · {result.safety.summary}</Text> : null}
          {result.stats ? <Text variant="small" muted>{result.model} · {result.stats.seconds} s</Text> : null}
        </View>
      ) : null}
      {result?.prompt ? <Text variant="small" muted>{result.prompt}</Text> : null}
    </Card>
  );
}
