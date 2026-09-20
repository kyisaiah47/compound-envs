import Link from "next/link";
import Shell, { Band, Chip, Read, Reads, ViewHead } from "@/components/Shell";
import { getEnvironments, totals } from "@/lib/data";

export const dynamic = "force-static";
export default function EnvironmentsPage() {
  const envs = getEnvironments(); const all = totals(envs);
  return <Shell active="environments" envs={envs}>
    <ViewHead title="Environment register" src={<><b>schema</b> compound-evals/results@1 · <b>build read</b> versioned results</>}>
      Each row is a resettable product sandbox: realistic state, explicit work, known cheats and guards that inspect what the model actually left behind.
    </ViewHead>
    <Reads>
      <Read label="SUITES"><b>{all.tasks.toLocaleString()}</b> concrete tasks are gradable.</Read>
      <Read label="EXPECTATIONS"><b>{all.guards.toLocaleString()}</b> state checks hold the line.</Read>
      <Read label="FINDINGS"><b>{all.fixed.toLocaleString()}</b> of {all.defects.toLocaleString()} recorded defects are fixed.</Read>
    </Reads>
    <Band note="click a row for its task book">ENVIRONMENTS</Band>
    <table className="g"><thead><tr><th>PRODUCT</th><th>STATE</th><th className="r">TASKS</th><th className="r">GUARDS</th><th className="r">CHEATS</th><th className="r">SUITE</th></tr></thead><tbody>{envs.map((env) => <tr key={env.product}><td><Link className="nm" href={`/${env.product}`}>{env.product}<small>{env.title}</small></Link></td><td><Chip tone={env.verdict === "gradable" ? "ok" : "wn"}>{env.verdict}</Chip></td><td className="fig">{env.tasks.length}</td><td className="fig">{env.counts.guards}</td><td className="fig">{env.counts.cheats}</td><td className="fig">{env.suite.expectations_held}/{env.suite.expectations_total}</td></tr>)}</tbody></table>
  </Shell>;
}
