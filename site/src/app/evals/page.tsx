import Shell, { Band, Empty, Read, Reads, ViewHead } from "@/components/Shell";
import { getEnvironments, scoreRows, totals } from "@/lib/data";

export const dynamic = "force-static";
export default function EvalsPage() {
  const envs = getEnvironments(); const all = totals(envs); const rows = scoreRows(envs);
  return <Shell active="evals" envs={envs}>
    <ViewHead title="Model evals" src={<><b>source</b> envs/*/results.json · <b>method</b> reset, run, grade</>}>
      Task-level scores only appear after a model has been driven through the resettable environment and its guards have graded the resulting state. Missing runs stay missing; they are never shown as zeroes.
    </ViewHead>
    <Reads>
      <Read label="COVERAGE"><b>{all.tasks.toLocaleString()}</b> tasks are ready to run.<span className="muted"> Every task names its route, writes and adversarial guards.</span></Read>
      <Read label="GRADING"><b>{all.guards.toLocaleString()}</b> guards challenge the result.<span className="muted"> {all.cheats.toLocaleString()} known shortcuts are named.</span></Read>
      <Read label="RECORDED"><b>{all.scored.toLocaleString()}</b> task-model scores exist.<span className="muted"> The scorecard is waiting for actual runs.</span></Read>
    </Reads>
    <Band note={rows.length ? `${rows.length} models` : "no completed runs"}>MODEL SCORECARD</Band>
    {rows.length ? <table className="g"><thead><tr><th>MODEL</th><th className="r">TASKS SCORED</th><th className="r">PASS RATE</th></tr></thead><tbody>{rows.map((row) => <tr key={row.model}><td className="id">{row.model}</td><td className="fig">{row.scored}</td><td className="fig">{Math.round(row.pct * 100)}%</td></tr>)}</tbody></table> : <Empty><b>No model run has been recorded yet.</b> The environment suite is complete; this table will populate from task scores after the free-rail runner lands its first graded pass.</Empty>}
  </Shell>;
}
