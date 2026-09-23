import { useQueryClient } from '@tanstack/react-query';
import { createContext, useContext, useEffect, useMemo, useSyncExternalStore, type ReactNode } from 'react';

import type { Story } from '../types';
import { getEngine, type PlayerSnapshot } from './engine';
import type { SleepMode } from './logic';

type PlayerState = PlayerSnapshot & {
  play: (story: Story, options?: { queue?: Story[]; autoContinue?: boolean }) => Promise<void>;
  toggle: () => void;
  seekBy: (seconds: number) => void;
  seekTo: (seconds: number) => void;
  setRate: (rate: number) => void;
  setSleep: (mode: SleepMode) => void;
  setBedtime: (on: boolean) => void;
  setDriveMode: (on: boolean) => void;
  setDataSaver: (on: boolean) => void;
  next: () => void;
  previous: () => void;
  stop: () => void;
  dismissGoodnight: () => void;
};

const Context = createContext<PlayerState | null>(null);

export function PlayerProvider({ children }: { children: ReactNode }) {
  const engine = getEngine();
  const snapshot = useSyncExternalStore(engine.subscribe, engine.getSnapshot, engine.getSnapshot);
  const queryClient = useQueryClient();

  useEffect(() => engine.onStoryCompleted(() => {
    void queryClient.invalidateQueries({ queryKey: ['home'] });
    void queryClient.invalidateQueries({ queryKey: ['catalog'] });
  }), [engine, queryClient]);

  const value = useMemo<PlayerState>(() => ({
    ...snapshot,
    play: engine.play, toggle: engine.toggle, seekBy: engine.seekBy, seekTo: engine.seekTo, setRate: engine.setRate,
    setSleep: engine.setSleep, setBedtime: engine.setBedtime, setDriveMode: engine.setDriveMode,
    setDataSaver: engine.setDataSaver, next: engine.next, previous: engine.previous, stop: engine.stop,
    dismissGoodnight: engine.dismissGoodnight,
  }), [snapshot, engine]);

  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function usePlayer() {
  const context = useContext(Context);
  if (!context) throw new Error('usePlayer must be used inside PlayerProvider');
  return context;
}
