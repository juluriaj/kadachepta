import Ionicons from '@expo/vector-icons/Ionicons';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { router, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { Pressable, ScrollView, View } from 'react-native';

import { StoryRatings, StoryReviews, TalkAboutIt } from '@/components/community';
import { AddToPlaylist } from '@/components/playlists';
import { DownloadButton, minutes, NarratedBy, Shelf } from '@/components/stories';
import { Button, Chip, Cover, ErrorState, Loading, Screen, Text, useColors } from '@/components/ui';
import { api, mediaUrl } from '@/lib/api';
import { formatClock, useI18n, type TranslationKey } from '@/lib/i18n';
import { usePlayer } from '@/lib/player/PlayerProvider';
import { resumePosition } from '@/lib/player/logic';
import { useSession } from '@/lib/session';
import { space } from '@/lib/theme';
import type { StoryDetail } from '@/lib/types';

export default function Story() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { t, title, language } = useI18n();
  const colors = useColors();
  const player = usePlayer();
  const queryClient = useQueryClient();
  const { profile } = useSession();
  const [note, setNote] = useState<string | null>(null);
  const story = useQuery({
    queryKey: ['story', id, profile?.id], enabled: !!id && !!profile,
    queryFn: () => api<StoryDetail>(`/api/stories/${id}`),
  });

  if (story.isLoading) return <Loading />;
  if (story.error || !story.data) {
    return <Screen><Back /><ErrorState error={story.error ?? t('story.notAvailable')} onRetry={() => void story.refetch()} /></Screen>;
  }
  const s = story.data;
  // In the app language when there is one; otherwise the listening-language teaser and the English moral.
  const teaser = s.teasers?.[`${language}-IN`] ?? s.teaser;
  const moral = s.morals?.[`${language}-IN`] ?? s.metadata.moralTakeaway;
  const resume = resumePosition(s.progress, s.duration);
  const isCurrent = player.story?.id === s.id;

  const toggleFavorite = async () => {
    await api('/api/me/favorites', { method: 'POST', body: { assetId: s.id, saved: !s.favorite } });
    await queryClient.invalidateQueries({ queryKey: ['story', id] });
    void queryClient.invalidateQueries({ queryKey: ['home'] });
    void queryClient.invalidateQueries({ queryKey: ['catalog'] });
  };

  return (
    <Screen padded={false}>
      <ScrollView contentContainerStyle={{ gap: space.xl, paddingBottom: space.xxl }}>
        <View style={{ paddingHorizontal: space.lg }}><Back /></View>
        <View style={{ alignItems: 'center', gap: space.lg, paddingHorizontal: space.lg }}>
          <Cover id={s.id} title={title(s)} artworkUrl={mediaUrl(s.artworkUrl)} size={240} />
          <Text variant="display" style={{ textAlign: 'center' }} accessibilityRole="header">{title(s)}</Text>
          <Text muted style={{ textAlign: 'center' }}>
            <NarratedBy story={s} /> · {t('common.min', { n: minutes(s.duration) })}
            {s.metadata.audienceAgeRange ? ` · ${s.metadata.audienceAgeRange}` : ''}
          </Text>
        </View>

        <View style={{ paddingHorizontal: space.lg, gap: space.md }}>
          <Button
            title={isCurrent && player.playing ? t('player.pause')
              : resume ? t('story.resume', { time: formatClock(resume) })
                : s.progress?.completed ? t('story.playAgain') : t('story.play')}
            icon={<Ionicons name={isCurrent && player.playing ? 'pause' : 'play'} size={20} color={colors.onPrimary} />}
            onPress={() => {
              if (isCurrent) player.toggle();
              else {
                void player.play(s, { queue: s.upNext, autoContinue: false });
                router.push('/player');
              }
            }}
          />
          {player.story && !isCurrent ? (
            player.queue.some((item) => item.id === s.id) ? (
              <Button kind="secondary" title={t('queue.inQueue')} onPress={() => player.removeFromQueue(s.id)}
                accessibilityHint={t('queue.remove')}
                icon={<Ionicons name="checkmark-circle" size={18} color={colors.success} />} />
            ) : (
              <View style={{ flexDirection: 'row', gap: space.md }}>
                <Button kind="secondary" title={t('queue.playNext')} style={{ flex: 1 }} onPress={() => player.enqueue(s, 'next')}
                  icon={<Ionicons name="play-skip-forward-outline" size={18} color={colors.text} />} />
                <Button kind="secondary" title={t('queue.add')} style={{ flex: 1 }} onPress={() => player.enqueue(s, 'last')}
                  icon={<Ionicons name="list-outline" size={18} color={colors.text} />} />
              </View>
            )
          ) : null}
          <View style={{ flexDirection: 'row', gap: space.md }}>
            <Button title={s.favorite ? t('story.removeFavorite') : t('story.addFavorite')} kind="secondary" style={{ flex: 1 }}
              icon={<Ionicons name={s.favorite ? 'heart' : 'heart-outline'} size={18} color={s.favorite ? colors.accent : colors.text} />}
              onPress={() => void toggleFavorite()} />
            <DownloadButton story={s} onError={setNote} style={{ flex: 1 }} />
          </View>
          <AddToPlaylist storyId={s.id} />
          {note ? <Text variant="small" color={colors.danger}>{note}</Text> : null}
          <StoryRatings storyId={s.id} />
        </View>

        {teaser?.long || teaser?.short ? (
          <View style={{ paddingHorizontal: space.lg, gap: space.sm }}>
            <Text style={{ fontSize: 17, lineHeight: 28 }}>{teaser.long || teaser.short}</Text>
          </View>
        ) : null}

        {s.moments?.length ? (
          <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: space.sm, paddingHorizontal: space.lg }}>
            {s.moments.map((m) => <Chip key={m} label={t(`moment.${m}` as TranslationKey)} />)}
          </View>
        ) : null}

        {moral ? (
          <View style={{ marginHorizontal: space.lg, padding: space.lg, borderRadius: 16, backgroundColor: colors.surfaceAlt, gap: space.xs }}>
            <Text variant="label" muted>{t('story.moral')}</Text>
            <Text>{moral}</Text>
          </View>
        ) : null}

        {s.prompts ? <View style={{ paddingHorizontal: space.lg }}><TalkAboutIt prompts={s.prompts} /></View> : null}

        {s.upNext.length ? <Shelf title={t('story.upNext')} items={s.upNext} /> : null}
        {s.moreLikeThis.length ? <Shelf title={t('story.moreLikeThis')} items={s.moreLikeThis} /> : null}
        {s.moreFromNarrator.length ? <Shelf title={t('story.moreFromNarrator')} items={s.moreFromNarrator} /> : null}

        <View style={{ paddingHorizontal: space.lg }}><StoryReviews storyId={s.id} /></View>
      </ScrollView>
    </Screen>
  );
}

function Back() {
  const { t } = useI18n();
  const colors = useColors();
  return (
    <Pressable onPress={() => (router.canGoBack() ? router.back() : router.replace('/'))} accessibilityRole="button"
      accessibilityLabel={t('common.back')} hitSlop={12} style={{ paddingVertical: space.md, alignSelf: 'flex-start' }}>
      <Ionicons name="chevron-back" size={26} color={colors.text} />
    </Pressable>
  );
}
