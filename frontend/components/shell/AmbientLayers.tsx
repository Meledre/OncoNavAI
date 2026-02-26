"use client";

import { useMemo, type CSSProperties } from "react";

type Star = {
  id: string;
  top: string;
  left: string;
  size: number;
  duration: string;
  delay: string;
  minOp: number;
  maxOp: number;
};

function seededRandomFactory(seed: number): () => number {
  let value = seed >>> 0;
  return () => {
    value += 0x6d2b79f5;
    let token = value;
    token = Math.imul(token ^ (token >>> 15), token | 1);
    token ^= token + Math.imul(token ^ (token >>> 7), token | 61);
    return ((token ^ (token >>> 14)) >>> 0) / 4294967296;
  };
}

function makeStars(count: number, seed: number): Star[] {
  const rand = seededRandomFactory(seed);
  const stars: Star[] = [];
  for (let i = 0; i < count; i += 1) {
    const size = rand() * 1.5 + 0.4;
    stars.push({
      id: `star-${i}`,
      top: `${rand() * 100}%`,
      left: `${rand() * 100}%`,
      size,
      duration: `${2 + rand() * 5}s`,
      delay: `${rand() * 5}s`,
      minOp: 0.05 + rand() * 0.1,
      maxOp: 0.2 + rand() * 0.4
    });
  }
  return stars;
}

export default function AmbientLayers() {
  const stars = useMemo(() => makeStars(100, 20260225), []);
  return (
    <>
      <div className="starfield" aria-hidden="true">
        {stars.map((star) => (
          <span
            key={star.id}
            className="star"
            style={
              {
                top: star.top,
                left: star.left,
                width: `${star.size}px`,
                height: `${star.size}px`,
                "--duration": star.duration,
                "--delay": star.delay,
                "--min-op": star.minOp,
                "--max-op": star.maxOp
              } as CSSProperties
            }
          />
        ))}
      </div>
      <div className="ambient-nebula ambient-nebula-a" aria-hidden="true" />
      <div className="ambient-nebula ambient-nebula-b" aria-hidden="true" />
    </>
  );
}
