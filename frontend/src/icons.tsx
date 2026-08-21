import type { ReactNode } from "react";

type IconName =
  | "camera"
  | "chevron-down"
  | "compass"
  | "forum"
  | "knock"
  | "locate"
  | "log-out"
  | "messages"
  | "minimize"
  | "plus"
  | "search"
  | "send"
  | "user"
  | "x";

export function Icon({
  name,
  size = 20,
}: {
  name: IconName;
  size?: number;
}) {
  const paths: Record<IconName, ReactNode> = {
    camera: (
      <>
        <path d="M14.5 4.5 16 7h3a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V9a2 2 0 0 1 2-2h3l1.5-2.5h5Z" />
        <circle cx="12" cy="13" r="3.25" />
      </>
    ),
    "chevron-down": <path d="m7 10 5 5 5-5" />,
    compass: (
      <>
        <circle cx="12" cy="12" r="9" />
        <path d="m15.5 8.5-2 5-5 2 2-5 5-2Z" />
      </>
    ),
    forum: (
      <>
        <path d="M20 14a3 3 0 0 1-3 3H9l-5 3v-3.8A3 3 0 0 1 2 13V7a3 3 0 0 1 3-3h12a3 3 0 0 1 3 3v7Z" />
        <path d="M7 9h10M7 12h6" />
      </>
    ),
    knock: (
      <>
        <rect x="7" y="3" width="10" height="5" rx="1.4" />
        <path d="M12 8v2.5" />
        <circle cx="12" cy="15.5" r="4.5" />
      </>
    ),
    locate: (
      <>
        <circle cx="12" cy="12" r="3" />
        <path d="M12 2v3M12 19v3M2 12h3M19 12h3" />
        <circle cx="12" cy="12" r="7" />
      </>
    ),
    "log-out": (
      <>
        <path d="M10 17l5-5-5-5M15 12H3" />
        <path d="M14 3h5a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-5" />
      </>
    ),
    messages: (
      <>
        <path d="M21 11.5a8.4 8.4 0 0 1-9 8.5 9.5 9.5 0 0 1-4-.9L3 21l1.7-4.5A8.4 8.4 0 0 1 3 11.5 8.6 8.6 0 0 1 12 3a8.6 8.6 0 0 1 9 8.5Z" />
        <path d="M8 11.5h.01M12 11.5h.01M16 11.5h.01" />
      </>
    ),
    minimize: <path d="M6 12h12" />,
    plus: <path d="M12 5v14M5 12h14" />,
    search: (
      <>
        <circle cx="11" cy="11" r="7" />
        <path d="m20 20-4-4" />
      </>
    ),
    send: (
      <>
        <path d="m22 2-7 20-4-9-9-4 20-7Z" />
        <path d="M22 2 11 13" />
      </>
    ),
    user: (
      <>
        <circle cx="12" cy="8" r="4" />
        <path d="M4 21a8 8 0 0 1 16 0" />
      </>
    ),
    x: <path d="M6 6l12 12M18 6 6 18" />,
  };

  return (
    <svg
      aria-hidden="true"
      className="icon"
      fill="none"
      height={size}
      viewBox="0 0 24 24"
      width={size}
    >
      <g
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.8"
      >
        {paths[name]}
      </g>
    </svg>
  );
}
