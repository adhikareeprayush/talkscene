/**
 * Server-sent events over `fetch`.
 *
 * `EventSource` cannot be used for turns: it is GET-only and cannot carry an
 * `Authorization` header or a multipart body. So the stream is parsed by hand
 * from the response body, which also means the caller can abort it (barge-in,
 * navigation) with an `AbortSignal`.
 *
 * The parser is a real SSE parser rather than a `split("\n\n")`: a chunk
 * boundary can land anywhere, including inside a multi-byte Korean character,
 * so the decoder is streaming and the buffer persists across reads.
 */

export type SseMessage = { event: string; data: unknown };

export class SseError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly problem?: unknown,
  ) {
    super(message);
    this.name = "SseError";
  }
}

export async function* readEventStream(
  response: Response,
  signal?: AbortSignal,
): AsyncGenerator<SseMessage> {
  if (!response.ok) {
    let problem: unknown;
    try {
      problem = await response.json();
    } catch {
      problem = undefined;
    }
    const detail =
      (problem as { detail?: string } | undefined)?.detail ??
      `Request failed with ${response.status}`;
    throw new SseError(detail, response.status, problem);
  }
  if (!response.body) throw new SseError("The response had no body.", response.status);

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  const onAbort = () => void reader.cancel().catch(() => {});
  signal?.addEventListener("abort", onAbort, { once: true });

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      let boundary = buffer.indexOf("\n\n");
      while (boundary !== -1) {
        const frame = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const message = parseFrame(frame);
        if (message) yield message;
        boundary = buffer.indexOf("\n\n");
      }
    }
    // A stream that ends without a trailing blank line still has a final frame.
    const tail = parseFrame(buffer);
    if (tail) yield tail;
  } finally {
    signal?.removeEventListener("abort", onAbort);
    reader.releaseLock();
  }
}

function parseFrame(frame: string): SseMessage | null {
  let event = "message";
  const dataLines: string[] = [];
  for (const line of frame.split("\n")) {
    if (line.startsWith(":")) continue; // comment / keep-alive
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    const rawValue = colon === -1 ? "" : line.slice(colon + 1);
    const value = rawValue.startsWith(" ") ? rawValue.slice(1) : rawValue;
    if (field === "event") event = value;
    else if (field === "data") dataLines.push(value);
  }
  if (dataLines.length === 0) return null;
  const payload = dataLines.join("\n");
  try {
    return { event, data: JSON.parse(payload) };
  } catch {
    return { event, data: payload };
  }
}
