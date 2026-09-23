import { DMSans_400Regular, DMSans_500Medium, DMSans_700Bold } from '@expo-google-fonts/dm-sans';
import { NotoSansTelugu_400Regular, NotoSansTelugu_700Bold } from '@expo-google-fonts/noto-sans-telugu';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useFonts } from 'expo-font';
import { Stack } from 'expo-router';
import * as SplashScreen from 'expo-splash-screen';
import { StatusBar } from 'expo-status-bar';
import { useEffect, useState } from 'react';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { useColors } from '@/components/ui';
import { I18nProvider } from '@/lib/i18n';
import { PlayerProvider, usePlayer } from '@/lib/player/PlayerProvider';
import { SessionProvider } from '@/lib/session';

SplashScreen.preventAutoHideAsync().catch(() => {});

function Navigator() {
  const colors = useColors();
  const { bedtime } = usePlayer();
  return (
    <>
      <StatusBar style={bedtime ? 'light' : 'dark'} />
      <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: colors.background } }}>
        <Stack.Screen name="index" />
        <Stack.Screen name="sign-in" />
        <Stack.Screen name="onboarding" />
        <Stack.Screen name="profiles" />
        <Stack.Screen name="(tabs)" />
        <Stack.Screen name="story/[id]" />
        <Stack.Screen name="player" options={{ presentation: 'modal' }} />
        <Stack.Screen name="drive" options={{ presentation: 'fullScreenModal', animation: 'fade' }} />
      </Stack>
    </>
  );
}

export default function RootLayout() {
  const [queryClient] = useState(() => new QueryClient({
    defaultOptions: { queries: { retry: 1, staleTime: 30_000, refetchOnWindowFocus: false } },
  }));
  const [fontsLoaded] = useFonts({
    DMSans_400Regular, DMSans_500Medium, DMSans_700Bold, NotoSansTelugu_400Regular, NotoSansTelugu_700Bold,
  });

  useEffect(() => {
    if (fontsLoaded) SplashScreen.hideAsync().catch(() => {});
  }, [fontsLoaded]);

  if (!fontsLoaded) return null;
  return (
    <SafeAreaProvider>
      <QueryClientProvider client={queryClient}>
        <I18nProvider>
          <PlayerProvider>
            <SessionProvider>
              <Navigator />
            </SessionProvider>
          </PlayerProvider>
        </I18nProvider>
      </QueryClientProvider>
    </SafeAreaProvider>
  );
}
