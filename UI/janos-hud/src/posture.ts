// Posture from MediaPipe Pose landmarks, pure geometry (no model import) so it is unit-testable.
// Image coords 0..1, y points DOWN. Sides are the SUBJECT'S anatomical sides (the camera preview is mirrored, the labels are not).

export interface PosePt { x: number; y: number; visibility: number }
export interface Posture { label: string; details: Record<string, boolean> }

export const VIS = 0.5;            // min landmark visibility to be usable; tune live
export const HEAD_DIST = 0.15;     // wrist-to-nose distance (fraction of image) that counts as hand-to-head
export const LEAN_DEG = 12;        // torso tilt from vertical that counts as leaning
export const TILT_DEG = 10;        // shoulder line deviation from horizontal that counts as shoulder tilt

const NOSE = 0, L_SH = 11, R_SH = 12, L_WR = 15, R_WR = 16, L_HIP = 23, R_HIP = 24;
const deg = (r: number) => (r * 180) / Math.PI;

export function classifyPosture(lm: PosePt[]): Posture | null {
  const ok = (i: number) => (lm[i]?.visibility ?? 0) >= VIS;
  if (!ok(L_SH) || !ok(R_SH)) return null;
  const ls = lm[L_SH], rs = lm[R_SH];
  const mid = { x: (ls.x + rs.x) / 2, y: (ls.y + rs.y) / 2 };

  const leftHandRaised = ok(L_WR) && lm[L_WR].y < ls.y;
  const rightHandRaised = ok(R_WR) && lm[R_WR].y < rs.y;
  const handToHead = ok(NOSE) && [L_WR, R_WR].some((w) => ok(w) && Math.hypot(lm[w].x - lm[NOSE].x, lm[w].y - lm[NOSE].y) < HEAD_DIST);

  // torso vector, bottom -> top: hips to shoulders, else shoulders to nose (upper-body framing)
  let top: { x: number; y: number } | null = null, bottom = mid;
  if (ok(L_HIP) && ok(R_HIP)) { top = mid; bottom = { x: (lm[L_HIP].x + lm[R_HIP].x) / 2, y: (lm[L_HIP].y + lm[R_HIP].y) / 2 }; }
  else if (ok(NOSE)) top = lm[NOSE];
  // positive tilt = top toward image +x = the subject's left (unmirrored camera frame)
  const lean = top ? deg(Math.atan2(top.x - bottom.x, bottom.y - top.y)) : 0;
  const leaningLeft = lean > LEAN_DEG, leaningRight = lean < -LEAN_DEG;

  const shoulderTilt = deg(Math.abs(Math.atan2(ls.y - rs.y, Math.abs(ls.x - rs.x) || 1e-6))) > TILT_DEG;
  const armsRaised = leftHandRaised && rightHandRaised;
  const upright = !(leaningLeft || leaningRight || shoulderTilt || leftHandRaised || rightHandRaised || handToHead);

  const details = { leftHandRaised, rightHandRaised, armsRaised, handToHead, leaningLeft, leaningRight, shoulderTilt, upright };
  const label = armsRaised ? 'arms raised'
    : leftHandRaised ? 'left hand raised'
    : rightHandRaised ? 'right hand raised'
    : handToHead ? 'hand to head'
    : leaningLeft ? 'leaning left'
    : leaningRight ? 'leaning right'
    : shoulderTilt ? 'shoulder tilt'
    : 'upright';
  return { label, details };
}
