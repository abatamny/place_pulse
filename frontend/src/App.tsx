import {
  type FormEvent,
  type KeyboardEvent as ReactKeyboardEvent,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { Icon } from "./icons";

type View = "login" | "register" | "verify";

type User = {
  id: number;
  phone: string;
  nickname: string;
};

type RegistrationResponse = {
  message: string;
  verification_code: string | null;
};

type LoginResponse = {
  access_token: string;
  token_type: string;
  user: User;
};

type CurrentPlace = {
  id: number;
  osm_type: string;
  osm_id: number;
  name: string;
  locality: string | null;
  display_name: string;
  parent_place_id: number | null;
  rank: "VISITOR" | "BELONG";
  completed_visits: number;
};

type NearbyUser = {
  id: number;
  nickname: string;
  shared_place_id: number;
  shared_place_name: string;
  shared_place_display_name: string;
};

type PresenceResponse = {
  places: CurrentPlace[];
  nearby_users: NearbyUser[];
  expires_in_seconds: number;
};

type KnockMessage = {
  id: number;
  place_id: number;
  place_name: string;
  place_display_name: string;
  origin_place_id: number;
  origin_place_name: string;
  origin_place_display_name: string;
  user_id: number;
  nickname: string;
  author_rank: "VISITOR" | "BELONG";
  text: string;
  created_at: string;
};

type KnockHistoryResponse = {
  messages: KnockMessage[];
};

type Dig = {
  id: number;
  place_id: number;
  place_name: string;
  place_display_name: string;
  origin_place_id: number;
  origin_place_name: string;
  origin_place_display_name: string;
  user_id: number;
  nickname: string;
  media_type: "image" | "video";
  content_type: string;
  original_filename: string;
  file_size: number;
  media_url: string;
  created_at: string;
  expires_at: string;
};

type DigFeedResponse = {
  digs: Dig[];
};

type ExploreDig = {
  id: number;
  user_id: number;
  nickname: string;
  media_type: "image" | "video";
  content_type: string;
  original_filename: string;
  media_url: string;
  created_at: string;
};

type ExploreComment = {
  id: number;
  user_id: number;
  nickname: string;
  text: string;
  created_at: string;
};

type ExploreMemory = {
  id: number;
  place_id: number;
  place_name: string;
  place_display_name: string;
  place_names: string[];
  participant_count: number;
  created_at: string;
  participant: boolean;
  liked_by_me: boolean;
  like_count: number;
  digs: ExploreDig[];
  comments: ExploreComment[];
};

type ExploreFeedResponse = {
  memories: ExploreMemory[];
};

type ExploreLikeResponse = {
  liked_by_me: boolean;
  like_count: number;
};

type ForumComment = {
  id: number;
  user_id: number;
  nickname: string;
  text: string;
  created_at: string;
};

type ForumPost = {
  id: number;
  place_id: number;
  place_name: string;
  place_display_name: string;
  origin_place_id: number;
  origin_place_name: string;
  origin_place_display_name: string;
  user_id: number | null;
  nickname: string;
  is_anonymous: boolean;
  is_mine: boolean;
  title: string;
  body: string;
  upvotes: number;
  downvotes: number;
  score: number;
  my_vote: number;
  created_at: string;
  comments: ForumComment[];
};

type ForumFeedResponse = {
  posts: ForumPost[];
};

type PendingForumPost = ForumPost & {
  pending: true;
};

type PendingKnock = {
  id: number;
  text: string;
  created_at: string;
};

type PendingDig = {
  id: number;
  nickname: string;
  place_name: string;
  place_display_name: string;
  media_type: "image" | "video";
  preview_url: string;
};

type PersonalForumResponse = {
  posts: ForumPost[];
  total_upvotes: number;
  total_downvotes: number;
  total_score: number;
};

type DMUser = {
  id: number;
  nickname: string;
  phone?: string;
};

type DMChatRequest = {
  requestId: number;
  user: DMUser;
};

type DMMessage = {
  id: number;
  sender_id: number;
  sender_nickname: string;
  recipient_id: number;
  recipient_nickname: string;
  text: string;
  created_at: string;
  read_at: string | null;
};

type DMConversation = {
  user: DMUser;
  last_message: DMMessage;
  unread_count: number;
};

type DMConversationListResponse = {
  conversations: DMConversation[];
};

type DMHistoryResponse = {
  user: DMUser;
  messages: DMMessage[];
};

type DMUserSearchResponse = {
  users: DMUser[];
};

function mergeDMMessages(messages: DMMessage[]): DMMessage[] {
  return Array.from(
    new Map(messages.map((message) => [message.id, message])).values(),
  ).sort(
    (first, second) =>
      new Date(first.created_at).getTime() - new Date(second.created_at).getTime(),
  );
}

function updateDMConversations(
  conversations: DMConversation[],
  message: DMMessage,
  viewerUserId: number,
  activeUserId: number | null,
  fallbackUser?: DMUser,
): DMConversation[] {
  const otherUserId =
    message.sender_id === viewerUserId ? message.recipient_id : message.sender_id;
  const existing = conversations.find(
    (conversation) => conversation.user.id === otherUserId,
  );

  if (!existing) {
    if (!fallbackUser || fallbackUser.id !== otherUserId) {
      return conversations;
    }
    return [
      {
        user: fallbackUser,
        last_message: message,
        unread_count:
          message.recipient_id === viewerUserId && activeUserId !== otherUserId ? 1 : 0,
      },
      ...conversations,
    ];
  }

  const isDuplicate = existing.last_message.id === message.id;
  const unreadCount =
    activeUserId === otherUserId
      ? 0
      : message.recipient_id === viewerUserId && !isDuplicate
        ? existing.unread_count + 1
        : existing.unread_count;
  const updated = {
    ...existing,
    last_message: message,
    unread_count: unreadCount,
  };

  return [
    updated,
    ...conversations.filter((conversation) => conversation.user.id !== otherUserId),
  ];
}

const TOKEN_KEY = "placepulse-session";

function submitTextOnEnter(
  event: ReactKeyboardEvent<HTMLTextAreaElement>,
  disabled = false,
) {
  if (
    event.key !== "Enter" ||
    event.shiftKey ||
    event.nativeEvent.isComposing
  ) {
    return;
  }
  event.preventDefault();
  if (!disabled) {
    event.currentTarget.form?.requestSubmit();
  }
}

async function apiRequest<T>(
  path: string,
  options: RequestInit = {},
  token?: string,
): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body && !(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  const response = await fetch(path, { ...options, headers });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const detail = body?.detail;
    const message = Array.isArray(detail)
      ? detail.map((item) => item.msg).join(". ")
      : detail || "Something went wrong. Please try again.";
    throw new Error(message);
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return response.json() as Promise<T>;
}

function mergeMessages(messages: KnockMessage[]): KnockMessage[] {
  const byId = new Map(messages.map((message) => [message.id, message]));
  return [...byId.values()]
    .sort(
      (left, right) =>
        new Date(left.created_at).getTime() -
        new Date(right.created_at).getTime(),
    )
    .slice(-100);
}

function scrollFeedToEnd(element: HTMLElement | null) {
  if (!element) {
    return;
  }
  window.requestAnimationFrame(() => {
    element.scrollTo({
      top: element.scrollHeight,
      behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches
        ? "auto"
        : "smooth",
    });
  });
}

function PresencePanel({
  token,
  places,
  onPlacesChange,
  onNearbyUsersChange,
}: {
  token: string;
  places: CurrentPlace[];
  onPlacesChange: (places: CurrentPlace[]) => void;
  onNearbyUsersChange: (users: NearbyUser[]) => void;
}) {
  const [requestNumber, setRequestNumber] = useState(0);
  const [status, setStatus] = useState<"idle" | "requesting" | "active">(
    "idle",
  );
  const [error, setError] = useState("");

  useEffect(() => {
    apiRequest<PresenceResponse>("/api/presence/current", {}, token)
      .then((response) => {
        onPlacesChange(response.places);
        onNearbyUsersChange(response.nearby_users);
        if (response.places.length) {
          setStatus("active");
        }
      })
      .catch(() => undefined);
  }, [token, onPlacesChange, onNearbyUsersChange]);

  useEffect(() => {
    if (requestNumber === 0) {
      return;
    }
    if (!navigator.geolocation) {
      setError("This browser does not support location sharing.");
      return;
    }

    let active = true;
    let sending = false;
    let latestCoordinates: { latitude: number; longitude: number } | null = null;
    setStatus("requesting");
    setError("");

    async function sendHeartbeat(latitude: number, longitude: number) {
      if (sending) {
        return;
      }
      sending = true;
      try {
        const response = await apiRequest<PresenceResponse>(
          "/api/presence/heartbeat",
          {
            method: "POST",
            body: JSON.stringify({ latitude, longitude }),
          },
          token,
        );
        if (active) {
          onPlacesChange(response.places);
          onNearbyUsersChange(response.nearby_users);
          setStatus("active");
          setError("");
        }
      } catch (caught) {
        if (active) {
          setError(
            caught instanceof Error
              ? caught.message
              : "Could not detect your place",
          );
          setStatus("idle");
        }
      } finally {
        sending = false;
      }
    }

    const watchId = navigator.geolocation.watchPosition(
      (position) => {
        latestCoordinates = {
          latitude: position.coords.latitude,
          longitude: position.coords.longitude,
        };
        void sendHeartbeat(
          latestCoordinates.latitude,
          latestCoordinates.longitude,
        );
      },
      (locationError) => {
        if (active) {
          setError(
            locationError.message || "Location permission was not granted.",
          );
          setStatus("idle");
        }
      },
      { enableHighAccuracy: true, maximumAge: 15_000, timeout: 12_000 },
    );

    const intervalId = window.setInterval(() => {
      if (latestCoordinates) {
        void sendHeartbeat(
          latestCoordinates.latitude,
          latestCoordinates.longitude,
        );
      }
    }, 30_000);

    const leaveOnPageExit = () => {
      void fetch("/api/presence/leave", {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
        keepalive: true,
      });
    };
    window.addEventListener("pagehide", leaveOnPageExit);

    return () => {
      active = false;
      navigator.geolocation.clearWatch(watchId);
      window.clearInterval(intervalId);
      window.removeEventListener("pagehide", leaveOnPageExit);
    };
  }, [requestNumber, token, onPlacesChange, onNearbyUsersChange]);

  return (
    <section className="presence-panel">
      <div className="presence-heading">
        <div>
          <p className="eyebrow">Your place</p>
          <h3>{places.length ? "Location detected" : "Share your location"}</h3>
        </div>
        {status === "active" && <span className="live-badge">Live</span>}
      </div>

      {places.length > 0 && (
        <ol className="place-list">
          {places.map((place) => (
            <li key={place.id}>
              <span>{place.display_name}</span>
              <small>{place.rank}</small>
            </li>
          ))}
        </ol>
      )}

      {error && <p className="location-error">{error}</p>}
      <button
        className="button"
        disabled={status === "requesting"}
        onClick={() => setRequestNumber((value) => value + 1)}
        type="button"
      >
        <Icon name="locate" size={18} />
        {status === "requesting"
          ? "Detecting place..."
          : status === "active"
            ? "Refresh location"
            : "Share my location"}
      </button>
      <p className="location-note">
        Presence expires after 90 seconds without a location heartbeat.
      </p>
    </section>
  );
}

function KnockPanel({
  token,
  user,
  places,
}: {
  token: string;
  user: User;
  places: CurrentPlace[];
}) {
  const socketRef = useRef<WebSocket | null>(null);
  const feedRef = useRef<HTMLDivElement | null>(null);
  const pendingIdRef = useRef(-1);
  const [messages, setMessages] = useState<KnockMessage[]>([]);
  const [pendingMessages, setPendingMessages] = useState<PendingKnock[]>([]);
  const [connection, setConnection] = useState<
    "waiting" | "connecting" | "connected" | "disconnected"
  >("waiting");
  const [draft, setDraft] = useState("");
  const [error, setError] = useState("");
  const placeKey = places.map((place) => place.id).join(",");

  useEffect(() => {
    scrollFeedToEnd(feedRef.current);
  }, [messages.length, pendingMessages.length]);

  useEffect(() => {
    if (!places.length) {
      setMessages([]);
      setPendingMessages([]);
      setConnection("waiting");
      setError("");
      return;
    }

    let active = true;
    let reconnectTimer: number | undefined;

    Promise.all(
      places.map((place) =>
        apiRequest<KnockHistoryResponse>(
          `/api/knock/history?place_id=${place.id}`,
          {},
          token,
        ),
      ),
    )
      .then((histories) => {
        if (active) {
          const historyMessages = histories.flatMap(
            (history) => history.messages,
          );
          setMessages((current) =>
            mergeMessages([...historyMessages, ...current]),
          );
        }
      })
      .catch((caught) => {
        if (active) {
          setError(
            caught instanceof Error ? caught.message : "Could not load history",
          );
        }
      });

    function connect() {
      if (!active) {
        return;
      }
      setConnection("connecting");
      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      const socket = new WebSocket(
        `${protocol}//${window.location.host}/ws/knock?token=${encodeURIComponent(token)}`,
      );
      socketRef.current = socket;

      socket.onmessage = (event) => {
        const payload = JSON.parse(event.data);
        if (payload.type === "ready") {
          setConnection("connected");
          setError("");
        } else if (payload.type === "message") {
          const incoming = payload.message as KnockMessage;
          setMessages((current) =>
            mergeMessages([...current, incoming]),
          );
          if (incoming.user_id === user.id) {
            setPendingMessages((current) => {
              const matchIndex = current.findIndex(
                (pending) => pending.text === incoming.text,
              );
              return matchIndex === -1
                ? current
                : current.filter((_, index) => index !== matchIndex);
            });
          }
          setError("");
        } else if (payload.type === "error") {
          setPendingMessages((current) => current.slice(1));
          setError(payload.detail || "The KNOCK could not be sent.");
        }
      };

      socket.onclose = (event) => {
        if (!active) {
          return;
        }
        setConnection("disconnected");
        setPendingMessages([]);
        if (event.code === 4401) {
          setError("Your session expired. Log in again.");
          return;
        }
        if (event.code === 4403) {
          setError("Share your location to join nearby KNOCKS.");
          return;
        }
        reconnectTimer = window.setTimeout(connect, 2_000);
      };
    }

    connect();
    return () => {
      active = false;
      if (reconnectTimer !== undefined) {
        window.clearTimeout(reconnectTimer);
      }
      socketRef.current?.close();
      socketRef.current = null;
    };
  }, [token, placeKey]);

  function sendKnock(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const text = draft.trim();
    if (!text) {
      return;
    }
    if (socketRef.current?.readyState !== WebSocket.OPEN) {
      setError("KNOCK is reconnecting. Try again in a moment.");
      return;
    }
    socketRef.current.send(JSON.stringify({ type: "message", text }));
    setPendingMessages((current) => [
      ...current,
      {
        id: pendingIdRef.current--,
        text,
        created_at: new Date().toISOString(),
      },
    ]);
    setDraft("");
  }

  if (!places.length) {
    return (
      <section className="knock-card knock-empty">
        <span className="knock-icon" aria-hidden="true"><Icon name="messages" size={28} /></span>
        <h2>Nearby KNOCKS appear here</h2>
        <p>Share your location to join the live conversation at your place.</p>
      </section>
    );
  }

  return (
    <section className="knock-card">
      <header className="knock-heading">
        <div>
          <p className="eyebrow">Live nearby</p>
          <h2>KNOCK</h2>
        </div>
        <span className={`socket-status socket-status--${connection}`}>
          {connection === "connected" ? "Connected" : connection}
        </span>
      </header>

      <div className="place-chips" aria-label="Active place layers">
        {places.map((place) => (
          <span key={place.id}>{place.display_name}</span>
        ))}
      </div>

      <div className="knock-feed" aria-live="polite" ref={feedRef}>
        {messages.length === 0 && pendingMessages.length === 0 ? (
          <div className="feed-empty">
            <p>No KNOCKS yet.</p>
            <span>Start the conversation at this place.</span>
          </div>
        ) : (
          <>
            {messages.map((message) => (
              <article
                className={`knock-message ${message.user_id === user.id ? "knock-message--own" : ""}`}
                key={message.id}
              >
                <div className="message-meta">
                  <strong>{message.nickname}</strong>
                  <span>
                    {message.origin_place_id === message.place_id
                      ? message.place_display_name
                      : `${message.origin_place_display_name} · shared with ${message.place_display_name}`}
                  </span>
                  <time dateTime={message.created_at}>
                    {new Date(message.created_at).toLocaleTimeString([], {
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
                  </time>
                </div>
                <p>{message.text}</p>
              </article>
            ))}
            {pendingMessages.map((message) => (
              <article
                className="knock-message knock-message--own moderation-pending"
                key={message.id}
              >
                <div className="message-meta">
                  <strong>{user.nickname}</strong>
                  <span className="pending-status">Checking</span>
                  <time dateTime={message.created_at}>
                    {new Date(message.created_at).toLocaleTimeString([], {
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
                  </time>
                </div>
                <p>{message.text}</p>
                <small className="pending-explanation">
                  Being checked · visible only to you
                </small>
              </article>
            ))}
          </>
        )}
      </div>

      {error && <p className="knock-error">{error}</p>}
      <form className="knock-composer" onSubmit={sendKnock}>
        <label htmlFor="knock-message">Send a KNOCK</label>
        <textarea
          id="knock-message"
          maxLength={500}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={submitTextOnEnter}
          placeholder="What is happening here?"
          rows={3}
          value={draft}
        />
        <div className="composer-footer">
          <small>{draft.length}/500</small>
          <button
            className="button"
            disabled={connection !== "connected" || !draft.trim()}
            type="submit"
          >
            <Icon name="send" size={17} />
            Send
          </button>
        </div>
      </form>
    </section>
  );
}

function DigMedia({
  dig,
  token,
  variant = "full",
}: {
  dig: Dig;
  token: string;
  variant?: "full" | "marker";
}) {
  const [source, setSource] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    let objectUrl = "";
    fetch(dig.media_url, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((response) => {
        if (!response.ok) {
          throw new Error("Media is no longer available");
        }
        return response.blob();
      })
      .then((blob) => {
        if (active) {
          objectUrl = URL.createObjectURL(blob);
          setSource(objectUrl);
        }
      })
      .catch((caught) => {
        if (active) {
          setError(caught instanceof Error ? caught.message : "Media unavailable");
        }
      });

    return () => {
      active = false;
      if (objectUrl) {
        URL.revokeObjectURL(objectUrl);
      }
    };
  }, [dig.id, dig.media_url, token]);

  if (error) {
    return <p className="dig-media-state">{error}</p>;
  }
  if (!source) {
    return <span className="dig-media-state">Loading...</span>;
  }
  if (dig.media_type === "video") {
    return (
      <video
        className={`dig-media dig-media--${variant}`}
        controls={variant === "full"}
        muted={variant === "marker"}
        playsInline
        preload="metadata"
        src={source}
      />
    );
  }
  return (
    <img
      alt={`DIG shared by ${dig.nickname} from ${dig.origin_place_display_name}`}
      className={`dig-media dig-media--${variant}`}
      src={source}
    />
  );
}

function formatDigAge(createdAt: string, now: number) {
  const elapsedMinutes = Math.max(
    1,
    Math.floor((now - new Date(createdAt).getTime()) / 60_000),
  );

  if (elapsedMinutes < 60) {
    return `${elapsedMinutes} ${elapsedMinutes === 1 ? "minute" : "minutes"} ago`;
  }

  const elapsedHours = Math.floor(elapsedMinutes / 60);
  return `${elapsedHours} ${elapsedHours === 1 ? "hour" : "hours"} ago`;
}

function DigSharedTime({ createdAt }: { createdAt: string }) {
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    const intervalId = window.setInterval(() => setNow(Date.now()), 60_000);
    return () => window.clearInterval(intervalId);
  }, []);

  return <time dateTime={createdAt}>{formatDigAge(createdAt, now)}</time>;
}

function DigPanel({
  token,
  places,
}: {
  token: string;
  places: CurrentPlace[];
}) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [digs, setDigs] = useState<Dig[]>([]);
  const [refreshNumber, setRefreshNumber] = useState(0);
  const [uploading, setUploading] = useState(false);
  const [composerOpen, setComposerOpen] = useState(false);
  const [selectedDig, setSelectedDig] = useState<Dig | null>(null);
  const [pendingDig, setPendingDig] = useState<PendingDig | null>(null);
  const [selectedFilename, setSelectedFilename] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const placeKey = places.map((place) => place.id).join(",");

  useEffect(() => {
    if (!places.length) {
      setDigs([]);
      return;
    }

    let active = true;
    setError("");
    Promise.all(
      places.map((place) =>
        apiRequest<DigFeedResponse>(
          `/api/digs?place_id=${place.id}`,
          {},
          token,
        ),
      ),
    )
      .then((feeds) => {
        if (!active) {
          return;
        }
        const unique = new Map<number, Dig>();
        feeds.flatMap((feed) => feed.digs).forEach((dig) => unique.set(dig.id, dig));
        setDigs(
          [...unique.values()].sort(
            (left, right) =>
              new Date(right.created_at).getTime() -
              new Date(left.created_at).getTime(),
          ),
        );
      })
      .catch((caught) => {
        if (active) {
          setError(caught instanceof Error ? caught.message : "Could not load DIGs");
        }
      });
    return () => {
      active = false;
    };
  }, [placeKey, places, refreshNumber, token]);

  async function uploadDig(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const selectedFile = inputRef.current?.files?.[0];
    if (!selectedFile) {
      setError("Choose a media file.");
      return;
    }
    if (selectedFile.size > 10 * 1024 * 1024) {
      setError("DIG uploads cannot exceed 10 MB.");
      return;
    }

    setUploading(true);
    setError("");
    setNotice("");
    const originPlace = places[places.length - 1];
    const previewUrl = URL.createObjectURL(selectedFile);
    setPendingDig({
      id: -Date.now(),
      nickname: "You",
      place_name: originPlace?.name ?? "Nearby place",
      place_display_name: originPlace?.display_name ?? "Nearby place",
      media_type: selectedFile.type.startsWith("video/") ? "video" : "image",
      preview_url: previewUrl,
    });
    setComposerOpen(false);
    const form = new FormData();
    form.set("file", selectedFile);
    try {
      const published = await apiRequest<Dig>(
        "/api/digs",
        { method: "POST", body: form },
        token,
      );
      if (inputRef.current) {
        inputRef.current.value = "";
      }
      setNotice(
        `DIG shared with ${published.place_display_name}. It will disappear after 24 hours.`,
      );
      setDigs((current) => [published, ...current]);
      setRefreshNumber((value) => value + 1);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Upload failed");
      setComposerOpen(true);
    } finally {
      setPendingDig(null);
      setSelectedFilename("");
      URL.revokeObjectURL(previewUrl);
      setUploading(false);
    }
  }

  if (!places.length) {
    return null;
  }

  return (
    <div
      className={`dig-map-layer ${selectedDig ? "dig-map-layer--expanded" : ""}`}
      aria-live="polite"
    >
      {pendingDig && (
        <div
          className="dig-map-marker dig-map-marker--pending"
          style={{ left: "46%", top: "24%" }}
        >
          <span className="dig-marker-shell moderation-pending">
            {pendingDig.media_type === "video" ? (
              <video
                className="dig-media dig-media--marker"
                muted
                playsInline
                src={pendingDig.preview_url}
              />
            ) : (
              <img
                alt="Your DIG being checked"
                className="dig-media dig-media--marker"
                src={pendingDig.preview_url}
              />
            )}
          </span>
          <span className="dig-marker-name pending-marker-label">
            Checking · only you
          </span>
        </div>
      )}
      {digs.map((dig, index) => {
        const positions = [
          [18, 24], [71, 18], [31, 68], [77, 64],
          [52, 34], [12, 52], [61, 76], [85, 39],
        ];
        const [left, top] = positions[index % positions.length];
        return (
          <button
            aria-label={`Open DIG by ${dig.nickname} from ${dig.origin_place_display_name}`}
            className="dig-map-marker"
            key={dig.id}
            onClick={() => setSelectedDig(dig)}
            style={{ left: `${left}%`, top: `${top}%` }}
            type="button"
          >
            <span className="dig-marker-shell">
              <DigMedia dig={dig} token={token} variant="marker" />
            </span>
            <span className="dig-marker-name">{dig.nickname}</span>
          </button>
        );
      })}

      <div className="map-dig-toolbar">
        <button
          className="map-dig-add"
          disabled={uploading}
          onClick={() => {
            if (composerOpen) {
              setSelectedFilename("");
            }
            setComposerOpen((open) => !open);
          }}
          type="button"
        >
          <Icon name="camera" size={18} />
          {uploading ? "Checking DIG..." : "Add DIG"}
        </button>
      </div>

      {digs.length === 0 && !composerOpen && (
        <button
          className="dig-map-empty"
          onClick={() => setComposerOpen(true)}
          type="button"
        >
          <Icon name="plus" size={18} />
          Be the first to leave a DIG here
        </button>
      )}

      {composerOpen && (
        <section className="dig-upload-popover" aria-label="Add a DIG">
          <header className="popover-header">
            <div>
              <p className="eyebrow">Visible for 24 hours</p>
              <h2>Add a DIG</h2>
            </div>
            <button
              aria-label="Close DIG upload"
              className="icon-button"
              onClick={() => {
                setComposerOpen(false);
                setSelectedFilename("");
              }}
              type="button"
            >
              <Icon name="x" />
            </button>
          </header>
          <form className="dig-composer" onSubmit={uploadDig}>
            <small>
              The audience is chosen automatically from your current place hierarchy.
            </small>
            <label className="dig-file-field">
              Image or short video
              <span className="dig-file-picker">
                <input
                  accept="image/jpeg,image/png,image/webp,video/mp4,video/webm"
                  aria-label="Choose an image or short video"
                  onChange={(event) =>
                    setSelectedFilename(event.target.files?.[0]?.name ?? "")
                  }
                  ref={inputRef}
                  required
                  type="file"
                />
                <span className="dig-file-action">
                  <Icon name="camera" size={18} />
                  Browse media
                </span>
                <span className="dig-file-name">
                  {selectedFilename || "No file selected"}
                </span>
              </span>
            </label>
            <small>JPEG, PNG, WebP, MP4, or WebM. Up to 10 MB and 15 seconds.</small>
            <button className="button" disabled={uploading} type="submit">
              <Icon name="camera" size={17} />
              {uploading ? "Checking..." : "Post DIG"}
            </button>
          </form>
          {error && <p className="knock-error">{error}</p>}
        </section>
      )}

      {notice && <p className="dig-map-notice">{notice}</p>}
      {error && !composerOpen && <p className="dig-map-notice dig-map-notice--error">{error}</p>}

      {selectedDig && (
        <article className="dig-expanded-card">
          <header className="popover-header">
            <div>
              <span className="dig-author-row">
                <strong>{selectedDig.nickname}</strong>
                <DigSharedTime createdAt={selectedDig.created_at} />
              </span>
              <span>{selectedDig.origin_place_display_name}</span>
              {selectedDig.origin_place_id !== selectedDig.place_id && (
                <small>Shared with {selectedDig.place_display_name}</small>
              )}
            </div>
            <button
              aria-label="Close DIG"
              className="icon-button"
              onClick={() => setSelectedDig(null)}
              type="button"
            >
              <Icon name="x" />
            </button>
          </header>
          <DigMedia dig={selectedDig} token={token} />
        </article>
      )}
    </div>
  );
}

function ExploreMedia({
  dig,
  token,
  variant = "full",
}: {
  dig: ExploreDig;
  token: string;
  variant?: "full" | "thumbnail";
}) {
  const [source, setSource] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    let objectUrl = "";
    fetch(dig.media_url, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((response) => {
        if (!response.ok) {
          throw new Error("Memory media is unavailable");
        }
        return response.blob();
      })
      .then((blob) => {
        if (active) {
          objectUrl = URL.createObjectURL(blob);
          setSource(objectUrl);
        }
      })
      .catch((caught) => {
        if (active) {
          setError(caught instanceof Error ? caught.message : "Media unavailable");
        }
      });

    return () => {
      active = false;
      if (objectUrl) {
        URL.revokeObjectURL(objectUrl);
      }
    };
  }, [dig.id, dig.media_url, token]);

  if (error) {
    return <p className="dig-media-state">{error}</p>;
  }
  if (!source) {
    return <p className="dig-media-state">Loading memory...</p>;
  }
  if (dig.media_type === "video") {
    return (
      <video
        className={`dig-media explore-media--${variant}`}
        controls={variant === "full"}
        muted={variant === "thumbnail"}
        playsInline
        preload="metadata"
        src={source}
      />
    );
  }
  return (
    <img
      alt={`Memory shared by ${dig.nickname}`}
      className={`dig-media explore-media--${variant}`}
      src={source}
    />
  );
}

function ExploreMemoryCard({
  memory,
  token,
  onChange,
}: {
  memory: ExploreMemory;
  token: string;
  onChange: (memory: ExploreMemory) => void;
}) {
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [error, setError] = useState("");

  async function toggleLike() {
    setBusy(true);
    setError("");
    try {
      const reaction = await apiRequest<ExploreLikeResponse>(
        `/api/explore/${memory.id}/likes`,
        { method: memory.liked_by_me ? "DELETE" : "POST" },
        token,
      );
      onChange({ ...memory, ...reaction });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not update like");
    } finally {
      setBusy(false);
    }
  }

  async function addComment(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const text = draft.trim();
    if (!text) {
      return;
    }
    setBusy(true);
    setError("");
    try {
      const comment = await apiRequest<ExploreComment>(
        `/api/explore/${memory.id}/comments`,
        { method: "POST", body: JSON.stringify({ text }) },
        token,
      );
      onChange({ ...memory, comments: [...memory.comments, comment] });
      setDraft("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not add comment");
    } finally {
      setBusy(false);
    }
  }

  const placeNames = memory.place_names?.length
    ? memory.place_names
    : [memory.place_display_name];
  const participantCount = memory.participant_count
    ?? new Set(memory.digs.map((dig) => dig.user_id)).size;

  return (
    <>
      <article className="explore-memory-summary">
        <button
          className="memory-summary-button"
          onClick={() => setExpanded(true)}
          type="button"
        >
          <span className="memory-summary-preview">
            {memory.digs[0] ? (
              <ExploreMedia dig={memory.digs[0]} token={token} variant="thumbnail" />
            ) : (
              <Icon name="compass" size={24} />
            )}
          </span>
          <span className="memory-summary-copy">
            <span className="memory-summary-heading">
              <strong>{memory.place_display_name}</strong>
              <span className="memory-access">
                {memory.participant ? "Your memory" : "Here now"}
              </span>
            </span>
            <span className="place-path" aria-label="Nested places">
              {placeNames.map((name) => <span key={name}>{name}</span>)}
            </span>
            <span className="memory-summary-stats">
              <span><Icon name="user" size={15} /> {participantCount} participants</span>
              <span><Icon name="messages" size={15} /> {memory.comments.length} comments</span>
              <span>{memory.like_count} likes</span>
            </span>
            <time dateTime={memory.created_at}>
              {new Date(memory.created_at).toLocaleString()}
            </time>
          </span>
        </button>
      </article>

      {expanded && (
        <section
          aria-label={`Memory at ${memory.place_display_name}`}
          aria-modal="true"
          className="content-detail-window memory-detail-window"
          role="dialog"
        >
          <header className="content-detail-heading">
            <div>
              <p className="eyebrow">Long-term place memory</p>
              <h2>{memory.place_display_name}</h2>
            </div>
            <button
              aria-label="Close memory"
              className="icon-button"
              onClick={() => setExpanded(false)}
              type="button"
            >
              <Icon name="x" />
            </button>
          </header>
          <div className="content-detail-scroll">
            <div className="memory-detail-context">
              <span className="place-path" aria-label="Nested places">
                {placeNames.map((name) => <span key={name}>{name}</span>)}
              </span>
              <strong>{participantCount} distinct participants</strong>
            </div>

            <div className="explore-media-grid">
              {memory.digs.map((dig) => (
                <div className="explore-media-item" key={dig.id}>
                  <ExploreMedia dig={dig} token={token} />
                  <span>{dig.nickname}</span>
                </div>
              ))}
            </div>

            <div className="explore-actions">
              <button
                className={`button button--secondary ${memory.liked_by_me ? "explore-liked" : ""}`}
                disabled={busy}
                onClick={() => void toggleLike()}
                type="button"
              >
                {memory.liked_by_me ? "Liked" : "Like"} · {memory.like_count}
              </button>
              <span>{memory.comments.length} comments</span>
            </div>

            <div className="explore-comments">
              {memory.comments.length === 0 ? (
                <p className="explore-comment-empty">No comments yet.</p>
              ) : (
                memory.comments.map((comment) => (
                  <div className="explore-comment" key={comment.id}>
                    <strong>{comment.nickname}</strong>
                    <p>{comment.text}</p>
                    <time dateTime={comment.created_at}>
                      {new Date(comment.created_at).toLocaleString()}
                    </time>
                  </div>
                ))
              )}
            </div>

            {error && <p className="knock-error">{error}</p>}
            <form className="explore-comment-form" onSubmit={addComment}>
              <label htmlFor={`memory-comment-${memory.id}`}>Add a comment</label>
              <div>
                <input
                  id={`memory-comment-${memory.id}`}
                  maxLength={500}
                  onChange={(event) => setDraft(event.target.value)}
                  placeholder="What do you remember?"
                  value={draft}
                />
                <button className="button" disabled={busy || !draft.trim()} type="submit">
                  Post
                </button>
              </div>
            </form>
          </div>
        </section>
      )}
    </>
  );
}

function ExplorePanel({
  token,
  places,
}: {
  token: string;
  places: CurrentPlace[];
}) {
  const [memories, setMemories] = useState<ExploreMemory[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const placeKey = places.map((place) => place.id).join(",");

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    apiRequest<ExploreFeedResponse>("/api/explore", {}, token)
      .then((response) => {
        if (active) {
          setMemories(response.memories);
        }
      })
      .catch((caught) => {
        if (active) {
          setError(caught instanceof Error ? caught.message : "Could not load memories");
        }
      })
      .finally(() => {
        if (active) {
          setLoading(false);
        }
      });
    return () => {
      active = false;
    };
  }, [placeKey, token]);

  function updateMemory(updated: ExploreMemory) {
    setMemories((current) =>
      current.map((memory) => (memory.id === updated.id ? updated : memory)),
    );
  }

  return (
    <section className="knock-card explore-card">
      <header className="knock-heading">
        <div>
          <p className="eyebrow">Long-term place memory</p>
          <h2>Explore</h2>
        </div>
        <span className="memory-permanent">Permanent</span>
      </header>

      {error && <p className="knock-error">{error}</p>}
      <div className="explore-feed" aria-live="polite">
        {loading ? (
          <div className="feed-empty"><p>Loading memories...</p></div>
        ) : memories.length === 0 ? (
          <div className="feed-empty">
            <p>No accessible memories yet.</p>
            <span>Three nearby DIGs within an hour can create one.</span>
          </div>
        ) : (
          memories.map((memory) => (
            <ExploreMemoryCard
              key={memory.id}
              memory={memory}
              onChange={updateMemory}
              token={token}
            />
          ))
        )}
      </div>
    </section>
  );
}

function ForumPostCard({
  post,
  token,
  onChanged,
}: {
  post: ForumPost;
  token: string;
  onChanged: () => void;
}) {
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [error, setError] = useState("");

  async function vote(value: 1 | -1) {
    setBusy(true);
    setError("");
    try {
      if (post.my_vote === value) {
        await apiRequest(`/api/forum/posts/${post.id}/vote`, { method: "DELETE" }, token);
      } else {
        await apiRequest(
          `/api/forum/posts/${post.id}/vote`,
          { method: "PUT", body: JSON.stringify({ value }) },
          token,
        );
      }
      onChanged();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not update vote");
    } finally {
      setBusy(false);
    }
  }

  async function submitComment(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const text = comment.trim();
    if (!text) {
      return;
    }
    setBusy(true);
    setError("");
    try {
      await apiRequest<ForumComment>(
        `/api/forum/posts/${post.id}/comments`,
        { method: "POST", body: JSON.stringify({ text }) },
        token,
      );
      setComment("");
      onChanged();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not add comment");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <article className="forum-post-summary">
        <button
          className="forum-summary-button"
          onClick={() => setExpanded(true)}
          type="button"
        >
          <span className="forum-summary-main">
            <span className="forum-summary-meta">
              <strong>{post.nickname}{post.is_mine ? " · You" : ""}</strong>
              <span>{post.place_display_name}</span>
            </span>
            <strong className="forum-summary-title">{post.title}</strong>
            <span className="forum-summary-excerpt">{post.body}</span>
          </span>
          <span className="forum-summary-side">
            <span className="score-pill">{post.score} score</span>
            <span><Icon name="messages" size={15} /> {post.comments.length} comments</span>
            <time dateTime={post.created_at}>
              {new Date(post.created_at).toLocaleDateString()}
            </time>
          </span>
        </button>
      </article>

      {expanded && (
        <section
          aria-label={post.title}
          aria-modal="true"
          className="content-detail-window forum-detail-window"
          role="dialog"
        >
          <header className="content-detail-heading">
            <div>
              <p className="eyebrow">{post.place_display_name}</p>
              <h2>{post.title}</h2>
              <span>Posted by {post.nickname}{post.is_mine ? " · You" : ""}</span>
            </div>
            <button
              aria-label="Close forum post"
              className="icon-button"
              onClick={() => setExpanded(false)}
              type="button"
            >
              <Icon name="x" />
            </button>
          </header>
          <div className="content-detail-scroll">
            <div className="forum-post-copy">
              <p>{post.body}</p>
              <time dateTime={post.created_at}>
                {new Date(post.created_at).toLocaleString()}
              </time>
            </div>
            <div className="forum-votes" aria-label={`Score ${post.score}`}>
              <button
                className={post.my_vote === 1 ? "active" : ""}
                disabled={busy}
                onClick={() => void vote(1)}
                type="button"
              >
                ▲ {post.upvotes}
              </button>
              <strong>{post.score} score</strong>
              <button
                className={post.my_vote === -1 ? "active" : ""}
                disabled={busy}
                onClick={() => void vote(-1)}
                type="button"
              >
                ▼ {post.downvotes}
              </button>
            </div>
            <div className="forum-comments">
              {post.comments.map((item) => (
                <div className="forum-comment" key={item.id}>
                  <strong>{item.nickname}</strong>
                  <p>{item.text}</p>
                  <time dateTime={item.created_at}>
                    {new Date(item.created_at).toLocaleString()}
                  </time>
                </div>
              ))}
              {post.comments.length === 0 && <p className="forum-no-comments">No comments yet.</p>}
            </div>
            {error && <p className="knock-error">{error}</p>}
            <form className="forum-comment-form" onSubmit={submitComment}>
              <input
                aria-label={`Comment on ${post.title}`}
                maxLength={1000}
                onChange={(event) => setComment(event.target.value)}
                placeholder="Add a comment"
                value={comment}
              />
              <button className="button" disabled={busy || !comment.trim()} type="submit">
                Reply
              </button>
            </form>
          </div>
        </section>
      )}
    </>
  );
}

function ForumPanel({
  token,
  places,
  user,
}: {
  token: string;
  places: CurrentPlace[];
  user: User;
}) {
  const [mode, setMode] = useState<"place" | "mine">("place");
  const [selectedPlaceId, setSelectedPlaceId] = useState("");
  const [posts, setPosts] = useState<ForumPost[]>([]);
  const [personal, setPersonal] = useState<PersonalForumResponse | null>(null);
  const [refreshNumber, setRefreshNumber] = useState(0);
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [composerOpen, setComposerOpen] = useState(false);
  const [pendingPosts, setPendingPosts] = useState<PendingForumPost[]>([]);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const placeKey = places.map((place) => place.id).join(",");

  useEffect(() => {
    if (!places.length) {
      setSelectedPlaceId("");
      return;
    }
    if (!places.some((place) => String(place.id) === selectedPlaceId)) {
      setSelectedPlaceId(String(places[places.length - 1].id));
    }
  }, [placeKey, places, selectedPlaceId]);

  useEffect(() => {
    let active = true;
    setError("");
    if (mode === "place" && !selectedPlaceId) {
      setPosts([]);
      setPersonal(null);
      setLoading(false);
      return;
    }

    setLoading(true);
    async function loadForum() {
      try {
        if (mode === "mine") {
          const response = await apiRequest<PersonalForumResponse>(
            "/api/forum/me",
            {},
            token,
          );
          if (active) {
            setPersonal(response);
            setPosts(response.posts);
          }
        } else {
          const response = await apiRequest<ForumFeedResponse>(
            `/api/forum?place_id=${selectedPlaceId}`,
            {},
            token,
          );
          if (active) {
            setPersonal(null);
            setPosts(response.posts);
          }
        }
      } catch (caught) {
        if (active) {
          setError(caught instanceof Error ? caught.message : "Could not load forum");
        }
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    }
    void loadForum();
    return () => {
      active = false;
    };
  }, [mode, refreshNumber, selectedPlaceId, token]);

  async function submitPost(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    const title = String(form.get("title") || "");
    const body = String(form.get("body") || "");
    const isAnonymous = form.get("anonymous") === "on";
    const selectedPlace = places.find(
      (place) => String(place.id) === selectedPlaceId,
    );
    const originPlace = places[places.length - 1] ?? selectedPlace;
    const pendingPlace = selectedPlace ?? originPlace;
    const pendingId = -Date.now();
    const pendingPost: PendingForumPost = {
      id: pendingId,
      place_id: pendingPlace?.id ?? 0,
      place_name: pendingPlace?.name ?? "Nearby place",
      place_display_name: pendingPlace?.display_name ?? "Nearby place",
      origin_place_id: originPlace?.id ?? pendingPlace?.id ?? 0,
      origin_place_name: originPlace?.name ?? "Nearby place",
      origin_place_display_name: originPlace?.display_name ?? "Nearby place",
      user_id: isAnonymous ? null : user.id,
      nickname: isAnonymous ? "Anonymous" : user.nickname,
      is_anonymous: isAnonymous,
      is_mine: true,
      title,
      body,
      upvotes: 0,
      downvotes: 0,
      score: 0,
      my_vote: 0,
      created_at: new Date().toISOString(),
      comments: [],
      pending: true,
    };
    setSubmitting(true);
    setComposerOpen(false);
    setPendingPosts((current) => [pendingPost, ...current]);
    setError("");
    setNotice("");
    try {
      const published = await apiRequest<ForumPost>(
        "/api/forum/posts",
        {
          method: "POST",
          body: JSON.stringify({
            title,
            body,
            is_anonymous: isAnonymous,
          }),
        },
        token,
      );
      formElement.reset();
      setPendingPosts((current) => current.filter((post) => post.id !== pendingId));
      setPosts((current) => [published, ...current.filter((post) => post.id !== published.id)]);
      setSelectedPlaceId(String(published.place_id));
      setNotice(`Forum post shared with ${published.place_display_name}.`);
      setRefreshNumber((value) => value + 1);
    } catch (caught) {
      setPendingPosts((current) => current.filter((post) => post.id !== pendingId));
      setError(caught instanceof Error ? caught.message : "Could not publish post");
      setComposerOpen(true);
    } finally {
      setSubmitting(false);
    }
  }

  const visiblePendingPosts = pendingPosts.filter(
    (post) => mode === "mine" || post.place_id === Number(selectedPlaceId),
  );

  return (
    <section className="knock-card forum-card">
      <header className="knock-heading">
        <div>
          <p className="eyebrow">Place discussions</p>
          <h2>Forum</h2>
        </div>
        <div className="forum-heading-actions">
          {mode === "place" && places.length > 0 && (
            <label className="forum-place-picker">
              <span>Viewing</span>
              <select
                aria-label="Forum place"
                onChange={(event) => setSelectedPlaceId(event.target.value)}
                value={selectedPlaceId}
              >
                {places.map((place) => (
                  <option key={place.id} value={place.id}>{place.display_name}</option>
                ))}
              </select>
            </label>
          )}
          {mode === "place" && places.length > 0 && (
            <button
              className="button forum-create-button"
              disabled={submitting}
              onClick={() => setComposerOpen(true)}
              type="button"
            >
              <Icon name="plus" size={17} />
              {submitting ? "Checking post..." : "Create post"}
            </button>
          )}
          <div className="forum-mode-tabs">
            <button
              className={mode === "place" ? "active" : ""}
              onClick={() => setMode("place")}
              type="button"
            >
              Place
            </button>
            <button
              className={mode === "mine" ? "active" : ""}
              onClick={() => setMode("mine")}
              type="button"
            >
              My posts
            </button>
          </div>
        </div>
      </header>

      {composerOpen && mode === "place" && places.length > 0 && (
        <section
          aria-label="Create forum post"
          aria-modal="true"
          className="forum-create-window"
          role="dialog"
        >
          <header className="content-detail-heading">
            <div>
              <p className="eyebrow">Place discussion</p>
              <h2>Create a post</h2>
            </div>
            <button
              aria-label="Close post form"
              className="icon-button"
              onClick={() => setComposerOpen(false)}
              type="button"
            >
              <Icon name="x" />
            </button>
          </header>
          <form className="forum-composer" onSubmit={submitPost}>
            <small>
              The audience is chosen automatically from your current place hierarchy.
            </small>
            <label>
              Title
              <input maxLength={120} name="title" required />
            </label>
            <label>
              Post
              <textarea maxLength={1800} name="body" required rows={4} />
            </label>
            <div className="forum-composer-footer">
              <label className="checkbox-label">
                <input name="anonymous" type="checkbox" />
                Post anonymously
              </label>
              <button className="button" disabled={submitting} type="submit">
                Publish
              </button>
            </div>
          </form>
        </section>
      )}

      {mode === "place" && places.length === 0 && (
        <div className="forum-location-empty">
          <strong>Share your location to open a place forum.</strong>
          <span>Your own posts remain available under My posts.</span>
        </div>
      )}

      {mode === "mine" && personal && (
        <div className="forum-personal-summary">
          <span><strong>{personal.posts.length}</strong> posts</span>
          <span><strong>{personal.total_upvotes}</strong> likes</span>
          <span><strong>{personal.total_downvotes}</strong> dislikes</span>
          <span><strong>{personal.total_score}</strong> total score</span>
        </div>
      )}

      {notice && <p className="dig-notice">{notice}</p>}
      {error && <p className="knock-error">{error}</p>}
      <div className="forum-feed" aria-live="polite">
        {loading ? (
          <div className="feed-empty"><p>Loading forum...</p></div>
        ) : posts.length === 0 && visiblePendingPosts.length === 0 ? (
          <div className="feed-empty">
            <p>{mode === "mine" ? "You have not posted yet." : "No forum posts yet."}</p>
            <span>{mode === "mine" ? "Your posts will appear here." : "Start a place discussion."}</span>
          </div>
        ) : (
          <>
            {visiblePendingPosts.map((post) => (
              <article className="forum-post-summary moderation-pending" key={post.id}>
                <div className="forum-summary-button forum-summary-button--pending">
                  <span className="forum-summary-main">
                    <span className="forum-summary-meta">
                      <strong>{post.nickname} · You</strong>
                      <span>{post.place_display_name}</span>
                    </span>
                    <strong className="forum-summary-title">{post.title}</strong>
                    <span className="forum-summary-excerpt">{post.body}</span>
                  </span>
                  <span className="forum-summary-side">
                    <span className="pending-status">Checking</span>
                    <span>Visible only to you</span>
                  </span>
                </div>
              </article>
            ))}
            {posts.map((post) => (
              <ForumPostCard
                key={post.id}
                onChanged={() => setRefreshNumber((value) => value + 1)}
                post={post}
                token={token}
              />
            ))}
          </>
        )}
      </div>
    </section>
  );
}

function DMPanel({
  token,
  user,
  chatRequest,
  incomingMessage,
  socketStatus,
  onUnreadChange,
  sidebarOpen,
  onSidebarClose,
}: {
  token: string;
  user: User;
  chatRequest: DMChatRequest | null;
  incomingMessage: DMMessage | null;
  socketStatus: "connecting" | "connected" | "disconnected";
  onUnreadChange: (count: number) => void;
  sidebarOpen: boolean;
  onSidebarClose: () => void;
}) {
  const messagesRef = useRef<HTMLDivElement | null>(null);
  const processedIncomingMessageIdRef = useRef<number | null>(null);
  const [conversations, setConversations] = useState<DMConversation[]>([]);
  const [selectedUser, setSelectedUser] = useState<DMUser | null>(null);
  const [messages, setMessages] = useState<DMMessage[]>([]);
  const [searchResults, setSearchResults] = useState<DMUser[]>([]);
  const [draft, setDraft] = useState("");
  const [loading, setLoading] = useState(false);
  const [sending, setSending] = useState(false);
  const [chatMinimized, setChatMinimized] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!chatRequest) {
      return;
    }
    setSelectedUser(chatRequest.user);
    setChatMinimized(false);
    setSearchResults([]);
    setError("");
    onSidebarClose();
  }, [chatRequest?.requestId]);

  useLayoutEffect(() => {
    if (chatMinimized || loading || !messagesRef.current) {
      return;
    }
    const messageFeed = messagesRef.current;
    messageFeed.scrollTop = messageFeed.scrollHeight;
    const frameId = window.requestAnimationFrame(() => {
      messageFeed.scrollTop = messageFeed.scrollHeight;
    });
    return () => window.cancelAnimationFrame(frameId);
  }, [chatMinimized, loading, messages.length, selectedUser?.id]);

  useEffect(() => {
    let active = true;
    apiRequest<DMConversationListResponse>(
      "/api/dms/conversations",
      {},
      token,
    )
      .then((response) => {
        if (active) {
          setConversations(response.conversations);
        }
      })
      .catch((caught) => {
        if (active) {
          setError(caught instanceof Error ? caught.message : "Could not load messages");
        }
      });
    return () => {
      active = false;
    };
  }, [token]);

  useEffect(() => {
    onUnreadChange(
      conversations.reduce(
        (total, conversation) => total + conversation.unread_count,
        0,
      ),
    );
  }, [conversations, onUnreadChange]);

  useEffect(() => {
    if (!selectedUser) {
      setMessages([]);
      return;
    }
    let active = true;
    setLoading(true);
    setError("");

    async function loadHistory() {
      try {
        const history = await apiRequest<DMHistoryResponse>(
          `/api/dms/${selectedUser!.id}`,
          {},
          token,
        );
        if (!active) {
          return;
        }
        setMessages(history.messages);
        setSelectedUser(history.user);
        await apiRequest<void>(
          `/api/dms/${history.user.id}/read`,
          { method: "POST" },
          token,
        );
        if (active) {
          setConversations((current) =>
            current.map((conversation) =>
              conversation.user.id === history.user.id
                ? { ...conversation, unread_count: 0 }
                : conversation,
            ),
          );
        }
      } catch (caught) {
        if (active) {
          setError(caught instanceof Error ? caught.message : "Could not load history");
        }
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    }
    void loadHistory();
    return () => {
      active = false;
    };
  }, [selectedUser?.id, token]);

  useEffect(() => {
    if (
      !incomingMessage ||
      processedIncomingMessageIdRef.current === incomingMessage.id
    ) {
      return;
    }
    processedIncomingMessageIdRef.current = incomingMessage.id;

    const otherUserId =
      incomingMessage.sender_id === user.id
        ? incomingMessage.recipient_id
        : incomingMessage.sender_id;
    const activeUserId = selectedUser?.id ?? null;

    if (otherUserId === activeUserId) {
      setMessages((current) => mergeDMMessages([...current, incomingMessage]));
      if (incomingMessage.recipient_id === user.id) {
        void apiRequest<void>(
          `/api/dms/${otherUserId}/read`,
          { method: "POST" },
          token,
        ).catch(() => undefined);
      }
    }

    const knownConversation = conversations.some(
      (conversation) => conversation.user.id === otherUserId,
    );
    setConversations((current) =>
      updateDMConversations(current, incomingMessage, user.id, activeUserId),
    );

    if (!knownConversation) {
      apiRequest<DMConversationListResponse>(
        "/api/dms/conversations",
        {},
        token,
      )
        .then((response) => setConversations(response.conversations))
        .catch(() => undefined);
    }
  }, [incomingMessage, selectedUser?.id, token, user.id]);

  async function searchUsers(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const query = String(form.get("query") || "").trim();
    if (query.length < 2) {
      setError("Enter at least two search characters.");
      return;
    }
    setError("");
    try {
      const response = await apiRequest<DMUserSearchResponse>(
        `/api/dms/users?query=${encodeURIComponent(query)}`,
        {},
        token,
      );
      setSearchResults(response.users);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not search users");
    }
  }

  async function sendMessage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const text = draft.trim();
    if (!selectedUser || !text) {
      return;
    }
    setSending(true);
    setError("");
    try {
      const message = await apiRequest<DMMessage>(
        "/api/dms/messages",
        {
          method: "POST",
          body: JSON.stringify({ recipient_id: selectedUser.id, text }),
        },
        token,
      );
      setMessages((current) => mergeDMMessages([...current, message]));
      setConversations((current) =>
        updateDMConversations(
          current,
          message,
          user.id,
          selectedUser.id,
          selectedUser,
        ),
      );
      setDraft("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not send message");
    } finally {
      setSending(false);
    }
  }

  function openConversation(person: DMUser) {
    setSelectedUser(person);
    setChatMinimized(false);
    setSearchResults([]);
    setError("");
    onSidebarClose();
  }

  return (
    <div className="messaging-layer">
      {sidebarOpen && (
        <aside className="message-drawer">
          <header className="message-drawer-heading">
            <div>
              <p className="eyebrow">Private conversations</p>
              <h2>Messages</h2>
            </div>
            <div className="message-heading-actions">
              <span className={`socket-status socket-status--${socketStatus}`}>
                {socketStatus}
              </span>
              <button
                aria-label="Close messages"
                className="icon-button"
                onClick={onSidebarClose}
                type="button"
              >
                <Icon name="x" />
              </button>
            </div>
          </header>

          <form className="dm-search" onSubmit={searchUsers}>
            <input
              aria-label="Search users"
              maxLength={30}
              name="query"
              placeholder="Nickname or phone"
              required
            />
            <button aria-label="Find user" className="button" type="submit">
              <Icon name="search" size={17} />
              Find
            </button>
          </form>

          {searchResults.length > 0 && (
            <div className="dm-search-results">
              {searchResults.map((person) => (
                <button key={person.id} onClick={() => openConversation(person)} type="button">
                  <strong>{person.nickname}</strong>
                  {person.phone && <span>{person.phone}</span>}
                </button>
              ))}
            </div>
          )}

          <div className="dm-conversations">
            {conversations.length === 0 ? (
              <p>No conversations yet.</p>
            ) : (
              conversations.map((conversation) => (
                <button
                  className={selectedUser?.id === conversation.user.id ? "active" : ""}
                  key={conversation.user.id}
                  onClick={() => openConversation(conversation.user)}
                  type="button"
                >
                  <span>
                    <strong>{conversation.user.nickname}</strong>
                    <small>{conversation.last_message.text}</small>
                  </span>
                  {conversation.unread_count > 0 && (
                    <b>{conversation.unread_count}</b>
                  )}
                </button>
              ))
            )}
          </div>
          {error && <p className="knock-error">{error}</p>}
        </aside>
      )}

      {selectedUser && (
        <section className={`chat-window ${chatMinimized ? "chat-window--minimized" : ""}`}>
          <header className="dm-chat-heading">
            <span className="chat-avatar" aria-hidden="true">
              {selectedUser.nickname.slice(0, 1).toUpperCase()}
            </span>
            <span className="chat-person">
              <strong>{selectedUser.nickname}</strong>
              <small>{socketStatus === "connected" ? "Available" : "Reconnecting"}</small>
            </span>
            <span className="chat-window-actions">
              <button
                aria-label={chatMinimized ? "Restore chat" : "Minimize chat"}
                className="icon-button"
                onClick={() => setChatMinimized((value) => !value)}
                type="button"
              >
                {chatMinimized ? <Icon name="chevron-down" /> : <Icon name="minimize" />}
              </button>
              <button
                aria-label="Close chat"
                className="icon-button"
                onClick={() => setSelectedUser(null)}
                type="button"
              >
                <Icon name="x" />
              </button>
            </span>
          </header>
          {!chatMinimized && (
            <>
              <div className="dm-messages" aria-live="polite" ref={messagesRef}>
                {loading ? (
                  <p className="dm-loading">Loading messages...</p>
                ) : messages.length === 0 ? (
                  <p className="dm-loading">Start this private conversation.</p>
                ) : (
                  messages.map((message) => (
                    <article
                      className={message.sender_id === user.id ? "dm-message dm-message--own" : "dm-message"}
                      key={message.id}
                    >
                      <p>{message.text}</p>
                      <time dateTime={message.created_at}>
                        {new Date(message.created_at).toLocaleString()}
                      </time>
                    </article>
                  ))
                )}
              </div>
              <form className="dm-composer" onSubmit={sendMessage}>
                <textarea
                  maxLength={1000}
                  onChange={(event) => setDraft(event.target.value)}
                  onKeyDown={(event) => submitTextOnEnter(event, sending)}
                  placeholder={`Message ${selectedUser.nickname}`}
                  rows={2}
                  value={draft}
                />
                <button className="button" disabled={sending || !draft.trim()} type="submit">
                  <Icon name="send" size={17} />
                  {sending ? "Sending..." : "Send"}
                </button>
              </form>
              {error && <p className="knock-error chat-error">{error}</p>}
            </>
          )}
        </section>
      )}
    </div>
  );
}

function MapTexture() {
  return (
    <svg
      aria-label="Abstract map of your nearby place"
      className="map-art"
      preserveAspectRatio="none"
      role="img"
      viewBox="0 0 1000 700"
    >
      <defs>
        <pattern height="28" id="map-grid" patternUnits="userSpaceOnUse" width="28">
          <path d="M28 0H0V28" fill="none" stroke="currentColor" strokeOpacity=".06" />
        </pattern>
      </defs>
      <rect fill="url(#map-grid)" height="700" width="1000" />
      <g className="map-blocks">
        <path d="M-40 84 184 34l72 110-38 121-232 16Z" />
        <path d="m320-40 183 8 74 123-81 105-186-29Z" />
        <path d="m691 21 265-46 74 187-147 91-197-74Z" />
        <path d="m92 399 198-54 81 124-48 184-251 17Z" />
        <path d="m462 346 185-79 88 153-76 168-208-19Z" />
        <path d="m768 376 249-69 54 261-213 87-118-133Z" />
      </g>
      <g className="map-roads">
        <path d="M-30 331c172-9 249-44 367-16 143 34 238 12 332-42 120-69 211-62 361-34" />
        <path d="M238-30c1 164 26 261 112 354 87 94 111 209 90 408" />
        <path d="M726-40c-52 161-46 292 35 401 74 100 77 208 44 371" />
        <path d="M-20 574c154-95 297-100 427-44 145 62 282 49 426-44 61-39 124-50 207-42" />
      </g>
      <g className="map-contours">
        <path d="M84 162c72-73 186-71 239-18 52 51 45 134-27 174-76 43-193 29-239-27-38-47-16-87 27-129Z" />
        <path d="M698 471c52-70 167-85 231-31 58 49 45 134-31 174-80 41-187 15-217-51-13-29-6-62 17-92Z" />
      </g>
    </svg>
  );
}

function nearbyMarkerPosition(userId: number) {
  const angle = (((userId * 137.508) % 360) * Math.PI) / 180;
  const radius = 21 + (userId % 3) * 6;
  return {
    left: 50 + Math.cos(angle) * radius,
    top: 50 + Math.sin(angle) * radius * 0.72,
  };
}

function SignedInApp({
  token,
  user,
  onLogout,
}: {
  token: string;
  user: User;
  onLogout: () => void;
}) {
  const [places, setPlaces] = useState<CurrentPlace[]>([]);
  const [nearbyUsers, setNearbyUsers] = useState<NearbyUser[]>([]);
  const [selectedNearbyUser, setSelectedNearbyUser] = useState<NearbyUser | null>(null);
  const [dmChatRequest, setDmChatRequest] = useState<DMChatRequest | null>(null);
  const [activeOverlay, setActiveOverlay] = useState<"explore" | "forum" | null>(null);
  const [messagesOpen, setMessagesOpen] = useState(false);
  const [accountOpen, setAccountOpen] = useState(false);
  const [dmUnread, setDmUnread] = useState(0);
  const [latestDMMessage, setLatestDMMessage] = useState<DMMessage | null>(null);
  const [dmSocketStatus, setDmSocketStatus] = useState<
    "connecting" | "connected" | "disconnected"
  >("connecting");

  useEffect(() => {
    if (
      selectedNearbyUser &&
      !nearbyUsers.some((nearbyUser) => nearbyUser.id === selectedNearbyUser.id)
    ) {
      setSelectedNearbyUser(null);
    }
  }, [nearbyUsers, selectedNearbyUser]);

  useEffect(() => {
    if (!selectedNearbyUser) {
      return;
    }
    function closeNearbyUserCard(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setSelectedNearbyUser(null);
      }
    }
    window.addEventListener("keydown", closeNearbyUserCard);
    return () => window.removeEventListener("keydown", closeNearbyUserCard);
  }, [selectedNearbyUser]);

  function openNearbyUserChat(nearbyUser: NearbyUser) {
    setDmChatRequest((current) => ({
      requestId: (current?.requestId ?? 0) + 1,
      user: {
        id: nearbyUser.id,
        nickname: nearbyUser.nickname,
      },
    }));
    setSelectedNearbyUser(null);
  }

  useEffect(() => {
    let active = true;
    let reconnectTimer: number | undefined;
    let socket: WebSocket | null = null;
    let reconnectAttempts = 0;

    function connect() {
      if (!active) {
        return;
      }
      setDmSocketStatus("connecting");
      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      socket = new WebSocket(
        `${protocol}//${window.location.host}/ws/dms?token=${encodeURIComponent(token)}`,
      );
      socket.onmessage = (event) => {
        const payload = JSON.parse(event.data);
        if (payload.type === "ready") {
          reconnectAttempts = 0;
          setDmSocketStatus("connected");
        } else if (payload.type === "message") {
          if (payload.message) {
            setLatestDMMessage(payload.message as DMMessage);
          }
        }
      };
      socket.onclose = (event) => {
        if (!active) {
          return;
        }
        setDmSocketStatus("disconnected");
        if (event.code !== 4401 && reconnectAttempts < 5) {
          reconnectAttempts += 1;
          reconnectTimer = window.setTimeout(connect, 2_000);
        }
      };
    }

    connect();
    return () => {
      active = false;
      if (reconnectTimer !== undefined) {
        window.clearTimeout(reconnectTimer);
      }
      socket?.close();
    };
  }, [token, user.id]);

  const primaryPlace = places.at(-1);

  return (
    <main className="map-app-shell">
      <header className="map-topbar">
        <div className="map-brand">
          <span className="brand-mark" aria-hidden="true"><Icon name="compass" size={22} /></span>
          <span>
            <strong>PlacePulse</strong>
            <small>{primaryPlace ? primaryPlace.display_name : "Your nearby place"}</small>
          </span>
        </div>

        <nav className="map-nav" aria-label="Place activity">
          <button
            className={activeOverlay === "explore" ? "active" : ""}
            onClick={() => setActiveOverlay((current) => current === "explore" ? null : "explore")}
            type="button"
          >
            <Icon name="compass" size={18} />
            Explore
          </button>
          <button
            className={activeOverlay === "forum" ? "active" : ""}
            onClick={() => setActiveOverlay((current) => current === "forum" ? null : "forum")}
            type="button"
          >
            <Icon name="forum" size={18} />
            Forum
          </button>
        </nav>

        <div className="topbar-actions">
          <button
            aria-label={dmUnread ? `Messages, ${dmUnread} unread` : "Messages"}
            className={`topbar-action ${messagesOpen ? "active" : ""}`}
            onClick={() => setMessagesOpen((open) => !open)}
            type="button"
          >
            <Icon name="messages" size={20} />
            {dmUnread > 0 && <b className="unread-badge">{dmUnread > 9 ? "9+" : dmUnread}</b>}
          </button>
          <div className="profile-wrap">
            <button
              aria-expanded={accountOpen}
              aria-label="Open account menu"
              className="profile-button"
              onClick={() => setAccountOpen((open) => !open)}
              type="button"
            >
              <span>{user.nickname.slice(0, 1).toUpperCase()}</span>
              <Icon name="chevron-down" size={16} />
            </button>
            {accountOpen && (
              <section className="profile-menu">
                <span className="profile-avatar">{user.nickname.slice(0, 1).toUpperCase()}</span>
                <div>
                  <strong>{user.nickname}</strong>
                  <small>{user.phone}</small>
                </div>
                <button className="button button--secondary" onClick={onLogout} type="button">
                  <Icon name="log-out" size={17} />
                  Log out
                </button>
              </section>
            )}
          </div>
        </div>
      </header>

      <div className="map-workspace">
        <section className="map-main" aria-label="Nearby activity map">
          <div className="map-canvas">
            <MapTexture />
            <div className="map-place-label">
              <Icon name="locate" size={16} />
              <span className="map-place-copy">
                <small>Nearby now</small>
                <strong>{primaryPlace?.display_name ?? "Location not shared"}</strong>
              </span>
              {primaryPlace && (
                <span
                  aria-label={`Place status: ${primaryPlace.rank}`}
                  className={`map-place-rank map-place-rank--${primaryPlace.rank.toLowerCase()}`}
                >
                  {primaryPlace.rank}
                </span>
              )}
            </div>

            {places.length > 0 ? (
              <div className="map-user-marker" aria-label="Your position">
                <span className="user-pulse" />
                <span className="user-blob"><Icon name="user" size={20} /></span>
                <strong>You</strong>
              </div>
            ) : (
              <div className="map-empty-state">
                <Icon name="locate" size={26} />
                <strong>Put yourself on the map</strong>
                <span>Share your location to see nearby activity.</span>
              </div>
            )}

            {nearbyUsers.map((nearbyUser) => {
              const position = nearbyMarkerPosition(nearbyUser.id);
              const isSelected = selectedNearbyUser?.id === nearbyUser.id;
              const cardAlignment =
                position.left < 35
                  ? "nearby-user-card--align-left"
                  : position.left > 65
                    ? "nearby-user-card--align-right"
                    : "";
              return (
                <div
                  className={`map-nearby-marker map-nearby-marker--${nearbyUser.id % 4} ${isSelected ? "map-nearby-marker--open" : ""}`}
                  key={nearbyUser.id}
                  style={{ left: `${position.left}%`, top: `${position.top}%` }}
                >
                  <button
                    aria-controls={`nearby-user-card-${nearbyUser.id}`}
                    aria-expanded={isSelected}
                    aria-label={`Open actions for ${nearbyUser.nickname}, nearby at ${nearbyUser.shared_place_display_name}`}
                    className="nearby-user-trigger"
                    onClick={() =>
                      setSelectedNearbyUser((current) =>
                        current?.id === nearbyUser.id ? null : nearbyUser,
                      )
                    }
                    title={`Nearby at ${nearbyUser.shared_place_display_name}`}
                    type="button"
                  >
                    <span aria-hidden="true" className="nearby-user-blob">
                      {nearbyUser.nickname.slice(0, 1).toUpperCase()}
                    </span>
                    <strong>{nearbyUser.nickname}</strong>
                  </button>
                  {isSelected && (
                    <section
                      aria-label={`Actions for ${nearbyUser.nickname}`}
                      className={`nearby-user-card ${cardAlignment}`}
                      id={`nearby-user-card-${nearbyUser.id}`}
                    >
                      <span aria-hidden="true" className="nearby-user-card-avatar">
                        {nearbyUser.nickname.slice(0, 1).toUpperCase()}
                      </span>
                      <span className="nearby-user-card-copy">
                        <strong>{nearbyUser.nickname}</strong>
                        <small>Nearby at {nearbyUser.shared_place_display_name}</small>
                      </span>
                      <button
                        className="button nearby-user-message-button"
                        onClick={() => openNearbyUserChat(nearbyUser)}
                        type="button"
                      >
                        <Icon name="messages" size={16} />
                        Send direct message
                      </button>
                    </section>
                  )}
                </div>
              );
            })}

            <div className="map-location-control">
              <PresencePanel
                onNearbyUsersChange={setNearbyUsers}
                onPlacesChange={setPlaces}
                places={places}
                token={token}
              />
            </div>
            <DigPanel places={places} token={token} />

            {activeOverlay && (
              <section className={`map-overlay map-overlay--${activeOverlay}`}>
                <button
                  aria-label={`Close ${activeOverlay}`}
                  className="overlay-close icon-button"
                  onClick={() => setActiveOverlay(null)}
                  type="button"
                >
                  <Icon name="x" />
                </button>
                {activeOverlay === "explore" ? (
                  <ExplorePanel places={places} token={token} />
                ) : (
                  <ForumPanel places={places} token={token} user={user} />
                )}
              </section>
            )}
          </div>
        </section>

        <aside className="knock-column" aria-label="Live nearby conversation">
          <KnockPanel places={places} token={token} user={user} />
        </aside>
      </div>

      <DMPanel
        chatRequest={dmChatRequest}
        incomingMessage={latestDMMessage}
        onSidebarClose={() => setMessagesOpen(false)}
        onUnreadChange={setDmUnread}
        sidebarOpen={messagesOpen}
        socketStatus={dmSocketStatus}
        token={token}
        user={user}
      />
    </main>
  );
}

function App() {
  const [view, setView] = useState<View>("login");
  const [token, setToken] = useState<string | null>(() =>
    localStorage.getItem(TOKEN_KEY),
  );
  const [user, setUser] = useState<User | null>(null);
  const [checkingSession, setCheckingSession] = useState(Boolean(token));
  const [pendingPhone, setPendingPhone] = useState("");
  const [demoCode, setDemoCode] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!token) {
      setCheckingSession(false);
      return;
    }

    setCheckingSession(true);
    apiRequest<User>("/api/auth/me", {}, token)
      .then(setUser)
      .catch(() => {
        localStorage.removeItem(TOKEN_KEY);
        setToken(null);
        setUser(null);
      })
      .finally(() => setCheckingSession(false));
  }, [token]);

  function selectView(nextView: View) {
    setView(nextView);
    setError("");
    setNotice("");
  }

  async function handleRegister(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setError("");
    setNotice("");

    const form = new FormData(event.currentTarget);
    const phone = String(form.get("phone") || "");

    try {
      const response = await apiRequest<RegistrationResponse>(
        "/api/auth/register",
        {
          method: "POST",
          body: JSON.stringify({
            phone,
            nickname: String(form.get("nickname") || ""),
            password: String(form.get("password") || ""),
          }),
        },
      );
      setPendingPhone(phone);
      setDemoCode(response.verification_code);
      setNotice(response.message);
      setView("verify");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Registration failed");
    } finally {
      setLoading(false);
    }
  }

  async function handleVerify(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setError("");

    const form = new FormData(event.currentTarget);
    try {
      await apiRequest<User>("/api/auth/verify", {
        method: "POST",
        body: JSON.stringify({
          phone: pendingPhone,
          code: String(form.get("code") || ""),
        }),
      });
      setDemoCode(null);
      setNotice("Phone verified. You can now log in.");
      setView("login");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Verification failed");
    } finally {
      setLoading(false);
    }
  }

  async function handleLogin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setError("");
    setNotice("");

    const form = new FormData(event.currentTarget);
    try {
      const response = await apiRequest<LoginResponse>("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({
          phone: String(form.get("phone") || ""),
          password: String(form.get("password") || ""),
        }),
      });
      localStorage.setItem(TOKEN_KEY, response.access_token);
      setToken(response.access_token);
      setUser(response.user);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Login failed");
    } finally {
      setLoading(false);
    }
  }

  async function handleLogout() {
    if (token) {
      await apiRequest<void>(
        "/api/presence/leave",
        { method: "POST" },
        token,
      ).catch(() => undefined);
      await apiRequest<void>("/api/auth/logout", { method: "POST" }, token).catch(
        () => undefined,
      );
    }
    localStorage.removeItem(TOKEN_KEY);
    setToken(null);
    setUser(null);
    setNotice("You have been logged out.");
    setView("login");
  }

  if (checkingSession) {
    return (
      <main className="page-shell">
        <p className="session-check">Checking your session...</p>
      </main>
    );
  }

  if (user && token) {
    return <SignedInApp onLogout={handleLogout} token={token} user={user} />;
  }

  return (
    <main className="page-shell">
      <section className="auth-card">
        <header className="brand-block">
          <p className="eyebrow">PlacePulse</p>
          <h1>Know what is happening here.</h1>
          <p>
            Sign in and share your location to join live conversations around
            you.
          </p>
        </header>

        <div className="form-block" aria-live="polite">
          {view !== "verify" && (
            <nav className="auth-tabs" aria-label="Authentication options">
              <button
                className={view === "login" ? "active" : ""}
                onClick={() => selectView("login")}
                type="button"
              >
                Log in
              </button>
              <button
                className={view === "register" ? "active" : ""}
                onClick={() => selectView("register")}
                type="button"
              >
                Register
              </button>
            </nav>
          )}

          {notice && <p className="message message--success">{notice}</p>}
          {error && <p className="message message--error">{error}</p>}

          {view === "login" && (
            <form onSubmit={handleLogin}>
              <h2>Log in</h2>
              <label>
                Phone number
                <input
                  name="phone"
                  type="tel"
                  inputMode="tel"
                  autoComplete="tel"
                  required
                />
              </label>
              <label>
                Password
                <input
                  name="password"
                  type="password"
                  autoComplete="current-password"
                  required
                />
              </label>
              <button className="button" disabled={loading} type="submit">
                {loading ? "Logging in..." : "Log in"}
              </button>
            </form>
          )}

          {view === "register" && (
            <form onSubmit={handleRegister}>
              <h2>Create an account</h2>
              <label>
                Nickname
                <input
                  name="nickname"
                  type="text"
                  minLength={2}
                  maxLength={30}
                  autoComplete="nickname"
                  required
                />
              </label>
              <label>
                Phone number
                <input
                  name="phone"
                  type="tel"
                  inputMode="tel"
                  autoComplete="tel"
                  required
                />
              </label>
              <label>
                Password
                <input
                  name="password"
                  type="password"
                  minLength={8}
                  maxLength={128}
                  autoComplete="new-password"
                  required
                />
              </label>
              <p className="hint">Use at least 8 characters.</p>
              <button className="button" disabled={loading} type="submit">
                {loading ? "Creating account..." : "Register"}
              </button>
            </form>
          )}

          {view === "verify" && (
            <form onSubmit={handleVerify}>
              <p className="eyebrow">One more step</p>
              <h2>Verify your phone</h2>
              <p className="form-copy">
                {demoCode
                  ? `Use the demo code shown below for ${pendingPhone}.`
                  : `Code sent by SMS to ${pendingPhone}.`}
              </p>
              {demoCode && (
                <p className="development-code">
                  Demo verification code: <strong>{demoCode}</strong>
                </p>
              )}
              <label>
                Six-digit code
                <input
                  name="code"
                  type="text"
                  inputMode="numeric"
                  pattern="[0-9]{6}"
                  maxLength={6}
                  autoComplete="one-time-code"
                  required
                />
              </label>
              <button className="button" disabled={loading} type="submit">
                {loading ? "Verifying..." : "Verify phone"}
              </button>
              <button
                className="text-button"
                onClick={() => selectView("register")}
                type="button"
              >
                Start registration again
              </button>
            </form>
          )}
        </div>
      </section>
    </main>
  );
}

export default App;
