// Soft, flat bot characters: one solid body and two slanted capsule eyes.
// Coordinates use the same 0–100 view box as the DS Bot shapes; each eye is
// [centerX, centerY, width, height, rotationDegrees].
export const softShapes = {
  orb: {
    body: "M50 8a42 42 0 1 1 0 84a42 42 0 1 1 0-84z",
    eyes: [
      [57, 31, 9, 20, -25],
      [70, 27, 9, 20, -25],
    ],
  },
  heart: {
    body: "M50 90C28 78 8 62 8 40C8 24 20 12 34 12C42 12 47 16 50 22C53 16 58 12 66 12C80 12 92 24 92 40C92 62 72 78 50 90Z",
    eyes: [
      [52, 42, 9, 19, -25],
      [65, 39, 9, 19, -25],
    ],
  },
  sparkle: {
    body: "M50 6C61 6 61 29 69 37C77 45 94 39 94 50C94 61 77 55 69 63C61 71 61 94 50 94C39 94 39 71 31 63C23 55 6 61 6 50C6 39 23 45 31 37C39 29 39 6 50 6Z",
    eyes: [
      [45, 46, 8, 17, -25],
      [57, 43, 8, 17, -25],
    ],
  },
  drop: {
    body: "M28 11C43 4 85 29 91 48C97 67 71 93 45 93C20 93 7 77 9 54C11 33 16 16 28 11Z",
    eyes: [
      [47, 40, 9, 19, -25],
      [60, 37, 9, 19, -25],
    ],
  },
  cloud: {
    body: "M26 80C12 80 5 68 9 57C3 46 10 32 24 32C26 18 42 11 55 19C63 9 82 13 84 30C96 34 98 51 89 59C93 71 85 81 72 80Z",
    eyes: [
      [52, 46, 9, 19, -25],
      [65, 43, 9, 19, -25],
    ],
  },
  bean: {
    body: "M19 29C30 16 70 16 84 29C96 40 95 62 82 73C68 85 32 85 18 73C5 62 7 40 19 29Z",
    eyes: [
      [57, 40, 9, 19, -25],
      [70, 37, 9, 19, -25],
    ],
  },
} satisfies Record<string, { body: string; eyes: number[][] }>;

// Flat inks for the soft characters: [light theme, dark theme].
export const softInks: Record<string, string[]> = {
  red: ["#FB2638", "#FF4C5B"],
  orange: ["#F58714", "#FF9B3D"],
  green: ["#11AF98", "#25C6AE"],
  blue: ["#1B7AFC", "#4C95FF"],
  violet: ["#844FF9", "#9C70FF"],
  black: ["#000000", "#FFFFFF"],
};
