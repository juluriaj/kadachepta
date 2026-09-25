import { useState } from 'react';
import { View } from 'react-native';

import { StudioPlayer } from '@/components/StudioPlayer';
import { Chip } from '@/components/ui';
import type { Mastering } from '@/lib/types';
import { space } from '@/lib/theme';

// P2-18: the listening copy next to the recording as made, both at the same loudness, so the difference
// you hear is the mastering and not a volume change.
export function MasteringCompare({ audioUrl, mastering, waveform, duration, labels }: {
  audioUrl: string | null; mastering: Mastering; waveform: number[]; duration: number;
  labels: { mastered: string; original: string };
}) {
  const [original, setOriginal] = useState(false);
  const compare = mastering.compareUrl;
  const url = original && compare ? compare : audioUrl;
  return (
    <View style={{ gap: space.sm }}>
      {compare ? (
        <View style={{ flexDirection: 'row', gap: space.sm }}>
          <Chip label={labels.mastered} selected={!original} onPress={() => setOriginal(false)} />
          <Chip label={labels.original} selected={original} onPress={() => setOriginal(true)} />
        </View>
      ) : null}
      {/* keyed: a fresh player per version, so switching never plays the wrong file */}
      <StudioPlayer key={url ?? 'none'} url={url} waveform={waveform} duration={duration} />
    </View>
  );
}
