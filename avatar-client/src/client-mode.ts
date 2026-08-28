export type AvatarRendererKind = 'vrm' | 'lam';
export type AvatarClientMode = { renderer: AvatarRendererKind; model: string };

export function resolveAvatarClientMode(search: string): AvatarClientMode {
  const params = new URLSearchParams(search);
  const renderer: AvatarRendererKind = params.get('renderer') === 'lam' ? 'lam' : 'vrm';
  const fallback = renderer === 'lam' ? '/models/lam-eval.zip' : '/models/avatar.vrm';
  return { renderer, model: params.get('model') || fallback };
}
