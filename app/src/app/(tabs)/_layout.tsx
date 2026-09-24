import Ionicons from '@expo/vector-icons/Ionicons';
import { Redirect, Tabs } from 'expo-router';
import { Pressable, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { MiniPlayer } from '@/components/stories';
import { Text, useColors } from '@/components/ui';
import { useI18n } from '@/lib/i18n';
import { useSession } from '@/lib/session';
import { space } from '@/lib/theme';

const ICONS: Record<string, [keyof typeof Ionicons.glyphMap, keyof typeof Ionicons.glyphMap]> = {
  index: ['home', 'home-outline'],
  library: ['heart', 'heart-outline'],
  family: ['people', 'people-outline'],
  narrate: ['mic', 'mic-outline'],
};

export default function TabsLayout() {
  const { t } = useI18n();
  const colors = useColors();
  const insets = useSafeAreaInsets();
  const { ready, session, profile, isNarrator } = useSession();
  if (ready && (!session.authenticated || !profile)) return <Redirect href="/" />;
  const labels: Record<string, string> = { index: t('tabs.home'), library: t('tabs.library'), family: t('tabs.family'),
    narrate: t('tabs.studio') };
  // Children don't see the Family tab (it's for parents and needs the PIN) or the narrator studio.
  const hidden = profile?.kind === 'child' ? new Set(['family', 'narrate'])
    : isNarrator ? new Set<string>() : new Set(['narrate']);

  return (
    <Tabs
      screenOptions={{ headerShown: false, sceneStyle: { backgroundColor: colors.background } }}
      tabBar={({ state, navigation }) => (
        <View style={{ backgroundColor: colors.surface }}>
          <MiniPlayer />
          <View style={{ flexDirection: 'row', borderTopWidth: 1, borderColor: colors.border, paddingBottom: Math.max(insets.bottom, space.sm) }}>
            {state.routes.filter((route) => !hidden.has(route.name)).map((route) => {
              const focused = state.routes[state.index]?.key === route.key;
              const [active, inactive] = ICONS[route.name] ?? ['ellipse', 'ellipse-outline'];
              return (
                <Pressable key={route.key} accessibilityRole="tab" accessibilityState={{ selected: focused }}
                  accessibilityLabel={labels[route.name]}
                  onPress={() => navigation.navigate(route.name)}
                  style={{ flex: 1, alignItems: 'center', gap: 2, paddingTop: space.sm, minHeight: 52 }}>
                  <Ionicons name={focused ? active : inactive} size={24} color={focused ? colors.primary : colors.muted} />
                  <Text variant="label" color={focused ? colors.primary : colors.muted}>{labels[route.name]}</Text>
                </Pressable>
              );
            })}
          </View>
        </View>
      )}>
      <Tabs.Screen name="index" />
      <Tabs.Screen name="library" />
      <Tabs.Screen name="narrate" />
      <Tabs.Screen name="family" />
    </Tabs>
  );
}
