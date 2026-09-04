import { describe, expect, it } from 'vitest';
import { resolveAvatarClientMode } from './client-mode';

describe('resolveAvatarClientMode', () => {
  it('keeps VRM as the default backend', () => {
    expect(resolveAvatarClientMode('')).toEqual({ renderer: 'vrm', model: '/models/avatar.vrm' });
  });
  it('selects LAM and its evaluation asset explicitly', () => {
    expect(resolveAvatarClientMode('?renderer=lam')).toEqual({ renderer: 'lam', model: '/models/lam-eval.zip' });
  });
  it('allows an explicit model URL without leaking renderer details into AvatarFrame', () => {
    expect(resolveAvatarClientMode('?renderer=lam&model=%2Fmodels%2Fcustom.zip')).toEqual({ renderer: 'lam', model: '/models/custom.zip' });
  });
});

it('prefixes bundled model paths with the deployment base', () => {
  expect(resolveAvatarClientMode('', '/avatar-abc/')).toEqual({ renderer: 'vrm', model: '/avatar-abc/models/avatar.vrm' });
  expect(resolveAvatarClientMode('?renderer=lam', '/avatar-abc')).toEqual({ renderer: 'lam', model: '/avatar-abc/models/lam-eval.zip' });
});
