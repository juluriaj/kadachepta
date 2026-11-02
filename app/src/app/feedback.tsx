import { useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { KeyboardAvoidingView, Platform, ScrollView } from 'react-native';

import { Button, Field, Screen, Text, useColors } from '@/components/ui';
import { api, ApiError } from '@/lib/api';
import { useI18n } from '@/lib/i18n';
import { space } from '@/lib/theme';

// "Send feedback": a message to the team, read in the studio's Feedback inbox.
export default function Feedback() {
  const { t } = useI18n();
  const colors = useColors();
  const { from } = useLocalSearchParams<{ from?: string }>();
  const [message, setMessage] = useState('');
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const send = async () => {
    setBusy(true);
    setError(null);
    try {
      await api('/api/feedback', { method: 'POST', profile: false,
        body: { message: message.trim(), page: from ?? null, platform: Platform.OS === 'web' ? 'web' : Platform.OS } });
      setSent(true);
      setMessage('');
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : String(failure));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Screen back>
      <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : undefined} style={{ flex: 1 }}>
        <ScrollView contentContainerStyle={{ gap: space.lg, paddingVertical: space.lg, maxWidth: 640, width: '100%', alignSelf: 'center' }}
          keyboardShouldPersistTaps="handled">
          <Text variant="title" accessibilityRole="header">{t('feedback.title')}</Text>
          <Text muted>{t('feedback.hint')}</Text>
          <Field label={t('feedback.message')} value={message} onChangeText={(value) => { setMessage(value); setSent(false); }}
            multiline numberOfLines={6} maxLength={4000} style={{ minHeight: 140, paddingTop: space.md, textAlignVertical: 'top' }} />
          {error ? <Text color={colors.danger} accessibilityLiveRegion="polite">{error}</Text> : null}
          {sent ? <Text color={colors.success} accessibilityLiveRegion="polite">{t('feedback.sent')}</Text> : null}
          <Button title={t('feedback.send')} loading={busy} disabled={message.trim().length < 3} onPress={() => void send()} />
        </ScrollView>
      </KeyboardAvoidingView>
    </Screen>
  );
}
