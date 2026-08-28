import { describe, expect, it } from 'vitest';
import { LamRenderer, type LamRendererModule } from './lam-renderer';
import { LamExpressionAdapter } from './lam-expression-adapter';

function fakeContainer(): HTMLElement {
  return {} as HTMLElement;
}

describe('LamRenderer', () => {
  it('passes live state/expression callbacks to the upstream renderer', async () => {
    const adapter = new LamExpressionAdapter();
    adapter.setChatState('Thinking');
    let options: any;
    const instance = { dispose() {} };
    const module: LamRendererModule = {
      GaussianSplatRenderer: {
        async getInstance(_container, _assetPath, supplied) {
          options = supplied;
          return instance;
        },
      },
    };
    const renderer = new LamRenderer(fakeContainer(), adapter, async () => module);
    await renderer.start('/models/lam-eval.zip');
    expect(options.getChatState()).toBe('Thinking');
    expect(options.getExpressionData()).toEqual({});
  });

  it('disposes the upstream renderer exactly once', async () => {
    const adapter = new LamExpressionAdapter();
    let disposeCount = 0;
    const module: LamRendererModule = {
      GaussianSplatRenderer: {
        async getInstance() { return { dispose() { disposeCount += 1; } }; },
      },
    };
    const renderer = new LamRenderer(fakeContainer(), adapter, async () => module);
    await renderer.start('/models/lam-eval.zip');
    renderer.dispose();
    renderer.dispose();
    expect(disposeCount).toBe(1);
  });

  it('fails clearly when the upstream singleton does not initialize', async () => {
    const adapter = new LamExpressionAdapter();
    const module: LamRendererModule = {
      GaussianSplatRenderer: { async getInstance() { return undefined; } },
    };
    const renderer = new LamRenderer(fakeContainer(), adapter, async () => module);
    await expect(renderer.start('/models/lam-eval.zip')).rejects.toThrow('LAM renderer failed to initialize');
  });

  it('does not allow a second start on the same wrapper', async () => {
    const adapter = new LamExpressionAdapter();
    const module: LamRendererModule = {
      GaussianSplatRenderer: { async getInstance() { return { dispose() {} }; } },
    };
    const renderer = new LamRenderer(fakeContainer(), adapter, async () => module);
    await renderer.start('/models/lam-eval.zip');
    await expect(renderer.start('/models/other.zip')).rejects.toThrow('already started');
  });
});
