import Ionicons from '@expo/vector-icons/Ionicons';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Image } from 'expo-image';
import { router, useLocalSearchParams } from 'expo-router';
import { useEffect, useState, type ReactNode } from 'react';
import { Linking, Platform, Pressable, ScrollView, TextInput, useWindowDimensions, View } from 'react-native';

import { QcList } from '@/components/narrator';
import { MasteringCompare } from '@/components/MasteringCompare';
import { Button, Card, Chip, ErrorState, Field, Loading, Text, useColors } from '@/components/ui';
import { api, ApiError, mediaUrl } from '@/lib/api';
import { formatClock, LANGUAGE_LABELS } from '@/lib/i18n';
import { useSession } from '@/lib/session';
import { AGE_RANGES, GENRES, hoursLabel, listText, MOMENTS, parseList, type Review } from '@/lib/studio';
import { fontFor, radius, space } from '@/lib/theme';

export default function ReviewScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const query = useQuery({ queryKey: ['studio-review', id],
    queryFn: () => api<Review>(`/api/studio/review/${id}`, { profile: false }) });
  if (query.isLoading) return <Loading />;
  if (query.error) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  const review = query.data!;
  // Keyed so the form starts fresh when new drafts or a new transcript arrive.
  return <ReviewForm key={`${review.asset.id}:${review.draft?.id}:${review.transcript?.id}:${review.asset.artworkUrl}`}
    review={review} refetch={() => void query.refetch()} />;
}

type TeaserTexts = Record<string, { short: string; long: string }>;

function ReviewForm({ review, refetch }: { review: Review; refetch: () => void }) {
  const colors = useColors();
  const queryClient = useQueryClient();
  const { width } = useWindowDimensions();
  const { session } = useSession();
  const isAdmin = (session.permissions ?? []).includes('jobs.manage');
  const wide = width >= 1000;
  const { asset, draft, transcript } = review;
  const meta = asset.metadata;

  const [title, setTitle] = useState(meta.title);
  const [genres, setGenres] = useState<string[]>(meta.genres.length ? meta.genres : draft?.suggestions.genres ?? []);
  const [age, setAge] = useState(meta.audienceAgeRange ?? draft?.ageSuggestion ?? '');
  const [moral, setMoral] = useState(meta.moralTakeaway ?? '');
  const [moments, setMoments] = useState<string[]>(meta.listeningContexts.length ? meta.listeningContexts
    : draft?.suggestions.listeningContexts ?? []);
  const [keywords, setKeywords] = useState(listText(meta.keywords.length ? meta.keywords : draft?.suggestions.keywords));
  const [warnings, setWarnings] = useState(listText(meta.contentWarnings.length ? meta.contentWarnings : draft?.warnings));
  const [source, setSource] = useState(meta.sourceAdaptation ?? (asset.isSubmission ? '' : 'KathaChepta'));
  const [teasers, setTeasers] = useState<TeaserTexts>(() => {
    const texts: TeaserTexts = {};
    if (draft) {
      texts[draft.language] = { short: draft.shortText ?? '', long: draft.longText ?? '' };
      for (const [language, value] of Object.entries(draft.alternates ?? {})) {
        texts[language] = { short: value.short ?? '', long: value.long ?? '' };
      }
    }
    return texts;
  });
  const [transcriptText, setTranscriptText] = useState(transcript?.text ?? '');
  const [transcriptOpen, setTranscriptOpen] = useState(!!transcript?.reviewRequired);
  const [transcriptChecked, setTranscriptChecked] = useState(false);
  const [captions, setCaptions] = useState(review.captionsEnabled);
  const [rights, setRights] = useState<'owned' | 'attestation' | null>(
    review.rights.status === 'approved' ? null : asset.isSubmission ? null : 'owned');
  const [checklist, setChecklist] = useState<Set<string>>(new Set());
  const [changes, setChanges] = useState<Set<string> | null>(null);
  const [note, setNote] = useState('');
  const [problems, setProblems] = useState<string[]>([]);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const body = () => ({
    metadata: { title, genres, audienceAgeRange: age, moralTakeaway: moral, listeningContexts: moments,
      keywords: parseList(keywords), contentWarnings: parseList(warnings), sourceAdaptation: source },
    teaser: teasers, transcript: { text: transcriptText, reviewed: transcriptChecked }, rights,
    checklist: [...checklist], captionsEnabled: captions,
  });

  const act = async (label: string, work: () => Promise<unknown>, after?: () => void) => {
    setBusy(label);
    setProblems([]);
    setMessage(null);
    try {
      await work();
      await queryClient.invalidateQueries({ queryKey: ['studio-queue'] });
      if (after) after();
    } catch (failure) {
      if (failure instanceof ApiError && Array.isArray(failure.body.problems)) setProblems(failure.body.problems as string[]);
      else setMessage(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setBusy(null);
    }
  };
  const publish = () => act('publish', () => api(`/api/studio/review/${asset.id}/publish`, { method: 'POST', profile: false, body: body() }),
    () => router.replace('/studio'));
  const save = () => act('save', () => api(`/api/studio/review/${asset.id}/save`, { method: 'POST', profile: false, body: body() }),
    () => setMessage('Saved.'));
  const regenerate = (step: string) => act(step, () => api(`/api/studio/review/${asset.id}/regenerate`,
    { method: 'POST', profile: false, body: { step } }), () => { setMessage(`${step} queued; this page refreshes when it's done.`); refetch(); });

  // Ctrl/Cmd + Enter publishes; Escape goes back to the queue.
  useEffect(() => {
    if (Platform.OS !== 'web') return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') router.replace('/studio');
      else if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
        event.preventDefault();
        document.getElementById('publish-button')?.click();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const running = review.jobs.some((job) => ['queued', 'leased', 'failed'].includes(job.queueStatus));
  useEffect(() => {
    if (!running) return;
    const timer = setInterval(refetch, 8000);
    return () => clearInterval(timer);
  }, [running, refetch]);

  const safety = draft?.safety ?? {};
  const safetyColor = safety.rating === 'all-ages' ? colors.success : safety.rating === 'caution' ? colors.accent : colors.danger;
  const required = review.policy.checklist.filter((item) => item.required);
  const needsTranscriptTick = !!transcript?.reviewRequired || captions;

  const left = (
    <View style={{ gap: space.lg, flex: wide ? 1 : undefined }}>
      <Card>
        <MasteringCompare audioUrl={asset.audioUrl} mastering={review.mastering} waveform={review.waveform}
          duration={asset.duration} labels={{ mastered: 'Listening copy', original: 'As recorded' }} />
        {asset.originalAudioUrl ? (
          <Pressable onPress={() => void Linking.openURL(mediaUrl(asset.originalAudioUrl)!)}>
            <Text variant="small" color={colors.primary}>Original upload</Text>
          </Pressable>
        ) : null}
      </Card>
      <Card>
        <Text variant="heading">Sound check: {review.qc.verdict ?? 'not run'}</Text>
        {review.qc.checks?.length ? <QcList checks={review.qc.checks} /> : null}
        <Text variant="small" muted>
          {[review.qc.integratedLufs != null ? `${review.qc.integratedLufs.toFixed(0)} LUFS` : null,
            review.qc.noiseFloorDb != null ? `noise ${review.qc.noiseFloorDb} dB` : null,
            review.qc.speechRatio != null ? `speech ${Math.round(review.qc.speechRatio * 100)}%` : null].filter(Boolean).join(' · ')}
        </Text>
        <MasteringChoice mastering={review.mastering} busy={busy === 'mastering'} disabled={running}
          onChoose={(choice) => void act('mastering', () => api(`/api/studio/review/${asset.id}/mastering`,
            { method: 'POST', profile: false, body: { choice } }), () => { setMessage('Re-processing the audio; this page refreshes when it’s done.'); refetch(); })} />
      </Card>
      <Card>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: space.sm }}>
          <Text variant="heading" style={{ flex: 1 }}>Transcript</Text>
          {transcript ? (
            <Text variant="small" color={transcript.reviewRequired ? colors.danger : colors.success}>
              confidence {transcript.confidence == null ? '?' : `${Math.round(transcript.confidence * 100)}%`}
              {transcript.reviewRequired ? ' · must be read' : ' · optional to read'}
            </Text>
          ) : null}
        </View>
        {!transcript ? <Text muted>No transcript yet.</Text> : (
          <>
            {transcript.quality.reasons?.map((reason) => <Text key={reason} variant="small" color={colors.danger}>{reason}</Text>)}
            {transcript.introRemoved ? <Text variant="small" muted>Channel intro removed: “{transcript.introRemoved}”</Text> : null}
            {transcriptOpen ? (
              <TextInput multiline value={transcriptText} onChangeText={setTranscriptText} accessibilityLabel="Transcript"
                style={{ minHeight: 320, borderWidth: 1, borderColor: colors.border, borderRadius: radius.md, padding: space.md,
                  color: colors.text, fontSize: 16, lineHeight: 26, fontFamily: fontFor(transcriptText), textAlignVertical: 'top' }} />
            ) : (
              <Pressable onPress={() => setTranscriptOpen(true)}>
                <Text numberOfLines={6}>{transcriptText}</Text>
                <Text variant="small" color={colors.primary}>Show all and edit</Text>
              </Pressable>
            )}
            <Toggle label="Captions on (requires reading the transcript)" value={captions} onChange={setCaptions} />
            <Toggle label="I checked the transcript" value={transcriptChecked} onChange={setTranscriptChecked}
              highlight={needsTranscriptTick && !transcriptChecked} />
          </>
        )}
      </Card>
      {review.sourceText ? (
        <Card>
          <Text variant="heading">Text the narrator read from</Text>
          <Text numberOfLines={12}>{review.sourceText}</Text>
        </Card>
      ) : null}
      <Card>
        <Text variant="heading">History</Text>
        {review.history.slice(0, 15).map((event, index) => (
          <Text key={index} variant="small" muted>
            {new Date(event.createdAt).toLocaleString()} · {event.actor} · {event.action}{event.notes ? ` · ${event.notes}` : ''}
          </Text>
        ))}
      </Card>
    </View>
  );

  const right = (
    <View style={{ gap: space.lg, flex: wide ? 1 : undefined }}>
      <Card>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: space.sm }}>
          <Text variant="heading" style={{ flex: 1 }}>Safety pre-check</Text>
          <Text variant="heading" color={safetyColor}>{safety.rating ?? 'not checked'}</Text>
        </View>
        {safety.summary ? <Text>{safety.summary}</Text> : null}
        {safety.minAge != null ? <Text variant="small" muted>Youngest suitable age (AI): {safety.minAge}</Text> : null}
        {(safety.flags ?? []).map((flag, index) => (
          <Text key={index} variant="small" color={flag.severity === 'high' ? colors.danger : colors.text}>
            • {flag.category} ({flag.severity}): {flag.evidence}
          </Text>
        ))}
        {!draft ? <Text muted>No AI drafts yet.</Text> : (
          <Text variant="small" muted>{draft.model} · {draft.promptVersion}</Text>
        )}
      </Card>

      <Card>
        <View style={{ flexDirection: 'row', gap: space.md, alignItems: 'center' }}>
          {asset.artworkUrl ? (
            <Image source={{ uri: mediaUrl(asset.artworkUrl)! }} style={{ width: 120, height: 120, borderRadius: radius.md }} />
          ) : <Text muted>No artwork.</Text>}
          <View style={{ flex: 1, gap: space.sm }}>
            <Text variant="heading">Artwork</Text>
            <Button kind="secondary" title="Make new artwork" loading={busy === 'artwork'} onPress={() => void regenerate('artwork')} />
          </View>
        </View>
      </Card>

      <Card>
        <View style={{ flexDirection: 'row', alignItems: 'center' }}>
          <Text variant="heading" style={{ flex: 1 }}>Teaser</Text>
          <Button kind="ghost" title="Redo AI drafts" loading={busy === 'drafts'} onPress={() => void regenerate('drafts')} />
        </View>
        {Object.entries(teasers).map(([language, text]) => (
          <View key={language} style={{ gap: space.xs }}>
            <Text variant="label" muted>{LANGUAGE_LABELS[language] ?? language}</Text>
            <Field label="One line" value={text.short} onChangeText={(value) => setTeasers({ ...teasers, [language]: { ...text, short: value } })}
              style={{ fontFamily: fontFor(text.short) }} />
            <Field label="Longer" value={text.long} multiline onChangeText={(value) => setTeasers({ ...teasers, [language]: { ...text, long: value } })}
              style={{ minHeight: 90, paddingTop: space.md, fontFamily: fontFor(text.long) }} />
          </View>
        ))}
      </Card>

      <Card>
        <Text variant="heading">Details</Text>
        <Field label="Title" value={title} onChangeText={setTitle} style={{ fontFamily: fontFor(title) }} />
        {draft?.suggestions.englishTitle ? <Text variant="small" muted>English title (AI): {draft.suggestions.englishTitle}</Text> : null}
        <Label>Genres</Label>
        <Chips options={GENRES} values={genres} onChange={setGenres} />
        <Label>Age range {draft?.ageSuggestion ? `(AI suggests ${draft.ageSuggestion})` : ''}</Label>
        <Chips options={AGE_RANGES} values={age ? [age] : []} single onChange={(values) => setAge(values[0] ?? '')} />
        <Label>Listening moments</Label>
        <Chips options={MOMENTS} values={moments} onChange={setMoments} />
        <Field label="The idea behind it (moral)" value={moral} onChangeText={setMoral} />
        <Field label="Content warnings (comma separated)" value={warnings} onChangeText={setWarnings} />
        <Field label="Search keywords (comma separated)" value={keywords} onChangeText={setKeywords} />
        <Field label="Source or adaptation" value={source} onChangeText={setSource} />
        {review.series ? <Text variant="small" muted>Series: {review.series.title} · chapter {review.series.position ?? '?'}</Text> : null}
      </Card>

      <Card>
        <Text variant="heading">Rights: {review.rights.status}</Text>
        {review.rights.attestation?.sourceType ? (
          <Text variant="small">
            Narrator says: {review.rights.attestation.sourceType}
            {review.rights.attestation.sourceReference ? ` · ${review.rights.attestation.sourceReference}` : ''}
          </Text>
        ) : null}
        {review.rights.evidenceUrl ? (
          <Pressable onPress={() => void Linking.openURL(mediaUrl(review.rights.evidenceUrl)!)}>
            <Text variant="small" color={colors.primary}>Open the licence evidence</Text>
          </Pressable>
        ) : null}
        {review.rights.status !== 'approved' ? (
          <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: space.sm }}>
            {!asset.isSubmission ? <Chip label="KathaChepta owns this" selected={rights === 'owned'} onPress={() => setRights('owned')} /> : null}
            {review.rights.attestation?.sourceType ? (
              <Chip label="Accept the narrator's statement" selected={rights === 'attestation'} onPress={() => setRights('attestation')} />
            ) : null}
          </View>
        ) : <Text variant="small" color={colors.success}>{review.rights.message}</Text>}
      </Card>

      {review.narrator ? (
        <Card>
          <Text variant="heading">Narrator: {review.narrator.name}</Text>
          <Text variant="small" muted>
            {[review.narrator.email, review.narrator.phone].filter(Boolean).join(' · ') || 'No contact details yet'}
            {review.narrator.contactChannel ? ` · prefers ${review.narrator.contactChannel}` : ''}
            {review.narrator.contactNotes ? ` (${review.narrator.contactNotes})` : ''}
          </Text>
          <Text variant="small" muted>
            {review.narrator.trustLevel ?? 'new'} · {review.narrator.published ?? 0} published · {review.narrator.changesRequested ?? 0} change requests · {review.narrator.rejected ?? 0} rejected
          </Text>
          {review.narrator.sampleUrl ? (
            <Pressable onPress={() => void Linking.openURL(mediaUrl(review.narrator!.sampleUrl)!)}>
              <Text variant="small" color={colors.primary}>Hear their sample recording</Text>
            </Pressable>
          ) : null}
        </Card>
      ) : null}

      <Card>
        <Text variant="heading">Before publishing</Text>
        {review.policy.checklist.map((item) => (
          <Toggle key={item.id} label={item.text + (item.required ? '' : ' (optional)')} value={checklist.has(item.id)}
            onChange={(on) => setChecklist((current) => {
              const next = new Set(current);
              if (on) next.add(item.id);
              else next.delete(item.id);
              return next;
            })} />
        ))}
        {problems.length ? (
          <View style={{ gap: 4 }}>
            {problems.map((problem) => <Text key={problem} color={colors.danger}>• {problem}</Text>)}
          </View>
        ) : null}
        {message ? <Text>{message}</Text> : null}
        <Button nativeID="publish-button" title="Publish" loading={busy === 'publish'}
          disabled={!!busy || review.stage === 'published' || required.some((item) => !checklist.has(item.id))}
          onPress={() => void publish()} />
        <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: space.sm }}>
          <Button kind="secondary" title="Save without publishing" loading={busy === 'save'} onPress={() => void save()} />
          {asset.isSubmission ? (
            <Button kind="secondary" title="Ask for changes" onPress={() => setChanges(changes ? null : new Set())} />
          ) : null}
          <Button kind="ghost" title="Redo sound check" loading={busy === 'audio'} onPress={() => void regenerate('audio')} />
          {isAdmin && !transcript ? (
            <Button kind="ghost" title="Transcribe (paid)" loading={busy === 'transcription'} onPress={() => void regenerate('transcription')} />
          ) : null}
        </View>
        {changes ? (
          <View style={{ gap: space.sm }}>
            {Object.entries(review.policy.changeReasons).map(([code, text]) => (
              <Toggle key={code} label={text} value={changes.has(code)} onChange={(on) => {
                const next = new Set(changes);
                if (on) next.add(code);
                else next.delete(code);
                setChanges(next);
              }} />
            ))}
            <Field label="Note for the narrator (timestamps help)" value={note} onChangeText={setNote} multiline />
            <View style={{ flexDirection: 'row', gap: space.sm }}>
              <Button title="Send to narrator" disabled={!changes.size} loading={busy === 'changes'}
                onPress={() => void act('changes', () => api(`/api/studio/review/${asset.id}/request-changes`,
                  { method: 'POST', profile: false, body: { reasons: [...changes], note } }), () => router.replace('/studio'))} />
              <Button kind="danger" title="Reject" disabled={!note.trim()} loading={busy === 'reject'}
                onPress={() => void act('reject', () => api(`/api/studio/review/${asset.id}/reject`,
                  { method: 'POST', profile: false, body: { note } }), () => router.replace('/studio'))} />
            </View>
          </View>
        ) : null}
        {!asset.isSubmission && review.stage !== 'published' ? (
          <Button kind="ghost" title="Reject (catalog)" disabled={!note.trim()}
            onPress={() => void act('reject', () => api(`/api/studio/review/${asset.id}/reject`, { method: 'POST', profile: false,
              body: { note } }), () => router.replace('/studio'))} />
        ) : null}
        {Platform.OS === 'web' ? <Text variant="small" muted>Keys: Space play · [ ] skip 10 s · Ctrl+Enter publish · Esc queue</Text> : null}
      </Card>
    </View>
  );

  return (
    <ScrollView contentContainerStyle={{ padding: space.xl, gap: space.lg, maxWidth: 1400, width: '100%', alignSelf: 'center' }}>
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: space.md }}>
        <Pressable accessibilityRole="button" accessibilityLabel="Back to the queue" onPress={() => router.replace('/studio')}>
          <Ionicons name="arrow-back" size={24} color={colors.text} />
        </Pressable>
        <Text variant="title" style={{ fontFamily: fontFor(asset.title, 'bold') }}>{asset.title}</Text>
        <Text muted>{[asset.narrator, LANGUAGE_LABELS[asset.language] ?? asset.language, formatClock(asset.duration),
          review.stageLabel].join(' · ')}</Text>
        {review.waitingHours != null ? (
          <Text color={review.overdue ? colors.danger : colors.muted}>waiting {hoursLabel(review.waitingHours)}</Text>
        ) : null}
      </View>
      {review.pipelineError ? <Text color={colors.danger}>{review.pipelineError}</Text> : null}
      {running ? <Text variant="small" muted>Work is running for this story; the page refreshes automatically.</Text> : null}
      {review.changesRequested ? (
        <Text variant="small" muted>Changes were requested by {review.changesRequested.by}: {review.changesRequested.texts.join(' ')} {review.changesRequested.note}</Text>
      ) : null}
      <View style={{ flexDirection: wide ? 'row' : 'column', gap: space.lg, alignItems: 'flex-start' }}>
        {left}
        {right}
      </View>
    </ScrollView>
  );
}

function Label({ children }: { children: ReactNode }) {
  return <Text variant="label" muted>{children}</Text>;
}

function Chips({ options, values, onChange, single }: { options: string[]; values: string[]; onChange: (values: string[]) => void;
  single?: boolean }) {
  return (
    <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 6 }}>
      {[...new Set([...options, ...values])].map((option) => (
        <Chip key={option} label={option} selected={values.includes(option)} onPress={() => {
          if (single) onChange(values.includes(option) ? [] : [option]);
          else onChange(values.includes(option) ? values.filter((v) => v !== option) : [...values, option]);
        }} />
      ))}
    </View>
  );
}

function Toggle({ label, value, onChange, highlight }: { label: string; value: boolean; onChange: (value: boolean) => void;
  highlight?: boolean }) {
  const colors = useColors();
  return (
    <Pressable accessibilityRole="checkbox" accessibilityState={{ checked: value }} onPress={() => onChange(!value)}
      style={{ flexDirection: 'row', alignItems: 'center', gap: space.sm, minHeight: 36 }}>
      <Ionicons name={value ? 'checkbox' : 'square-outline'} size={22} color={highlight ? colors.danger : colors.primary} />
      <Text style={{ flex: 1 }} color={highlight ? colors.danger : undefined}>{label}</Text>
    </Pressable>
  );
}

const LEVEL_TEXT: Record<string, string> = {
  full: 'Cleaned up: noise removed, then polished',
  light: 'Lightly polished: harsh “s” sounds softened, peaks caught, fades',
  none: 'As recorded (loudness levelled only)',
};
const CHOICES = [['auto', 'Automatic'], ['full', 'Clean up'], ['light', 'Light polish'], ['none', 'As recorded']] as const;

// P2-18: what mastering did, why, and the editor's per-story override. Words, pauses, and expression are
// never edited: only steady background noise, harshness, peaks, and dead air at the very ends.
function MasteringChoice({ mastering, busy, disabled, onChoose }: {
  mastering: Review['mastering']; busy: boolean; disabled: boolean; onChoose: (choice: string) => void;
}) {
  const colors = useColors();
  if (!mastering.level) return <Text variant="small" muted>Mastering: not run yet (re-process the audio to analyse it).</Text>;
  const trimmed = (mastering.trimmedStart ?? 0) + (mastering.trimmedEnd ?? 0);
  return (
    <View style={{ gap: space.xs, marginTop: space.sm }}>
      <Text variant="heading">Mastering: {LEVEL_TEXT[mastering.level] ?? mastering.level}</Text>
      {mastering.reason ? <Text variant="small" muted>{mastering.reason}</Text> : null}
      {mastering.fallback ? <Text variant="small" color={colors.accent}>{mastering.fallback}</Text> : null}
      <Text variant="small" muted>
        {[mastering.beforeDb != null && mastering.afterDb != null && mastering.level !== 'none'
          ? `background ${mastering.beforeDb} → ${mastering.afterDb} dB` : null,
          trimmed >= 0.5 ? `${trimmed.toFixed(1)} s of dead air trimmed at the ends` : null].filter(Boolean).join(' · ')}
      </Text>
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: space.sm, alignItems: 'center' }}>
        {CHOICES.map(([value, label]) => (
          <Chip key={value} label={label} selected={mastering.choice === value}
            onPress={() => { if (!busy && !disabled && value !== mastering.choice) onChoose(value); }} />
        ))}
        {busy || disabled ? <Text variant="small" muted>working…</Text> : null}
      </View>
    </View>
  );
}
