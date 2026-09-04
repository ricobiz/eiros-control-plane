export type AvatarRendererKind = 'vrm' | 'lam';
export type AvatarClientMode = { renderer: AvatarRendererKind; model: string };

export function resolveAvatarClientMode(search: string, base = '/'): AvatarClientMode {
  const params = new URLSearchParams(search);
  const renderer: AvatarRendererKind = params.get('renderer') === 'lam' ? 'lam' : 'vrm';
  const prefix = base.endsWith('/') ? base : `${base}/`;
  const fallback = renderer === 'lam' ? `${prefix}models/lam-eval.zip` : `${prefix}models/avatar.vrm`;
  return { renderer, model: params.get('model') || fallback };
}
