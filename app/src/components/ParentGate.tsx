import Ionicons from '@expo/vector-icons/Ionicons';
import { useState } from 'react';
import { Modal, Pressable, View } from 'react-native';

import { api, rememberParentPin } from '@/lib/api';
import { useI18n } from '@/lib/i18n';
import { radius, space } from '@/lib/theme';

import { Text, useColors } from './ui';

// A number pad instead of the keyboard: works for a parent one-handed, and small children can't guess
// what it's for. The server checks the PIN and rate-limits attempts.
export function PinPad({ visible, mode = 'verify', onDone, onCancel }: {
  visible: boolean; mode?: 'verify' | 'create'; onDone: (pin: string) => void; onCancel: () => void;
}) {
  const colors = useColors();
  const { t } = useI18n();
  const [digits, setDigits] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);

  const press = async (digit: string) => {
    if (checking) return;
    const next = (digits + digit).slice(0, 4);
    setDigits(next);
    setError(null);
    if (next.length < 4) return;
    if (mode === 'create') {
      setDigits('');
      onDone(next);
      return;
    }
    setChecking(true);
    try {
      const result = await api<{ ok: boolean }>('/api/household/pin/verify', { method: 'POST', body: { pin: next }, profile: false });
      if (result.ok) {
        rememberParentPin(next);
        setDigits('');
        onDone(next);
      } else {
        setError(t('pin.wrong'));
        setDigits('');
      }
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
      setDigits('');
    } finally {
      setChecking(false);
    }
  };

  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onCancel}>
      <View style={{ flex: 1, backgroundColor: colors.overlay, alignItems: 'center', justifyContent: 'center', padding: space.xl }}>
        <View style={{ width: '100%', maxWidth: 340, backgroundColor: colors.surface, borderRadius: radius.lg, padding: space.xl,
          gap: space.lg, alignItems: 'center' }}>
          <Text variant="heading">{mode === 'create' ? t('pin.create') : t('pin.enter')}</Text>
          <View style={{ flexDirection: 'row', gap: space.md }} accessibilityLabel={`${digits.length} of 4 digits entered`}>
            {[0, 1, 2, 3].map((i) => (
              <View key={i} style={{ width: 16, height: 16, borderRadius: 8, borderWidth: 2, borderColor: colors.primary,
                backgroundColor: i < digits.length ? colors.primary : 'transparent' }} />
            ))}
          </View>
          {error ? <Text variant="small" color={colors.danger}>{error}</Text> : null}
          <View style={{ flexDirection: 'row', flexWrap: 'wrap', justifyContent: 'center', gap: space.md, width: 252 }}>
            {['1', '2', '3', '4', '5', '6', '7', '8', '9', 'x', '0', '<'].map((key) => (
              <Pressable
                key={key} accessibilityRole="button"
                accessibilityLabel={key === 'x' ? t('common.cancel') : key === '<' ? 'Delete' : key}
                onPress={() => (key === 'x' ? (setDigits(''), onCancel()) : key === '<' ? setDigits(digits.slice(0, -1)) : press(key))}
                style={({ pressed }) => ({ width: 72, height: 60, borderRadius: radius.md, alignItems: 'center', justifyContent: 'center',
                  backgroundColor: pressed ? colors.border : colors.surfaceAlt })}>
                {key === 'x' ? <Ionicons name="close" size={24} color={colors.text} />
                  : key === '<' ? <Ionicons name="backspace-outline" size={24} color={colors.text} />
                    : <Text variant="title">{key}</Text>}
              </Pressable>
            ))}
          </View>
        </View>
      </View>
    </Modal>
  );
}
