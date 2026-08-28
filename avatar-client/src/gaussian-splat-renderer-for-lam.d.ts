declare module 'gaussian-splat-renderer-for-lam/build/gaussian-splat-renderer-for-lam.module.js' {
  export type GaussianSplatRendererOptions = {
    getChatState?: () => string;
    getExpressionData?: () => Record<string, number>;
    backgroundColor?: string;
    alpha?: number;
    downloadProgress?: (progress: number) => void;
    loadProgress?: (progress: number) => void;
  };

  export type GaussianSplatRendererInstance = {
    dispose(): void;
  };

  export const GaussianSplatRenderer: {
    getInstance(
      container: HTMLElement,
      assetPath: string,
      options?: GaussianSplatRendererOptions,
    ): Promise<GaussianSplatRendererInstance | undefined>;
  };
}
