import Ionicons from '@expo/vector-icons/Ionicons';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { router, useLocalSearchParams } from 'expo-router';
import { useEffect, useState } from 'react';
import { Pressable, ScrollView, View } from 'react-native';

import { minutes, Shelf } from '@/components/stories';
import { Button, Chip, Cover, ErrorState, Loading, Screen, Text, useColors } from '@/components/ui';
import { api, mediaUrl } from '@/lib/api';
import { downloadStory, downloadsSupported, localUri } from '@/lib/downloads';
import { formatClock, useI18n, type TranslationKey } from '@/lib/i18n';
import { usePlayer } from '@/lib/player/PlayerProvider';
import { resumePosition } from '@/lib/player/logic';
import { useSession } from '@/lib/session';
import { space } from '@/lib/theme';
import type { StoryDetail } from '@/lib/types';

export default function Story() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { t } = useI18n();
  const colors = useColors();
  const player = usePlayer();
  const queryClient = useQueryClient();
  const { profile } = useSession();
  const [downloaded, setDownloaded] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const story = useQuery({
    queryKey: ['story', id, profile?.id], enabled: !!id && !!profile,
    queryFn: () => api<StoryDetail>(`/api/stories/${id}`),
  });

  useEffect(() => {
    if (id) void localUri(id).then((uri) => setDownloaded(!!uri));
  }, [id]);

  if (story.isLoading) return <Loading />;
  if (story.error || !story.data) {
    return <Screen><Back /><ErrorState error={story.error ?? t('story.notAvailable')} onRetry={() => void story.refetch()} /></Screen>;
  }
  const s = story.data;
  const resume = resumePosition(s.progress, s.duration);
  const isCurrent = player.story?.id === s.id;

  const toggleFavorite = async () => {
    await api('/api/me/favorites', { method: 'POST', body: { assetId: s.id, saved: !s.favorite } });
    await queryClient.invalidateQueries({ queryKey: ['story', id] });
    void queryClient.invalidateQueries({ queryKey: ['home'] });
    void queryClient.invalidateQueries({ queryKey: ['catalog'] });
  };

  const download = async () => {
    setDownloading(true);
    setNote(null);
    try {
      await downloadStory(s, player.dataSaver);
      setDownloaded(true);
    } catch (failure) {
      setNote(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setDownloading(false);
    }
  };

  return (
    <Screen padded={false}>
      <ScrollView contentContainerStyle={{ gap: space.xl, paddingBottom: space.xxl }}>
        <View style={{ paddingHorizontal: space.lg }}><Back /></View>
        <View style={{ alignItems: 'center', gap: space.lg, paddingHorizontal: space.lg }}>
          <Cover id={s.id} title={s.title} artworkUrl={mediaUrl(s.artworkUrl)} size={240} />
          <Text variant="display" style={{ textAlign: 'center' }} accessibilityRole="header">{s.title}</Text>
          <Text muted style={{ textAlign: 'center' }}>
            {t('story.narratedBy', { name: s.narrator })} · {t('common.min', { n: minutes(s.duration) })}
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
          <View style={{ flexDirection: 'row', gap: space.md }}>
            <Button title={s.favorite ? t('story.removeFavorite') : t('story.addFavorite')} kind="secondary" style={{ flex: 1 }}
              icon={<Ionicons name={s.favorite ? 'heart' : 'heart-outline'} size={18} color={s.favorite ? colors.accent : colors.text} />}
              onPress={() => void toggleFavorite()} />
            {downloadsSupported ? (
              <Button title={downloaded ? t('story.downloaded') : downloading ? t('story.downloading') : t('story.download')}
                kind="secondary" style={{ flex: 1 }} loading={downloading} disabled={downloaded}
                icon={<Ionicons name={downloaded ? 'checkmark-circle' : 'download-outline'} size={18} color={colors.text} />}
                onPress={() => void download()} />
            ) : null}
          </View>
          {note ? <Text variant="small" color={colors.danger}>{note}</Text> : null}
        </View>

        {s.teaser?.long || s.teaser?.short ? (
          <View style={{ paddingHorizontal: space.lg, gap: space.sm }}>
            <Text style={{ fontSize: 17, lineHeight: 28 }}>{s.teaser.long || s.teaser.short}</Text>
          </View>
        ) : null}

        {s.moments?.length ? (
          <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: space.sm, paddingHorizontal: space.lg }}>
            {s.moments.map((m) => <Chip key={m} label={t(`moment.${m}` as TranslationKey)} />)}
          </View>
        ) : null}

        {s.metadata.moralTakeaway ? (
          <View style={{ marginHorizontal: space.lg, padding: space.lg, borderRadius: 16, backgroundColor: colors.surfaceAlt, gap: space.xs }}>
            <Text variant="label" muted>{t('story.moral')}</Text>
            <Text>{s.metadata.moralTakeaway}</Text>
          </View>
        ) : null}

        {s.upNext.length ? <Shelf title={t('story.upNext')} items={s.upNext} /> : null}
        {s.moreFromNarrator.length ? <Shelf title={t('story.moreFromNarrator')} items={s.moreFromNarrator} /> : null}
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
