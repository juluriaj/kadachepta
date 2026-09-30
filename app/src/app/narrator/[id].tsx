import Ionicons from '@expo/vector-icons/Ionicons';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { router, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { Pressable, ScrollView, View } from 'react-native';

import { Stars } from '@/components/community';
import { StoryRow } from '@/components/stories';
import { Button, ErrorState, Loading, Screen, Text, useColors } from '@/components/ui';
import { api } from '@/lib/api';
import { useI18n } from '@/lib/i18n';
import { useSession } from '@/lib/session';
import { space } from '@/lib/theme';
import type { NarratorPage } from '@/lib/types';

const LANGUAGE_NAMES: Record<string, string> = { 'te-IN': 'తెలుగు', 'hi-IN': 'हिन्दी', 'en-IN': 'English' };

// A narrator's public page (P3-04): who they are, what they've narrated, how families rate the narration.
export default function Narrator() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { t } = useI18n();
  const colors = useColors();
  const { profile, session } = useSession();
  const queryClient = useQueryClient();
  const [busy, setBusy] = useState(false);
  const page = useQuery({ queryKey: ['narrator', id, profile?.id], enabled: !!id && session.authenticated,
    queryFn: () => api<NarratorPage>(`/api/narrators/${id}`) });

  if (page.isLoading) return <Loading />;
  if (page.error || !page.data) return <Screen><ErrorState error={page.error} onRetry={() => void page.refetch()} /></Screen>;
  const n = page.data;

  const toggleFollow = async () => {
    setBusy(true);
    try {
      await api(`/api/narrators/${n.id}/follow`, { method: 'POST', body: { following: !n.following } });
      await queryClient.invalidateQueries({ queryKey: ['narrator', id] });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Screen>
      <ScrollView contentContainerStyle={{ gap: space.lg, paddingVertical: space.lg, maxWidth: 640, width: '100%', alignSelf: 'center' }}>
        <Pressable onPress={() => (router.canGoBack() ? router.back() : router.replace('/'))} accessibilityRole="button"
          accessibilityLabel={t('common.back')} hitSlop={12}>
          <Ionicons name="chevron-back" size={26} color={colors.text} />
        </Pressable>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: space.md }}>
          <View style={{ width: 64, height: 64, borderRadius: 32, backgroundColor: colors.primary, alignItems: 'center',
            justifyContent: 'center' }}>
            <Ionicons name="mic" size={30} color={colors.onPrimary} />
          </View>
          <View style={{ flex: 1, gap: 2 }}>
            <Text variant="title" accessibilityRole="header">{n.name}</Text>
            <Text variant="small" muted>
              {[n.languages.map((code) => LANGUAGE_NAMES[code] ?? code).join(' · '), t('narrator.followers', { n: n.followers })]
                .filter(Boolean).join(' · ')}
            </Text>
          </View>
        </View>
        {n.canFollow ? (
          <View style={{ gap: space.xs }}>
            <Button kind={n.following ? 'secondary' : 'primary'} loading={busy} onPress={() => void toggleFollow()}
              title={n.following ? t('narrator.following') : t('narrator.follow')}
              icon={<Ionicons name={n.following ? 'checkmark' : 'add'} size={18} color={n.following ? colors.text : colors.onPrimary} />} />
            {n.following ? <Text variant="small" muted>{t('narrator.followHint')}</Text> : null}
          </View>
        ) : null}
        {n.biography ? <Text style={{ lineHeight: 24 }}>{n.biography}</Text> : null}
        {n.narration ? (
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: space.sm }}>
            <Text variant="label" muted>{t('narrator.score')}</Text>
            {n.narration.score != null ? (
              <>
                <Stars value={n.narration.score} size={16} label={t('narrator.score')} />
                <Text variant="small">{n.narration.score.toFixed(1)} · {t('rate.count', { n: n.narration.count })}</Text>
              </>
            ) : <Text variant="small" muted>{t('rate.few')}</Text>}
          </View>
        ) : null}
        <Text variant="heading">{t('narrator.stories')}</Text>
        {n.stories.map((story) => <StoryRow key={story.id} story={story} />)}
      </ScrollView>
    </Screen>
  );
}
