import Ionicons from '@expo/vector-icons/Ionicons';
import { useQuery } from '@tanstack/react-query';
import { router } from 'expo-router';
import { useState } from 'react';
import { Pressable, ScrollView, View } from 'react-native';

import { ReviewItem, Stars } from '@/components/community';
import { Button, Card, ErrorState, Field, Loading, Screen, Text, useColors } from '@/components/ui';
import { api } from '@/lib/api';
import { useI18n } from '@/lib/i18n';
import { space } from '@/lib/theme';
import type { Review, Score } from '@/lib/types';

type NarratorReview = Review & { storyId: string; storyTitle: string; story: Score };

// What families say about a narrator's stories, with one reply per review (P3-03, right of reply).
export default function NarratorReviews() {
  const { t } = useI18n();
  const colors = useColors();
  const query = useQuery({ queryKey: ['narrator-reviews'],
    queryFn: () => api<{ narration: Score; items: NarratorReview[] }>('/api/narrator/reviews', { profile: false }) });

  if (query.isLoading) return <Loading />;
  if (query.error || !query.data) return <Screen><ErrorState error={query.error} onRetry={() => void query.refetch()} /></Screen>;
  const { narration, items } = query.data;
  return (
    <Screen>
      <ScrollView contentContainerStyle={{ gap: space.lg, paddingVertical: space.lg, maxWidth: 640, width: '100%', alignSelf: 'center' }}>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: space.sm }}>
          <Pressable onPress={() => (router.canGoBack() ? router.back() : router.replace('/(tabs)/narrate'))}
            accessibilityRole="button" accessibilityLabel={t('common.back')} hitSlop={12}>
            <Ionicons name="chevron-back" size={26} color={colors.text} />
          </Pressable>
          <Text variant="title" accessibilityRole="header">{t('narrate.reviews')}</Text>
        </View>
        <Card>
          <Text variant="heading">{t('narrate.score')}</Text>
          {narration.score != null ? (
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: space.sm }}>
              <Stars value={narration.score} size={20} label={t('narrate.score')} />
              <Text>{narration.score.toFixed(1)} · {t('rate.count', { n: narration.count })}</Text>
            </View>
          ) : <Text muted>{t('rate.few')}</Text>}
        </Card>
        {!items.length ? <Text muted>{t('narrate.reviewsEmpty')}</Text> : null}
        {items.map((review) => <ReviewWithReply key={review.id} review={review} onSaved={() => void query.refetch()} />)}
      </ScrollView>
    </Screen>
  );
}

function ReviewWithReply({ review, onSaved }: { review: NarratorReview; onSaved: () => void }) {
  const { t } = useI18n();
  const colors = useColors();
  const [open, setOpen] = useState(false);
  const [text, setText] = useState(review.reply ?? '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      await api(`/api/narrator/reviews/${review.id}/reply`, { method: 'POST', profile: false, body: { text } });
      setOpen(false);
      onSaved();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setBusy(false);
    }
  };
  return (
    <View style={{ gap: space.xs }}>
      <Text variant="label" color={colors.primary} onPress={() => router.push(`/narrate/submission/${review.storyId}`)}>
        {review.storyTitle}
      </Text>
      <ReviewItem review={review} actions={open ? (
        <View style={{ gap: space.sm }}>
          <Field label={t('narrate.reply')} value={text} onChangeText={setText} multiline maxLength={1000}
            style={{ minHeight: 70, paddingTop: space.md }} />
          <Text variant="small" muted>{t('narrate.replyHint')}</Text>
          {error ? <Text variant="small" color={colors.danger}>{error}</Text> : null}
          <Button title={t('narrate.replySend')} loading={busy} onPress={() => void save()} />
        </View>
      ) : <Button kind="ghost" title={t('narrate.reply')} onPress={() => setOpen(true)} />} />
    </View>
  );
}
