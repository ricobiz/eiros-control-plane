export type FaceState = Record<string, number>;
export type HeadState = { quat: [number, number, number, number] };
export type GazeState = { x: number; y: number };
export type BodyState = { breath: number; lean: number };
export type AvatarFrame = {
  sessionId: string;
  characterId: string;
  sequence: number;
  audioPtsMs: number;
  framePtsMs: number;
  face: FaceState;
  head: HeadState;
  gaze: GazeState;
  body: BodyState;
};

const clamp = (value: number, min = -1, max = 1): number => Math.max(min, Math.min(max, value));

export function clampAvatarFrame(frame: AvatarFrame): AvatarFrame {
  const face = Object.fromEntries(
    Object.entries(frame.face).map(([key, value]) => [key, clamp(value, 0, 1)]),
  );
  const q = frame.head.quat;
  const length = Math.hypot(...q);
  const quat: [number, number, number, number] = length > 1e-8
    ? q.map((value) => value / length) as [number, number, number, number]
    : [0, 0, 0, 1];
  return {
    ...frame,
    face,
    head: { quat },
    gaze: { x: clamp(frame.gaze.x), y: clamp(frame.gaze.y) },
    body: { breath: clamp(frame.body.breath, 0, 1), lean: clamp(frame.body.lean) },
  };
}
