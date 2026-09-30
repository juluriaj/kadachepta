import Ionicons from '@expo/vector-icons/Ionicons';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Pressable, View } from 'react-native';

import { Button, Card, Chip, Field, Text, useColors } from '@/components/ui';
import { api } from '@/lib/api';
import { useI18n, type TranslationKey } from '@/lib/i18n';
import { getEngine } from '@/lib/player/engine';
import { space, touch } from '@/lib/theme';
import type { Community, Reaction, Review, Score } from '@/lib/types';

const REACTIONS: { id: Reaction; emoji: string }[] = [
  { id: 'love', emoji: '😍' }, { id: 'like', emoji: '🙂' }, { id: 'okay', emoji: '😐' }, { id: 'sleepy', emoji: '😴' },
];
const REPORT_REASONS = ['inappropriate', 'personal-info', 'spam', 'unkind', 'other'] as const;

export function useCommunity(storyId: string | undefined) {
  return useQuery({ queryKey: ['community', storyId], enabled: !!storyId,
    queryFn: () => api<Community>(`/api/stories/${storyId}/community`) });
}

// Sends the pending listening time first, so a rating right at the end of a story counts that listening.
async function send(storyId: string, path: string, body: unknown, method: 'POST' | 'DELETE' = 'POST') {
  await getEngine().flushNow();
  return api<Community>(`/api/stories/${storyId}/${path}`, { method, body });
}

export function Stars({ value, onChange, size = 30, label }: { value: number | null; onChange?: (n: number) => void;
  size?: number; label: string }) {
  const { t } = useI18n();
  const colors = useColors();
  return (
    <View style={{ flexDirection: 'row', gap: 2 }} accessibilityRole={onChange ? 'adjustable' : 'image'}
      accessibilityLabel={`${label}: ${value ? t('rate.stars', { n: value }) : '—'}`}>
      {[1, 2, 3, 4, 5].map((n) => {
        const icon = (value ?? 0) >= n ? 'star' : (value ?? 0) >= n - 0.5 ? 'star-half' : 'star-outline';
        const star = <Ionicons name={icon} size={size} color={colors.accent} />;
        return onChange ? (
          <Pressable key={n} onPress={() => onChange(n)} accessibilityRole="button" accessibilityLabel={t('rate.stars', { n })}
            style={{ minWidth: Math.max(size + 6, touch), minHeight: touch, alignItems: 'center', justifyContent: 'center' }}>
            {star}
          </Pressable>
        ) : <View key={n}>{star}</View>;
      })}
    </View>
  );
}

function ScoreLine({ label, score }: { label: string; score?: Score }) {
  const { t } = useI18n();
  if (!score) return null;
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', gap: space.sm, flexWrap: 'wrap' }}>
      <Text variant="label" muted style={{ minWidth: 90 }}>{label}</Text>
      {score.score != null ? (
        <>
          <Stars value={score.score} size={16} label={label} />
          <Text variant="small">{score.score.toFixed(1)} · {t('rate.count', { n: score.count })}</Text>
        </>
      ) : <Text variant="small" muted>{t('rate.few')}</Text>}
    </View>
  );
}

// Rating for the listener: stars (story and narration) for grown-ups, an emoji reaction for children.
export function RatingCard({ storyId, compact, onDismiss }: { storyId: string; compact?: boolean; onDismiss?: () => void }) {
  const { t } = useI18n();
  const colors = useColors();
  const queryClient = useQueryClient();
  const community = useCommunity(storyId);
  const [error, setError] = useState<string | null>(null);
  const data = community.data;
  if (!data || data.ownWork) return null;

  const rate = async (body: Record<string, unknown>) => {
    setError(null);
    try {
      queryClient.setQueryData(['community', storyId], await send(storyId, 'rating', body));
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    }
  };

  if (!data.eligible) {
    return compact ? null : <Text variant="small" muted>{t('rate.listenFirst')}</Text>;
  }
  const mine = data.mine;
  const done = data.kind === 'child' ? !!mine?.reaction : !!(mine?.story && mine?.narration);
  return (
    <Card style={compact ? { gap: space.sm } : undefined}>
      {data.kind === 'child' ? (
        <>
          <Text variant="heading">{t('rate.kids')}</Text>
          <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: space.sm }}>
            {REACTIONS.map((reaction) => (
              <Pressable key={reaction.id} onPress={() => void rate({ reaction: reaction.id })} accessibilityRole="button"
                accessibilityLabel={t(`reaction.${reaction.id}` as TranslationKey)}
                accessibilityState={{ selected: mine?.reaction === reaction.id }}
                style={{ padding: space.sm, borderRadius: 16, borderWidth: 2, alignItems: 'center', minWidth: 72,
                  borderColor: mine?.reaction === reaction.id ? colors.primary : colors.border }}>
                <Text style={{ fontSize: 34, lineHeight: 42 }}>{reaction.emoji}</Text>
                <Text variant="small">{t(`reaction.${reaction.id}` as TranslationKey)}</Text>
              </Pressable>
            ))}
          </View>
        </>
      ) : (
        <>
          <Text variant="heading">{t('rate.title')}</Text>
          <Stars value={mine?.story ?? null} onChange={(n) => void rate({ story: n })} label={t('rate.storyLabel')} />
          <Text variant="heading">{t('rate.narration')}</Text>
          <Stars value={mine?.narration ?? null} onChange={(n) => void rate({ narration: n })} label={t('rate.narrationLabel')} />
        </>
      )}
      {done ? <Text variant="small" color={colors.success}>{t('rate.thanks')}</Text> : null}
      {error ? <Text variant="small" color={colors.danger}>{error}</Text> : null}
      {onDismiss && !done ? <Button kind="ghost" title={t('rate.later')} onPress={onDismiss} /> : null}
    </Card>
  );
}

// Near the top of the story page, right under Play: rate it (once most of it was heard) and see the scores.
// It used to sit at the bottom of the page, below the shelves, where few listeners scrolled.
export function StoryRatings({ storyId }: { storyId: string }) {
  const { t } = useI18n();
  const community = useCommunity(storyId);
  const data = community.data;
  if (!data) return null;
  const reactions = Object.entries(data.reactions).filter(([, n]) => n);
  return (
    <View style={{ gap: space.md }}>
      <RatingCard storyId={storyId} />
      {data.kind === 'adult' ? (
        <View style={{ gap: space.sm }}>
          <ScoreLine label={t('rate.storyLabel')} score={data.story} />
          <ScoreLine label={t('rate.narrationLabel')} score={data.narration} />
          {reactions.length ? (
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: space.sm, flexWrap: 'wrap' }}>
              <Text variant="label" muted style={{ minWidth: 90 }}>{t('rate.kidsSaid')}</Text>
              {reactions.map(([id, n]) => (
                <Text key={id} variant="small">{REACTIONS.find((r) => r.id === id)?.emoji} {n}</Text>
              ))}
            </View>
          ) : null}
        </View>
      ) : null}
    </View>
  );
}

// Reviews, lower on the story page (grown-ups only; children never see reviews).
export function StoryReviews({ storyId }: { storyId: string }) {
  const colors = useColors();
  const community = useCommunity(storyId);
  const data = community.data;
  if (community.error) return <Text variant="small" color={colors.danger}>{String(community.error)}</Text>;
  if (!data || data.kind !== 'adult') return null;
  return <Reviews storyId={storyId} data={data} />;
}

function Reviews({ storyId, data }: { storyId: string; data: Community }) {
  const { t } = useI18n();
  const colors = useColors();
  const queryClient = useQueryClient();
  const mine = data.myReview;
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(mine?.text ?? '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (method: 'POST' | 'DELETE') => {
    setBusy(true);
    setError(null);
    try {
      queryClient.setQueryData(['community', storyId], await send(storyId, 'review', method === 'POST' ? { text } : undefined, method));
      setEditing(false);
      if (method === 'DELETE') setText('');
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setBusy(false);
    }
  };
  const others = (data.reviews ?? []).filter((review) => !review.mine);
  const statusNote = mine?.status && mine.status !== 'published' ? t(`review.${mine.status}` as TranslationKey) : null;

  return (
    <View style={{ gap: space.md }}>
      <Text variant="title" style={{ fontSize: 19 }}>{t('review.title')}</Text>
      {mine && !editing ? (
        <ReviewItem review={mine} note={statusNote} actions={
          <View style={{ flexDirection: 'row', gap: space.sm }}>
            <Button kind="ghost" title={t('review.edit')} onPress={() => { setText(mine.text); setEditing(true); }} />
            <Button kind="ghost" title={t('review.delete')} disabled={busy} onPress={() => void submit('DELETE')} />
          </View>} />
      ) : null}
      {data.eligible && (editing || !mine) ? (
        <View style={{ gap: space.sm }}>
          <Field label={mine ? t('review.edit') : t('review.write')} value={text} onChangeText={setText} multiline maxLength={1000}
            placeholder={t('review.placeholder')} style={{ minHeight: 90, paddingTop: space.md }} />
          <Button title={t('review.send')} loading={busy} disabled={text.trim().length < 3} onPress={() => void submit('POST')} />
        </View>
      ) : null}
      {error ? <Text variant="small" color={colors.danger}>{error}</Text> : null}
      {others.map((review) => <ReviewItem key={review.id} review={review} reportable />)}
      {!others.length && !mine ? <Text variant="small" muted>{t('review.none')}</Text> : null}
    </View>
  );
}

export function ReviewItem({ review, note, actions, reportable }: { review: Review; note?: string | null; actions?: React.ReactNode;
  reportable?: boolean }) {
  const { t } = useI18n();
  const colors = useColors();
  const [reporting, setReporting] = useState(false);
  const [reported, setReported] = useState(false);
  const report = async (reason: string) => {
    await api(`/api/reviews/${review.id}/report`, { method: 'POST', body: { reason } }).catch(() => {});
    setReported(true);
    setReporting(false);
  };
  return (
    <View style={{ gap: space.xs, paddingVertical: space.sm, borderTopWidth: 1, borderColor: colors.border }}>
      <Text variant="label">{review.mine ? t('review.you') : review.author} · <Text variant="small" muted>
        {new Date(review.createdAt).toLocaleDateString()}</Text></Text>
      <Text>{review.text}</Text>
      {note ? <Text variant="small" color={colors.accent}>{note}</Text> : null}
      {review.reply ? (
        <View style={{ marginLeft: space.lg, paddingLeft: space.md, borderLeftWidth: 2, borderColor: colors.primary, gap: 2 }}>
          <Text variant="label" color={colors.primary}>{t('review.reply')}</Text>
          <Text variant="small">{review.reply}</Text>
        </View>
      ) : null}
      {actions}
      {reportable && !reported ? (
        reporting ? (
          <View style={{ gap: space.xs }}>
            <Text variant="small" muted>{t('review.reportWhy')}</Text>
            <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: space.xs }}>
              {REPORT_REASONS.map((reason) => (
                <Chip key={reason} label={t(`report.${reason}` as TranslationKey)} onPress={() => void report(reason)} />
              ))}
            </View>
          </View>
        ) : (
          <Pressable onPress={() => setReporting(true)} accessibilityRole="button" hitSlop={8} style={{ alignSelf: 'flex-start' }}>
            <Text variant="small" muted>{t('review.report')}</Text>
          </Pressable>
        )
      ) : null}
      {reported ? <Text variant="small" muted>{t('review.reported')}</Text> : null}
    </View>
  );
}

// Conversation starters for parents after a story (P3-07).
export function TalkAboutIt({ prompts }: { prompts: Record<string, string[]> | null }) {
  const { t, language } = useI18n();
  const colors = useColors();
  const questions = prompts?.[`${language}-IN`]?.length ? prompts[`${language}-IN`] : prompts?.['en-IN'] ?? prompts?.['te-IN'];
  if (!questions?.length) return null;
  return (
    <View style={{ padding: space.lg, borderRadius: 16, backgroundColor: colors.surfaceAlt, gap: space.sm }}>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: space.sm }}>
        <Ionicons name="chatbubbles-outline" size={20} color={colors.primary} />
        <Text variant="heading">{t('story.talk')}</Text>
      </View>
      <Text variant="small" muted>{t('story.talkHint')}</Text>
      {questions.map((question) => <Text key={question}>• {question}</Text>)}
    </View>
  );
}
