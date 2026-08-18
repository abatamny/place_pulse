import {
  type FormEvent,
  useEffect,
  useRef,
  useState,
} from "react";

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
  parent_place_id: number | null;
  rank: "VISITOR" | "BELONG";
  completed_visits: number;
};

type PresenceResponse = {
  places: CurrentPlace[];
  expires_in_seconds: number;
};

type KnockMessage = {
  id: number;
  place_id: number;
  place_name: string;
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

type PersonalForumResponse = {
  posts: ForumPost[];
  total_upvotes: number;
  total_downvotes: number;
  total_score: number;
};

type DMUser = {
  id: number;
  nickname: string;
  phone: string;
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

const TOKEN_KEY = "placepulse-session";

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

function PresencePanel({
  token,
  places,
  onPlacesChange,
}: {
  token: string;
  places: CurrentPlace[];
  onPlacesChange: (places: CurrentPlace[]) => void;
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
        if (response.places.length) {
          setStatus("active");
        }
      })
      .catch(() => undefined);
  }, [token, onPlacesChange]);

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
  }, [requestNumber, token, onPlacesChange]);

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
              <span>{place.name}</span>
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
  const [messages, setMessages] = useState<KnockMessage[]>([]);
  const [connection, setConnection] = useState<
    "waiting" | "connecting" | "connected" | "disconnected"
  >("waiting");
  const [draft, setDraft] = useState("");
  const [error, setError] = useState("");
  const placeKey = places.map((place) => place.id).join(",");

  useEffect(() => {
    if (!places.length) {
      setMessages([]);
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
          setMessages((current) =>
            mergeMessages([...current, payload.message as KnockMessage]),
          );
          setError("");
        } else if (payload.type === "error") {
          setError(payload.detail || "The KNOCK could not be sent.");
        }
      };

      socket.onclose = (event) => {
        if (!active) {
          return;
        }
        setConnection("disconnected");
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
    setDraft("");
  }

  if (!places.length) {
    return (
      <section className="knock-card knock-empty">
        <span className="knock-icon" aria-hidden="true">◎</span>
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
          <span key={place.id}>{place.name}</span>
        ))}
      </div>

      <div className="knock-feed" aria-live="polite">
        {messages.length === 0 ? (
          <div className="feed-empty">
            <p>No KNOCKS yet.</p>
            <span>Start the conversation at this place.</span>
          </div>
        ) : (
          messages.map((message) => (
            <article
              className={`knock-message ${message.user_id === user.id ? "knock-message--own" : ""}`}
              key={message.id}
            >
              <div className="message-meta">
                <strong>{message.nickname}</strong>
                <span>{message.place_name}</span>
                <time dateTime={message.created_at}>
                  {new Date(message.created_at).toLocaleTimeString([], {
                    hour: "2-digit",
                    minute: "2-digit",
                  })}
                </time>
              </div>
              <p>{message.text}</p>
            </article>
          ))
        )}
      </div>

      {error && <p className="knock-error">{error}</p>}
      <form className="knock-composer" onSubmit={sendKnock}>
        <label htmlFor="knock-message">Send a KNOCK</label>
        <textarea
          id="knock-message"
          maxLength={500}
          onChange={(event) => setDraft(event.target.value)}
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
            KNOCK
          </button>
        </div>
      </form>
    </section>
  );
}

function DigMedia({ dig, token }: { dig: Dig; token: string }) {
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
    return <p className="dig-media-state">Loading media...</p>;
  }
  if (dig.media_type === "video") {
    return <video className="dig-media" controls playsInline src={source} />;
  }
  return (
    <img
      alt={`DIG shared by ${dig.nickname} at ${dig.place_name}`}
      className="dig-media"
      src={source}
    />
  );
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
  const [selectedPlaceId, setSelectedPlaceId] = useState("");
  const [refreshNumber, setRefreshNumber] = useState(0);
  const [uploading, setUploading] = useState(false);
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
    if (!selectedFile || !selectedPlaceId) {
      setError("Choose a place and a media file.");
      return;
    }
    if (selectedFile.size > 10 * 1024 * 1024) {
      setError("DIG uploads cannot exceed 10 MB.");
      return;
    }

    setUploading(true);
    setError("");
    setNotice("");
    const form = new FormData();
    form.set("place_id", selectedPlaceId);
    form.set("file", selectedFile);
    try {
      await apiRequest<Dig>(
        "/api/digs",
        { method: "POST", body: form },
        token,
      );
      if (inputRef.current) {
        inputRef.current.value = "";
      }
      setNotice("DIG published. It will disappear after 24 hours.");
      setRefreshNumber((value) => value + 1);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  }

  if (!places.length) {
    return (
      <section className="knock-card knock-empty">
        <span className="knock-icon" aria-hidden="true">&#9673;</span>
        <h2>Nearby DIGs appear here</h2>
        <p>Share your location to view and post temporary media.</p>
      </section>
    );
  }

  return (
    <section className="knock-card dig-card">
      <header className="knock-heading">
        <div>
          <p className="eyebrow">Temporary nearby media</p>
          <h2>DIG</h2>
        </div>
        <span className="dig-lifetime">24 hours</span>
      </header>

      <form className="dig-composer" onSubmit={uploadDig}>
        <label>
          Post to
          <select
            onChange={(event) => setSelectedPlaceId(event.target.value)}
            required
            value={selectedPlaceId}
          >
            {places.map((place) => (
              <option key={place.id} value={place.id}>
                {place.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Image or short video
          <input
            accept="image/jpeg,image/png,image/webp,video/mp4,video/webm"
            ref={inputRef}
            required
            type="file"
          />
        </label>
        <div className="dig-upload-footer">
          <small>JPEG, PNG, WebP, MP4, or WebM. Up to 10 MB and 15 seconds.</small>
          <button className="button" disabled={uploading} type="submit">
            {uploading ? "Checking..." : "Post DIG"}
          </button>
        </div>
      </form>

      {notice && <p className="dig-notice">{notice}</p>}
      {error && <p className="knock-error">{error}</p>}

      <div className="dig-feed" aria-live="polite">
        {digs.length === 0 ? (
          <div className="feed-empty">
            <p>No active DIGs yet.</p>
            <span>Share the first view from this place.</span>
          </div>
        ) : (
          digs.map((dig) => (
            <article className="dig-item" key={dig.id}>
              <DigMedia dig={dig} token={token} />
              <div className="dig-meta">
                <div>
                  <strong>{dig.nickname}</strong>
                  <span>{dig.place_name}</span>
                </div>
                <time dateTime={dig.expires_at}>
                  Expires {new Date(dig.expires_at).toLocaleTimeString([], {
                    hour: "2-digit",
                    minute: "2-digit",
                  })}
                </time>
              </div>
            </article>
          ))
        )}
      </div>
    </section>
  );
}

function ExploreMedia({ dig, token }: { dig: ExploreDig; token: string }) {
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
    return <video className="dig-media" controls playsInline src={source} />;
  }
  return (
    <img
      alt={`Memory shared by ${dig.nickname}`}
      className="dig-media"
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

  return (
    <article className="explore-memory">
      <header className="explore-memory-heading">
        <div>
          <strong>{memory.place_name}</strong>
          <time dateTime={memory.created_at}>
            Saved {new Date(memory.created_at).toLocaleString()}
          </time>
        </div>
        <span className="memory-access">
          {memory.participant ? "Your memory" : "Here now"}
        </span>
      </header>

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
    </article>
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
    <article className="forum-post">
      <header className="forum-post-heading">
        <div>
          <span>{post.nickname}{post.is_mine ? " · You" : ""}</span>
          <span>{post.place_name}</span>
        </div>
        <time dateTime={post.created_at}>
          {new Date(post.created_at).toLocaleString()}
        </time>
      </header>
      <div className="forum-post-copy">
        <h3>{post.title}</h3>
        <p>{post.body}</p>
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
        <strong>{post.score}</strong>
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
    </article>
  );
}

function ForumPanel({
  token,
  places,
}: {
  token: string;
  places: CurrentPlace[];
}) {
  const [mode, setMode] = useState<"place" | "mine">("place");
  const [selectedPlaceId, setSelectedPlaceId] = useState("");
  const [posts, setPosts] = useState<ForumPost[]>([]);
  const [personal, setPersonal] = useState<PersonalForumResponse | null>(null);
  const [refreshNumber, setRefreshNumber] = useState(0);
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
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
    if (!selectedPlaceId) {
      return;
    }
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    setSubmitting(true);
    setError("");
    setNotice("");
    try {
      await apiRequest<ForumPost>(
        "/api/forum/posts",
        {
          method: "POST",
          body: JSON.stringify({
            place_id: Number(selectedPlaceId),
            title: String(form.get("title") || ""),
            body: String(form.get("body") || ""),
            is_anonymous: form.get("anonymous") === "on",
          }),
        },
        token,
      );
      formElement.reset();
      setNotice("Forum post published.");
      setRefreshNumber((value) => value + 1);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not publish post");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className="knock-card forum-card">
      <header className="knock-heading">
        <div>
          <p className="eyebrow">Place discussions</p>
          <h2>Forum</h2>
        </div>
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
      </header>

      {mode === "place" && places.length > 0 && (
        <form className="forum-composer" onSubmit={submitPost}>
          <label>
            Forum place
            <select
              onChange={(event) => setSelectedPlaceId(event.target.value)}
              value={selectedPlaceId}
            >
              {places.map((place) => (
                <option key={place.id} value={place.id}>{place.name}</option>
              ))}
            </select>
          </label>
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
              {submitting ? "Checking..." : "Publish"}
            </button>
          </div>
        </form>
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
        ) : posts.length === 0 ? (
          <div className="feed-empty">
            <p>{mode === "mine" ? "You have not posted yet." : "No forum posts yet."}</p>
            <span>{mode === "mine" ? "Your posts will appear here." : "Start a place discussion."}</span>
          </div>
        ) : (
          posts.map((post) => (
            <ForumPostCard
              key={post.id}
              onChanged={() => setRefreshNumber((value) => value + 1)}
              post={post}
              token={token}
            />
          ))
        )}
      </div>
    </section>
  );
}

function DMPanel({
  token,
  user,
  notificationNumber,
  socketStatus,
  onUnreadChange,
}: {
  token: string;
  user: User;
  notificationNumber: number;
  socketStatus: "connecting" | "connected" | "disconnected";
  onUnreadChange: (count: number) => void;
}) {
  const [conversations, setConversations] = useState<DMConversation[]>([]);
  const [selectedUser, setSelectedUser] = useState<DMUser | null>(null);
  const [messages, setMessages] = useState<DMMessage[]>([]);
  const [searchResults, setSearchResults] = useState<DMUser[]>([]);
  const [draft, setDraft] = useState("");
  const [refreshNumber, setRefreshNumber] = useState(0);
  const [loading, setLoading] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");

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
          onUnreadChange(
            response.conversations.reduce(
              (total, conversation) => total + conversation.unread_count,
              0,
            ),
          );
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
  }, [notificationNumber, onUnreadChange, refreshNumber, token]);

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
        const refreshed = await apiRequest<DMConversationListResponse>(
          "/api/dms/conversations",
          {},
          token,
        );
        if (active) {
          setConversations(refreshed.conversations);
          onUnreadChange(
            refreshed.conversations.reduce(
              (total, conversation) => total + conversation.unread_count,
              0,
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
  }, [notificationNumber, onUnreadChange, refreshNumber, selectedUser?.id, token]);

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
      setMessages((current) => [...current, message]);
      setDraft("");
      setRefreshNumber((value) => value + 1);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not send message");
    } finally {
      setSending(false);
    }
  }

  function openConversation(person: DMUser) {
    setSelectedUser(person);
    setSearchResults([]);
    setError("");
  }

  return (
    <section className="knock-card dm-card">
      <header className="knock-heading">
        <div>
          <p className="eyebrow">Private conversations</p>
          <h2>Messages</h2>
        </div>
        <span className={`socket-status socket-status--${socketStatus}`}>
          {socketStatus}
        </span>
      </header>

      <div className="dm-layout">
        <aside className="dm-sidebar">
          <form className="dm-search" onSubmit={searchUsers}>
            <input
              aria-label="Search users"
              maxLength={30}
              name="query"
              placeholder="Nickname or phone"
              required
            />
            <button className="button" type="submit">Find</button>
          </form>

          {searchResults.length > 0 && (
            <div className="dm-search-results">
              {searchResults.map((person) => (
                <button key={person.id} onClick={() => openConversation(person)} type="button">
                  <strong>{person.nickname}</strong>
                  <span>{person.phone}</span>
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
        </aside>

        <div className="dm-chat">
          {!selectedUser ? (
            <div className="dm-empty">
              <strong>Select a conversation</strong>
              <span>Or find a verified user by nickname or phone.</span>
            </div>
          ) : (
            <>
              <header className="dm-chat-heading">
                <strong>{selectedUser.nickname}</strong>
                <span>{selectedUser.phone}</span>
              </header>
              <div className="dm-messages" aria-live="polite">
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
                  placeholder={`Message ${selectedUser.nickname}`}
                  rows={2}
                  value={draft}
                />
                <button className="button" disabled={sending || !draft.trim()} type="submit">
                  {sending ? "Sending..." : "Send"}
                </button>
              </form>
            </>
          )}
        </div>
      </div>
      {error && <p className="knock-error">{error}</p>}
    </section>
  );
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
  const [mainView, setMainView] = useState<
    "knock" | "dig" | "explore" | "forum" | "dms"
  >(
    "knock",
  );
  const [dmUnread, setDmUnread] = useState(0);
  const [dmNotificationNumber, setDmNotificationNumber] = useState(0);
  const [dmSocketStatus, setDmSocketStatus] = useState<
    "connecting" | "connected" | "disconnected"
  >("connecting");

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
          setDmNotificationNumber((value) => value + 1);
          if (payload.message?.recipient_id === user.id) {
            setDmUnread((value) => value + 1);
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

    apiRequest<DMConversationListResponse>(
      "/api/dms/conversations",
      {},
      token,
    )
      .then((response) =>
        setDmUnread(
          response.conversations.reduce(
            (total, conversation) => total + conversation.unread_count,
            0,
          ),
        ),
      )
      .catch(() => undefined);
    connect();
    return () => {
      active = false;
      if (reconnectTimer !== undefined) {
        window.clearTimeout(reconnectTimer);
      }
      socket?.close();
    };
  }, [token, user.id]);

  return (
    <main className="app-shell">
      <header className="app-header">
        <div>
          <p className="eyebrow">PlacePulse</p>
          <h1>What is happening here?</h1>
        </div>
        <div className="user-chip">
          <span>{user.nickname}</span>
          <small>Signed in</small>
        </div>
      </header>

      <div className="app-content">
        <aside className="app-sidebar">
          <PresencePanel
            onPlacesChange={setPlaces}
            places={places}
            token={token}
          />
          <section className="account-summary">
            <p className="eyebrow">Account</p>
            <strong>{user.nickname}</strong>
            <span>{user.phone}</span>
            <button
              className="button button--secondary"
              onClick={onLogout}
              type="button"
            >
              Log out
            </button>
          </section>
        </aside>

        <div className="main-pane">
          <nav className="main-tabs" aria-label="Place activity">
            <button
              className={mainView === "knock" ? "active" : ""}
              onClick={() => setMainView("knock")}
              type="button"
            >
              KNOCK
            </button>
            <button
              className={mainView === "dig" ? "active" : ""}
              onClick={() => setMainView("dig")}
              type="button"
            >
              DIG
            </button>
            <button
              className={mainView === "explore" ? "active" : ""}
              onClick={() => setMainView("explore")}
              type="button"
            >
              Explore
            </button>
            <button
              className={mainView === "forum" ? "active" : ""}
              onClick={() => setMainView("forum")}
              type="button"
            >
              Forum
            </button>
            <button
              className={mainView === "dms" ? "active" : ""}
              onClick={() => setMainView("dms")}
              type="button"
            >
              Messages{dmUnread > 0 ? ` (${dmUnread})` : ""}
            </button>
          </nav>
          {mainView === "knock" ? (
            <KnockPanel places={places} token={token} user={user} />
          ) : mainView === "dig" ? (
            <DigPanel places={places} token={token} />
          ) : mainView === "explore" ? (
            <ExplorePanel places={places} token={token} />
          ) : mainView === "forum" ? (
            <ForumPanel places={places} token={token} />
          ) : (
            <DMPanel
              notificationNumber={dmNotificationNumber}
              onUnreadChange={setDmUnread}
              socketStatus={dmSocketStatus}
              token={token}
              user={user}
            />
          )}
        </div>
      </div>
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
  const [developmentCode, setDevelopmentCode] = useState<string | null>(null);
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
      setDevelopmentCode(response.verification_code);
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
      setDevelopmentCode(null);
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
              <p className="form-copy">Code sent for {pendingPhone}.</p>
              {developmentCode && (
                <p className="development-code">
                  Local verification code: <strong>{developmentCode}</strong>
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
