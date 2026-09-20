import fs from "node:fs";
import path from "node:path";

export type Guard = { id: string; checks: string };
export type Score = number | { score?: number; passed?: boolean };
export type Task = {
  id: string;
  description: string;
  driven: string;
  route: string;
  writes: string[];
  guards: Guard[];
  cheats: { id: string; fakes: string; caught_by: string }[];
  scores: Record<string, Score>;
};
export type Defect = { summary: string; where: string; severity: string; fixed: boolean };
export type Environment = {
  product: string;
  environment: string;
  title: string;
  product_url: string;
  generated_at: string;
  verdict: string;
  tasks: Task[];
  defects: Defect[];
  suite: { expectations_total: number; expectations_held: number; exit_code: number; last_run: string };
  counts: { tasks: number; cheats: number; guards: number; browser_tasks: number };
  models: Record<string, unknown>;
};

function envRoot() {
  return path.resolve(process.cwd(), "..", "envs");
}

export function getEnvironments(): Environment[] {
  const root = envRoot();
  return fs.readdirSync(root)
    .map((name) => path.join(root, name, "results.json"))
    .filter((file) => fs.existsSync(file))
    .map((file) => JSON.parse(fs.readFileSync(file, "utf8")) as Environment)
    .sort((a, b) => a.product.localeCompare(b.product));
}

export function getEnvironment(product: string) {
  return getEnvironments().find((env) => env.product === product);
}

export function scoreRows(envs = getEnvironments()) {
  const models = new Map<string, { scored: number; total: number; points: number }>();
  for (const env of envs) for (const task of env.tasks) {
    for (const [model, raw] of Object.entries(task.scores || {})) {
      const row = models.get(model) || { scored: 0, total: 0, points: 0 };
      const score = typeof raw === "number" ? raw : typeof raw.score === "number" ? raw.score : raw.passed ? 1 : 0;
      row.scored += 1;
      row.total += 1;
      row.points += score;
      models.set(model, row);
    }
  }
  return [...models].map(([model, row]) => ({ model, ...row, pct: row.total ? row.points / row.total : 0 }))
    .sort((a, b) => b.pct - a.pct);
}

export function totals(envs = getEnvironments()) {
  return envs.reduce((sum, env) => ({
    tasks: sum.tasks + env.tasks.length,
    guards: sum.guards + env.tasks.reduce((n, task) => n + task.guards.length, 0),
    cheats: sum.cheats + env.tasks.reduce((n, task) => n + task.cheats.length, 0),
    scored: sum.scored + env.tasks.reduce((n, task) => n + Object.keys(task.scores || {}).length, 0),
    defects: sum.defects + env.defects.length,
    fixed: sum.fixed + env.defects.filter((d) => d.fixed).length,
  }), { tasks: 0, guards: 0, cheats: 0, scored: 0, defects: 0, fixed: 0 });
}
