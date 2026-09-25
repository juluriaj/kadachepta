// Run with: node --test src/lib/recording.test.ts
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { levelFromDb, levelHint } from './recording.ts';

test('meter maps dBFS to 0..1', () => {
  assert.equal(levelFromDb(-160), 0);
  assert.equal(levelFromDb(0), 1);
  assert.equal(levelFromDb(-30), 0.5);
  assert.equal(levelFromDb(undefined), 0);
});

test('hints nag only about real problems, never during pauses', () => {
  assert.equal(levelHint(-70), null);
  assert.equal(levelHint(-45), 'quiet');
  assert.equal(levelHint(-20), 'good');
  assert.equal(levelHint(-1), 'loud');
});
