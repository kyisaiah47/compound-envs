import { notFound } from "next/navigation";
import Shell, { Band, Chip, Read, Reads, ViewHead } from "@/components/Shell";
import { getEnvironment, getEnvironments } from "@/lib/data";

export const dynamic = "force-static";
export function generateStaticParams() { return getEnvironments().map((env) => ({ product: env.product })); }

export default async function ProductPage({ params }: { params: Promise<{ product: string }> }) {
  const { product } = await params; const env = getEnvironment(product); if (!env) notFound();
  const scored = env.tasks.reduce((n, task) => n + Object.keys(task.scores || {}).length, 0);
  const fixed = env.defects.filter((d) => d.fixed).length;
  return <Shell active={env.product} envs={getEnvironments()}>
    <ViewHead title={env.title} src={<><b>environment</b> {env.environment} · <b>generated</b> {env.generated_at} · <b>suite</b> {env.suite.last_run}</>}>
      A task book for <a className="accent" href={env.product_url}>{env.product_url}</a>. The grader resets known state, drives the named surface, and checks the database and side effects against every guard below.
    </ViewHead>
    <Reads>
      <Read label="TASK BOOK"><b>{env.tasks.length}</b> tasks span {Array.from(new Set(env.tasks.map((t) => t.driven))).join(", ")}.</Read>
      <Read label="ADVERSARIAL"><b>{env.counts.guards}</b> guards catch {env.counts.cheats} named shortcuts.</Read>
      <Read label="RESULTS"><b>{scored}</b> model scores are recorded.<span className="muted"> {fixed}/{env.defects.length} findings fixed.</span></Read>
    </Reads>
    <Band note={`${env.tasks.length} tasks`}>TASKS AND GUARDS</Band>
    <div className="taskbook">{env.tasks.map((task) => <article className="task" key={task.id}>
      <header><div><code>{task.id}</code><h2>{task.description}</h2></div><Chip tone={Object.keys(task.scores || {}).length ? "ok" : "no"}>{Object.keys(task.scores || {}).length ? "scored" : "not run"}</Chip></header>
      <p className="route"><b>{task.driven}</b> · {task.route} · writes {task.writes.join(", ") || "none"}</p>
      <ol>{task.guards.map((guard) => <li key={guard.id}><code>{guard.id}</code><span>{guard.checks}</span></li>)}</ol>
    </article>)}</div>
  </Shell>;
}
