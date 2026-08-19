/** Small named FIFO queue so concurrent IPC requests that each spawn a
 * local process (a headless `claude -p`, a `quorum backtest`) don't all
 * pile up running at once — jobs beyond `concurrency` wait for a slot
 * instead of contending for CPU/network together. */
const queues = new Map<string, { running: number; pending: Array<() => void> }>();

export function withQueue<T>(name: string, concurrency: number, task: () => Promise<T>): Promise<T> {
  if (!queues.has(name)) queues.set(name, { running: 0, pending: [] });
  const q = queues.get(name)!;

  return new Promise((resolve, reject) => {
    const run = () => {
      q.running++;
      task()
        .then(resolve, reject)
        .finally(() => {
          q.running--;
          const next = q.pending.shift();
          if (next) next();
        });
    };
    if (q.running < concurrency) run();
    else q.pending.push(run);
  });
}
