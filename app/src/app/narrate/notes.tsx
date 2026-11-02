import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Alert, Platform, ScrollView, Switch, View } from 'react-native';

import { Button, Card, ErrorState, Field, Loading, Screen, Text, useColors } from '@/components/ui';
import { api } from '@/lib/api';
import { useI18n } from '@/lib/i18n';
import { space } from '@/lib/theme';
import type { ReceivedNote } from '@/lib/types';

type Inbox = { accepting: boolean; blockedFamilies: number; items: ReceivedNote[] };

function confirmAction(message: string): Promise<boolean> {
  if (Platform.OS === 'web') return Promise.resolve(window.confirm(message));
  return new Promise((resolve) => Alert.alert('', message, [
    { text: 'Cancel', style: 'cancel', onPress: () => resolve(false) },
    { text: 'OK', style: 'destructive', onPress: () => resolve(true) },
  ]));
}

// Thank-you notes from families (P3-12): only notes our checks passed arrive here. Reply, block, or report one.
export default function Notes() {
  const { t } = useI18n();
  const colors = useColors();
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const inbox = useQuery({ queryKey: ['narrator-notes'], queryFn: () => api<Inbox>('/api/narrator/notes', { profile: false }) });

  const act = async (path: string, body?: unknown) => {
    setError(null);
    try {
      queryClient.setQueryData(['narrator-notes'], await api<Inbox>(path, { method: 'POST', profile: false, body: body ?? {} }));
      void queryClient.invalidateQueries({ queryKey: ['narrator-home'] });
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    }
  };

  if (inbox.isLoading) return <Loading />;
  if (inbox.error || !inbox.data) return <Screen back><ErrorState error={inbox.error} onRetry={() => void inbox.refetch()} /></Screen>;
  const data = inbox.data;
  return (
    <Screen back>
      <ScrollView contentContainerStyle={{ gap: space.lg, paddingVertical: space.lg, maxWidth: 640, width: '100%', alignSelf: 'center' }}
        keyboardShouldPersistTaps="handled">
        <Text variant="title" accessibilityRole="header">{t('narrate.notes')}</Text>
        <Card>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: space.md }}>
            <View style={{ flex: 1, gap: 2 }}>
              <Text variant="heading">{t('narrate.notesAccept')}</Text>
              <Text variant="small" muted>{t('narrate.notesAcceptHint')}</Text>
            </View>
            <Switch value={data.accepting} accessibilityLabel={t('narrate.notesAccept')}
              onValueChange={(accepting) => void act('/api/narrator/notes/settings', { accepting })} />
          </View>
          {data.blockedFamilies ? <Text variant="small" muted>{t('narrate.notesBlocked', { n: data.blockedFamilies })}</Text> : null}
        </Card>
        {error ? <Text color={colors.danger}>{error}</Text> : null}
        {!data.items.length ? <Text muted>{t('narrate.notesEmpty')}</Text> : null}
        {data.items.map((note) => <NoteCard key={note.id} note={note} act={act} />)}
      </ScrollView>
    </Screen>
  );
}

function NoteCard({ note, act }: { note: ReceivedNote; act: (path: string, body?: unknown) => Promise<void> }) {
  const { t } = useI18n();
  const colors = useColors();
  const [reply, setReply] = useState<string | null>(null);
  return (
    <Card style={{ gap: space.sm }}>
      <Text>{note.text}</Text>
      <Text variant="small" muted>
        {note.author} · {new Date(note.createdAt).toLocaleDateString()}
        {note.storyTitle ? ` · ${t('narrate.notesAbout', { title: note.storyTitle })}` : ''}
      </Text>
      {note.reply && reply === null ? (
        <View style={{ paddingLeft: space.md, borderLeftWidth: 2, borderColor: colors.primary }}>
          <Text variant="label" muted>{t('narrate.notesYourReply')}</Text>
          <Text>{note.reply}</Text>
        </View>
      ) : null}
      {reply !== null ? (
        <>
          <Field label={t('narrate.notesYourReply')} value={reply} onChangeText={setReply} multiline maxLength={1000}
            style={{ minHeight: 80, paddingTop: space.md, textAlignVertical: 'top' }} />
          <View style={{ flexDirection: 'row', gap: space.sm }}>
            <Button title={t('common.save')} disabled={!reply.trim()}
              onPress={() => void act(`/api/narrator/notes/${note.id}/reply`, { text: reply.trim() }).then(() => setReply(null))} />
            <Button kind="ghost" title={t('common.cancel')} onPress={() => setReply(null)} />
          </View>
        </>
      ) : (
        <View style={{ flexDirection: 'row', gap: space.sm, flexWrap: 'wrap' }}>
          <Button kind="secondary" title={t('narrate.notesReply')} onPress={() => setReply(note.reply ?? '')} />
          <Button kind="ghost" title={t('narrate.notesReport')} onPress={() => void act(`/api/narrator/notes/${note.id}/report`)} />
          <Button kind="ghost" title={t('narrate.notesBlock')} onPress={() => void confirmAction(t('narrate.notesBlockConfirm'))
            .then((ok) => { if (ok) void act(`/api/narrator/notes/${note.id}/block`); })} />
        </View>
      )}
    </Card>
  );
}
