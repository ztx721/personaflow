import { useEffect, useState } from "react";
import { api } from "../api";
import type { DebugSnapshot } from "../types";

type Props = {
  conversationId: string | null;
  revision: number;
};

function JsonBlock({ value }: { value: unknown }) {
  return (
    <pre className="scrollbar-thin overflow-x-auto rounded-xl bg-stone-950 p-4 text-xs leading-5 text-stone-200">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

function Field({ label, value }: { label: string; value: string | number | null | undefined }) {
  return (
    <div className="rounded-xl border border-stone-200 bg-white/70 p-3">
      <dt className="text-xs font-medium uppercase tracking-wider text-stone-400">{label}</dt>
      <dd className="mt-1 break-all font-medium text-ink">{value ?? "—"}</dd>
    </div>
  );
}

export function AdminPanel({ conversationId, revision }: Props) {
  const [snapshot, setSnapshot] = useState<DebugSnapshot | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    if (!conversationId) return;
    setLoading(true);
    try {
      setSnapshot(await api.getDebug(conversationId));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "读取 Debug 信息失败");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void refresh();
  }, [conversationId, revision]);

  if (!conversationId) return <p className="py-20 text-center text-stone-500">尚未创建会话。</p>;
  if (!snapshot && loading) return <p className="py-20 text-center text-stone-500">正在读取 Debug 快照…</p>;

  const last = snapshot?.last_turn;
  const relationship = snapshot?.state.relationship ?? {};
  const transition = last?.applied.story as { from?: string; to?: string; reason?: string } | undefined;

  return (
    <section className="mx-auto w-full max-w-6xl space-y-5 pb-12">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-ink">Admin Debug</h1>
          <p className="mt-1 text-sm text-stone-500">只读运行时快照 · MockProvider</p>
        </div>
        <button onClick={() => void refresh()} disabled={loading} className="rounded-xl border border-stone-300 bg-white px-4 py-2 text-sm text-stone-700 hover:border-stone-400 disabled:opacity-50">
          {loading ? "刷新中…" : "刷新"}
        </button>
      </div>

      {error && <p className="rounded-xl bg-red-50 p-3 text-sm text-red-700">{error}</p>}

      <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Field label="Conversation ID" value={snapshot?.conversation_id} />
        <Field label="Role" value={snapshot?.role.display_name} />
        <Field label="Emotion" value={snapshot ? `${snapshot.state.emotion} / ${snapshot.state.emotion_intensity}` : null} />
        <Field label="Topic" value={snapshot?.state.current_topic} />
        <Field label="Story" value={snapshot?.story?.story_id} />
        <Field label="Node" value={snapshot?.story?.current_node_id} />
        <Field label="Story Status" value={snapshot?.story?.status} />
        <Field label="Transition" value={transition ? `${transition.from ?? "?"} → ${transition.to ?? "?"}` : null} />
      </dl>

      <div className="grid gap-5 lg:grid-cols-2">
        <div className="rounded-2xl border border-stone-200 bg-white/65 p-5">
          <h2 className="mb-3 font-semibold text-ink">Relationship</h2>
          <div className="space-y-3">
            {Object.entries(relationship).map(([key, value]) => (
              <div key={key}>
                <div className="mb-1 flex justify-between text-sm"><span>{key}</span><span>{value}</span></div>
                <div className="h-2 overflow-hidden rounded-full bg-stone-200"><div className="h-full rounded-full bg-moss" style={{ width: `${value}%` }} /></div>
              </div>
            ))}
          </div>
        </div>
        <div className="rounded-2xl border border-stone-200 bg-white/65 p-5">
          <h2 className="mb-3 font-semibold text-ink">Applied Action</h2>
          <dl className="grid grid-cols-2 gap-3 text-sm">
            <Field label="Reason" value={transition?.reason} />
            <Field label="Asset Tag" value={last?.applied.asset_tag as string | null} />
            <div className="col-span-2"><Field label="Asset URL" value={last?.applied.asset_url as string | null} /></div>
          </dl>
        </div>
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <div>
          <h2 className="mb-3 font-semibold text-ink">Last Planner Output</h2>
          <JsonBlock value={last?.planner_output ?? {}} />
        </div>
        <div>
          <h2 className="mb-3 font-semibold text-ink">Validation Errors</h2>
          <JsonBlock value={last?.validation_errors ?? []} />
        </div>
      </div>

      <div>
        <h2 className="mb-3 font-semibold text-ink">TurnLog ({snapshot?.turn_logs.length ?? 0})</h2>
        <div className="space-y-3">
          {[...(snapshot?.turn_logs ?? [])].reverse().map((turn, index) => {
            const story = turn.applied.story as { from?: string; to?: string; reason?: string } | undefined;
            return (
              <details key={turn.id} open={index === 0} className="rounded-2xl border border-stone-200 bg-white/70 p-4">
                <summary className="cursor-pointer select-none font-medium text-ink">
                  Turn {snapshot!.turn_logs.length - index} · {story ? `${story.from} → ${story.to}` : "no transition"} · {new Date(turn.created_at).toLocaleTimeString()}
                </summary>
                <div className="mt-4 grid gap-4 lg:grid-cols-2"><JsonBlock value={turn.planner_output} /><JsonBlock value={turn.applied} /></div>
              </details>
            );
          })}
        </div>
      </div>
    </section>
  );
}
