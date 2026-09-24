import Ionicons from '@expo/vector-icons/Ionicons';
import { router } from 'expo-router';
import { useKeepAwake } from 'expo-keep-awake';
import { Pressable, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { Text } from '@/components/ui';
import { useI18n } from '@/lib/i18n';
import { usePlayer } from '@/lib/player/PlayerProvider';
import { palette, radius, space } from '@/lib/theme';

// Drive mode: four huge targets, high contrast, screen kept awake, series continue automatically.
// Nothing here needs reading while driving; each button is a quarter of the screen.
export default function Drive() {
  useKeepAwake();
  const { t } = useI18n();
  const player = usePlayer();
  const colors = palette.night;

  const exit = () => {
    player.setDriveMode(false);
    router.back();
  };

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: colors.background }}>
      <View style={{ flexDirection: 'row', alignItems: 'center', padding: space.lg }}>
        <Text variant="title" color={colors.text} numberOfLines={1} style={{ flex: 1 }}>{player.story?.title ?? '—'}</Text>
        <Pressable onPress={exit} accessibilityRole="button" accessibilityLabel={t('drive.exit')} hitSlop={16}
          style={{ padding: space.md, borderRadius: radius.pill, backgroundColor: colors.surface }}>
          <Ionicons name="close" size={28} color={colors.text} />
        </Pressable>
      </View>
      <View style={{ flex: 2, flexDirection: 'row' }}>
        <Big colors={colors} icon={player.playing ? 'pause' : 'play'} label={player.playing ? t('player.pause') : t('player.play')} onPress={player.toggle} primary />
      </View>
      <View style={{ flex: 1, flexDirection: 'row' }}>
        <Big colors={colors} icon="play-back" label="15" onPress={() => player.seekBy(-15)} />
        <Big colors={colors} icon="play-skip-forward" label={t('player.next')} onPress={player.next} />
      </View>
    </SafeAreaView>
  );
}

function Big({ icon, label, onPress, primary, colors }: { icon: keyof typeof Ionicons.glyphMap; label: string; onPress: () => void;
  primary?: boolean; colors: typeof palette.night }) {
  return (
    <Pressable onPress={onPress} accessibilityRole="button" accessibilityLabel={label}
      style={({ pressed }) => ({ flex: 1, margin: space.sm, borderRadius: radius.lg, alignItems: 'center', justifyContent: 'center', gap: space.sm,
        backgroundColor: primary ? colors.primary : pressed ? colors.surfaceAlt : colors.surface })}>
      <Ionicons name={icon} size={primary ? 96 : 64} color={primary ? colors.onPrimary : colors.text} />
      <Text variant="heading" color={primary ? colors.onPrimary : colors.text}>{label}</Text>
    </Pressable>
  );
}
