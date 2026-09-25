import { Redirect, router, Stack, usePathname } from 'expo-router';
import { Pressable, View } from 'react-native';

import { Loading, Text, useColors } from '@/components/ui';
import { useGuardSession } from '@/lib/session';
import { space } from '@/lib/theme';

const LINKS = [
  { href: '/studio', label: 'Queue', match: (path: string) => path === '/studio' || path.startsWith('/studio/review') },
  { href: '/studio/narrators', label: 'Narrators' },
  { href: '/studio/activity', label: 'Activity' },
  { href: '/studio/settings', label: 'AI & processing', permission: 'jobs.manage' },
] as const;

// The editor and admin studio. Designed for a desktop browser; it still works on a tablet.
export default function StudioLayout() {
  const colors = useColors();
  const path = usePathname();
  const { ready, session, isStaff, signOut } = useGuardSession();
  if (!ready) return <Loading />;
  if (!session.authenticated) return <Redirect href="/sign-in" />;
  if (!isStaff) return <Redirect href="/" />;
  const permissions = new Set(session.permissions ?? []);

  return (
    <View style={{ flex: 1, backgroundColor: colors.background }}>
      <View accessibilityRole="header" style={{ flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: space.lg,
        paddingHorizontal: space.xl, paddingVertical: space.md, borderBottomWidth: 1, borderColor: colors.border,
        backgroundColor: colors.surface }}>
        <Text variant="heading" color={colors.primary}>KathaChepta Studio</Text>
        {LINKS.filter((link) => !('permission' in link) || permissions.has(link.permission)).map((link) => {
          const active = 'match' in link ? link.match(path) : path.startsWith(link.href);
          return (
            <Pressable key={link.href} accessibilityRole="link" onPress={() => router.navigate(link.href)}
              style={{ paddingVertical: space.xs, borderBottomWidth: 2, borderColor: active ? colors.primary : 'transparent' }}>
              <Text variant="body" color={active ? colors.primary : colors.text}>{link.label}</Text>
            </Pressable>
          );
        })}
        <View style={{ flex: 1 }} />
        <Pressable accessibilityRole="link" onPress={() => router.navigate('/studio/profile')}>
          <Text variant="small" color={path === '/studio/profile' ? colors.primary : colors.muted}>
            {session.username} · {session.role} · My details
          </Text>
        </Pressable>
        <Pressable accessibilityRole="button" onPress={() => void signOut()}>
          <Text variant="small" color={colors.primary}>Sign out</Text>
        </Pressable>
      </View>
      <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: colors.background } }} />
    </View>
  );
}
