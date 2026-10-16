import { useQuery } from '@tanstack/react-query';
import * as DocumentPicker from 'expo-document-picker';
import { useState } from 'react';
import { ScrollView, View } from 'react-native';

import { Button, Card, Chip, Cover, ErrorState, Field, Loading, Text, useColors } from '@/components/ui';
import { api, apiSendFile } from '@/lib/api';
import { fontFor, space } from '@/lib/theme';

type BookCover = { url: string | null; kind: 'book-cover' | 'own-cover' | null; source: string | null;
  updatedAt: string | null; pending: boolean; title: string | null };
type Book = { id: number; title: string; language: string; chapters: number; published: number; withdrawn: number;
  cover: BookCover; withdrawnAt: string | null; withdrawnReason: string | null };

const KIND_LABEL = { 'book-cover': 'Printed book cover', 'own-cover': 'Our own cover' } as const;

// Audiobooks: the cover every chapter shows, where it came from, and taking a book down. Claims are handled as
// they come: swap a claimed cover for our own, or withdraw every chapter of a claimed book at once.
export default function Books() {
  const [search, setSearch] = useState('');
  const query = useQuery({
    queryKey: ['studio-books'],
    queryFn: () => api<{ items: Book[] }>('/api/studio/series', { profile: false }),
    refetchInterval: (q) => (q.state.data?.items.some((book) => book.cover.pending) ? 8_000 : false),
  });

  if (query.isLoading) return <Loading />;
  if (query.error) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  const items = query.data!.items.filter((book) => book.title.toLowerCase().includes(search.trim().toLowerCase()));

  return (
    <ScrollView contentContainerStyle={{ padding: space.xl, gap: space.md, maxWidth: 1100, width: '100%', alignSelf: 'center' }}>
      <Text variant="title">Books</Text>
      <Text muted>
        A book’s cover stands for every chapter. Upload the printed book’s cover and say where it came from, or make
        our own (an illustration in the house style with the Telugu title). If a cover is claimed, make our own to
        replace it. If the book itself is claimed, take it down: every chapter leaves the app until you restore it.
      </Text>
      <Field label="Find a book" value={search} onChangeText={setSearch} placeholder="Barister Parvateesam" />
      {items.map((book) => <BookRow key={book.id} book={book} onChanged={() => void query.refetch()} />)}
      {!items.length ? <Text muted>No books match.</Text> : null}
    </ScrollView>
  );
}

function BookRow({ book, onChanged }: { book: Book; onChanged: () => void }) {
  const colors = useColors();
  const [source, setSource] = useState(book.cover.source ?? '');
  const [coverTitle, setCoverTitle] = useState(book.cover.title ?? '');
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const run = async (label: string, action: () => Promise<unknown>, done?: string) => {
    setBusy(label);
    setMessage(null);
    try {
      await action();
      if (done) setMessage(done);
      onChanged();
    } catch (failure) {
      setMessage(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setBusy(null);
    }
  };

  const upload = () => run('upload', async () => {
    if (source.trim().length < 3) throw new Error('Say where the cover is from first (for example "Visalandhra 1982 edition").');
    const result = await DocumentPicker.getDocumentAsync({ type: ['image/jpeg', 'image/png', 'image/webp'], multiple: false });
    if (result.canceled || !result.assets?.length) return;
    const picked = result.assets[0];
    const file = (picked as { file?: Blob }).file ?? await (await fetch(picked.uri)).blob();
    await apiSendFile(`/api/studio/series/${book.id}/cover?source=${encodeURIComponent(source.trim())}`, file,
      picked.mimeType ?? file.type ?? 'image/jpeg');
  }, 'Cover saved. Every chapter shows it now.');

  const patch = (body: Record<string, string>, done: string) => run('save', () =>
    api(`/api/studio/series/${book.id}`, { method: 'PATCH', profile: false, body }), done);

  const kind = book.cover.kind ? KIND_LABEL[book.cover.kind] : 'None: each chapter shows its own artwork';
  const takenDown = Boolean(book.withdrawnAt);

  return (
    <Card style={{ gap: space.md, borderColor: takenDown ? colors.danger : undefined, borderWidth: takenDown ? 1 : 0 }}>
      <View style={{ flexDirection: 'row', gap: space.lg, flexWrap: 'wrap' }}>
        <Cover id={`book-${book.id}`} title={book.title} artworkUrl={book.cover.url} size={132} />
        <View style={{ flex: 1, minWidth: 260, gap: space.xs }}>
          <Text variant="heading">{book.title}</Text>
          <Text variant="small" muted>
            {book.chapters} chapters · {book.published} published{book.withdrawn ? ` · ${book.withdrawn} taken down` : ''}
          </Text>
          <View style={{ flexDirection: 'row', gap: space.sm, flexWrap: 'wrap', alignItems: 'center' }}>
            <Chip label={book.cover.pending ? 'Making our own cover…' : kind} selected={Boolean(book.cover.kind)} />
            {takenDown ? <Chip label="Taken down" selected /> : null}
          </View>
          {takenDown ? (
            <Text variant="small" color={colors.danger}>
              Taken down {new Date(book.withdrawnAt!).toLocaleDateString()}: {book.withdrawnReason}
            </Text>
          ) : null}
        </View>
      </View>

      <View style={{ flexDirection: 'row', gap: space.sm, flexWrap: 'wrap', alignItems: 'flex-end' }}>
        <View style={{ flex: 2, minWidth: 280 }}>
          <Field label="Where the cover came from" value={source} onChangeText={setSource}
            placeholder="Visalandhra 1982 edition, scanned from our copy" />
        </View>
        <Button kind="secondary" title="Upload book cover…" loading={busy === 'upload'} onPress={() => void upload()} />
        {book.cover.kind === 'book-cover' && source.trim() !== (book.cover.source ?? '') ? (
          <Button kind="ghost" title="Save note" loading={busy === 'save'}
            onPress={() => void patch({ coverSource: source }, 'Note saved.')} />
        ) : null}
      </View>

      <View style={{ flexDirection: 'row', gap: space.sm, flexWrap: 'wrap', alignItems: 'flex-end' }}>
        <View style={{ flex: 2, minWidth: 280 }}>
          <Field label="Title on our own cover (Telugu)" value={coverTitle} onChangeText={setCoverTitle}
            placeholder="Taken from how the narrator says it" style={{ fontFamily: fontFor(coverTitle) }} />
        </View>
        {coverTitle.trim() !== (book.cover.title ?? '') ? (
          <Button kind="ghost" title="Save title" loading={busy === 'save'}
            onPress={() => void patch({ coverTitle }, 'Title saved. Make our own cover again to use it.')} />
        ) : null}
        <Button kind="secondary" title={book.cover.kind === 'own-cover' ? 'Make a new own cover' : 'Make our own cover'}
          disabled={book.cover.pending} loading={busy === 'generate'}
          onPress={() => void run('generate', () => api(`/api/studio/series/${book.id}/cover/generate`,
            { method: 'POST', profile: false }), 'The GPU worker is painting it (about a minute when it is running).')} />
        {book.cover.kind ? (
          <Button kind="ghost" title="Remove cover" loading={busy === 'remove'}
            onPress={() => void run('remove', () => api(`/api/studio/series/${book.id}/cover`,
              { method: 'DELETE', profile: false }), 'Removed. Chapters show their own artwork again.')} />
        ) : null}
      </View>

      {takenDown ? (
        <Button kind="secondary" title="Restore the book" loading={busy === 'restore'}
          onPress={() => void run('restore', () => api(`/api/studio/series/${book.id}/restore`,
            { method: 'POST', profile: false }), 'Restored. Every chapter is back in the app.')} />
      ) : book.published ? (
        <View style={{ flexDirection: 'row', gap: space.sm, flexWrap: 'wrap', alignItems: 'flex-end' }}>
          <View style={{ flex: 2, minWidth: 280 }}>
            <Field label="Take the whole book down (after a claim)" value={reason} onChangeText={setReason}
              placeholder="Who claimed it and when, e.g. Email from the publisher, 15 Oct" />
          </View>
          <Button kind="danger" title={`Take down ${book.published} chapters`} disabled={reason.trim().length < 3}
            loading={busy === 'withdraw'}
            onPress={() => void run('withdraw', () => api(`/api/studio/series/${book.id}/withdraw`,
              { method: 'POST', profile: false, body: { reason } }), 'Taken down. Listeners no longer see this book.')} />
        </View>
      ) : null}
      {message ? <Text variant="small">{message}</Text> : null}
    </Card>
  );
}
