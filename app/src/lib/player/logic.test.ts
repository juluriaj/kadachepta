// Run with: node --test src/lib/player/logic.test.ts   (Node 22.6+ strips the types)
import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  fadeVolume, listenedDelta, nextSleep, nextSpeed, onStoryFinished, resumePosition, sleepRemaining,
} from './logic.ts';

test('sleep countdown', () => {
  assert.equal(sleepRemaining(null, 1000), null);
  assert.equal(sleepRemaining(61_000, 1_000), 60);
  assert.equal(sleepRemaining(1_000, 5_000), 0);
});

test('fade is silent at zero, full before the fade window, and eases in between', () => {
  assert.equal(fadeVolume(null), 1);
  assert.equal(fadeVolume(120), 1);
  assert.equal(fadeVolume(0), 0);
  const mid = fadeVolume(22.5, 45);
  assert.ok(mid > 0.2 && mid < 0.3, `mid-fade volume ${mid}`);
  assert.ok(fadeVolume(40) > fadeVolume(10));
});

test('bedtime and stop-at-end never roll into another story', () => {
  assert.equal(onStoryFinished({ bedtime: true, sleep: 'off', hasNext: true, autoContinue: true }), 'goodnight');
  assert.equal(onStoryFinished({ bedtime: false, sleep: 'end', hasNext: true, autoContinue: true }), 'goodnight');
  assert.equal(onStoryFinished({ bedtime: false, sleep: 20, hasNext: true, autoContinue: true }), 'next');
  assert.equal(onStoryFinished({ bedtime: false, sleep: 'off', hasNext: true, autoContinue: false }), 'stop');
  assert.equal(onStoryFinished({ bedtime: false, sleep: 'off', hasNext: false, autoContinue: true }), 'stop');
});

test('resume rewinds a little, but not for finished or barely started stories', () => {
  assert.equal(resumePosition(null, 600), 0);
  assert.equal(resumePosition({ position: 5, completed: false }, 600), 0);
  assert.equal(resumePosition({ position: 200, completed: false }, 600), 197);
  assert.equal(resumePosition({ position: 200, completed: true }, 600), 0);
  assert.equal(resumePosition({ position: 595, completed: false }, 600), 0);
});

test('only forward playback counts as listening', () => {
  assert.equal(listenedDelta(null, 10), 0);
  assert.equal(listenedDelta(10, 11), 1);
  assert.equal(listenedDelta(10, 9), 0);      // seek back
  assert.equal(listenedDelta(10, 100), 0);    // seek forward
  assert.equal(listenedDelta(10, 12, 2), 1);  // 2 s of audio at 2x = 1 s of real listening
});

test('cycling speed and sleep choices wraps around', () => {
  assert.equal(nextSpeed(1), 1.25);
  assert.equal(nextSpeed(2), 0.75);
  assert.equal(nextSleep('off'), 10);
  assert.equal(nextSleep('end'), 'off');
});
