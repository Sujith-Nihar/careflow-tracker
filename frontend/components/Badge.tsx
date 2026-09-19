import type { Tone } from "@/lib/status";

/**
 * A status badge always carries three channels: colour, a dot, and a word.
 * Two of the four status hues fall below 3:1 on a light surface, so the label is
 * what makes the badge readable, not the colour.
 */
export function Badge({
  tone,
  children,
  alarm = false,
}: {
  tone: Tone;
  children: React.ReactNode;
  alarm?: boolean;
}) {
  return (
    <span className={`badge ${alarm ? "alarm" : tone}`}>
      <span className="badge-dot" aria-hidden="true" />
      {children}
    </span>
  );
}
