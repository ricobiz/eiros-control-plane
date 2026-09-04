import type { LamExpressionAdapter } from './lam-expression-adapter';

export type LamRendererInstance = { dispose(): void };
export type LamRendererOptions = {
  getChatState: () => string;
  getExpressionData: () => Record<string, number>;
  backgroundColor?: string;
  alpha?: number;
  downloadProgress?: (progress: number) => void;
  loadProgress?: (progress: number) => void;
};
export type LamRendererModule = {
  GaussianSplatRenderer: {
    getInstance(
      container: HTMLElement,
      assetPath: string,
      options: LamRendererOptions,
    ): Promise<LamRendererInstance | undefined>;
  };
};
export type LamRendererImporter = () => Promise<LamRendererModule>;

const defaultImporter: LamRendererImporter = async () => {
  const module = await import('gaussian-splat-renderer-for-lam/build/gaussian-splat-renderer-for-lam.module.js');
  return module as LamRendererModule;
};

export class LamRenderer {
  private instance: LamRendererInstance | null = null;
  private startAttempted = false;

  constructor(
    private readonly container: HTMLElement,
    private readonly adapter: LamExpressionAdapter,
    private readonly importer: LamRendererImporter = defaultImporter,
  ) {}

  async start(
    assetPath: string,
    progress?: (phase: 'download' | 'load', value: number) => void,
  ): Promise<void> {
    if (this.startAttempted) throw new Error('LAM renderer already started');
    this.startAttempted = true;
    const module = await this.importer();
    const instance = await module.GaussianSplatRenderer.getInstance(this.container, assetPath, {
      getChatState: () => this.adapter.getChatState(),
      getExpressionData: () => this.adapter.getExpressionData(),
      backgroundColor: '0x101014',
      alpha: 1,
      downloadProgress: (value) => progress?.('download', value),
      loadProgress: (value) => progress?.('load', value),
    });
    if (!instance) throw new Error('LAM renderer failed to initialize');
    this.instance = instance;
  }

  dispose(): void {
    if (!this.instance) return;
    const instance = this.instance;
    this.instance = null;
    instance.dispose();
  }
}
