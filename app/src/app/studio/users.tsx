import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { ScrollView, View } from 'react-native';

import { Button, Card, Field, Loading, Text, useColors } from '@/components/ui';
import { api } from '@/lib/api';
import { space } from '@/lib/theme';

type Account = { userId: number; username: string | null; email: string | null; displayName: string | null;
  phone: string | null; role: string; createdAt: string; lastLoginAt: string | null; hasPassword: boolean };

// Admins only: find an account and give it a new password. Email is off, so nobody can reset their own.
export default function Users() {
  const colors = useColors();
  const [search, setSearch] = useState('');
  const [confirming, setConfirming] = useState<number | null>(null);
  const [issued, setIssued] = useState<{ userId: number; password: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const term = search.trim();
  const query = useQuery({ queryKey: ['studio-users', term], enabled: term.length >= 2,
    queryFn: () => api<{ items: Account[] }>(`/api/admin/users?q=${encodeURIComponent(term)}`, { profile: false }) });

  const reset = async (account: Account) => {
    setError(null);
    try {
      const result = await api<{ password: string }>(`/api/admin/users/${account.userId}/password`,
        { method: 'POST', profile: false, body: {} });
      setIssued({ userId: account.userId, password: result.password });
      setConfirming(null);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    }
  };

  return (
    <ScrollView contentContainerStyle={{ padding: space.xl, gap: space.md, maxWidth: 900, width: '100%', alignSelf: 'center' }}
      keyboardShouldPersistTaps="handled">
      <Text variant="title">Users</Text>
      <Text muted>
        Someone forgot their password? Find their account and give it a new one. They are signed out everywhere, sign
        in with the new password, and can change it in Account. Check it’s really them before you pass it on.
      </Text>
      <Field label="Username, email, name or phone" value={search} onChangeText={(value) => { setSearch(value); setIssued(null); }}
        autoCapitalize="none" autoCorrect={false} />
      {error ? <Text color={colors.danger}>{error}</Text> : null}
      {term.length < 2 ? <Text variant="small" muted>Type at least 2 characters.</Text> : null}
      {query.isFetching && !query.data ? <Loading /> : null}
      {query.data && !query.data.items.length ? <Text variant="small" muted>No account matches.</Text> : null}
      {query.data?.items.map((account) => (
        <Card key={account.userId}>
          <View style={{ flexDirection: 'row', gap: space.md, flexWrap: 'wrap', alignItems: 'center' }}>
            <View style={{ flex: 1, minWidth: 240, gap: 2 }}>
              <Text variant="heading">{account.displayName ?? account.username ?? account.email}</Text>
              <Text variant="small" selectable>
                {[account.username && `@${account.username}`, account.email, account.phone].filter(Boolean).join(' · ')}
              </Text>
              <Text variant="small" muted>
                {account.role} · joined {new Date(account.createdAt).toLocaleDateString()} · {account.lastLoginAt
                  ? `last signed in ${new Date(account.lastLoginAt).toLocaleDateString()}` : 'never signed in here'}
                {account.hasPassword ? '' : ' · no password yet'}
              </Text>
            </View>
            {confirming === account.userId ? (
              <View style={{ flexDirection: 'row', gap: space.sm }}>
                <Button kind="danger" title="Yes, reset it" onPress={() => void reset(account)} />
                <Button kind="ghost" title="Cancel" onPress={() => setConfirming(null)} />
              </View>
            ) : <Button kind="secondary" title="Reset password" onPress={() => { setConfirming(account.userId); setIssued(null); }} />}
          </View>
          {issued?.userId === account.userId ? (
            <View style={{ gap: space.xs, marginTop: space.sm }}>
              <Text variant="small" muted>New password (shown once; it isn’t stored anywhere you can see it again):</Text>
              <Text variant="title" selectable style={{ fontFamily: 'monospace' }}>{issued.password}</Text>
            </View>
          ) : null}
        </Card>
      ))}
    </ScrollView>
  );
}
