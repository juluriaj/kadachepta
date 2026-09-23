import { Image } from 'expo-image';
import type { ReactNode } from 'react';
import {
  ActivityIndicator, Pressable, Text as RNText, TextInput, View, type PressableProps, type StyleProp,
  type TextInputProps, type TextProps, type TextStyle, type ViewStyle,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { usePlayer } from '@/lib/player/PlayerProvider';
import { coverColor, fontFor, fonts, palette, radius, space, touch, type Colors } from '@/lib/theme';

export function useColors(): Colors {
  const { bedtime } = usePlayer();
  return bedtime ? palette.night : palette.day;
}

type Variant = 'display' | 'title' | 'heading' | 'body' | 'small' | 'label';
const SIZES: Record<Variant, { fontSize: number; lineHeight: number; bold?: boolean }> = {
  display: { fontSize: 30, lineHeight: 40, bold: true },
  title: { fontSize: 22, lineHeight: 32, bold: true },
  heading: { fontSize: 17, lineHeight: 26, bold: true },
  body: { fontSize: 15, lineHeight: 23 },
  small: { fontSize: 13, lineHeight: 19 },
  label: { fontSize: 12, lineHeight: 16, bold: true },
};

export function Text({ variant = 'body', muted, color, style, children, ...rest }:
  TextProps & { variant?: Variant; muted?: boolean; color?: string; children?: ReactNode }) {
  const colors = useColors();
  const size = SIZES[variant];
  const plain = typeof children === 'string' ? children : Array.isArray(children) ? children.join('') : '';
  return (
    <RNText
      {...rest}
      style={[{ fontSize: size.fontSize, lineHeight: size.lineHeight, fontFamily: fontFor(plain, size.bold ? 'bold' : 'regular'),
        color: color ?? (muted ? colors.muted : colors.text) }, style]}>
      {children}
    </RNText>
  );
}

export function Screen({ children, style, padded = true }: { children: ReactNode; style?: StyleProp<ViewStyle>; padded?: boolean }) {
  const colors = useColors();
  return (
    <SafeAreaView style={[{ flex: 1, backgroundColor: colors.background }, padded && { paddingHorizontal: space.lg }, style]}
      edges={['top', 'left', 'right']}>
      {children}
    </SafeAreaView>
  );
}

type ButtonProps = PressableProps & {
  title: string; kind?: 'primary' | 'secondary' | 'ghost' | 'danger'; loading?: boolean; icon?: ReactNode;
  style?: StyleProp<ViewStyle>;
};

export function Button({ title, kind = 'primary', loading, disabled, icon, style, ...rest }: ButtonProps) {
  const colors = useColors();
  const background = { primary: colors.primary, secondary: colors.surfaceAlt, ghost: 'transparent', danger: colors.danger }[kind];
  const foreground = { primary: colors.onPrimary, secondary: colors.text, ghost: colors.primary, danger: '#fff' }[kind];
  return (
    <Pressable
      accessibilityRole="button" accessibilityLabel={title} disabled={disabled || loading} {...rest}
      style={({ pressed }) => [{
        minHeight: touch, borderRadius: radius.pill, paddingHorizontal: space.xl, flexDirection: 'row',
        alignItems: 'center', justifyContent: 'center', gap: space.sm, backgroundColor: background,
        opacity: disabled ? 0.5 : pressed ? 0.85 : 1,
      }, style]}>
      {loading ? <ActivityIndicator color={foreground} /> : icon}
      <Text variant="heading" color={foreground} style={{ fontSize: 15 }}>{title}</Text>
    </Pressable>
  );
}

export function Field(props: TextInputProps & { label: string }) {
  const colors = useColors();
  const { label, style, ...rest } = props;
  return (
    <View style={{ gap: space.xs }}>
      <Text variant="label" muted>{label}</Text>
      <TextInput
        accessibilityLabel={label} placeholderTextColor={colors.muted} {...rest}
        style={[{ minHeight: touch, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border,
          backgroundColor: colors.surface, color: colors.text, paddingHorizontal: space.lg, fontSize: 16,
          fontFamily: fonts.body }, style as StyleProp<TextStyle>]}
      />
    </View>
  );
}

export function Chip({ label, selected, onPress, icon }: { label: string; selected?: boolean; onPress?: () => void; icon?: ReactNode }) {
  const colors = useColors();
  return (
    <Pressable
      accessibilityRole="button" accessibilityLabel={label} accessibilityState={{ selected }} onPress={onPress}
      style={{ minHeight: 40, paddingHorizontal: space.lg, borderRadius: radius.pill, flexDirection: 'row', gap: 6,
        alignItems: 'center', borderWidth: 1, borderColor: selected ? colors.primary : colors.border,
        backgroundColor: selected ? colors.primary : colors.surface }}>
      {icon}
      <Text variant="small" color={selected ? colors.onPrimary : colors.text} style={{ fontFamily: fontFor(label, 'bold') }}>{label}</Text>
    </Pressable>
  );
}

export function Cover({ id, title, artworkUrl, size, rounded = radius.md }: { id: string; title: string; artworkUrl: string | null;
  size: number; rounded?: number }) {
  return (
    <View style={{ width: size, height: size, borderRadius: rounded, overflow: 'hidden', backgroundColor: coverColor(id),
      alignItems: 'center', justifyContent: 'center' }}>
      {artworkUrl ? (
        <Image source={{ uri: artworkUrl }} style={{ width: size, height: size }} contentFit="cover" transition={200}
          accessibilityIgnoresInvertColors />
      ) : (
        <RNText style={{ color: '#fff', fontSize: size * 0.34, fontFamily: fontFor(title, 'bold') }}>{title.trim().charAt(0)}</RNText>
      )}
    </View>
  );
}

export function ProgressBar({ value, color, height = 3 }: { value: number; color?: string; height?: number }) {
  const colors = useColors();
  return (
    <View style={{ height, borderRadius: height, backgroundColor: colors.border, overflow: 'hidden' }}>
      <View style={{ width: `${Math.min(100, Math.max(0, value * 100))}%`, height, backgroundColor: color ?? colors.accent }} />
    </View>
  );
}

export const AVATAR_EMOJI: Record<string, string> = {
  peacock: '🦚', elephant: '🐘', parrot: '🦜', tiger: '🐯', monkey: '🐒', deer: '🦌', owl: '🦉', lotus: '🪷',
  moon: '🌙', star: '⭐',
};

export function Avatar({ avatar, size = 56 }: { avatar: string; size?: number }) {
  const colors = useColors();
  return (
    <View style={{ width: size, height: size, borderRadius: size / 2, backgroundColor: colors.surfaceAlt, alignItems: 'center',
      justifyContent: 'center' }}>
      <RNText style={{ fontSize: size * 0.52 }}>{AVATAR_EMOJI[avatar] ?? '🙂'}</RNText>
    </View>
  );
}

export function Loading() {
  const colors = useColors();
  return (
    <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: colors.background }}>
      <ActivityIndicator color={colors.primary} size="large" />
    </View>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const message = error instanceof Error ? error.message : String(error);
  const diagnostics = (error as { diagnostics?: string })?.diagnostics;
  return (
    <View style={{ padding: space.xl, gap: space.md, alignItems: 'center' }}>
      <Text variant="heading" style={{ textAlign: 'center' }}>{message}</Text>
      {diagnostics ? <Text variant="small" muted style={{ textAlign: 'center' }}>{diagnostics}</Text> : null}
      {onRetry ? <Button title="Try again" kind="secondary" onPress={onRetry} /> : null}
    </View>
  );
}

export function Card({ children, style }: { children: ReactNode; style?: StyleProp<ViewStyle> }) {
  const colors = useColors();
  return (
    <View style={[{ backgroundColor: colors.surface, borderRadius: radius.lg, borderWidth: 1, borderColor: colors.border,
      padding: space.lg, gap: space.sm }, style]}>
      {children}
    </View>
  );
}
