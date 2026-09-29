import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { ScrollView, View } from 'react-native';

import { Button, Card, Cover, ErrorState, Loading, Text, useColors } from '@/components/ui';
import { api } from '@/lib/api';
import { space } from '@/lib/theme';

type StoryRef = { id: string; title: string; artworkUrl: string | null };
type HeldReview = { id: number; text: string; author: string; createdAt: string; status: string; reports: number;
  reportReasons: string[]; waitingForCheck: boolean; story: StoryRef;
  moderation: { verdict?: string; reasons?: string[]; note?: string; by?: string; heldForReports?: number } };
type RatingAlert = { id: number; windowStart: string; createdAt: string; story: StoryRef;
  details: { recent: number; usualPer48h: number; recentMean: number; beforeMean: number | null; newAccounts: number } };

// Reviews the automatic check held or listeners reported, and bursts of ratings that look like a raid.
export default function Moderation() {
  const colors = useColors();
  const [error, setError] = useState<string | null>(null);
  const query = useQuery({ queryKey: ['studio-moderation'],
    queryFn: () => api<{ reviews: HeldReview[]; ratingFlags: RatingAlert[] }>('/api/studio/moderation', { profile: false }) });

  const act = async (path: string, body: unknown) => {
    setError(null);
    try {
      await api(path, { method: 'POST', profile: false, body });
      await query.refetch();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    }
  };

  if (query.isLoading) return <Loading />;
  if (query.error || !query.data) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  const { reviews, ratingFlags } = query.data;
  return (
    <ScrollView contentContainerStyle={{ padding: space.xl, gap: space.md, maxWidth: 1100, width: '100%', alignSelf: 'center' }}>
      <Text variant="title">Moderation</Text>
      <Text muted>
        Reviews appear here when the automatic check isn’t sure, when it found personal details, when two families
        report one, or when the check hasn’t run for an hour (is the AI worker running?). Children never see reviews.
      </Text>
      {error ? <Text color={colors.danger}>{error}</Text> : null}

      <Text variant="heading">Rating alerts ({ratingFlags.length})</Text>
      {!ratingFlags.length ? <Text variant="small" muted>No unusual bursts of ratings.</Text> : null}
      {ratingFlags.map((flag) => (
        <Card key={flag.id}>
          <View style={{ flexDirection: 'row', gap: space.md, alignItems: 'center', flexWrap: 'wrap' }}>
            <Cover id={flag.story.id} title={flag.story.title} artworkUrl={flag.story.artworkUrl} size={48} rounded={8} />
            <View style={{ flex: 1, minWidth: 240, gap: 2 }}>
              <Text variant="heading">{flag.story.title}</Text>
              <Text variant="small">
                {flag.details.recent} ratings in 48 hours (usually {flag.details.usualPer48h}), average {flag.details.recentMean}
                {flag.details.beforeMean != null ? ` against ${flag.details.beforeMean} before` : ''}; {flag.details.newAccounts} from
                new or barely-listening accounts.
              </Text>
              <Text variant="small" muted>These ratings are left out of the story’s score until you decide.</Text>
            </View>
            <Button kind="secondary" title="Genuine: count them" onPress={() => void act(`/api/studio/rating-flags/${flag.id}`, { decision: 'clear' })} />
            <Button kind="danger" title="Raid: leave them out" onPress={() => void act(`/api/studio/rating-flags/${flag.id}`, { decision: 'confirm' })} />
          </View>
        </Card>
      ))}

      <Text variant="heading">Reviews ({reviews.length})</Text>
      {!reviews.length ? <Text variant="small" muted>Nothing waiting.</Text> : null}
      {reviews.map((review) => (
        <Card key={review.id}>
          <View style={{ flexDirection: 'row', gap: space.md, flexWrap: 'wrap' }}>
            <View style={{ flex: 1, minWidth: 280, gap: space.xs }}>
              <Text variant="small" muted>{review.story.title} · {review.author} · {new Date(review.createdAt).toLocaleString()}</Text>
              <Text>{review.text}</Text>
              <Text variant="small" color={colors.accent}>
                {[review.waitingForCheck ? 'Automatic check hasn’t run yet' : null,
                  review.moderation.verdict ? `Check: ${review.moderation.verdict} (${review.moderation.by ?? ''})` : null,
                  review.moderation.reasons?.length ? review.moderation.reasons.join(', ') : null,
                  review.moderation.note || null,
                  review.reports ? `${review.reports} report${review.reports > 1 ? 's' : ''}: ${review.reportReasons.join(', ')}` : null]
                  .filter(Boolean).join(' · ')}
              </Text>
            </View>
            <View style={{ gap: space.sm, justifyContent: 'center' }}>
              <Button title="Publish" onPress={() => void act(`/api/studio/reviews/${review.id}`, { decision: 'publish' })} />
              <Button kind="secondary" title="Hide" onPress={() => void act(`/api/studio/reviews/${review.id}`, { decision: 'hide' })} />
              <Button kind="ghost" title="Reject" onPress={() => void act(`/api/studio/reviews/${review.id}`, { decision: 'reject' })} />
            </View>
          </View>
        </Card>
      ))}
    </ScrollView>
  );
}
